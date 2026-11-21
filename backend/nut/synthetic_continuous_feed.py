#!/usr/bin/env python3
"""Create an explicitly simulated continuous feed; this module never opens hardware."""

from __future__ import annotations

import argparse
from pathlib import Path
import time
import uuid

from continuous_protocol import FIELD_KINDS, PROTOCOL, SCHEMA_VERSION
from continuous_capture import AtomicSamplePublisher


SOURCE_ID = "synthetic-ups-feed"


def _record(elapsed_ms: int, sequence: int, slot: int, missed: int) -> dict[str, object]:
    # Deliberately synthetic measurements; they are not H03 or device evidence.
    values: dict[str, str | None] = {
        "ups.status": "OL",
        "battery.charge": "93.5",
        "battery.runtime": "1280",
        "battery.voltage": "27.4",
        "battery.temperature": "24.0",
        "ups.temperature": "24.0",
        "input.voltage": "231.2",
        "input.frequency": "50.0",
        "output.voltage": "229.8",
        "output.current": "1.10",
        "output.frequency": "50.0",
        "ups.load": "31.5",
        "experimental.ups.load.apparent": "42.0",
        "ups.realpower.nominal": "650",
        "ups.power.nominal": "900",
        "ups.realpower": "204.75",
        "ups.power": "378",
    }
    fields = {
        name: {"value": values[name], "observed_ms": elapsed_ms, "kind": kind, "state": "observed"}
        for name, kind in FIELD_KINDS.items()
    }
    return {
        "protocol": PROTOCOL, "schema_version": SCHEMA_VERSION, "type": "sample",
        "sequence": sequence, "slot": slot, "elapsed_ms": elapsed_ms,
        "missed_slots": missed, "fields": fields,
    }


def create_feed(directory: str | os.PathLike[str], *, duration_seconds: int = 120,
                interval_seconds: int = 5, once: bool = False) -> int:
    if type(duration_seconds) is not int or not 1 <= duration_seconds <= 120:
        raise ValueError("invalid_duration")
    if type(interval_seconds) is not int or interval_seconds != 5:
        raise ValueError("invalid_interval")
    target = Path(directory)
    session_id = uuid.uuid4().hex
    publisher = AtomicSamplePublisher(target, SOURCE_ID, session_id)
    start_wall = time.time_ns() // 1_000_000
    start_mono = time.monotonic_ns() // 1_000_000
    latest: dict[str, object] | None = None
    sequence = 0
    last_slot = -1
    try:
        deadline = start_mono + duration_seconds * 1000
        while True:
            now = time.monotonic_ns() // 1_000_000
            elapsed = now - start_mono
            if elapsed >= duration_seconds * 1000:
                break
            slot = min(elapsed // 5000, 23)
            if slot > last_slot:
                sequence += 1
                latest = _record(elapsed, sequence, int(slot), int(slot + 1 - sequence))
                publisher.publish(state="active", started_at_unix_ms=start_wall, terminal_reason=None,
                                  sample=latest, published_at_unix_ms=time.time_ns() // 1_000_000)
                last_slot = int(slot)
                if once:
                    return 0
            remaining = deadline - (time.monotonic_ns() // 1_000_000)
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining / 1000))
        publisher.publish(state="stopped", started_at_unix_ms=start_wall, terminal_reason="duration_complete",
                          sample=latest, published_at_unix_ms=time.time_ns() // 1_000_000)
        return 0
    finally:
        publisher.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, help="existing owner-only 0700 feed directory")
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--once", action="store_true", help="write one synthetic active sample for interop")
    args = parser.parse_args(argv)
    try:
        return create_feed(args.directory, duration_seconds=args.duration_seconds,
                           interval_seconds=args.interval_seconds, once=args.once)
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

