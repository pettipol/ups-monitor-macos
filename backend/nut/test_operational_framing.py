from __future__ import annotations

import json
import unittest

from continuous_protocol import FIELD_KINDS, MAX_LINE_BYTES, OperationalEnd, OperationalSample, ProtocolError
from operational_publication import MAX_PENDING_BYTES, OperationalFramer


def sample_line() -> bytes:
    values = {
        "ups.status": "OL", "battery.charge": "93.5", "battery.runtime": "1280",
        "battery.voltage": "27.4", "battery.temperature": "24.0", "ups.temperature": "24.0",
        "input.voltage": "231.2", "input.frequency": "50.0", "output.voltage": "229.8",
        "output.current": "1.10", "output.frequency": "50.0", "ups.load": "31.5",
        "experimental.ups.load.apparent": "42.0", "ups.realpower.nominal": "650",
        "ups.power.nominal": "900", "ups.realpower": "204.75", "ups.power": "378",
    }
    fields = {name: {"value": values[name], "observed_ms": 0, "kind": kind, "state": "observed"}
              for name, kind in FIELD_KINDS.items()}
    obj = {"protocol": "ups-monitor.continuous.v2", "schema_version": 2, "type": "sample",
           "sequence": 1, "slot": 0, "elapsed_ms": 0, "missed_slots": 0, "fields": fields}
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("ascii")


def end_line() -> bytes:
    return b'{"protocol":"ups-monitor.continuous.v2","schema_version":2,"type":"end","elapsed_ms":0,"reason":"cancelled"}\n'


class BoundedSpyBytearray(bytearray):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum
        self.extend_calls = 0
        self.max_observed = 0

    def extend(self, data) -> None:
        projected = len(self) + len(data)
        if projected > self.maximum:
            raise AssertionError("pending buffer exceeded configured bound")
        self.extend_calls += 1
        super().extend(data)
        self.max_observed = max(self.max_observed, len(self))


class OperationalFramerTests(unittest.TestCase):
    def test_split_and_multiline_records_only_sample_progresses(self) -> None:
        records = []
        framer = OperationalFramer(lambda record: records.append(record) or isinstance(record, OperationalSample))
        sample = sample_line()
        self.assertFalse(framer.accept(sample[:13]))
        self.assertEqual(framer.pending_bytes, 13)
        self.assertTrue(framer.accept(sample[13:] + end_line()))
        self.assertEqual(len(records), 2)
        self.assertIs(type(records[0]), OperationalSample)
        self.assertIs(type(records[1]), OperationalEnd)
        self.assertFalse(framer.accept(b""))
        self.assertFalse(framer.accept(b""))

    def test_pending_and_complete_line_boundaries(self) -> None:
        records = []
        framer = OperationalFramer(lambda record: records.append(record) or True)
        line = sample_line()
        padded = line[:-1] + b" " * (MAX_LINE_BYTES - len(line)) + b"\n"
        self.assertEqual(len(padded), MAX_LINE_BYTES)
        self.assertFalse(framer.accept(padded[:-1]))
        self.assertEqual(framer.pending_bytes, MAX_PENDING_BYTES)
        self.assertTrue(framer.accept(padded[-1:]))
        self.assertEqual(framer.pending_bytes, 0)
        oversized = OperationalFramer(lambda _record: False)
        spy = BoundedSpyBytearray(MAX_PENDING_BYTES)
        oversized._pending = spy
        with self.assertRaises(ProtocolError):
            oversized.accept(b"x" * MAX_LINE_BYTES)
        self.assertTrue(oversized.failed)
        self.assertEqual(oversized.pending_bytes, 0)
        self.assertEqual(spy.extend_calls, 0)
        self.assertLessEqual(spy.max_observed, MAX_PENDING_BYTES)

        near_limit = OperationalFramer(lambda _record: False)
        near_spy = BoundedSpyBytearray(MAX_PENDING_BYTES)
        near_limit._pending = near_spy
        near_limit.accept(b"x" * MAX_PENDING_BYTES)
        calls_before_reject = near_spy.extend_calls
        with self.assertRaises(ProtocolError):
            near_limit.accept(b"x")
        self.assertEqual(near_spy.extend_calls, calls_before_reject)
        self.assertLessEqual(near_spy.max_observed, MAX_PENDING_BYTES)

        boundary = OperationalFramer(lambda _record: True)
        boundary_spy = BoundedSpyBytearray(MAX_LINE_BYTES)
        boundary._pending = boundary_spy
        self.assertFalse(boundary.accept(padded[:-1]))
        self.assertTrue(boundary.accept(padded[-1:]))
        self.assertEqual(boundary_spy.max_observed, MAX_LINE_BYTES)
        self.assertEqual(boundary.pending_bytes, 0)

    def test_eof_rejects_partial_and_input_after_eof(self) -> None:
        partial = OperationalFramer(lambda _record: False)
        partial.accept(b'{"partial":')
        with self.assertRaises(ProtocolError) as missing:
            partial.accept(b"")
        self.assertEqual(missing.exception.code, "missing_newline")
        self.assertTrue(partial.failed)
        closed = OperationalFramer(lambda _record: False)
        self.assertFalse(closed.accept(b""))
        with self.assertRaises(ProtocolError) as late:
            closed.accept(b"x")
        self.assertEqual(late.exception.code, "input_after_eof")

    def test_parse_callback_and_bool_errors_latch_failure(self) -> None:
        invalid = OperationalFramer(lambda _record: True)
        with self.assertRaises(ProtocolError):
            invalid.accept(b"not json\n")
        self.assertTrue(invalid.failed)
        bad_callback = OperationalFramer(lambda _record: 1)
        with self.assertRaises(ProtocolError) as bad_return:
            bad_callback.accept(sample_line())
        self.assertEqual(bad_return.exception.code, "consumer_error")
        self.assertTrue(bad_callback.failed)
        raised = OperationalFramer(lambda _record: (_ for _ in ()).throw(RuntimeError("synthetic")))
        with self.assertRaises(RuntimeError):
            raised.accept(sample_line())
        self.assertTrue(raised.failed)

