from __future__ import annotations

import json
import unittest

from continuous_protocol import (
    FIELD_KINDS,
    MAX_SAFE_INTEGER,
    OperationalEnd,
    OperationalSample,
    OperationalStreamValidator,
    ProtocolError,
    Sample,
    End,
    parse_line,
    parse_line_v2,
)


def sample_record(sequence: int = 1, elapsed_ms: int = 0, **changes):
    values = {
        "ups.status": "OL", "battery.charge": "93.5", "battery.runtime": "1280",
        "battery.voltage": "27.4", "battery.temperature": "24.0", "ups.temperature": "24.0",
        "input.voltage": "231.2", "input.frequency": "50.0", "output.voltage": "229.8",
        "output.current": "1.10", "output.frequency": "50.0", "ups.load": "31.5",
        "experimental.ups.load.apparent": "42.0", "ups.realpower.nominal": "650",
        "ups.power.nominal": "900", "ups.realpower": "204.75", "ups.power": "378",
    }
    fields = {
        name: {"value": values[name], "observed_ms": elapsed_ms, "kind": kind, "state": "observed"}
        for name, kind in FIELD_KINDS.items()
    }
    slot = elapsed_ms // 5000
    record = {
        "protocol": "ups-monitor.continuous.v2", "schema_version": 2, "type": "sample",
        "sequence": sequence, "slot": slot, "elapsed_ms": elapsed_ms,
        "missed_slots": slot + 1 - sequence, "fields": fields,
    }
    record.update(changes)
    return record


def end_record(elapsed_ms: int, reason: str = "cancelled"):
    return {"protocol": "ups-monitor.continuous.v2", "schema_version": 2,
            "type": "end", "elapsed_ms": elapsed_ms, "reason": reason}


def line(record, *, duplicate: bool = False) -> bytes:
    rendered = json.dumps(record, separators=(",", ":"))
    if duplicate:
        rendered = rendered[:-1] + ',"type":"sample"}'
    return (rendered + "\n").encode("utf-8")


def parsed_sample(sequence: int, elapsed_ms: int) -> OperationalSample:
    parsed = parse_line_v2(line(sample_record(sequence, elapsed_ms)))
    assert type(parsed) is OperationalSample
    return parsed


