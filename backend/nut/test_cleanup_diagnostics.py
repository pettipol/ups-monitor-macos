"""Synthetic contract tests for the bounded native cleanup diagnostic parser."""
from __future__ import annotations

import json
import unittest

from cleanup_diagnostics import CleanupDiagnosticParser, MAX_RECORD_BYTES, PREFIX


def valid_value() -> dict:
    return {
        "v": 1,
        "reason_before": 0,
        "reason_after": 3,
        "phase_before": 3,
        "health_before": 1,
        "phase_after": 4,
        "health_after": 1,
        "admitted": 1,
        "stop_ok": 0,
        "released": 1,
        "complete": 0,
        "clock_ok": 1,
        "cleanup_attempted": 1,
        "cleanup_failed": 1,
        "write_called": 1,
        "write_kind": 2,
        "write_rc": 63,
        "cleanup_delta_ms": 100,
    }


def record(value: dict | None = None) -> bytes:
    body = json.dumps(value if value is not None else valid_value(),
                      separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return PREFIX + body + b"\n"


def parse(chunks: list[bytes], eof: bool = True) -> dict:
    parser = CleanupDiagnosticParser()
    for chunk in chunks:
        parser.accept(chunk)
    return parser.snapshot(stderr_eof=eof)


class ParserContractTests(unittest.TestCase):
    def test_every_single_split_and_bytewise_chunks(self):
        data = record()
        for split in range(len(data) + 1):
            with self.subTest(split=split):
                result = parse([data[:split], data[split:]])
                self.assertEqual(result["state"], "valid")
                self.assertEqual(result["diagnostic"], valid_value())
        self.assertEqual(parse([bytes([byte]) for byte in data])["state"], "valid")

    def test_prefix_lf_and_multiple_records_across_chunks(self):
        data = record()
        parser = CleanupDiagnosticParser()
        parser.accept(b"supervisor text\n" + data[:-1])
        self.assertEqual(parser.snapshot(stderr_eof=False), {
            "state": "incomplete", "error_code": "stream_not_final", "diagnostic": None})
        parser.accept(data[-1:])
        self.assertEqual(parser.snapshot(stderr_eof=True)["state"], "valid")
        self.assertEqual(parse([b"ordinary line\n", data])["state"], "valid")

    def test_eof_false_is_incomplete_even_after_valid_candidate(self):
        result = parse([record()], eof=False)
        self.assertEqual(result, {"state": "incomplete", "error_code": "stream_not_final",
                                  "diagnostic": None})

    def test_absent_and_foreign_stdout_like_bytes(self):
        self.assertEqual(parse([], eof=True), {"state": "absent", "error_code": None,
                                              "diagnostic": None})
        self.assertEqual(parse([b"ordinary diagnostic only\n"]), {
            "state": "absent", "error_code": None, "diagnostic": None})
        self.assertEqual(parse([b'{"samples":[1,2,3]}\n']), {
            "state": "absent", "error_code": None, "diagnostic": None})
        self.assertEqual(parse([], eof=False), {"state": "incomplete", "error_code": "stream_not_final",
                                     "diagnostic": None}, "EOF has not been established")

    def test_partial_prefix_and_candidate_are_truncated_at_eof(self):
        self.assertEqual(parse([PREFIX[:-1]])["state"], "incomplete")
        self.assertEqual(parse([PREFIX[:-1]])["error_code"], "truncated")
        self.assertEqual(parse([record()[:-1]])["error_code"], "truncated")
        valid_then_partial = parse([record() + PREFIX[:8]])
        self.assertEqual(valid_then_partial, {"state": "incomplete", "error_code": "truncated",
                                              "diagnostic": None})

    def test_duplicate_record_and_valid_then_duplicate_are_invalid(self):
        data = record()
        for chunks in ([data + data], [data, data[:len(PREFIX)], data[len(PREFIX):]]):
            result = parse(list(chunks))
            self.assertEqual(result, {"state": "invalid", "error_code": "duplicate_record",
                                      "diagnostic": None})
        parser = CleanupDiagnosticParser()
        parser.accept(data + data)
        self.assertEqual(parser._seen_candidate, 2)

    def test_first_invalid_error_remains_latched_without_eof(self):
        parser = CleanupDiagnosticParser()
        parser.accept(PREFIX + b"{bad}\n")
        parser.accept(record())
        self.assertEqual(parser.snapshot(stderr_eof=False), {
            "state": "invalid", "error_code": "shape", "diagnostic": None})

    def test_snapshot_returns_a_copy_of_diagnostic(self):
        parser = CleanupDiagnosticParser()
        parser.accept(record())
        first = parser.snapshot(stderr_eof=True)
        first["diagnostic"]["reason_before"] = 4
        second = parser.snapshot(stderr_eof=True)
        self.assertEqual(second["diagnostic"]["reason_before"], 0)
        self.assertNotIn("UPS_CLEANUP_DIAG_V1", repr(parser.__dict__))

    def test_1024_byte_candidate_fits_limit_and_1025_is_overlong(self):
        prefix_length = len(PREFIX)
        exactly = PREFIX + b"x" * (MAX_RECORD_BYTES - prefix_length - 1) + b"\n"
        self.assertEqual(len(exactly), MAX_RECORD_BYTES)
        parser = CleanupDiagnosticParser()
        for byte in exactly:
            parser.accept(bytes([byte]))
            self.assertLessEqual(len(parser._buffer), MAX_RECORD_BYTES)
        self.assertEqual(parser.snapshot(stderr_eof=True)["error_code"], "shape")
        over = PREFIX + b"x" * (MAX_RECORD_BYTES - prefix_length) + b"\n"
        self.assertEqual(len(over), MAX_RECORD_BYTES + 1)
        parser = CleanupDiagnosticParser()
        for byte in over:
            parser.accept(bytes([byte]))
            self.assertLessEqual(len(parser._buffer), MAX_RECORD_BYTES)
        self.assertEqual(parser.snapshot(stderr_eof=True), {
            "state": "invalid", "error_code": "overlong", "diagnostic": None})

    def test_foreign_sensitive_long_input_is_never_retained(self):
        secret = b"SERIAL=synthetic-secret-" + b"z" * 200_000
        parser = CleanupDiagnosticParser()
        parser.accept(secret)
        self.assertLessEqual(len(parser._buffer), MAX_RECORD_BYTES)
        self.assertNotIn(secret[:64], repr(parser.__dict__).encode())
        parser.accept(b"\n")
        self.assertEqual(parser.snapshot(stderr_eof=True)["state"], "absent")
        self.assertEqual(len(parser._buffer), 0)

    def test_contract_requires_exact_keys_and_rejects_each_bad_field(self):
        for key in valid_value():
            with self.subTest(missing=key):
                value = valid_value()
                del value[key]
                self.assertEqual(parse([record(value)])["error_code"], "shape")

        cases = {
            "v": (2, "range"),
            "reason_before": (5, "range"),
            "reason_after": (-1, "range"),
            "phase_before": (5, "range"),
            "phase_after": (-1, "range"),
            "health_before": (8, "range"),
            "health_after": (-1, "range"),
            "admitted": (2, "range"),
            "stop_ok": (-1, "range"),
            "released": (2, "range"),
            "complete": (-1, "range"),
            "clock_ok": (2, "range"),
            "cleanup_attempted": (2, "range"),
            "cleanup_failed": (-1, "range"),
            "write_called": (2, "range"),
            "write_kind": (5, "range"),
            "cleanup_delta_ms": (9_007_199_254_740_992, "range"),
        }
        for key, (bad, expected) in cases.items():
            with self.subTest(field=key):
                value = valid_value()
                value[key] = bad
                self.assertEqual(parse([record(value)])["error_code"], expected)

        value = valid_value()
        value["extra"] = 1
        self.assertEqual(parse([record(value)])["error_code"], "shape")

    def test_json_duplicates_and_noncompact_or_non_scalar_payloads_fail(self):
        compact = record()
        payload = compact[len(PREFIX):-1].decode("ascii")
        duplicate = payload.replace('"v":1,', '"v":1,"v":1,', 1).encode() + b"\n"
        self.assertEqual(parse([PREFIX + duplicate])["error_code"], "duplicate_key")
        for body in (
            payload.replace(",", ", ", 1),
            payload.replace('"v":1', '"v":true', 1),
            payload.replace('"v":1', '"v":1.0', 1),
            payload.replace('"v":1', '"v":1e0', 1),
            payload.replace('"v":1', '"v":NaN', 1),
            payload.replace('"v":1', '"v":"1"', 1),
            payload.replace('"v":1', '"v":"\\u0031"', 1),
            payload.replace('"v":1', '"v":[]', 1),
            payload + "garbage",
        ):
            with self.subTest(body=body[:32]):
                self.assertEqual(parse([PREFIX + body.encode("ascii") + b"\n"])["error_code"], "shape")
        self.assertEqual(parse([PREFIX + payload.encode() + b"\r\n"])["error_code"], "shape")
        self.assertEqual(parse([PREFIX + payload.encode() + b"\xff\n"])["error_code"], "shape")

    def test_integer_digit_bound_is_checked_before_conversion(self):
        payload = record().decode("ascii").replace('"v":1,', '"v":10000000000000000,', 1)
        result = parse([payload.encode("ascii")])
        self.assertEqual(result["error_code"], "range")

    def test_write_kind_return_code_and_cleanup_attempt_consistency(self):
        valid_pairs = ((0, 0, None), (1, 1, -1), (2, 1, 0), (2, 1, 63),
                       (3, 1, 64), (4, 1, None))
        for kind, called, rc in valid_pairs:
            value = valid_value()
            value.update(write_kind=kind, write_called=called, write_rc=rc)
            if not called:
                value["cleanup_attempted"] = 0
            with self.subTest(valid=(kind, called, rc)):
                self.assertEqual(parse([record(value)])["state"], "valid")

        invalid = ((0, 1, None), (1, 1, None), (1, 1, -2), (2, 1, 64),
                   (3, 1, 63), (4, 1, 64), (2, 0, 1))
        for kind, called, rc in invalid:
            value = valid_value()
            value.update(write_kind=kind, write_called=called, write_rc=rc)
            with self.subTest(invalid=(kind, called, rc)):
                self.assertEqual(parse([record(value)])["error_code"], "write_consistency")
        value = valid_value()
        value.update(cleanup_attempted=0, write_called=0, write_kind=0, write_rc=None)
        self.assertEqual(parse([record(value)])["state"], "valid")
        value["write_called"] = 1
        value["write_kind"] = 2
        value["write_rc"] = 1
        self.assertEqual(parse([record(value)])["error_code"], "write_consistency")

    def test_foreign_prefix_occurrence_after_start_of_line_is_not_candidate(self):
        result = parse([b"other " + PREFIX + b"{}\n"])
        self.assertEqual(result, {"state": "absent", "error_code": None, "diagnostic": None})


if __name__ == "__main__":
    unittest.main()
