"""Emit a fixed-duration synthetic NDJSON stream; never opens UPS hardware."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable

from continuous_protocol import MAX_END_ELAPSED_MS, PROTOCOL, SCHEMA_VERSION, StreamValidator, parse_line
from synthetic_continuous_feed import _record


DURATION_MS = 120_000
SLOT_MS = 5_000


def produce_stream(
    writer: Callable[[bytes], object],
    clock_ms: Callable[[], int],
    wait: Callable[[float], object],
) -> None:
    """Emit timed samples and one terminal record using injected I/O functions."""
    start = clock_ms()
    start_wall = time.time_ns() // 1_000_000
    validator = StreamValidator(start_wall, start)
    last_clock = start
    sequence = 0
    last_slot = -1

    def elapsed_now() -> int:
        nonlocal last_clock
        now = clock_ms()
        if type(now) is not int or now < last_clock:
            raise ValueError("clock_discontinuity")
        last_clock = now
        return now - start

    def emit(record: dict[str, object], elapsed: int) -> None:
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
        parsed = parse_line(line)
        now = start + elapsed
        validator.accept(parsed, now_wall_ms=start_wall + elapsed, now_monotonic_ms=now)
        writer(line)

    while True:
        elapsed = elapsed_now()
        if elapsed >= DURATION_MS:
            if elapsed > MAX_END_ELAPSED_MS:
                raise ValueError("duration_overrun")
            end = {"protocol": PROTOCOL, "schema_version": SCHEMA_VERSION, "type": "end",
                   "elapsed_ms": elapsed, "reason": "duration_complete"}
            emit(end, elapsed)
            return

        slot = elapsed // SLOT_MS
        if slot > last_slot:
            sequence += 1
            missed = slot + 1 - sequence
            sample = _record(elapsed, sequence, slot, missed)
            emit(sample, elapsed)
            last_slot = slot

        next_boundary = min((last_slot + 1) * SLOT_MS, DURATION_MS)
        delay_ms = next_boundary - elapsed
        if delay_ms > 0:
            wait(delay_ms / 1000)


def _stdout_writer(line: bytes) -> None:
    remaining = memoryview(line)
    while remaining:
        written = os.write(1, remaining)
        if written <= 0:
            raise OSError("stdout_write_failed")
        remaining = remaining[written:]


def main() -> int:
    if sys.argv[1:]:
        try:
            sys.stderr.write("synthetic_stream_error\n")
            sys.stderr.flush()
        except OSError:
            pass
        return 2
    try:
        produce_stream(_stdout_writer, lambda: time.monotonic_ns() // 1_000_000, time.sleep)
        return 0
    except Exception:
        try:
            sys.stderr.write("synthetic_stream_error\n")
            sys.stderr.flush()
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