class OperationalProtocolTests(unittest.TestCase):
    def test_unbounded_stream_exceeds_v1_sample_and_duration_limits(self):
        validator = OperationalStreamValidator(100_000, 500_000)
        for sequence in range(1, 130):  # 640 seconds, 129 complete samples.
            elapsed = (sequence - 1) * 5_000
            validator.accept(parsed_sample(sequence, elapsed),
                             now_wall_ms=100_000 + elapsed,
                             now_monotonic_ms=500_000 + elapsed)
        self.assertEqual(validator.sample_count, 129)
        self.assertEqual(validator.last_sample.sequence, 129)
        self.assertEqual(validator.last_elapsed_ms, 640_000)

    def test_thousand_samples_retain_no_history(self):
        validator = OperationalStreamValidator(0, 0)
        for sequence in range(1, 1001):
            elapsed = (sequence - 1) * 5_000
            validator.accept(parsed_sample(sequence, elapsed), now_wall_ms=elapsed,
                             now_monotonic_ms=elapsed)
        self.assertEqual(validator.sample_count, 1000)
        self.assertFalse(hasattr(validator, "samples"))
        self.assertEqual(validator.last_sample.sequence, 1000)

    def test_all_integer_wire_fields_reject_bool_and_float(self):
        for key in ("sequence", "slot", "elapsed_ms", "missed_slots"):
            for invalid in (True, 1.0):
                record = sample_record()
                record[key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ProtocolError):
                    parse_line_v2(line(record))
        for invalid in (True, 1.0):
            with self.subTest(anchor=invalid), self.assertRaises(ProtocolError):
                OperationalStreamValidator(invalid, 0)
            with self.subTest(monotonic_anchor=invalid), self.assertRaises(ProtocolError):
                OperationalStreamValidator(0, invalid)
            with self.subTest(now=invalid):
                validator = OperationalStreamValidator(0, 0)
                with self.assertRaises(ProtocolError):
                    validator.accept(parsed_sample(1, 0), now_wall_ms=invalid, now_monotonic_ms=0)
            with self.subTest(monotonic_now=invalid):
                validator = OperationalStreamValidator(0, 0)
                with self.assertRaises(ProtocolError):
                    validator.accept(parsed_sample(1, 0), now_wall_ms=0, now_monotonic_ms=invalid)

    def test_integer_representation_ceiling(self):
        record = sample_record(sequence=MAX_SAFE_INTEGER + 1,
                               elapsed_ms=(MAX_SAFE_INTEGER // 5000) * 5000)
        with self.assertRaises(ProtocolError):
            parse_line_v2(line(record))
        with self.assertRaises(ProtocolError):
            parse_line_v2(line(end_record(MAX_SAFE_INTEGER + 1)))

    def test_all_integer_wire_fields_reject_lower_bounds_and_overflow(self):
        for key in ("sequence", "slot", "elapsed_ms", "missed_slots"):
            invalid_values = (-1, 0, MAX_SAFE_INTEGER + 1) if key == "sequence" else (-1, MAX_SAFE_INTEGER + 1)
            for invalid in invalid_values:
                record = sample_record(**{key: invalid})
                with self.subTest(key=key, invalid=invalid):
                    with self.assertRaises(ProtocolError) as caught:
                        parse_line_v2(line(record))
                    self.assertEqual(caught.exception.code, "invalid_integer")

    def test_integer_and_observation_bounds_include_exact_maximum(self):
        record = sample_record(sequence=1, elapsed_ms=MAX_SAFE_INTEGER)
        record["slot"] = MAX_SAFE_INTEGER // 5000
        record["missed_slots"] = record["slot"]
        parsed = parse_line_v2(line(record))
        self.assertEqual(parsed.elapsed_ms, MAX_SAFE_INTEGER)
        self.assertTrue(all(field.observed_ms == MAX_SAFE_INTEGER for field in parsed.fields.values()))
        self.assertEqual(parse_line_v2(line(end_record(MAX_SAFE_INTEGER))).elapsed_ms, MAX_SAFE_INTEGER)

        for invalid in (True, 1.0, -1, MAX_SAFE_INTEGER + 1):
            invalid_record = sample_record(sequence=1, elapsed_ms=MAX_SAFE_INTEGER)
            invalid_record["slot"] = MAX_SAFE_INTEGER // 5000
            invalid_record["missed_slots"] = invalid_record["slot"]
            invalid_record["fields"]["battery.charge"]["observed_ms"] = invalid
            with self.subTest(observed=invalid), self.assertRaises(ProtocolError):
                parse_line_v2(line(invalid_record))

        with self.assertRaises(ProtocolError):
            parse_line_v2(line(sample_record(sequence=1, elapsed_ms=MAX_SAFE_INTEGER + 1)))

    def test_anchor_and_now_integer_bounds(self):
        validator = OperationalStreamValidator(MAX_SAFE_INTEGER, MAX_SAFE_INTEGER)
        validator.accept(parsed_sample(1, 0), now_wall_ms=MAX_SAFE_INTEGER,
                         now_monotonic_ms=MAX_SAFE_INTEGER)
        for invalid in (-1, MAX_SAFE_INTEGER + 1):
            with self.subTest(anchor=invalid), self.assertRaises(ProtocolError):
                OperationalStreamValidator(invalid, 0)
            with self.subTest(monotonic_anchor=invalid), self.assertRaises(ProtocolError):
                OperationalStreamValidator(0, invalid)
            validator = OperationalStreamValidator(0, 0)
            with self.subTest(wall_now=invalid), self.assertRaises(ProtocolError):
                validator.accept(parsed_sample(1, 0), now_wall_ms=invalid, now_monotonic_ms=0)
            validator = OperationalStreamValidator(0, 0)
            with self.subTest(monotonic_now=invalid), self.assertRaises(ProtocolError):
                validator.accept(parsed_sample(1, 0), now_wall_ms=0, now_monotonic_ms=invalid)

    def test_future_and_clock_discontinuities(self):
        validator = OperationalStreamValidator(10_000, 20_000)
        with self.assertRaises(ProtocolError) as caught:
            validator.accept(parsed_sample(1, 101), now_wall_ms=10_000, now_monotonic_ms=20_000)
        self.assertEqual(caught.exception.code, "future_sample")
        validator = OperationalStreamValidator(10_000, 20_000)
        validator.accept(parsed_sample(1, 0), now_wall_ms=10_000, now_monotonic_ms=20_000)
        with self.assertRaises(ProtocolError) as caught:
            validator.accept(parsed_sample(2, 5_000), now_wall_ms=15_000, now_monotonic_ms=19_999)
        self.assertEqual(caught.exception.code, "clock_discontinuity")
        validator = OperationalStreamValidator(10_000, 20_000)
        with self.assertRaises(ProtocolError) as caught:
            validator.accept(parsed_sample(1, 0), now_wall_ms=11_001, now_monotonic_ms=20_000)
        self.assertEqual(caught.exception.code, "clock_discontinuity")

    def test_version_cross_rejection_and_distinct_record_types(self):
        v2 = parse_line_v2(line(sample_record()))
        self.assertIs(type(v2), OperationalSample)
        with self.assertRaises(ProtocolError):
            parse_line(line(sample_record()))
        v1_record = sample_record()
        v1_record.update(protocol="ups-monitor.continuous.v1", schema_version=1)
        v1_sample = parse_line(line(v1_record))
        self.assertIs(type(v1_sample), Sample)
        v1_end = parse_line(b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":0,"reason":"cancelled"}\n')
        self.assertIs(type(v1_end), End)
        for v1_record_obj in (v1_sample, v1_end):
            validator = OperationalStreamValidator(0, 0)
            with self.assertRaises(ProtocolError) as caught:
                validator.accept(v1_record_obj, now_wall_ms=0, now_monotonic_ms=0)
            self.assertEqual(caught.exception.code, "invalid_record_type")
        for v1_line in (line(v1_record), b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":0,"reason":"cancelled"}\n'):
            with self.assertRaises(ProtocolError) as caught:
                parse_line_v2(v1_line)
            self.assertEqual(caught.exception.code, "unsupported_protocol")
        self.assertIs(type(parse_line_v2(line(end_record(0)))), OperationalEnd)

        v2_record = sample_record()
        for wrong_protocol, wrong_schema in (("ups-monitor.continuous.v1", 2), ("ups-monitor.continuous.v2", 1)):
            invalid = dict(v2_record, protocol=wrong_protocol, schema_version=wrong_schema)
            with self.subTest(protocol=wrong_protocol, schema=wrong_schema), self.assertRaises(ProtocolError):
                parse_line_v2(line(invalid))

    def test_duration_end_rejected_other_fixed_reasons_allowed(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(end_record(10, "duration_complete")))
        self.assertEqual(caught.exception.code, "invalid_end_reason")
        for reason in ("cancelled", "device_lost", "session_lost", "guard_error", "output_error"):
            self.assertIs(type(parse_line_v2(line(end_record(10, reason)))), OperationalEnd)

    def test_sequence_increment_and_record_after_end(self):
        validator = OperationalStreamValidator(0, 0)
        validator.accept(parsed_sample(1, 0), now_wall_ms=0, now_monotonic_ms=0)
        with self.assertRaises(ProtocolError):
            validator.accept(parsed_sample(3, 10_000), now_wall_ms=10_000, now_monotonic_ms=10_000)
        validator.accept(parse_line_v2(line(end_record(10_000))), now_wall_ms=10_000, now_monotonic_ms=10_000)
        with self.assertRaises(ProtocolError) as caught:
            validator.accept(parsed_sample(2, 5_000), now_wall_ms=10_000, now_monotonic_ms=10_000)
        self.assertEqual(caught.exception.code, "record_after_end")

    def test_end_before_last_sample_and_future_end_rejected(self):
        validator = OperationalStreamValidator(0, 0)
        validator.accept(parsed_sample(1, 5_000), now_wall_ms=5_000, now_monotonic_ms=5_000)
        with self.assertRaises(ProtocolError) as caught:
            validator.accept(parse_line_v2(line(end_record(4_999))), now_wall_ms=5_000, now_monotonic_ms=5_000)
        self.assertEqual(caught.exception.code, "future_end")

        validator = OperationalStreamValidator(0, 0)
        validator.accept(parsed_sample(1, 0), now_wall_ms=0, now_monotonic_ms=0)
        with self.assertRaises(ProtocolError) as caught:
            validator.accept(parse_line_v2(line(end_record(101))), now_wall_ms=0, now_monotonic_ms=0)
        self.assertEqual(caught.exception.code, "future_end")

    def test_next_sequence_with_nonincreasing_slot_or_elapsed_is_rejected(self):
        for first_elapsed, second_elapsed in ((5_000, 5_001), (6_000, 5_000)):
            with self.subTest(first_elapsed=first_elapsed, second_elapsed=second_elapsed):
                validator = OperationalStreamValidator(0, 0)
                first = parsed_sample(1, first_elapsed)
                second = parsed_sample(2, second_elapsed)
                self.assertEqual((first.slot, first.missed_slots), (1, 1))
                self.assertEqual((second.slot, second.missed_slots), (1, 0))
                validator.accept(first, now_wall_ms=6_000, now_monotonic_ms=6_000)
                with self.assertRaises(ProtocolError) as caught:
                    validator.accept(second, now_wall_ms=6_000, now_monotonic_ms=6_000)
                self.assertEqual(caught.exception.code, "nonmonotonic_sample")

    def test_invalid_dependencies_and_status(self):
        record = sample_record()
        record["fields"]["ups.load"]["state"] = "unavailable"
        record["fields"]["ups.load"].update(value=None, observed_ms=None)
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(record))
        self.assertEqual(caught.exception.code, "missing_numeric_dependency")
        record = sample_record()
        record["fields"]["ups.status"]["value"] = "OB OL"
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(record))
        self.assertEqual(caught.exception.code, "invalid_status")

    def test_duplicate_v2_keys_field_status_alias_derived_and_nonfinite_rejected(self):
        duplicated = b'{"protocol":"ups-monitor.continuous.v2","protocol":"ups-monitor.continuous.v2","schema_version":2,"type":"end","elapsed_ms":0,"reason":"cancelled"}\n'
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(duplicated)
        self.assertEqual(caught.exception.code, "duplicate_key")

        wrong_alias = sample_record()
        wrong_alias["fields"]["ups.temperature"]["value"] = "25.0"
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(wrong_alias))
        self.assertEqual(caught.exception.code, "temperature_alias_mismatch")

        wrong_derived = sample_record()
        wrong_derived["fields"]["ups.realpower"]["value"] = "204.7"
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(wrong_derived))
        self.assertEqual(caught.exception.code, "incoherent_derived_value")

        nonfinite = sample_record()
        nonfinite["fields"]["battery.charge"]["value"] = "1e999"
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(nonfinite))
        self.assertEqual(caught.exception.code, "nonfinite_number")

    def test_line_cap_unknown_and_duplicate_keys(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(b" " * 8192 + b"\n")
        self.assertEqual(caught.exception.code, "invalid_line_framing")
        record = sample_record(extra="no")
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(record))
        self.assertEqual(caught.exception.code, "unknown_or_missing_key")
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(line(end_record(0), duplicate=True))
        self.assertEqual(caught.exception.code, "duplicate_key")

    def test_exact_8192_byte_line_accepted_and_8193_rejected(self):
        encoded = line(end_record(0))
        exact = encoded[:-1] + b" " * (8192 - len(encoded)) + b"\n"
        self.assertEqual(len(exact), 8192)
        self.assertIs(type(parse_line_v2(exact)), OperationalEnd)
        with self.assertRaises(ProtocolError) as caught:
            parse_line_v2(exact[:-1] + b" " + b"\n")
        self.assertEqual(caught.exception.code, "invalid_line_framing")


if __name__ == "__main__":
    unittest.main()
