# Operational stream protocol v2

This document describes the isolated Python parser and validator format. It does not claim integration with the capture runner, native UPS driver, or Swift app.

## Wire format

Each record is one UTF-8 JSON object followed by a newline. The maximum record size is 8,192 bytes, including the newline. The protocol identifier is `ups-monitor.continuous.v2`, with `schema_version: 2`.

A `sample` has `sequence`, `slot`, `elapsed_ms`, `missed_slots`, and `fields`. Its fields use the same exact 17-name allowlist as v1. Integer counters and observation times are exact nonnegative integers no greater than `2**53 - 1`; booleans and floating-point JSON numbers are rejected. The timing relations are `slot == elapsed_ms // 5000` and `missed_slots == slot + 1 - sequence`.

An `end` has `elapsed_ms` and a fixed reason: `cancelled`, `device_lost`, `session_lost`, `guard_error`, or `output_error`. `duration_complete` is not valid for v2.

## Python API

`parse_line_v2(line: bytes)` parses one complete v2 record and returns either `OperationalSample` or `OperationalEnd`. These frozen, slotted dataclasses are distinct from the v1 `Sample` and `End`; the v2 parser rejects v1 records, and the v1 parser retains its existing protocol, limits, behavior, and error semantics.

The v2 parser retains the v1 field checks: exact allowlist and field shape, allowed kind/state values, finite numeric grammar, load bounds, status token validation, temperature alias equality, and derived-value dependencies. It also rejects duplicate JSON keys and unknown or missing keys.

`OperationalStreamValidator(started_wall_ms, started_monotonic_ms).accept(record, now_wall_ms=..., now_monotonic_ms=...)` accepts only the new v2 record types. It enforces consecutive sequence numbers, increasing sample slot and elapsed time, end ordering, the 100 ms future tolerance, and the 1,000 ms wall/monotonic discontinuity limit. Monotonic time cannot regress. It keeps constant-size state, including only the latest sample rather than a sample history.

## Verification boundary

The isolated parser suite reports **25 unit tests passing**: 8 v1 and 17 v2. Synthetic coverage includes a 1,000-sample stream and a separate 640-second virtual stream. This validates parser and validator behavior only; it does not qualify hardware compatibility or prove integration with the runner, driver, or Swift app. Full CI completion is **NOT_RUN**.

No additional dependency is required. Keep the v1 tests and behavior unchanged when extending this isolated v2 format.
