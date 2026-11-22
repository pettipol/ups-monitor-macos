"""Assertions for the single synthetic NEXT-gap pacing comparison.

The caller supplies two bounded fake-process captures. This module never
starts processes, writes files, builds code, or accesses a device.
"""

from __future__ import annotations

import json
from typing import Any


protocol: Any = None

PACING_BUDGET_MS = 250
DURATION_CUTOFF_MS = 120_000
DYNAMIC_FIELDS = (
    "ups.status",
    "battery.charge",
    "battery.runtime",
    "battery.voltage",
    "battery.temperature",
    "ups.temperature",
    "input.voltage",
    "input.frequency",
    "output.voltage",
    "output.current",
    "output.frequency",
    "ups.load",
    "experimental.ups.load.apparent",
    "ups.realpower",
    "ups.power",
)


def _records(capture: bytes, label: str) -> list[dict[str, Any]]:
    assert type(capture) is bytes, f"{label}: stdout must be bytes"
    lines = capture.splitlines(keepends=True)
    assert lines, f"{label}: stdout contains no wire records"
    result: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        assert line.endswith(b"\n"), f"{label}: record {index} is not newline terminated"
        assert line != b"\n", f"{label}: blank wire record at line {index}"
        try:
            item = json.loads(line.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssertionError(f"{label}: invalid JSON wire record {index}") from error
        assert type(item) is dict, f"{label}: wire record {index} is not an object"
        assert item.get("protocol") == "ups-monitor.continuous.v1", f"{label}: protocol changed"
        assert item.get("schema_version") == 1, f"{label}: schema version changed"
        if protocol is not None:
            protocol.parse_line(line)
        result.append(item)
    assert sum(item.get("type") == "end" for item in result) == 1, f"{label}: expected one terminal record"
    assert result[-1].get("type") == "end", f"{label}: terminal record is not last"
    return result


def _counters(stderr: bytes, label: str) -> tuple[dict[str, int], dict[str, int]]:
    assert type(stderr) is bytes, f"{label}: stderr must be bytes"
    text = stderr.decode("utf-8", "strict")
    general = [line for line in text.splitlines() if line.startswith("FAKE_COUNTERS ")]
    pacing = [line for line in text.splitlines() if line.startswith("FAKE_PACING ")]
    assert len(general) == 1, f"{label}: expected exactly one FAKE_COUNTERS summary"
    assert len(pacing) == 1, f"{label}: expected exactly one FAKE_PACING summary"

    def parse(line: str) -> dict[str, int]:
        parsed: dict[str, int] = {}
        for token in line.split()[1:]:
            key, separator, raw = token.partition("=")
            assert separator and key not in parsed, f"{label}: malformed or duplicate counter {token!r}"
            try:
                parsed[key] = int(raw, 10)
            except ValueError as error:
                raise AssertionError(f"{label}: counter {key} is not an integer") from error
        return parsed

    return parse(general[0]), parse(pacing[0])


def _assert_accounting(counters: dict[str, int], pacing: dict[str, int], label: str) -> None:
    assert counters["init"] == 1, f"{label}: expected one initial native INIT"
    assert counters["init_byte"] == 1, f"{label}: expected one bootstrap INIT byte, with no restart"
    assert counters["open"] == 1 and counters["close"] == 1, f"{label}: transport reopened or was not closed once"
    assert counters["dispose"] == 1, f"{label}: expected one native release"
    assert counters["finish_clock"] == 1, f"{label}: expected one post-finish clock receipt"
    assert counters["stop"] == 2, f"{label}: expected bootstrap STOP plus one cleanup STOP"
    assert counters["cleanup_stop"] == 1, f"{label}: expected exactly one cleanup STOP after bootstrap"
    assert counters["other_write"] == 0, f"{label}: unexpected transport write"
    assert counters["next"] > 0, f"{label}: no NEXT request was observed"
    assert pacing["gap_count"] == counters["next"] - 1, f"{label}: a NEXT gap was omitted from timing counters"
    assert pacing["acquisitions_after_cutoff"] == pacing["next_after_cutoff"] + pacing["read_after_cutoff"]
    assert pacing["acquisitions_after_cutoff"] == 0, f"{label}: acquisition occurred at or after 120000 ms"
    assert pacing["last_next_ms"] < DURATION_CUTOFF_MS, f"{label}: final NEXT reached the duration cutoff"


def _assert_samples(samples: list[dict[str, Any]], label: str) -> None:
    assert samples, f"{label}: no sample was emitted"
    previous_slot = -1
    previous_elapsed = -1
    for index, item in enumerate(samples, 1):
        assert item.get("sequence") == index, f"{label}: sample sequence is not contiguous"
        slot, elapsed = item.get("slot"), item.get("elapsed_ms")
        assert type(slot) is int and 0 <= slot < 24 and slot > previous_slot, f"{label}: slots are not strictly increasing within 0..23"
        assert type(elapsed) is int and elapsed > previous_elapsed, f"{label}: elapsed times are not strictly increasing"
        assert slot == elapsed // 5000, f"{label}: slot does not match elapsed time"
        assert elapsed < DURATION_CUTOFF_MS, f"{label}: sample was emitted at or after the cutoff"
        assert item.get("missed_slots") == slot + 1 - index, f"{label}: missed_slots does not match the real sequence"
        fields = item.get("fields")
        assert type(fields) is dict, f"{label}: fields is not an object"
        for name in DYNAMIC_FIELDS:
            field = fields.get(name)
            assert type(field) is dict, f"{label}: dynamic fixture field {name} is absent"
            assert field.get("state") == "observed", f"{label}: dynamic fixture field {name} was not observed"
            assert type(field.get("observed_ms")) is int, f"{label}: {name} has no observation timestamp"
            assert field["observed_ms"] <= elapsed, f"{label}: {name} timestamp is in the future"
        previous_slot, previous_elapsed = slot, elapsed
    assert len(samples) <= 24, f"{label}: more than 24 samples were emitted"


def validate_pair(
    off_stdout: bytes,
    off_stderr: bytes,
    off_rc: int,
    on_stdout: bytes,
    on_stderr: bytes,
    on_rc: int,
) -> dict[str, Any]:
    """Validate bounded OFF/ON captures for the one next-gap-budget scenario."""
    assert type(off_rc) is int and off_rc == 1, "OFF: expected session_lost exit status 1"
    assert type(on_rc) is int and on_rc == 0, "ON: expected clean duration_complete exit status 0"

    off_records = _records(off_stdout, "OFF")
    on_records = _records(on_stdout, "ON")
    off_end, on_end = off_records[-1], on_records[-1]
    off_samples = [item for item in off_records[:-1] if item.get("type") == "sample"]
    on_samples = [item for item in on_records[:-1] if item.get("type") == "sample"]
    assert all(item.get("type") == "sample" for item in off_records[:-1]), "OFF: unexpected record before end"
    assert all(item.get("type") == "sample" for item in on_records[:-1]), "ON: unexpected record before end"
    _assert_samples(off_samples, "OFF")
    _assert_samples(on_samples, "ON")

    off_counters, off_pacing = _counters(off_stderr, "OFF")
    on_counters, on_pacing = _counters(on_stderr, "ON")
    _assert_accounting(off_counters, off_pacing, "OFF")
    _assert_accounting(on_counters, on_pacing, "ON")

    assert off_end.get("reason") == "session_lost", "OFF: expected idle session_lost"
    assert 0 < off_end.get("elapsed_ms", DURATION_CUTOFF_MS) < DURATION_CUTOFF_MS, "OFF: session did not end before duration cutoff"
    assert off_pacing["gap_violations"] > 0, "OFF: no NEXT gap exceeded the synthetic 250 ms budget"
    assert off_pacing["first_violation_gap_ms"] > PACING_BUDGET_MS, "OFF: first reported gap did not violate the synthetic budget"
    assert off_pacing["first_violation_next_ms"] - off_pacing["first_violation_previous_ms"] == off_pacing["first_violation_gap_ms"], "OFF: first gap timestamps disagree"
    assert any(item["elapsed_ms"] > off_pacing["first_violation_next_ms"] for item in off_samples), "OFF: expected stale cache publication after the synthetic link went quiet"
    for name in DYNAMIC_FIELDS:
        observations = [item["fields"][name]["observed_ms"] for item in off_samples]
        assert len(set(observations)) == 1, f"OFF: {name} observation timestamp changed after the synthetic link went quiet"
        assert observations[-1] < off_pacing["first_violation_next_ms"], f"OFF: {name} was newly observed after the violating gap"
    assert off_counters["wait"] > 0, "OFF: expected the original slot wait"

    assert on_end.get("reason") == "duration_complete", "ON: expected full duration completion"
    assert DURATION_CUTOFF_MS <= on_end.get("elapsed_ms", 0) < 130_000, "ON: duration did not reach the existing completion window"
    assert len(on_samples) == 24, "ON: expected one sample in each of the 24 five-second slots"
    assert on_pacing["gap_violations"] == 0, "ON: NEXT gap exceeded the synthetic 250 ms budget"
    assert on_pacing["gap_max_ms"] <= PACING_BUDGET_MS, "ON: maximum NEXT gap exceeded the synthetic budget"
    assert on_counters["wait"] == 0, "ON: slot scheduler waited instead of continuing acquisition"

    for name in DYNAMIC_FIELDS:
        observations = [item["fields"][name]["observed_ms"] for item in on_samples]
        values = [item["fields"][name]["value"] for item in on_samples]
        assert all(a < b for a, b in zip(observations, observations[1:])), f"ON: {name} was not refreshed between emissions"
        assert len(set(values)) == 1, f"ON: repeated fixture payload changed value for {name}"

    return {
        "state": "PASS_SINGLE_SYNTHETIC_COUNTEREXAMPLE",
        "scenario": "next-gap-budget",
        "off": {"reason": off_end["reason"], "elapsed_ms": off_end["elapsed_ms"], "samples": len(off_samples), **off_pacing},
        "on": {"reason": on_end["reason"], "elapsed_ms": on_end["elapsed_ms"], "samples": len(on_samples), **on_pacing},
        "dynamic_fields_refreshed": list(DYNAMIC_FIELDS),
        "trace_scope": "bounded timing/lifecycle counters; not a lossless event trace",
        "hardware": "NOT_RUN",
    }
