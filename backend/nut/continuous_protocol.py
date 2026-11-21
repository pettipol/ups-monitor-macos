"""Strict offline parser for the bounded continuous v1 NDJSON feed."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any


PROTOCOL = "ups-monitor.continuous.v1"
SCHEMA_VERSION = 1
MAX_LINE_BYTES = 8192
MAX_SAMPLES = 24
MAX_ELAPSED_MS = 119_999
MAX_END_ELAPSED_MS = 132_000
SLOT_MS = 5_000
V2_PROTOCOL = "ups-monitor.continuous.v2"
V2_SCHEMA_VERSION = 2
MAX_SAFE_INTEGER = 2**53 - 1

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
STATUS_TOKENS = frozenset({"OL", "OB", "LB", "HB", "RB", "OFF", "BYPASS", "CAL", "OVER", "TRIM", "BOOST", "FSD", "ALARM"})
END_REASONS = frozenset({"duration_complete", "cancelled", "device_lost", "session_lost", "guard_error", "output_error"})
V2_END_REASONS = END_REASONS - {"duration_complete"}
NUMBER_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$", re.ASCII)


class ProtocolError(ValueError):
    """A fixed safe parser failure code, with no source data attached."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Field:
    value: str | None
    observed_ms: int | None
    kind: str
    state: str


@dataclass(frozen=True, slots=True)
class Sample:
    sequence: int
    slot: int
    elapsed_ms: int
    missed_slots: int
    fields: dict[str, Field]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class End:
    elapsed_ms: int
    reason: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OperationalSample:
    sequence: int
    slot: int
    elapsed_ms: int
    missed_slots: int
    fields: dict[str, Field]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OperationalEnd:
    elapsed_ms: int
    reason: str
    raw: dict[str, Any]


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate_key")
        result[key] = value
    return result


def _exact_keys(value: object, expected: set[str], code: str = "unknown_or_missing_key") -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise ProtocolError(code)
    return value


def _int(value: object, low: int, high: int, code: str = "invalid_integer") -> int:
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError(code)
    return value


def _number(value: str) -> float:
    try:
        ascii_length = len(value.encode("ascii", "strict"))
    except UnicodeEncodeError:
        raise ProtocolError("invalid_numeric_string") from None
    if ascii_length > 32 or NUMBER_RE.fullmatch(value) is None:
        raise ProtocolError("invalid_numeric_string")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ProtocolError("invalid_numeric_string") from None
    if not math.isfinite(number):
        raise ProtocolError("nonfinite_number")
    return number


def parse_line(line: bytes) -> Sample | End:
    """Parse one complete newline-terminated UTF-8 record."""
    if type(line) is not bytes or not line.endswith(b"\n") or len(line) > MAX_LINE_BYTES:
        raise ProtocolError("invalid_line_framing")
    try:
        text = line[:-1].decode("utf-8", "strict")
        obj = json.loads(text, object_pairs_hook=_reject_duplicates,
                         parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("nonfinite_number")))
    except ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ProtocolError("invalid_json") from None
    if type(obj) is not dict:
        raise ProtocolError("invalid_record")
    common = {"protocol", "schema_version", "type"}
    if not common.issubset(obj) or obj["protocol"] != PROTOCOL or type(obj["schema_version"]) is not int or obj["schema_version"] != SCHEMA_VERSION:
        raise ProtocolError("unsupported_protocol")
    if obj["type"] == "sample":
        expected = common | {"sequence", "slot", "elapsed_ms", "missed_slots", "fields"}
        _exact_keys(obj, expected)
        elapsed = _int(obj["elapsed_ms"], 0, MAX_ELAPSED_MS)
        seq = _int(obj["sequence"], 1, MAX_SAMPLES)
        slot = _int(obj["slot"], 0, MAX_SAMPLES - 1)
        missed = _int(obj["missed_slots"], 0, MAX_SAMPLES - 1)
        if slot != elapsed // SLOT_MS or missed != slot + 1 - seq:
            raise ProtocolError("slot_sequence_mismatch")
        fields_obj = _exact_keys(obj["fields"], set(FIELD_KINDS), "field_allowlist_mismatch")
        fields: dict[str, Field] = {}
        for name, expected_kind in FIELD_KINDS.items():
            item = _exact_keys(fields_obj[name], {"value", "observed_ms", "kind", "state"}, "invalid_field_shape")
            kind, state, value, observed = item["kind"], item["state"], item["value"], item["observed_ms"]
            if kind != expected_kind or state not in ("observed", "unavailable", "invalid"):
                raise ProtocolError("invalid_field_state")
            if state == "observed":
                if type(value) is not str or type(observed) is not int or not 0 <= observed <= elapsed:
                    raise ProtocolError("invalid_observed_field")
                if name == "ups.status":
                    try:
                        ascii_value = value.encode("ascii", "strict")
                    except UnicodeEncodeError:
                        raise ProtocolError("invalid_status") from None
                    if len(ascii_value) > 128:
                        raise ProtocolError("invalid_status")
                    tokens = value.split()
                    if (not tokens or value != " ".join(tokens) or tokens != sorted(set(tokens))
                            or any(token not in STATUS_TOKENS for token in tokens)):
                        raise ProtocolError("invalid_status")
                    if "OL" in tokens and "OB" in tokens:
                        raise ProtocolError("invalid_status")
                else:
                    numeric_value = _number(value)
                    if name in ("ups.load", "experimental.ups.load.apparent") and not 0 <= numeric_value <= 100:
                        raise ProtocolError("invalid_load_percent")
            elif value is not None or observed is not None:
                raise ProtocolError("invalid_empty_field")
            fields[name] = Field(value, observed, kind, state)
        if fields["battery.temperature"] != fields["ups.temperature"]:
            raise ProtocolError("temperature_alias_mismatch")
        _validate_dependencies(fields)
        return Sample(seq, slot, elapsed, missed, fields, obj)
    if obj["type"] == "end":
        _exact_keys(obj, common | {"elapsed_ms", "reason"})
        elapsed = _int(obj["elapsed_ms"], 0, MAX_END_ELAPSED_MS)
        if type(obj["reason"]) is not str or obj["reason"] not in END_REASONS:
            raise ProtocolError("invalid_end_reason")
        return End(elapsed, obj["reason"], obj)
    raise ProtocolError("unknown_record_type")


