from __future__ import annotations

import json
import unittest

from continuous_protocol import End, FIELD_KINDS, ProtocolError, Sample, StreamValidator, parse_line


def sample_record(**overrides):
    values = {
        "ups.status": "OL", "battery.charge": "93.5", "battery.runtime": "1280",
        "battery.voltage": "27.4", "battery.temperature": "24.0", "ups.temperature": "24.0",
        "input.voltage": "231.2", "input.frequency": "50.0", "output.voltage": "229.8",
        "output.current": "1.10", "output.frequency": "50.0", "ups.load": "31.5",
        "experimental.ups.load.apparent": "42.0", "ups.realpower.nominal": "650",
        "ups.power.nominal": "900", "ups.realpower": "204.75", "ups.power": "378",
    }
    fields = {
        name: {"value": values[name], "observed_ms": 0, "kind": kind, "state": "observed"}
        for name, kind in FIELD_KINDS.items()
    }
    result = {"protocol": "ups-monitor.continuous.v1", "schema_version": 1, "type": "sample",
              "sequence": 1, "slot": 0, "elapsed_ms": 0, "missed_slots": 0, "fields": fields}
    result.update(overrides)
    return result


def line(record):
    return (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")


class ContinuousProtocolTests(unittest.TestCase):
    def test_valid_sample_and_end(self):
        parsed = parse_line(line(sample_record()))
        self.assertIsInstance(parsed, Sample)
        self.assertEqual(parsed.fields["ups.realpower"].value, "204.75")
        end = parse_line(b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":120000,"reason":"duration_complete"}\n')
        self.assertIsInstance(end, End)

    def test_malformed_end_reason_and_oversized_json_integer_are_protocol_errors(self):
        bad_reason = b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":0,"reason":[]}\n'
        with self.assertRaises(ProtocolError) as caught:
            parse_line(bad_reason)
        self.assertEqual(caught.exception.code, "invalid_end_reason")
        huge_integer = (b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":'
                        + b"7" * 5000 + b',"reason":"cancelled"}\n')
        with self.assertRaises(ProtocolError) as caught:
            parse_line(huge_integer)
        self.assertEqual(caught.exception.code, "invalid_json")

    def test_duplicate_unknown_and_missing_keys_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_line(b'{"protocol":"ups-monitor.continuous.v1","protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":0,"reason":"cancelled"}\n')
        record = sample_record(extra="denied")
        with self.assertRaises(ProtocolError):
            parse_line(line(record))
        del record["missed_slots"]
        with self.assertRaises(ProtocolError):
            parse_line(line(record))

    def test_numeric_grammar_and_finite_bounds(self):
        for bad in ("+1", "01", "1.", ".1", " 1", "NaN", "Infinity", "1e999", "1" * 33):
            record = sample_record()
            record["fields"]["battery.charge"]["value"] = bad
            with self.subTest(value=bad), self.assertRaises(ProtocolError):
                parse_line(line(record))

    def test_temperature_alias_status_and_derived_dependencies(self):
        record = sample_record()
        record["fields"]["ups.temperature"]["observed_ms"] = 1
        with self.assertRaises(ProtocolError):
            parse_line(line(record))
        record = sample_record()
        record["fields"]["ups.status"]["value"] = "OB OL"
        with self.assertRaises(ProtocolError):
            parse_line(line(record))
        record = sample_record()
        record["fields"]["ups.realpower.nominal"]["value"] = "0"
        with self.assertRaises(ProtocolError):
            parse_line(line(record))

    def test_noninteger_derived_power_matches_wire_precision(self):
        record = sample_record()
        record["fields"]["ups.load"]["value"] = "18.7969"
        record["fields"]["ups.realpower.nominal"]["value"] = "900"
        record["fields"]["ups.realpower"]["value"] = "169.1721"
        self.assertIsInstance(parse_line(line(record)), Sample)
        record["fields"]["ups.realpower"]["value"] = "169.172"
        with self.assertRaises(ProtocolError):
            parse_line(line(record))

    def test_state_shape_and_slot_alignment(self):
        record = sample_record()
        record["fields"]["output.current"].update(value=None, observed_ms=None, state="unavailable")
        self.assertIsInstance(parse_line(line(record)), Sample)
        record["slot"] = 1
        with self.assertRaises(ProtocolError):
            parse_line(line(record))
        with self.assertRaises(ProtocolError):
            parse_line(line(sample_record())[:-1])

    def test_stream_rejects_future_and_nonconsecutive_samples(self):
        validator = StreamValidator(1_000, 5_000)
        validator.accept(parse_line(line(sample_record())), now_wall_ms=1_000, now_monotonic_ms=5_000)
        next_record = sample_record(sequence=3, slot=2, elapsed_ms=10_000, missed_slots=0)
        with self.assertRaises(ProtocolError):
            validator.accept(parse_line(line(next_record)), now_wall_ms=11_000, now_monotonic_ms=15_000)
        with self.assertRaises(ProtocolError):
            validator.accept(parse_line(line(sample_record(elapsed_ms=500))), now_wall_ms=1_000, now_monotonic_ms=5_000)


if __name__ == "__main__":
    unittest.main()

