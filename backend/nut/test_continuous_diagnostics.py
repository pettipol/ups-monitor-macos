#!/usr/bin/env python3
"""Discriminating offline checks for diagnostics OFF/ON fake NUT binaries.

The runner is intentionally supplied as two already-built fake-only paths. This
file never builds, discovers, or opens a genuine device.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
from pathlib import Path
import tempfile
import threading
import sys
import unittest
import argparse
import importlib.util
import copy
from types import SimpleNamespace

PREFIX = "MLINK_DIAG_V1 "
COUNTERS = {
    "poll.attempt", "poll.ok", "poll.failed", "poll.guard_exit", "poll.prime_failed",
    "next.attempt", "next.ok", "next.failed", "next.guard_exit",
    "receive.attempt", "receive.ok", "receive.guard_exit", "receive.read_error",
    "receive.timeout", "receive.process_reject", "receive.overflow_reset",
    "scan.checksum_candidate_reject", "scan.oversize_candidate_reject", "scan.resync_drop_events",
    "frame.processed", "frame.checksum_reject", "cache.accepted", "cache.short_reject",
    "cache.page0_implausible", "cache.time_invalid", "cache.geometry_changed",
    "blob.attempt", "blob.ok", "blob.unsupported", "blob.empty_geometry", "blob.definition_reject",
    "capture.called", "capture.observed", "capture.unavailable", "capture.invalid",
    "publication.samples", "publication.dynamic_min_advanced",
}
SUMMARY_KEYS = {
    "schema", "complete", "saturated", "time_saturated", "counters",
    "cache.first_ms", "cache.last_ms", "blob.rows_copied_min", "blob.rows_copied_max",
    "publication.dynamic_count_last", "publication.observed_min_ms_last",
    "publication.observed_max_ms_last", "terminal.first_site", "terminal.final_reason",
    "terminal.elapsed_ms", "terminal.session_ready", "terminal.consecutive_timeouts",
    "last_success.source", "last_success.defined", "last_success.age_s_at_idle_check",
    "cleanup.invoked", "cleanup.stop_state", "cleanup.finish_called", "cleanup.finish_state",
    "cleanup.clock_ok", "cleanup.ok", "cleanup.done", "cleanup.duration_reason_overridden",
}
REASONS = {"duration_complete", "cancelled", "device_lost", "session_lost", "guard_error", "output_error"}
FIRST_SITES = {
    "not_observed", "update_pre_session", "update_pre_idle", "update_post_session",
    "update_post_idle", "stream_session", "stream_guard",
}
APC_SITES = {
    "apc_2874", "apc_2909", "apc_2995", "apc_3005", "apc_3017", "apc_3030",
    "apc_3090", "apc_3119", "apc_4840", "apc_4845", "apc_4850", "apc_4854",
    "apc_4946", "apc_4951", "apc_4956", "apc_4961", "apc_4965", "apc_5065",
    "apc_5129", "apc_5133", "apc_5138", "apc_5142", "apc_5146", "apc_5162",
    "apc_5167", "apc_5172", "apc_5178", "apc_5185", "apc_5198",
}
ENV_PATH = Path("/usr/bin/env")
ENV_SHA256: str
MAX_CAPTURE_TOTAL = 32 * 1024 * 1024
capture_total = 0
run_receipts: list[dict[str, object]] = []
run_root: Path
PAIR_CACHE: dict[str, tuple] = {}


def load_pinned_sibling(name: str, pinned_hash: str):
    path = Path(__file__).resolve().with_name(name + ".py")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pinned_hash, "audited sibling hash mismatch"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssertionError(f"duplicate summary key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise AssertionError(f"non-finite JSON constant: {value}")


def run_fake(binary: Path, binary_sha256: str, scenario: str) -> SimpleNamespace:
    global capture_total
    assert len(run_receipts) < 24, "at most 24 fake subprocesses admitted per suite"
    actual_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert actual_hash == binary_sha256, "fake replay binary SHA-256 differs from the supplied pin"
    assert hashlib.sha256(ENV_PATH.read_bytes()).hexdigest() == ENV_SHA256, "/usr/bin/env SHA-256 pin mismatch"
    command = [str(ENV_PATH), f"MLINK_CONTINUOUS_REPLAY_SCENARIO={scenario}", str(binary),
               "-s", "replay", "-d1", "-x", "port=auto", "-x", "hidapi_shared",
               "-x", "guarded_monitor", "-x", "guard_vid=0001", "-x", "guard_pid=0002",
               "-x", "guard_deadline=130", "-x", "guard_probe_attempts=1", "-x",
               "hid_fallback=no", "-x", "monitor_stream_v1"]
    outdir = run_root / f"{len(run_receipts):02d}"
    result = run_bounded(
        command, executable_sha256=ENV_SHA256, output_directory=outdir,
        timeout_seconds=20, termination_grace_seconds=2,
        maximum_output_bytes=1_048_576, cancel_event=threading.Event(),
    )
    assert result.status is RunStatus.EXITED, f"bounded fake replay ended with {result.status.value}"
    assert result.trigger.value == "completed", "fake runner trigger was not completed"
    stdout = (outdir / "stdout.bin").read_bytes()
    stderr = (outdir / "stderr.bin").read_bytes()
    capture_total += len(stdout) + len(stderr)
    assert capture_total <= MAX_CAPTURE_TOTAL, "aggregate fake replay capture exceeded 32 MiB"
    run_receipts.append({
        "scenario": scenario, "binary_sha256": binary_sha256,
        "status": result.status.value, "returncode": result.returncode,
        "stdout_bytes": result.stdout_bytes, "stderr_bytes": result.stderr_bytes,
        "stdout_sha256": result.observation.stdout_sha256 if result.observation else None,
        "stderr_sha256": result.observation.stderr_sha256 if result.observation else None,
    })
    return SimpleNamespace(args=command, returncode=result.returncode, stdout=stdout, stderr=stderr)


def fake_counters(stderr: bytes) -> dict[str, int]:
    match = re.search(rb"^FAKE_COUNTERS (.+)$", stderr, re.MULTILINE)
    assert match is not None
    result = {key.decode("ascii"): int(value) for key, value in
              re.findall(rb"([a-z_]+)=(-?[0-9]+)", match.group(1))}
    assert result["trace_truncated"] == 0, "operation trace is incomplete"
    trace = re.search(rb"^FAKE_TRACE (.*)$", stderr, re.MULTILINE)
    assert trace is not None
    runs = trace.group(1).split(b",")
    totals: dict[str, int] = {}
    for run in runs:
        event = re.fullmatch(rb"([A-Z_]+)\*([1-9][0-9]*)", run)
        assert event is not None, "invalid lossless trace run"
        token = event.group(1).decode("ascii")
        assert token in {"INIT", "SELECT", "OPEN", "READ", "STOP", "INIT_BYTE", "NEXT", "CLOSE", "DISPOSE", "CLOCK", "WAIT", "SYSTEM_CLOCK"}
        totals[token] = totals.get(token, 0) + int(event.group(2))
    for token, counter in (("INIT", "init"), ("SELECT", "select"), ("OPEN", "open"),
                           ("READ", "read"), ("STOP", "stop"), ("INIT_BYTE", "init_byte"),
                           ("NEXT", "next"), ("CLOSE", "close"), ("DISPOSE", "dispose"),
                           ("CLOCK", "clock"), ("WAIT", "wait")):
        assert totals.get(token, 0) == result[counter], "lossless trace/counter mismatch"
    return result


def parse_summary(stderr: bytes, required: bool) -> tuple[dict[str, object] | None, bytes]:
    lines = stderr.splitlines(keepends=True)
    found = [line for line in lines if line.startswith(PREFIX.encode("ascii"))]
    if not required:
        assert not found, found
        return None, stderr
    assert len(found) == 1, found
    line = found[0]
    assert line.endswith(b"\n") and len(line) <= 4096
    parsed = json.loads(line[len(PREFIX):], object_pairs_hook=reject_duplicates,
                        parse_constant=reject_constant)
    assert set(parsed) == SUMMARY_KEYS, set(parsed) ^ SUMMARY_KEYS
    assert type(parsed["schema"]) is int and parsed["schema"] == 1
    assert parsed["complete"] is True
    assert type(parsed["saturated"]) is bool and type(parsed["time_saturated"]) is bool
    for key in ("terminal.session_ready", "last_success.defined", "cleanup.invoked",
                "cleanup.finish_called", "cleanup.clock_ok", "cleanup.ok", "cleanup.done",
                "cleanup.duration_reason_overridden"):
        assert type(parsed[key]) is bool
    assert type(parsed["terminal.consecutive_timeouts"]) is int and 0 <= parsed["terminal.consecutive_timeouts"] <= 0xFFFFFFFF
    assert type(parsed["publication.dynamic_count_last"]) is int and 0 <= parsed["publication.dynamic_count_last"] <= 15
    counters = parsed["counters"]
    assert type(counters) is dict and set(counters) == COUNTERS
    assert all(type(value) is int and 0 <= value <= 0xFFFFFFFF for value in counters.values())
    assert counters["poll.attempt"] == min(0xFFFFFFFF, sum(counters[key] for key in (
        "poll.ok", "poll.failed", "poll.guard_exit", "poll.prime_failed"))
    )
    assert counters["next.attempt"] == min(0xFFFFFFFF, sum(counters[key] for key in (
        "next.ok", "next.failed", "next.guard_exit"))
    )
    assert counters["receive.attempt"] == min(0xFFFFFFFF, sum(counters[key] for key in (
        "receive.ok", "receive.guard_exit", "receive.read_error", "receive.timeout",
        "receive.process_reject"))
    )
    for parent, children in (
        ("blob.attempt", ("blob.ok", "blob.unsupported", "blob.empty_geometry", "blob.definition_reject")),
        ("capture.called", ("capture.observed", "capture.unavailable", "capture.invalid")),
    ):
        assert counters[parent] == min(0xFFFFFFFF, sum(counters[key] for key in children))
    assert counters["publication.dynamic_min_advanced"] <= counters["publication.samples"]
    if not parsed["saturated"]:
        for parent, children in (
            ("poll.attempt", ("poll.ok", "poll.failed", "poll.guard_exit", "poll.prime_failed")),
            ("next.attempt", ("next.ok", "next.failed", "next.guard_exit")),
            ("receive.attempt", ("receive.ok", "receive.guard_exit", "receive.read_error", "receive.timeout", "receive.process_reject")),
            ("blob.attempt", ("blob.ok", "blob.unsupported", "blob.empty_geometry", "blob.definition_reject")),
            ("capture.called", ("capture.observed", "capture.unavailable", "capture.invalid")),
        ):
            assert counters[parent] == sum(counters[key] for key in children)
    assert parsed["terminal.final_reason"] in REASONS
    assert type(parsed["terminal.first_site"]) is str
    assert parsed["terminal.first_site"] in FIRST_SITES | APC_SITES
    assert parsed["last_success.source"] in {"none", "handshake", "poll"}
    assert parsed["cleanup.stop_state"] in {"not_required", "ok", "failed", "not_reached"}
    assert parsed["cleanup.finish_state"] in {"not_called", "released", "retained", "unknown"}
    nullable_u32 = (
        "cache.first_ms", "cache.last_ms", "blob.rows_copied_min", "blob.rows_copied_max",
        "publication.observed_min_ms_last", "publication.observed_max_ms_last",
        "terminal.elapsed_ms",
    )
    for key in nullable_u32:
        value = parsed[key]
        assert value is None or (type(value) is int and 0 <= value <= 0xFFFFFFFF)
    for low, high in (("cache.first_ms", "cache.last_ms"),
                      ("blob.rows_copied_min", "blob.rows_copied_max"),
                      ("publication.observed_min_ms_last", "publication.observed_max_ms_last")):
        assert (parsed[low] is None) == (parsed[high] is None)
        assert parsed[low] is None or parsed[low] <= parsed[high]
    assert parsed["blob.rows_copied_max"] is None or parsed["blob.rows_copied_max"] <= 255
    assert (parsed["publication.dynamic_count_last"] == 0) == (parsed["publication.observed_min_ms_last"] is None)
    age = parsed["last_success.age_s_at_idle_check"]
    assert age is None or (type(age) in {int, float} and math.isfinite(age))
    if age is not None:
        assert parsed["last_success.defined"] is True
        assert parsed["last_success.source"] != "none"
    if not parsed["last_success.defined"]:
        assert age is None
    if parsed["cleanup.finish_state"] == "not_called":
        assert parsed["cleanup.finish_called"] is False
    if parsed["cleanup.ok"]:
        assert parsed["cleanup.done"] and parsed["cleanup.clock_ok"] and parsed["cleanup.finish_called"]
        assert parsed["cleanup.finish_state"] == "released"
        assert parsed["cleanup.stop_state"] in {"ok", "not_required"}
    assert not any(isinstance(value, str) and ("/" in value or "\\" in value) for value in parsed.values())
    return parsed, b"".join(item for item in lines if item != line)


def validate_stdout(stdout: bytes, summary: dict[str, object]) -> list[object]:
    assert not stdout or stdout.endswith(b"\n"), "partial stdout record"
    records = [protocol.parse_line(line) for line in stdout.splitlines(keepends=True)]
    validator = protocol.StreamValidator(0, 0)
    for record in records:
        validator.accept(record, now_wall_ms=record.elapsed_ms, now_monotonic_ms=record.elapsed_ms)
    samples = validator.samples
    assert len(samples) == summary["counters"]["publication.samples"]
    if validator.end is not None:
        assert validator.end.reason == summary["terminal.final_reason"]
    else:
        assert not summary["cleanup.clock_ok"], "missing terminal despite valid cleanup clock"
    return samples


def empty_summary() -> dict[str, object]:
    result: dict[str, object] = {key: None for key in SUMMARY_KEYS}
    result.update({
        "schema": 1, "complete": True, "saturated": False, "time_saturated": False,
        "counters": dict.fromkeys(COUNTERS, 0), "publication.dynamic_count_last": 0,
        "terminal.first_site": "not_observed", "terminal.final_reason": "session_lost",
        "terminal.session_ready": False, "terminal.consecutive_timeouts": 0,
        "last_success.source": "none", "last_success.defined": False,
        "cleanup.invoked": False, "cleanup.stop_state": "not_reached",
        "cleanup.finish_called": False, "cleanup.finish_state": "not_called",
        "cleanup.clock_ok": False, "cleanup.ok": False, "cleanup.done": False,
        "cleanup.duration_reason_overridden": False,
    })
    return result


def encode_summary(value: dict[str, object]) -> bytes:
    return PREFIX.encode("ascii") + json.dumps(value, separators=(",", ":")).encode("ascii") + b"\n"


class StrictSummaryParser(unittest.TestCase):
    def test_nulls_and_negative_finite_wall_age(self) -> None:
        value = empty_summary()
        parse_summary(encode_summary(value), True)
        value.update({"last_success.source": "poll", "last_success.defined": True,
                      "last_success.age_s_at_idle_check": -3})
        parse_summary(encode_summary(value), True)

    def test_rejects_invalid_types_unknown_tokens_and_nonfinite_exponent(self) -> None:
        for key, invalid in (
            ("schema", True), ("schema", 1.0), ("terminal.first_site", "apc_999999"),
            ("terminal.elapsed_ms", 1.5), ("terminal.elapsed_ms", 0x100000000),
            ("terminal.consecutive_timeouts", -1), ("terminal.consecutive_timeouts", True),
            ("publication.dynamic_count_last", 16), ("publication.dynamic_count_last", True),
            ("last_success.age_s_at_idle_check", float("inf")),
        ):
            value = empty_summary()
            value[key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(AssertionError):
                parse_summary(encode_summary(value), True)
        value = empty_summary()
        value.update({"last_success.source": "poll", "last_success.defined": True,
                      "last_success.age_s_at_idle_check": 12345})
        encoded = encode_summary(value).replace(b"12345", b"1e999")
        with self.assertRaises(AssertionError):
            parse_summary(encoded, True)
        with self.assertRaises(AssertionError):
            parse_summary(encode_summary(empty_summary()).replace(b'"schema":1', b'"schema":1,"schema":1'), True)

    def test_partitions_and_saturation_censoring(self) -> None:
        for parent, child in (("poll.attempt", "poll.failed"), ("next.attempt", "next.failed"),
                              ("receive.attempt", "receive.timeout"), ("blob.attempt", "blob.ok"),
                              ("capture.called", "capture.invalid")):
            value = empty_summary()
            value["counters"][child] = 1
            with self.subTest(parent=parent), self.assertRaises(AssertionError):
                parse_summary(encode_summary(value), True)
        value = empty_summary()
        value["counters"].update({"poll.attempt": 0xFFFFFFFF, "poll.ok": 0xFFFFFFFF, "poll.failed": 1})
        with self.assertRaises(AssertionError):
            parse_summary(encode_summary(value), True)
        value["saturated"] = True
        parse_summary(encode_summary(value), True)

    def test_timestamp_pairs_and_privacy_schema(self) -> None:
        for updates in (
            {"cache.first_ms": 1},
            {"cache.first_ms": 2, "cache.last_ms": 1},
            {"blob.rows_copied_min": 1, "blob.rows_copied_max": 256},
            {"publication.dynamic_count_last": 1},
            {"last_success.age_s_at_idle_check": 0},
            {"raw_payload": "SYNTHETIC_PRIVATE_MARKER/path"},
        ):
            value = empty_summary()
            value.update(updates)
            with self.subTest(updates=updates), self.assertRaises(AssertionError):
                parse_summary(encode_summary(value), True)


class ContinuousDiagnosticsReplay(unittest.TestCase):
    def pair(self, scenario: str):
        if scenario in PAIR_CACHE:
            return PAIR_CACHE[scenario]
        off = run_fake(FAKE_OFF, FAKE_OFF_SHA256, scenario)
        on = run_fake(FAKE_ON, FAKE_ON_SHA256, scenario)
        self.assertEqual(off.stdout, on.stdout)
        self.assertEqual(off.returncode, on.returncode)
        self.assertEqual(fake_counters(off.stderr), fake_counters(on.stderr))
        summary, stripped = parse_summary(on.stderr, True)
        _, off_stripped = parse_summary(off.stderr, False)
        self.assertEqual(off_stripped, stripped)
        self.assertLessEqual(len(on.stderr) - len(stripped), 4096)
        validate_stdout(on.stdout, summary)
        lifecycle = fake_counters(on.stderr)
        self.assertEqual(lifecycle["open"], 1)
        self.assertEqual(lifecycle["init_byte"], 1)
        self.assertEqual(lifecycle["other_write"], 0)
        self.assertLessEqual(lifecycle["close"], 1)
        if scenario == "clock-guard":
            self.assertEqual(lifecycle["stop"], 1)
            self.assertEqual(summary["cleanup.stop_state"], "failed")
            self.assertFalse(summary["cleanup.clock_ok"])
        else:
            self.assertEqual(lifecycle["stop"], 2)
        PAIR_CACHE[scenario] = (summary, off, on)
        return PAIR_CACHE[scenario]

    def test_1_identical_payload_receives_fresh_provenance(self) -> None:
        summary, _, _ = self.pair("same-payload")
        counters = summary["counters"]
        self.assertGreater(counters["publication.samples"], 1)
        self.assertGreater(counters["publication.dynamic_min_advanced"], 0)

    def test_2_cache_receive_and_rebuild_are_separate(self) -> None:
        cached, _, _ = self.pair("cache-no-rebuild")
        unrelated, _, _ = self.pair("unrelated-refresh")
        self.assertGreater(cached["counters"]["cache.accepted"], cached["counters"]["blob.ok"])
        self.assertGreater(unrelated["counters"]["blob.ok"], cached["counters"]["blob.ok"])
        for summary in (cached, unrelated):
            self.assertGreater(summary["cache.last_ms"], summary["cache.first_ms"])
            self.assertEqual(summary["counters"]["publication.dynamic_min_advanced"], 0)

    def test_3_candidate_reject_and_implausible_page0_do_not_claim_frame_reject(self) -> None:
        healthy, _, _ = self.pair("same-payload")
        rejected, _, _ = self.pair("corrupt-recovery")
        implausible, _, _ = self.pair("implausible-page0")
        self.assertGreater(rejected["counters"]["scan.checksum_candidate_reject"],
                           healthy["counters"]["scan.checksum_candidate_reject"])
        self.assertEqual(rejected["counters"]["frame.checksum_reject"], 0)
        self.assertEqual(rejected["terminal.final_reason"], "duration_complete")
        self.assertTrue(rejected["cleanup.clock_ok"])
        self.assertGreater(rejected["counters"]["publication.dynamic_min_advanced"], 0)
        self.assertGreater(implausible["counters"]["cache.page0_implausible"], 0)
        counters = implausible["counters"]
        self.assertEqual(counters["cache.short_reject"], 0)
        self.assertEqual(counters["cache.time_invalid"], 0)
        self.assertEqual(counters["receive.ok"], counters["cache.accepted"] + counters["cache.page0_implausible"])
        self.assertEqual(counters["poll.ok"], counters["receive.ok"] - 1)
        self.assertEqual(counters["poll.failed"], 0)

    def test_4_handshake_wall_success_is_not_poll_freshness(self) -> None:
        silent, _, _ = self.pair("handshake-then-silent")
        self.assertEqual(silent["last_success.source"], "poll")
        self.assertGreater(silent["counters"]["receive.timeout"], 0)
        self.assertEqual(silent["terminal.first_site"], "update_pre_idle")
        off = run_fake(FAKE_OFF, FAKE_OFF_SHA256, "no-handshake-success")
        on = run_fake(FAKE_ON, FAKE_ON_SHA256, "no-handshake-success")
        self.assertEqual(off.returncode, on.returncode)
        self.assertNotEqual(on.returncode, 0)
        self.assertEqual(off.stdout, on.stdout)
        _, off_trace = parse_summary(off.stderr, False)
        _, on_trace = parse_summary(on.stderr, False)
        self.assertEqual(off_trace, on_trace)
        self.assertEqual(on.stdout, b"")

    def test_5_terminal_branches_preserve_public_reason_and_trace(self) -> None:
        expected = {
            "cancelled": ("apc_5129", "cancelled"),
            "clock-guard": ("apc_5133", "guard_error"),
        }
        for scenario, (site, reason) in expected.items():
            with self.subTest(scenario=scenario):
                summary, _, _ = self.pair(scenario)
                self.assertEqual(summary["terminal.first_site"], site)
                self.assertEqual(summary["terminal.final_reason"], reason)

    def test_6_cleanup_failure_is_distinct_and_duration_override_is_preserved(self) -> None:
        session_lost, _, on = self.pair("silent-close-fails")
        self.assertFalse(session_lost["cleanup.ok"])
        self.assertEqual(session_lost["cleanup.finish_state"], "retained")
        self.assertEqual(session_lost["terminal.final_reason"], "session_lost")
        self.assertEqual(fake_counters(on.stderr)["close"], 1)
        self.assertEqual(fake_counters(on.stderr)["dispose"], 0)
        self.assertEqual(fake_counters(on.stderr)["stop"], 2)
        stop_failed, _, _ = self.pair("stop-fails")
        self.assertEqual(stop_failed["cleanup.stop_state"], "failed")
        duration, _, _ = self.pair("duration-cleanup-fails")
        self.assertTrue(duration["cleanup.duration_reason_overridden"])
        self.assertEqual(duration["terminal.final_reason"], "guard_error")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fake_off", type=Path)
    parser.add_argument("fake_on", type=Path)
    parser.add_argument("sha_off")
    parser.add_argument("sha_on")
    parser.add_argument("--env-sha256", required=True)
    parser.add_argument("--supervisor-sha256", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    args = parser.parse_args()
    ENV_SHA256 = args.env_sha256
    supervisor = load_pinned_sibling("process_deadline", args.supervisor_sha256)
    protocol = load_pinned_sibling("continuous_protocol", args.protocol_sha256)
    RunStatus, run_bounded = supervisor.RunStatus, supervisor.run_bounded
    FAKE_OFF = args.fake_off.resolve(strict=True)
    FAKE_ON = args.fake_on.resolve(strict=True)
    FAKE_OFF_SHA256, FAKE_ON_SHA256 = args.sha_off, args.sha_on
    for binary, pinned_hash in ((FAKE_OFF, FAKE_OFF_SHA256), (FAKE_ON, FAKE_ON_SHA256)):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise SystemExit("fake replay paths must be executable files")
        if not re.fullmatch(r"[0-9a-f]{64}", pinned_hash):
            raise SystemExit("both fake replay SHA-256 pins must be lowercase 64-character hex")
    tmp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    run_root = Path(tempfile.mkdtemp(prefix="mlink-continuous-diag-", dir=tmp_root)).resolve(strict=True)
    if run_root.parent != tmp_root:
        raise SystemExit("temporary output directory escaped the resolved TMPDIR")
    import atexit

    def save_receipt() -> None:
        receipt = {
            "schema": 1, "environment_sha256": ENV_SHA256,
            "fake_off_sha256": FAKE_OFF_SHA256, "fake_on_sha256": FAKE_ON_SHA256,
            "capture_total_bytes": capture_total, "runs": run_receipts,
        }
        (run_root / "run-receipt.json").write_text(
            json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8"
        )

    atexit.register(save_receipt)
    sys.argv = [sys.argv[0]]
    unittest.main()