def parse_line_v2(line: bytes) -> OperationalSample | OperationalEnd:
    """Parse one complete v2 operational NDJSON record."""
    if type(line) is not bytes or not line.endswith(b"\n") or len(line) > MAX_LINE_BYTES:
        raise ProtocolError("invalid_line_framing")
    try:
        text = line[:-1].decode("utf-8", "strict")
        obj = json.loads(text, object_pairs_hook=_reject_duplicates,
                         parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("nonfinite_number")))
    except ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ProtocolError("invalid_json") from None
    if type(obj) is not dict:
        raise ProtocolError("invalid_record")
    common = {"protocol", "schema_version", "type"}
    if not common.issubset(obj) or obj["protocol"] != V2_PROTOCOL or type(obj["schema_version"]) is not int or obj["schema_version"] != V2_SCHEMA_VERSION:
        raise ProtocolError("unsupported_protocol")
    if obj["type"] == "sample":
        expected = common | {"sequence", "slot", "elapsed_ms", "missed_slots", "fields"}
        _exact_keys(obj, expected)
        elapsed = _int(obj["elapsed_ms"], 0, MAX_SAFE_INTEGER)
        seq = _int(obj["sequence"], 1, MAX_SAFE_INTEGER)
        slot = _int(obj["slot"], 0, MAX_SAFE_INTEGER)
        missed = _int(obj["missed_slots"], 0, MAX_SAFE_INTEGER)
        if slot != elapsed // SLOT_MS or missed != slot + 1 - seq:
            raise ProtocolError("slot_sequence_mismatch")
        fields_obj = _exact_keys(obj["fields"], set(FIELD_KINDS), "field_allowlist_mismatch")
        fields: dict[str, Field] = {}
        for name, expected_kind in FIELD_KINDS.items():
            item = _exact_keys(fields_obj[name], {"value", "observed_ms", "kind", "state"}, "invalid_field_shape")
            kind, state, value, observed = item["kind"], item["state"], item["value"], item["observed_ms"]
            if kind != expected_kind or state not in ("observed", "unavailable", "invalid"):
                raise ProtocolError("invalid_field_state")
            if state == "observed":
                if type(value) is not str or type(observed) is not int or not 0 <= observed <= elapsed:
                    raise ProtocolError("invalid_observed_field")
                if name == "ups.status":
                    try:
                        ascii_value = value.encode("ascii", "strict")
                    except UnicodeEncodeError:
                        raise ProtocolError("invalid_status") from None
                    if len(ascii_value) > 128:
                        raise ProtocolError("invalid_status")
                    tokens = value.split()
                    if (not tokens or value != " ".join(tokens) or tokens != sorted(set(tokens))
                            or any(token not in STATUS_TOKENS for token in tokens)):
                        raise ProtocolError("invalid_status")
                    if "OL" in tokens and "OB" in tokens:
                        raise ProtocolError("invalid_status")
                else:
                    numeric_value = _number(value)
                    if name in ("ups.load", "experimental.ups.load.apparent") and not 0 <= numeric_value <= 100:
                        raise ProtocolError("invalid_load_percent")
            elif value is not None or observed is not None:
                raise ProtocolError("invalid_empty_field")
            fields[name] = Field(value, observed, kind, state)
        if fields["battery.temperature"] != fields["ups.temperature"]:
            raise ProtocolError("temperature_alias_mismatch")
        _validate_dependencies(fields)
        return OperationalSample(seq, slot, elapsed, missed, fields, obj)
    if obj["type"] == "end":
        _exact_keys(obj, common | {"elapsed_ms", "reason"})
        elapsed = _int(obj["elapsed_ms"], 0, MAX_SAFE_INTEGER)
        if type(obj["reason"]) is not str or obj["reason"] not in V2_END_REASONS:
            raise ProtocolError("invalid_end_reason")
        return OperationalEnd(elapsed, obj["reason"], obj)
    raise ProtocolError("unknown_record_type")


