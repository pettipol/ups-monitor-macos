"""Bounded parser for one reserved native cleanup diagnostic line."""
from __future__ import annotations

import json


PREFIX = b"UPS_CLEANUP_DIAG_V1 "
MAX_RECORD_BYTES = 1_024
MAX_INTEGER_DIGITS = 16
MAX_SAFE_INTEGER = 9_007_199_254_740_991
_WHITESPACE = frozenset(b" \t\r\n\v\f")
_KEYS = frozenset({
    "v", "reason_before", "reason_after", "phase_before", "health_before",
    "phase_after", "health_after", "admitted", "stop_ok", "released",
    "complete", "clock_ok", "cleanup_attempted", "cleanup_failed",
    "write_called", "write_kind", "write_rc", "cleanup_delta_ms",
})
_REASONS = ("reason_before", "reason_after")
_PHASES = ("phase_before", "phase_after")
_HEALTH = ("health_before", "health_after")
_FLAGS = ("admitted", "stop_ok", "released", "complete", "clock_ok",
          "cleanup_attempted", "cleanup_failed", "write_called")


class _DiagnosticError(ValueError):
    def __init__(self, code: str):
        self.code = code


class CleanupDiagnosticParser:
    """Consume stderr chunks without retaining foreign lines or raw records."""

    def __init__(self) -> None:
        self._prefix_position = 0
        self._candidate = False
        self._discard_until_lf = False
        self._buffer = bytearray()
        self._seen_candidate = 0
        self._invalid_code: str | None = None
        self._incomplete_code: str | None = None
        self._diagnostic: dict | None = None

    def accept(self, chunk: bytes) -> None:
        if type(chunk) is not bytes:
            self._invalidate("shape")
            return
        if self._invalid_code is not None:
            return
        for byte in chunk:
            if self._discard_until_lf:
                if byte == 10:
                    self._end_line()
                continue

            if not self._candidate:
                if byte == PREFIX[self._prefix_position]:
                    self._prefix_position += 1
                    if self._prefix_position == len(PREFIX):
                        self._prefix_position = 0
                        if self._seen_candidate:
                            self._seen_candidate = 2
                            self._invalidate("duplicate_record")
                            self._discard_until_lf = byte != 10
                        else:
                            self._seen_candidate = 1
                            self._candidate = True
                            self._buffer.extend(PREFIX)
                    continue
                self._prefix_position = 0
                if byte == 10:
                    self._end_line()
                else:
                    self._discard_until_lf = True
                continue

            self._buffer.append(byte)
            if byte == 10:
                self._finish_candidate()
                self._end_line()
                if self._invalid_code is not None:
                    return
                continue

            if byte > 0x7F or byte in _WHITESPACE or byte == 0x5C:
                self._invalidate("shape")
                self._discard_until_lf = True
                continue
            # The newline itself must fit in the 1024-byte total.
            if len(self._buffer) >= MAX_RECORD_BYTES:
                self._invalidate("overlong")
                self._discard_until_lf = True

    def snapshot(self, stderr_eof: bool) -> dict:
        if self._invalid_code is not None:
            return {"state": "invalid", "error_code": self._invalid_code, "diagnostic": None}
        if not stderr_eof:
            return {"state": "incomplete", "error_code": "stream_not_final", "diagnostic": None}
        if self._candidate or self._prefix_position:
            self._incomplete_code = "truncated"
            self._buffer.clear()
            self._candidate = False
            self._prefix_position = 0
            self._discard_until_lf = False
            return {"state": "incomplete", "error_code": "truncated", "diagnostic": None}
        if self._incomplete_code is not None:
            return {"state": "incomplete", "error_code": self._incomplete_code, "diagnostic": None}
        if self._seen_candidate == 1 and self._diagnostic is not None:
            return {"state": "valid", "error_code": None, "diagnostic": dict(self._diagnostic)}
        return {"state": "absent", "error_code": None, "diagnostic": None}

    def _end_line(self) -> None:
        self._prefix_position = 0
        self._candidate = False
        self._discard_until_lf = False
        self._buffer.clear()

    def _finish_candidate(self) -> None:
        try:
            self._diagnostic = self._decode_record(bytes(self._buffer))
        except _DiagnosticError as error:
            self._invalidate(error.code)
        except RecursionError:
            self._invalidate("shape")
        except (UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            self._invalidate("shape")

    def _invalidate(self, code: str) -> None:
        if self._invalid_code is None:
            self._invalid_code = code
        self._diagnostic = None
        self._buffer.clear()

    @staticmethod
    def _decode_record(record: bytes) -> dict:
        if len(record) > MAX_RECORD_BYTES or not record.endswith(b"\n"):
            raise _DiagnosticError("overlong" if len(record) > MAX_RECORD_BYTES else "truncated")
        if any(byte > 0x7F or byte in _WHITESPACE or byte == 0x5C for byte in record[len(PREFIX):-1]):
            raise _DiagnosticError("shape")

        def parse_integer(token: str) -> int:
            if len(token.lstrip("-")) > MAX_INTEGER_DIGITS:
                raise _DiagnosticError("range")
            return int(token, 10)

        def reject_float(_token: str):
            raise _DiagnosticError("shape")

        def reject_constant(_token: str):
            raise _DiagnosticError("shape")

        def unique_object(pairs: list[tuple[str, object]]) -> dict:
            value = {}
            for key, item in pairs:
                if key in value:
                    raise _DiagnosticError("duplicate_key")
                value[key] = item
            return value

        payload = record[len(PREFIX):-1].decode("ascii")
        value = json.loads(payload, object_pairs_hook=unique_object,
                           parse_int=parse_integer, parse_float=reject_float,
                           parse_constant=reject_constant)
        if type(value) is not dict or set(value) != _KEYS:
            raise _DiagnosticError("shape")
        for key in value:
            if key in ("write_rc", "cleanup_delta_ms"):
                if value[key] is not None and type(value[key]) is not int:
                    raise _DiagnosticError("shape")
            elif type(value[key]) is not int:
                raise _DiagnosticError("shape")

        if value["v"] != 1:
            raise _DiagnosticError("range")
        for key in _REASONS:
            if not 0 <= value[key] <= 4:
                raise _DiagnosticError("range")
        for key in _PHASES:
            if not 0 <= value[key] <= 4:
                raise _DiagnosticError("range")
        for key in _HEALTH:
            if not 0 <= value[key] <= 7:
                raise _DiagnosticError("range")
        for key in _FLAGS:
            if value[key] not in (0, 1):
                raise _DiagnosticError("range")
        if not 0 <= value["write_kind"] <= 4:
            raise _DiagnosticError("range")
        delta = value["cleanup_delta_ms"]
        if delta is not None and not 0 <= delta <= MAX_SAFE_INTEGER:
            raise _DiagnosticError("range")
        if value["cleanup_attempted"] == 0 and value["write_called"] != 0:
            raise _DiagnosticError("write_consistency")

        kind, called, result = value["write_kind"], value["write_called"], value["write_rc"]
        consistent = (
            (kind == 0 and called == 0 and result is None)
            or (kind == 1 and called == 1 and result == -1)
            or (kind == 2 and called == 1 and type(result) is int and 0 <= result <= 63)
            or (kind == 3 and called == 1 and result == 64)
            or (kind == 4 and called == 1 and result is None)
        )
        if not consistent:
            raise _DiagnosticError("write_consistency")
        return dict(value)
