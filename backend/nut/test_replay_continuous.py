#!/usr/bin/env python3
"""Whole-NUT main/driver replay against the fake-only native host."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


FIELD_KINDS = {
    "ups.status": "reported",
    "battery.charge": "reported",
    "battery.runtime": "reported",
    "battery.voltage": "reported",
    "battery.temperature": "reported",
    "ups.temperature": "reported",
    "input.voltage": "reported",
    "input.frequency": "reported",
    "output.voltage": "reported",
    "output.current": "reported",
    "output.frequency": "reported",
    "ups.load": "reported",
    "experimental.ups.load.apparent": "reported",
    "ups.realpower.nominal": "static",
    "ups.power.nominal": "static",
    "ups.realpower": "driverDerived",
    "ups.power": "driverDerived",
}
EXPECTED_NUMBERS = {
    "battery.charge": 50.0,
    "battery.runtime": 3600.0,
    "battery.voltage": 12.0,
    "battery.temperature": 25.0,
    "ups.temperature": 25.0,
    "input.voltage": 120.0,
    "input.frequency": 60.0,
    "output.voltage": 120.0,
    "output.current": 5.0,
    "output.frequency": 60.0,
    "ups.load": 18.796875,
    "experimental.ups.load.apparent": 22.22265625,
    "ups.realpower.nominal": 900.0,
    "ups.power.nominal": 1200.0,
    "ups.realpower": 169.171875,
}
ENVELOPE = {"protocol", "schema_version", "type", "sequence", "slot", "elapsed_ms", "missed_slots", "fields"}


def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssertionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise AssertionError(f"non-finite JSON number: {value}")


def parse_case(binary: Path, scenario: str | None) -> tuple[int, list[dict[str, object]], str]:
    env = os.environ.copy()
    env.pop("MLINK_CONTINUOUS_REPLAY_SCENARIO", None)
    if scenario:
        env["MLINK_CONTINUOUS_REPLAY_SCENARIO"] = scenario
    proc = subprocess.run(
        [
            str(binary), "-s", "replay", "-d1",
            "-x", "port=auto", "-x", "hidapi_shared", "-x", "guarded_monitor",
            "-x", "guard_vid=0001", "-x", "guard_pid=0002",
            "-x", "guard_deadline=130", "-x", "guard_probe_attempts=1",
            "-x", "hid_fallback=no", "-x", "monitor_stream_v1",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        env=env,
        check=False,
    )
    assert not proc.stdout or proc.stdout.endswith("\n")
    lines = proc.stdout.splitlines()
    records = [
        json.loads(line, object_pairs_hook=reject_duplicates, parse_constant=reject_constant)
        for line in lines
    ]
    assert all(len(line.encode("utf-8")) <= 8192 for line in lines)
    assert "Network UPS Tools" not in proc.stdout
    return proc.returncode, records, proc.stderr


def counters(stderr: str) -> dict[str, int]:
    match = re.search(r"^FAKE_COUNTERS (.+)$", stderr, re.MULTILINE)
    assert match, stderr
    return {key: int(value) for key, value in re.findall(r"([a-z_]+)=(-?[0-9]+)", match.group(1))}


def assert_sample(record: dict[str, object]) -> None:
    assert set(record) == ENVELOPE
    assert record["protocol"] == "ups-monitor.continuous.v1"
    assert record["schema_version"] == 1
    assert record["type"] == "sample"
    fields = record["fields"]
    assert isinstance(fields, dict) and set(fields) == set(FIELD_KINDS)
    for name, field in fields.items():
        assert isinstance(field, dict)
        assert set(field) == {"value", "observed_ms", "kind", "state"}
        assert field["kind"] == FIELD_KINDS[name]
        if field["state"] == "unavailable":
            assert field["value"] is None and field["observed_ms"] is None
        assert field["state"] == "observed", (name, field)
        assert isinstance(field["observed_ms"], int)
        assert field["observed_ms"] <= record["elapsed_ms"]
    assert fields["ups.status"]["value"] == "OL"
    for name, expected in EXPECTED_NUMBERS.items():
        value = fields[name]["value"]
        assert isinstance(value, str) and math.isclose(
            float(value), expected, rel_tol=1e-9, abs_tol=1e-6
        ), (name, value, expected)
    for percent_name, nominal_name, target_name in (
        ("ups.load", "ups.realpower.nominal", "ups.realpower"),
        ("experimental.ups.load.apparent", "ups.power.nominal", "ups.power"),
    ):
        expected = float(fields[percent_name]["value"]) * float(
            fields[nominal_name]["value"]
        ) / 100.0
        actual = float(fields[target_name]["value"])
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9), (
            target_name, actual, expected
        )
    assert fields["battery.temperature"] == fields["ups.temperature"]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_replay_continuous.py FAKE_REPLAY_BINARY")
    binary = Path(sys.argv[1]).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)

    rc, records, stderr = parse_case(binary, None)
    assert rc == 0, stderr
    assert len(records) == 25
    samples = records[:-1]
    end = records[-1]
    assert [record["slot"] for record in samples] == list(range(24))
    assert [record["sequence"] for record in samples] == list(range(1, 25))
    assert [record["missed_slots"] for record in samples] == [0] * 24
    all_sample_times = [record["elapsed_ms"] for record in samples]
    assert all(isinstance(value, int) and value < 120000 for value in all_sample_times)
    for record in samples:
        assert_sample(record)
    assert set(end) == {"protocol", "schema_version", "type", "elapsed_ms", "reason"}
    assert end["type"] == "end" and end["elapsed_ms"] == 120000
    assert end["reason"] == "duration_complete"
    ordinary = counters(stderr)
    assert ordinary["init"] == ordinary["select"] == ordinary["open"] == 1
    assert ordinary["close"] == ordinary["dispose"] == 1
    assert ordinary["init_byte"] == 1 and ordinary["stop"] == 2
    assert ordinary["other_write"] == 0 and ordinary["next"] > 0

    rc, records, stderr = parse_case(binary, "missed-slots")
    assert rc == 0, stderr
    samples, end = records[:-1], records[-1]
    assert samples[0]["slot"] == 0 and samples[0]["missed_slots"] == 0
    assert samples[1]["slot"] == 3 and samples[1]["sequence"] == 2
    assert samples[1]["missed_slots"] == 2
    assert end["elapsed_ms"] == 120000 and end["reason"] == "duration_complete"
    missed = counters(stderr)
    assert missed["open"] == missed["init_byte"] == 1

    rc, records, stderr = parse_case(binary, "late-page")
    assert rc == 0, stderr
    samples, end = records[:-1], records[-1]
    assert len(samples) == 1 and samples[0]["slot"] == 0
    assert end["elapsed_ms"] == 125000 and end["reason"] == "duration_complete"
    late = counters(stderr)
    assert late["open"] == late["init_byte"] == late["close"] == late["dispose"] == 1
    assert late["next"] >= 3 and late["other_write"] == 0

    rc, records, stderr = parse_case(binary, "unrelated-refresh")
    assert rc == 0, stderr
    samples, end = records[:-1], records[-1]
    assert len(samples) == 24 and end["elapsed_ms"] == 120000
    assert_sample(samples[0])
    assert_sample(samples[1])
    assert all(field["observed_ms"] == 0 for field in samples[1]["fields"].values())
    unrelated = counters(stderr)
    assert unrelated["open"] == unrelated["init_byte"] == 1
    assert unrelated["next"] > 3 and unrelated["other_write"] == 0

    rc, records, stderr = parse_case(binary, "mutate-geometry")
    assert rc != 0, stderr
    samples, end = records[:-1], records[-1]
    assert len(samples) == 1 and samples[0]["slot"] == 0
    assert end["reason"] == "guard_error"
    changed = counters(stderr)
    assert changed["open"] == changed["init_byte"] == changed["close"] == changed["dispose"] == 1
    assert changed["next"] == 3 and changed["other_write"] == 0

    rc, records, stderr = parse_case(binary, "close-fails")
    assert rc != 0, stderr
    assert records[-1]["type"] == "end" and records[-1]["reason"] == "guard_error"
    retained = counters(stderr)
    assert retained["close"] == 1 and retained["dispose"] == 0

    rc, records, stderr = parse_case(binary, "bad-descriptor")
    assert rc != 0, stderr
    assert records == [], records
    rejected = counters(stderr)
    assert rejected["open"] == rejected["init_byte"] == rejected["close"] == 1
    assert rejected["dispose"] == 1 and rejected["other_write"] == 0

    rc, records, stderr = parse_case(binary, "silent")
    assert rc != 0, stderr
    assert records and records[-1]["type"] == "end"
    end = records[-1]
    assert end["reason"] == "session_lost", end
    samples = records[:-1]
    assert samples and all(record["type"] == "sample" for record in samples)
    assert all(record["elapsed_ms"] < end["elapsed_ms"] for record in samples)
    silent = counters(stderr)
    assert silent["open"] == silent["init_byte"] == silent["close"] == silent["dispose"] == 1
    assert silent["stop"] == 2 and silent["other_write"] == 0
    next_times = [int(value) for value in re.findall(r"^SILENT_NEXT at_ms=(\d+)$", stderr, re.MULTILINE)]
    assert next_times and max(next_times) < end["elapsed_ms"], (next_times, end)
    assert end["elapsed_ms"] == 35000, end

    rc, records, stderr = parse_case(binary, "slow-close")
    assert rc != 0, stderr
    assert not records or records[-1].get("type") != "end", records[-1:]
    slow = counters(stderr)
    assert slow["close"] == slow["dispose"] == 1
    assert slow["now_ms"] == 140000, slow

    print("whole NUT fake replay: telemetry, scheduling, stop latch, final close clock, geometry and parser passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