def _validate_dependencies(fields: dict[str, Field]) -> None:
    for derived_name, load_name, nominal_name in (
        ("ups.realpower", "ups.load", "ups.realpower.nominal"),
        ("ups.power", "experimental.ups.load.apparent", "ups.power.nominal"),
    ):
        derived, load, nominal = fields[derived_name], fields[load_name], fields[nominal_name]
        if derived.state == "observed":
            if load.state != "observed" or nominal.state != "observed":
                raise ProtocolError("missing_numeric_dependency")
            dvalue, lvalue, nvalue = map(_number, (derived.value or "", load.value or "", nominal.value or ""))
            if nvalue <= 0 or not math.isclose(dvalue, lvalue * nvalue / 100.0, rel_tol=1e-9, abs_tol=1e-6):
                raise ProtocolError("incoherent_derived_value")
            if derived.observed_ms != load.observed_ms:
                raise ProtocolError("derived_timestamp_mismatch")
        if nominal.state == "observed" and _number(nominal.value or "") <= 0:
            raise ProtocolError("invalid_nominal_rating")


class StreamValidator:
    """Enforce stream sequence, end ordering, timing anchors, and limits."""

    def __init__(self, started_wall_ms: int, started_monotonic_ms: int) -> None:
        self.started_wall_ms = started_wall_ms
        self.started_monotonic_ms = started_monotonic_ms
        self.samples: list[Sample] = []
        self.end: End | None = None
        self._last_elapsed = -1
        self._last_slot = -1

    def accept(self, record: Sample | End, *, now_wall_ms: int, now_monotonic_ms: int) -> None:
        if self.end is not None:
            raise ProtocolError("record_after_end")
        elapsed_now = now_monotonic_ms - self.started_monotonic_ms
        if elapsed_now < 0 or abs((now_wall_ms - self.started_wall_ms) - elapsed_now) > 1_000:
            raise ProtocolError("clock_discontinuity")
        if isinstance(record, Sample):
            if len(self.samples) >= MAX_SAMPLES:
                raise ProtocolError("sample_limit")
            if record.sequence != len(self.samples) + 1 or record.slot <= self._last_slot or record.elapsed_ms <= self._last_elapsed:
                raise ProtocolError("nonmonotonic_sample")
            if record.elapsed_ms > elapsed_now + 100:
                raise ProtocolError("future_sample")
            self._last_elapsed, self._last_slot = record.elapsed_ms, record.slot
            self.samples.append(record)
        else:
            if record.elapsed_ms < self._last_elapsed or record.elapsed_ms > elapsed_now + 100:
                raise ProtocolError("future_end")
            self.end = record


class OperationalStreamValidator:
    """Constant-state validator for the unbounded v2 operational stream."""

    def __init__(self, started_wall_ms: int, started_monotonic_ms: int) -> None:
        self.started_wall_ms = _int(started_wall_ms, 0, MAX_SAFE_INTEGER)
        self.started_monotonic_ms = _int(started_monotonic_ms, 0, MAX_SAFE_INTEGER)
        self.last_sample: OperationalSample | None = None
        self.sample_count = 0
        self.end: OperationalEnd | None = None
        self.last_slot = -1
        self.last_elapsed_ms = -1
        self._last_now_monotonic_ms = started_monotonic_ms

    def accept(
        self,
        record: OperationalSample | OperationalEnd,
        *,
        now_wall_ms: int,
        now_monotonic_ms: int,
    ) -> None:
        if self.end is not None:
            raise ProtocolError("record_after_end")
        now_wall_ms = _int(now_wall_ms, 0, MAX_SAFE_INTEGER)
        now_monotonic_ms = _int(now_monotonic_ms, 0, MAX_SAFE_INTEGER)
        if now_monotonic_ms < self._last_now_monotonic_ms:
            raise ProtocolError("clock_discontinuity")
        elapsed_now = now_monotonic_ms - self.started_monotonic_ms
        if abs((now_wall_ms - self.started_wall_ms) - elapsed_now) > 1_000:
            raise ProtocolError("clock_discontinuity")
        self._last_now_monotonic_ms = now_monotonic_ms
        if type(record) is OperationalSample:
            if record.sequence != self.sample_count + 1 or record.slot <= self.last_slot or record.elapsed_ms <= self.last_elapsed_ms:
                raise ProtocolError("nonmonotonic_sample")
            if record.elapsed_ms > elapsed_now + 100:
                raise ProtocolError("future_sample")
            self.sample_count += 1
            self.last_sample = record
            self.last_slot = record.slot
            self.last_elapsed_ms = record.elapsed_ms
            return
        if type(record) is OperationalEnd:
            if record.elapsed_ms < self.last_elapsed_ms or record.elapsed_ms > elapsed_now + 100:
                raise ProtocolError("future_end")
            self.end = record
            return
        raise ProtocolError("invalid_record_type")

