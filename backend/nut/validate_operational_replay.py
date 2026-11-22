"""Pure validator for captured whole-driver fake replay streams.

The caller injects the already admitted protocol module into ``protocol``.
This module never imports repository code, opens files, starts processes, or
accesses a device. It validates caller-supplied bounded byte captures only.
"""

import json


protocol = None

MAX_CAPTURE_BYTES = 1_048_576
MAX_RECORD_BYTES = 8_192
MAX_COUNTER = 10_000_000
MAX_VIRTUAL_MS = 900_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991
SLOT_MS = 5_000
STATUS_MAX_AGE_MS = 10_000
SUMMARY_PREFIX = b"OPERATIONAL_REPLAY_SUMMARY "

OPERATIONAL_SCENARIOS = frozenset({
    "healthy-700s",
    "high-absolute-anchor",
    "stale-only",
    "partial-only",
    "stop-pre-open",
    "stop-layout",
    "stop-read",
    "read-transport-error",
    "stop-write",
    "stop-cleanup",
    "cleanup-short",
    "cleanup-late",
    "clock-regression",
    "flush-startup-14000",
    "flush-startup-10000",
    "flush-startup-10001",
    "pre-output-stale",
    "flush-active-stale",
    "pre-open-dispose-fail",
    "pre-open-postclock-invalid",
    "stop-before-wait",
    "stop-before-published",
    "error-before-stop",
})
MODES = frozenset({"operational", "v1-macro-off", "v1-opt-in-unused"})
DYNAMIC_FIELDS = (
    "ups.status",
    "battery.charge",
    "battery.runtime",
    "battery.voltage",
    "battery.temperature",
    "ups.temperature",
    "input.voltage",
    "input.frequency",
    "output.voltage",
    "output.current",
    "output.frequency",
    "ups.load",
    "experimental.ups.load.apparent",
    "ups.realpower",
    "ups.power",
)

SUMMARY_COUNTERS = frozenset({
    "anchor_ms", "elapsed_ms", "create", "init", "select", "open",
    "layout", "close", "dispose", "read", "wait", "clock", "finish_clock",
    "handshake_stop", "cleanup_stop", "init_byte", "next", "other_write",
    "ordinary_after_cleaning", "cleanup_restop", "stop_requests", "sample_writes",
    "sample_flushes", "end_writes", "stdout_bytes", "regressions",
    "max_next_gap_ms", "publications",
})
SUMMARY_FLAGS = frozenset({"disposed", "cleanup_failed", "overflow", "invalid_write"})
SUMMARY_KEYS = frozenset({
    "schema", "scenario", *SUMMARY_COUNTERS, *SUMMARY_FLAGS,
    "minimum_observed_ms", "minimum_observed_measured", "phase", "reason",
})
TRANSPORT_ERROR_SUMMARY_KEYS = frozenset({
    "read_error_injections", "ordinary_after_transport_error",
})
TRANSPORT_ERROR_SCENARIOS = frozenset({"read-transport-error", "error-before-stop"})
BOUNDARY_SUMMARY_KEYS = frozenset({
    "before_wait_hooks", "before_published_hooks",
    "next_before_wait", "next_before_published",
})
BOUNDARY_SCENARIOS = frozenset({"stop-before-wait", "stop-before-published"})
FAKE_COUNTER_KEYS = frozenset({
    "init", "select", "open", "close", "dispose", "read", "wait", "clock",
    "stop", "cleanup_stop", "init_byte", "next", "other_write", "now_ms",
    "finish_clock",
})
FAKE_PACING_KEYS = frozenset({
    "gap_count", "gap_max_ms", "gap_violations", "first_violation_gap_ms",
    "first_violation_previous_ms", "first_violation_next_ms", "last_next_ms",
    "next_after_cutoff", "read_after_cutoff", "acquisitions_after_cutoff",
})

PRE_ADMISSION = frozenset({
    "stop-pre-open", "pre-open-dispose-fail", "pre-open-postclock-invalid",
})
EXPECTED_CANCELLED = frozenset({
    "healthy-700s", "high-absolute-anchor", "stop-pre-open", "stop-layout",
    "stop-read", "stop-write", "stop-cleanup", "flush-startup-10000",
    "stop-before-wait", "stop-before-published",
})
_BAD_STDERR_MARKERS = (
    b"addresssanitizer", b"undefinedbehaviorsanitizer", b"threadsanitizer",
    b"leaksanitizer", b"memorysanitizer", b"sanitizer", b"runtime error:",
    b"runtime-error", b"operational_replay_error", b"closed_contract",
    b"unknown-scenario", b"unknown_scenario", b"unknown scenario",
    b"fatal_harness", b"fatal harness", b"harness_limit", b"limit_exceeded",
    b"output_limit", b"counter_limit", b"virtual_limit", b"forbidden sentinel",
    b"forbidden_sentinel", b"forbidden-sentinel", b"forbidden_io_sentinel",
    b"forbidden:", b"os sentinel",
)


def _fail(code):
    """Raise a fixed diagnostic that never embeds caller-controlled data."""
    raise ValueError(code)


def _require(condition, code):
    if not condition:
        _fail(code)


def _exact_int(value, low, high):
    return type(value) is int and low <= value <= high


def _require_rejected(call, expected_code):
    try:
        call()
    except ValueError as error:
        _require(str(error) == expected_code, "selfcheck_wrong_rejection")
        return
    _fail("selfcheck_mutation_accepted")


def _iter_lines(data, require_final_newline):
    position = 0
    while position < len(data):
        end = data.find(b"\n", position)
        if end < 0:
            if require_final_newline:
                _fail("line_not_terminated")
            yield data[position:], False
            return
        yield data[position:end], True
        position = end + 1


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value):
    _fail("nonfinite_json_number")


def _scan_stderr(stderr):
    lowered = stderr.lower()
    for marker in _BAD_STDERR_MARKERS:
        if marker in lowered:
            _fail("stderr_forbidden_marker")


def _require_operational_summary_shape(summary, scenario):
    expected_keys = SUMMARY_KEYS
    if scenario in TRANSPORT_ERROR_SCENARIOS:
        expected_keys |= TRANSPORT_ERROR_SUMMARY_KEYS
    if scenario in BOUNDARY_SCENARIOS:
        expected_keys |= BOUNDARY_SUMMARY_KEYS
    _require(type(summary) is dict and frozenset(summary) == expected_keys,
             "summary_shape")
    if scenario in TRANSPORT_ERROR_SCENARIOS:
        for name in TRANSPORT_ERROR_SUMMARY_KEYS:
            _require(_exact_int(summary[name], 0, MAX_COUNTER),
                     "transport_error_counter")
    if scenario in BOUNDARY_SCENARIOS:
        for name in BOUNDARY_SUMMARY_KEYS:
            _require(_exact_int(summary[name], 0, MAX_COUNTER),
                     "boundary_counter")


def _read_operational_summary(stderr, scenario):
    found = []
    for line, terminated in _iter_lines(stderr, False):
        if SUMMARY_PREFIX in line:
            _require(line.startswith(SUMMARY_PREFIX), "summary_prefix_position")
            _require(terminated and len(line) + 1 <= MAX_RECORD_BYTES,
                     "summary_line_bounds")
            found.append(line[len(SUMMARY_PREFIX):])
    _require(len(found) == 1, "summary_count")
    try:
        summary = json.loads(found[0].decode("utf-8", "strict"),
                             object_pairs_hook=_reject_duplicate_pairs,
                             parse_constant=_reject_json_constant)
    except Exception:
        _fail("summary_json_invalid")
    _require_operational_summary_shape(summary, scenario)
    return summary


def _check_operational_summary(summary, scenario, stdout, returncode):
    _require(type(summary["schema"]) is int and summary["schema"] == 1,
             "summary_schema")
    _require(type(summary["scenario"]) is str, "summary_scenario_type")
    expected_scenario = "healthy-700s" if scenario == "cli-negative" else scenario
    _require(summary["scenario"] == expected_scenario, "summary_scenario")

    for name in SUMMARY_COUNTERS:
        high = MAX_SAFE_INTEGER if name == "anchor_ms" else MAX_VIRTUAL_MS
        if name not in {"anchor_ms", "elapsed_ms", "max_next_gap_ms"}:
            high = MAX_COUNTER
        _require(_exact_int(summary[name], 0, high), "summary_counter")
    for name in SUMMARY_FLAGS:
        _require(type(summary[name]) is int and summary[name] in (0, 1),
                 "summary_flag")
    _require(summary["minimum_observed_ms"] is None
             and type(summary["minimum_observed_measured"]) is bool
             and summary["minimum_observed_measured"] is False,
             "summary_private_watermark")
    _require(type(summary["phase"]) is int and 0 <= summary["phase"] <= 4,
             "summary_phase")
    _require(type(summary["reason"]) is int and 0 <= summary["reason"] <= 7,
             "summary_reason")
    _require(summary["stdout_bytes"] == len(stdout), "stdout_byte_count")
    _require(summary["overflow"] == 0 and summary["invalid_write"] == 0,
             "host_bound_or_write_failure")
    _require(summary["other_write"] == 0
             and summary["ordinary_after_cleaning"] == 0,
             "forbidden_transport_write")
    if scenario != "cli-negative":
        _require(summary["create"] == 1, "native_create_count")
    _require(summary["open"] <= 1 and summary["init"] <= 1
             and summary["init_byte"] <= 1 and summary["cleanup_stop"] <= 1
             and summary["handshake_stop"] <= 1 and summary["close"] <= 1
             and summary["dispose"] <= 1,
             "duplicate_lifecycle_action")
    _require(returncode != 124, "harness_exit")


def _get_wire_types(version):
    if protocol is None:
        _fail("protocol_not_injected")
    try:
        if version == 2:
            return protocol.parse_line_v2, protocol.OperationalSample, protocol.OperationalEnd
        return protocol.parse_line, protocol.Sample, protocol.End
    except Exception:
        _fail("protocol_api_invalid")


def _parse_wire(stdout, version, allow_empty=False, require_dynamic_observed=False,
                require_dynamic_fresh=False):
    parser, sample_type, end_type = _get_wire_types(version)
    _require(type(stdout) is bytes, "stdout_type")
    _require(bool(stdout) or allow_empty, "stdout_empty")
    position = 0
    sample_count = 0
    end_count = 0
    last_elapsed = -1
    last_slot = -1
    largest_elapsed = 0
    last_observations = {}
    sample_facts = []
    first_end_reason = None
    first_end_elapsed = None
    while position < len(stdout):
        end = stdout.find(b"\n", position)
        _require(end >= 0, "wire_record_not_terminated")
        line = stdout[position:end + 1]
        _require(0 < len(line) <= MAX_RECORD_BYTES, "wire_record_bounds")
        _require(line != b"\n", "wire_blank_record")
        try:
            record = parser(line)
        except Exception:
            _fail("wire_record_invalid")
        if type(record) is sample_type:
            _require(end_count == 0, "sample_after_end")
            sequence = getattr(record, "sequence", None)
            slot = getattr(record, "slot", None)
            missed = getattr(record, "missed_slots", None)
            elapsed = getattr(record, "elapsed_ms", None)
            _require(_exact_int(sequence, 1, MAX_SAFE_INTEGER)
                     and sequence == sample_count + 1,
                     "sample_sequence")
            _require(_exact_int(elapsed, 0, MAX_SAFE_INTEGER)
                     and elapsed > last_elapsed,
                     "sample_elapsed")
            _require(_exact_int(slot, 0, MAX_SAFE_INTEGER)
                     and slot > last_slot and slot == elapsed // SLOT_MS,
                     "sample_slot")
            _require(_exact_int(missed, 0, MAX_SAFE_INTEGER)
                     and missed == slot + 1 - sequence,
                     "sample_missed_slots")
            if version == 1:
                _require(slot == sequence - 1 and sequence <= 24,
                         "v1_full_slot_sequence")
            fields = getattr(record, "fields", None)
            _require(type(fields) is dict, "sample_fields")
            sample_count += 1
            sample_observations = {}
            for name in DYNAMIC_FIELDS:
                field = fields.get(name)
                if version == 1 or require_dynamic_observed or require_dynamic_fresh:
                    _require(field is not None, "dynamic_field_missing")
                if field is None:
                    continue
                state = getattr(field, "state", None)
                observed = getattr(field, "observed_ms", None)
                if name in DYNAMIC_FIELDS and state == "observed":
                    _require(_exact_int(observed, 0, MAX_SAFE_INTEGER)
                             and observed <= elapsed,
                             "dynamic_timestamp_range")
                    last = last_observations.get(name)
                    if version == 1 or require_dynamic_fresh:
                        _require(last is None or observed > last,
                                 "dynamic_timestamp_not_advanced")
                    if version == 1 or require_dynamic_fresh:
                        _require(elapsed - observed <= STATUS_MAX_AGE_MS,
                                 "dynamic_timestamp_stale")
                    last_observations[name] = observed
                    sample_observations[name] = observed
                elif version == 1 or require_dynamic_observed or require_dynamic_fresh:
                    _fail("dynamic_field_unobserved")
            if require_dynamic_fresh:
                _require(all(name in last_observations for name in DYNAMIC_FIELDS),
                         "healthy_dynamic_coverage")
            sample_facts.append({
                "elapsed_ms": elapsed,
                "observed_ms": tuple(sample_observations.get(name)
                                     for name in DYNAMIC_FIELDS),
            })
            last_slot, last_elapsed = slot, elapsed
            if elapsed > largest_elapsed:
                largest_elapsed = elapsed
        elif type(record) is end_type:
            end_count += 1
            _require(end_count == 1 and end == len(stdout) - 1,
                     "terminal_record_order")
            elapsed = getattr(record, "elapsed_ms", None)
            reason = getattr(record, "reason", None)
            _require(_exact_int(elapsed, 0, MAX_SAFE_INTEGER)
                     and elapsed >= last_elapsed,
                     "terminal_elapsed")
            _require(type(reason) is str, "terminal_reason_type")
            first_end_reason, first_end_elapsed = reason, elapsed
            if elapsed > largest_elapsed:
                largest_elapsed = elapsed
        else:
            _fail("wire_record_type")
        position = end + 1
    return {
        "sample_count": sample_count,
        "sample_facts": tuple(sample_facts),
        "end_count": end_count,
        "end_reason": first_end_reason,
        "end_elapsed_ms": first_end_elapsed,
        "largest_elapsed_ms": largest_elapsed,
    }


def _parse_v1_counter_line(stderr, prefix, expected_keys):
    matches = []
    for line, terminated in _iter_lines(stderr, False):
        if line.startswith(prefix):
            _require(terminated and len(line) + 1 <= MAX_RECORD_BYTES,
                     "v1_counter_summary_bounds")
            matches.append(line)
    _require(len(matches) == 1, "v1_counter_summary_count")
    try:
        text = matches[0][len(prefix):].decode("ascii", "strict")
    except UnicodeDecodeError:
        _fail("v1_counter_summary_encoding")
    parsed = {}
    for token in text.split():
        key, separator, raw = token.partition("=")
        _require(separator == "=" and key not in parsed
                 and key in expected_keys and raw.isascii() and raw.isdigit(),
                 "v1_counter_token")
        parsed[key] = int(raw, 10)
    _require(frozenset(parsed) == expected_keys, "v1_counter_schema")
    # The original v1 pacing host has unsigned-int counters, not the new
    # operational host's 10-million counter guard. Clock calls may exceed that
    # newer limit during the fixed 120-second v1 simulation. Time values are
    # still bounded by this closed scenario's lifetime.
    for key, value in parsed.items():
        high = 120_000 if key.endswith("_ms") else 2**32 - 1
        _require(_exact_int(value, 0, high), "v1_counter_range")
    return parsed


def _validate_v1(mode, scenario, stdout, stderr, returncode):
    _require(scenario == "next-gap-budget", "v1_scenario")
    _require(returncode == 0, "v1_exit_status")
    records = _parse_wire(stdout, 1)
    _require(records["sample_count"] == 24 and records["end_count"] == 1,
             "v1_record_count")
    _require(records["end_reason"] == "duration_complete"
             and records["end_elapsed_ms"] == 120_000,
             "v1_terminal_outcome")

    counters = _parse_v1_counter_line(stderr, b"FAKE_COUNTERS ", FAKE_COUNTER_KEYS)
    pacing = _parse_v1_counter_line(stderr, b"FAKE_PACING ", FAKE_PACING_KEYS)
    _require(counters["init"] == 1 and counters["init_byte"] == 1
             and counters["select"] == 1 and counters["open"] == 1
             and counters["close"] == 1 and counters["dispose"] == 1
             and counters["finish_clock"] == 1,
             "v1_lifecycle_counts")
    _require(counters["stop"] == 2 and counters["cleanup_stop"] == 1
             and counters["other_write"] == 0 and counters["next"] > 0,
             "v1_transport_counts")
    _require(pacing["gap_count"] == counters["next"] - 1
             and pacing["gap_violations"] == 0
             and pacing["gap_max_ms"] <= 250,
             "v1_pacing_counts")
    _require(pacing["acquisitions_after_cutoff"]
             == pacing["next_after_cutoff"] + pacing["read_after_cutoff"] == 0
             and pacing["last_next_ms"] < 120_000,
             "v1_cutoff_counts")
    _require(counters["wait"] == 0, "v1_wait_counter")
    return {
        "state": "PASS_SCOPE_ONLY",
        "mode": mode,
        "scenario": scenario,
        "samples": records["sample_count"],
        "ends": records["end_count"],
        "largest_elapsed_ms": records["largest_elapsed_ms"],
        "counts": {
            "next": counters["next"],
            "open": counters["open"],
            "close": counters["close"],
            "dispose": counters["dispose"],
            "cleanup_stop": counters["cleanup_stop"],
        },
        "pacing_gap_max_ms": pacing["gap_max_ms"],
        "dynamic_fields_refreshed": len(DYNAMIC_FIELDS),
        "execution": "NOT_RUN_BY_VALIDATOR",
    }


def _validate_cli_negative(summary, stream, stdout, returncode):
    _require(returncode > 0, "cli_negative_exit_status")
    _require(summary["anchor_ms"] == 0, "cli_negative_anchor")
    _require(stdout == b"" and stream["sample_count"] == 0
             and stream["end_count"] == 0,
             "cli_negative_stdout")
    _require(summary["create"] == 0 and summary["open"] == 0,
             "cli_negative_native_admission")
    report_counters = (
        "init", "select", "layout", "close", "dispose", "handshake_stop",
        "cleanup_stop", "init_byte", "next", "other_write", "ordinary_after_cleaning",
        "sample_writes", "sample_flushes", "end_writes", "publications",
    )
    _require(all(summary[name] == 0 for name in report_counters),
             "cli_negative_report_activity")
    _require(summary["disposed"] == 0 and summary["phase"] == 0
             and summary["reason"] == 0,
             "cli_negative_health_state")


def _validate_end_summary_time(summary, stream):
    if stream["end_count"]:
        _require(stream["end_elapsed_ms"] == summary["elapsed_ms"],
                 "end_summary_elapsed_mismatch")


def _validate_flush_expectation(scenario, summary, stream):
    facts = stream["sample_facts"]
    if scenario in {"flush-startup-14000", "flush-startup-10001"}:
        _require(len(facts) == 1 and facts[0]["elapsed_ms"] == 9000
                 and all(value == 0 for value in facts[0]["observed_ms"]),
                 "startup_flush_fault_timing")
        expected_elapsed = 14000 if scenario == "flush-startup-14000" else 10001
        _require(summary["reason"] == 6
                 and summary["elapsed_ms"] == expected_elapsed
                 and summary["publications"] == 0,
                 "startup_flush_io_outcome")
    elif scenario == "flush-startup-10000":
        _require(len(facts) == 1 and facts[0]["elapsed_ms"] == 9000
                 and all(value == 0 for value in facts[0]["observed_ms"]),
                 "startup_boundary_fault_timing")
    elif scenario == "flush-active-stale":
        _require(len(facts) == 2
                 and facts[0]["elapsed_ms"] == 0
                 and all(value == 0 for value in facts[0]["observed_ms"])
                 and facts[1]["elapsed_ms"] == 9000
                 and all(value == 5000 for value in facts[1]["observed_ms"]),
                 "active_flush_fault_timing")
        _require(summary["reason"] == 6 and summary["elapsed_ms"] == 16000
                 and summary["publications"] == 1,
                 "active_flush_io_outcome")


def _validate_partial_reason(summary):
    _require(summary["reason"] == 3, "partial_only_outcome")


def _validate_transport_error_contract(summary, stream, returncode):
    _require(summary["read_error_injections"] == 1,
             "transport_error_injection_count")
    _require(summary["ordinary_after_transport_error"] == 0,
             "transport_error_followup_io")
    _require(stream["sample_count"] == summary["sample_writes"]
             == summary["sample_flushes"] == summary["publications"] == 1,
             "transport_error_publication_count")
    _require(summary["reason"] == 6 and summary["phase"] == 4
             and summary["cleanup_failed"] == 0,
             "transport_error_health_outcome")
    _require(all(summary[name] == 1 for name in (
        "create", "init", "select", "open", "layout", "handshake_stop",
        "init_byte", "close", "dispose", "finish_clock", "disposed",
        "cleanup_stop", "end_writes",
    )), "transport_error_lifecycle")
    _require(summary["next"] > 0 and summary["cleanup_restop"] == 0
             and summary["stop_requests"] == 0
             and summary["ordinary_after_cleaning"] == 0
             and summary["other_write"] == 0
             and summary["invalid_write"] == 0
             and summary["overflow"] == 0,
             "transport_error_forbidden_activity")
    _require(stream["end_count"] == 1
             and stream["end_reason"] == "guard_error"
             and stream["end_elapsed_ms"] == summary["elapsed_ms"]
             and stream["end_elapsed_ms"] >= stream["largest_elapsed_ms"]
             and returncode == 1,
             "transport_error_terminal_outcome")


def run_transport_error_mutation_selfchecks():
    """Exercise E19 acceptance predicates with pure synthetic dictionaries."""
    base_summary = {
        "read_error_injections": 1, "ordinary_after_transport_error": 0,
        "sample_writes": 1, "sample_flushes": 1, "publications": 1,
        "reason": 6, "phase": 4, "cleanup_failed": 0,
        "create": 1, "init": 1, "select": 1, "open": 1, "layout": 1,
        "handshake_stop": 1, "init_byte": 1, "close": 1, "dispose": 1,
        "finish_clock": 1, "disposed": 1, "cleanup_stop": 1, "end_writes": 1,
        "next": 1, "cleanup_restop": 0, "stop_requests": 0,
        "ordinary_after_cleaning": 0, "other_write": 0, "invalid_write": 0,
        "overflow": 0, "elapsed_ms": 1000,
    }
    base_stream = {
        "sample_count": 1, "end_count": 1, "end_reason": "guard_error",
        "end_elapsed_ms": 1000, "largest_elapsed_ms": 1000,
    }
    _validate_transport_error_contract(base_summary, base_stream, 1)
    historical_shape = {key: 0 for key in SUMMARY_KEYS}
    historical_shape.update({
        "schema": 1, "scenario": "stop-read", "minimum_observed_ms": None,
        "minimum_observed_measured": False,
    })
    _require_operational_summary_shape(historical_shape, "stop-read")
    _require_rejected(lambda: _require_operational_summary_shape(
        historical_shape, "read-transport-error"), "summary_shape")
    e19_shape = dict(historical_shape)
    e19_shape["scenario"] = "read-transport-error"
    e19_shape.update({"read_error_injections": 1,
                      "ordinary_after_transport_error": 0})
    _require_operational_summary_shape(e19_shape, "read-transport-error")
    _require_rejected(lambda: _require_operational_summary_shape(
        e19_shape, "stop-read"), "summary_shape")
    e19_shape.pop("ordinary_after_transport_error")
    _require_rejected(lambda: _require_operational_summary_shape(
        e19_shape, "read-transport-error"), "summary_shape")
    e19_shape["ordinary_after_transport_error"] = 0
    e19_shape["read_error_injections"] = True
    _require_rejected(lambda: _require_operational_summary_shape(
        e19_shape, "read-transport-error"), "transport_error_counter")
    mutations = (
        ("read_error_injections", 0), ("read_error_injections", 2),
        ("ordinary_after_transport_error", 1), ("publications", 0),
        ("publications", 2), ("sample_writes", 0), ("sample_flushes", 2),
        ("reason", 1), ("reason", 2),
        ("cleanup_stop", 0), ("cleanup_stop", 2), ("close", 0),
        ("dispose", 0), ("init", 0), ("handshake_stop", 0),
        ("finish_clock", 0), ("disposed", 0), ("end_writes", 0),
        ("cleanup_restop", 1), ("ordinary_after_cleaning", 1),
        ("other_write", 1), ("overflow", 1), ("cleanup_failed", 1),
        ("stop_requests", 1),
        ("end_count", 0), ("end_count", 2), ("end_reason", "cancelled"),
        ("end_reason", "device_lost"), ("end_elapsed_ms", 999),
        ("returncode", 0),
    )
    for key, value in mutations:
        summary = dict(base_summary)
        stream = dict(base_stream)
        code = 1
        if key == "returncode":
            code = value
        elif key in {"sample_count", "end_count", "end_reason", "end_elapsed_ms"}:
            stream[key] = value
        else:
            summary[key] = value
        try:
            _validate_transport_error_contract(summary, stream, code)
        except ValueError:
            continue
        _fail("transport_error_selfcheck_mutation_accepted")
    return {"state": "PURE_TRANSPORT_ERROR_MUTATION_SELFCHECKS_PASS",
            "cases": len(mutations) + 4}


def run_pure_mutation_selfchecks():
    """Prove selected stale expectations fail using synthetic scalar inputs."""
    sample = {"elapsed_ms": 9000, "observed_ms": (0,) * len(DYNAMIC_FIELDS)}
    stream = {"sample_facts": (sample,)}
    _require_rejected(lambda: _validate_flush_expectation(
        "flush-startup-14000",
        {"reason": 2, "elapsed_ms": 35000, "publications": 0}, stream),
        "startup_flush_io_outcome")
    _require_rejected(lambda: _validate_end_summary_time(
        {"elapsed_ms": 16000},
        {"end_count": 1, "end_elapsed_ms": 14000}),
        "end_summary_elapsed_mismatch")
    _require_rejected(lambda: _validate_partial_reason({"reason": 4}),
                      "partial_only_outcome")
    _require_rejected(lambda: _validate_partial_reason({"reason": 6}),
                      "partial_only_outcome")
    return {"state": "PURE_MUTATION_SELFCHECKS_PASS", "cases": 4}


def _validate_operational(scenario, stdout, stderr, returncode):
    _require(scenario in OPERATIONAL_SCENARIOS or scenario == "cli-negative",
             "operational_scenario")
    summary = _read_operational_summary(stderr, scenario)
    _check_operational_summary(summary, scenario, stdout, returncode)
    healthy_scenario = scenario in {"healthy-700s", "high-absolute-anchor"}
    stream = _parse_wire(stdout, 2, allow_empty=scenario in {
        "cli-negative", "pre-open-postclock-invalid",
    }, require_dynamic_observed=True, require_dynamic_fresh=healthy_scenario)
    _require(summary["sample_writes"] == stream["sample_count"]
             and summary["sample_flushes"] == stream["sample_count"]
             and summary["end_writes"] == stream["end_count"],
             "output_accounting")
    _require(summary["publications"] <= stream["sample_count"],
             "publication_exceeds_flush")
    _require(summary["elapsed_ms"] >= stream["largest_elapsed_ms"],
             "summary_elapsed_order")
    _validate_end_summary_time(summary, stream)
    if scenario == "cli-negative":
        _validate_cli_negative(summary, stream, stdout, returncode)
        return {
            "state": "PASS_SCOPE_ONLY", "mode": "operational",
            "scenario": scenario, "host_scenario": summary["scenario"],
            "samples": 0, "ends": 0, "largest_elapsed_ms": summary["elapsed_ms"],
            "counts": {"create": 0, "open": 0, "samples": 0, "ends": 0},
            "native_create": 0, "native_open": 0,
            "execution": "NOT_RUN_BY_VALIDATOR",
        }

    _require(summary["anchor_ms"] == (2**32 + 12345
             if scenario == "high-absolute-anchor" else 0),
             "scenario_anchor")
    successful = scenario in EXPECTED_CANCELLED
    has_end = scenario != "pre-open-postclock-invalid"
    _require(stream["end_count"] == (1 if has_end else 0), "scenario_end_count")
    if has_end:
        expected_reason = "cancelled" if successful else "guard_error"
        _require(stream["end_reason"] == expected_reason, "scenario_end_reason")
        _require((returncode == 0) if successful else (returncode > 0),
                 "scenario_exit_status")
    else:
        _require(returncode > 0 and stdout == b"", "postclock_invalid_outcome")

    _require(summary["create"] == 1 and summary["dispose"] == 1,
             "scenario_create_dispose")
    _require(summary["disposed"] == (0 if scenario == "pre-open-dispose-fail" else 1),
             "scenario_disposed")
    if scenario in PRE_ADMISSION:
        _require(all(summary[name] == 0 for name in (
            "init", "select", "open", "layout", "close", "handshake_stop",
            "cleanup_stop", "init_byte", "read", "next",
        )) and stream["sample_count"] == 0 and summary["publications"] == 0,
                 "pre_admission_activity")
    elif scenario == "stop-layout":
        _require(all(summary[name] == 1 for name in (
            "init", "select", "open", "layout", "close",
        )), "layout_stop_lifecycle")
        _require(all(summary[name] == 0 for name in (
            "handshake_stop", "cleanup_stop", "init_byte", "read", "next",
        )) and stream["sample_count"] == 0 and summary["publications"] == 0,
                 "layout_stop_io")
    else:
        _require(all(summary[name] == 1 for name in (
            "init", "select", "open", "layout", "close", "handshake_stop",
            "cleanup_stop", "init_byte",
        )), "admitted_lifecycle")
        _require(summary["next"] > 0, "admitted_no_next")

    _require(summary["phase"] == (3 if scenario == "pre-open-dispose-fail" else 4),
             "scenario_phase")
    _require(summary["cleanup_failed"] == (1 if scenario in {
        "cleanup-short", "cleanup-late", "pre-open-postclock-invalid",
    } else 0), "scenario_cleanup_status")
    _require(summary["cleanup_restop"] == (1 if scenario == "stop-cleanup" else 0),
             "scenario_restop")
    _require(summary["regressions"] == (1 if scenario == "clock-regression" else 0),
             "scenario_regressions")
    _require(summary["stop_requests"] == (1 if scenario in {
        "healthy-700s", "high-absolute-anchor", "stop-pre-open", "stop-layout",
        "stop-read", "stop-write", "stop-cleanup", "cleanup-short", "cleanup-late",
        "flush-startup-10000", "pre-open-dispose-fail",
        "pre-open-postclock-invalid",
        "stop-before-wait", "stop-before-published", "error-before-stop",
    } else 0), "scenario_stop_requests")

    if scenario in {"healthy-700s", "high-absolute-anchor"}:
        _require(summary["anchor_ms"] == (2**32 + 12345 if scenario == "high-absolute-anchor" else 0),
                 "healthy_anchor")
        _require(summary["elapsed_ms"] > 600_000
                 and stream["largest_elapsed_ms"] > 600_000
                 and stream["sample_count"] >= 140
                 and stream["sample_count"] <= 180,
                 "healthy_duration_or_samples")
        _require(summary["publications"] == summary["sample_flushes"]
                 and summary["publications"] == summary["sample_writes"]
                 and summary["reason"] == 1
                 and summary["handshake_stop"] == 1
                 and summary["cleanup_stop"] == 1
                 and summary["init_byte"] == 1
                 and summary["max_next_gap_ms"] <= 250,
                 "healthy_publication_or_pacing")
    elif scenario == "stale-only":
        _require(stream["sample_count"] == 1 and summary["publications"] == 1
                 and summary["reason"] == 3 and summary["elapsed_ms"] >= 15_000,
                 "stale_only_outcome")
    elif scenario == "partial-only":
        _require(stream["sample_count"] <= 1
                 and summary["publications"] <= 1
                 and summary["elapsed_ms"] >= 15_000,
                 "partial_only_outcome")
        _validate_partial_reason(summary)
    elif scenario in {"flush-startup-14000", "flush-startup-10001"}:
        _require(stream["sample_count"] == 1 and summary["publications"] == 0
                 and summary["reason"] == 6,
                 "startup_flush_stale_outcome")
    elif scenario == "flush-startup-10000":
        _require(stream["sample_count"] == 1 and summary["publications"] == 1
                 and summary["reason"] == 1,
                 "startup_flush_boundary_outcome")
    elif scenario == "pre-output-stale":
        _require(stream["sample_count"] == 0 and summary["publications"] == 0
                 and summary["reason"] == 2 and summary["elapsed_ms"] >= 35_000,
                 "pre_output_stale_outcome")
    elif scenario == "flush-active-stale":
        _require(stream["sample_count"] == 2 and summary["publications"] == 1
                 and summary["reason"] == 6,
                 "active_flush_stale_outcome")
    elif scenario == "clock-regression":
        _require(summary["regressions"] == 1 and summary["reason"] == 4
                 and summary["elapsed_ms"] >= 1_000,
                 "clock_regression_outcome")
    elif scenario in {"cleanup-short", "cleanup-late"}:
        _require(summary["cleanup_failed"] == 1 and summary["reason"] == 1
                 and summary["elapsed_ms"] >= 10_000,
                 "cleanup_failure_outcome")
        if scenario == "cleanup-late":
            _require(summary["elapsed_ms"] == 12_000,
                     "cleanup_late_exact_elapsed")
    elif scenario == "stop-cleanup":
        _require(summary["reason"] == 1 and summary["elapsed_ms"] >= 10_000,
                 "stop_cleanup_outcome")
    elif scenario == "stop-before-wait":
        _require(stream["sample_count"] == summary["sample_writes"]
                 == summary["sample_flushes"] == summary["publications"] == 1
                 and summary["reason"] == 1 and summary["wait"] == 0
                 and summary["before_wait_hooks"] == 1
                 and summary["before_published_hooks"] == 1
                 and summary["next"] == summary["next_before_wait"],
                 "stop_before_wait_boundary")
    elif scenario == "stop-before-published":
        _require(stream["sample_count"] == summary["sample_writes"]
                 == summary["sample_flushes"] == 1
                 and summary["publications"] == 0 and summary["reason"] == 1
                 and summary["before_published_hooks"] == 1
                 and summary["before_wait_hooks"] == 0
                 and summary["next"] == summary["next_before_published"],
                 "stop_before_published_boundary")
    elif scenario in {"stop-read", "stop-write"}:
        _require(stream["sample_count"] == 1 and summary["publications"] == 1
                 and summary["reason"] == 1,
                 "admitted_stop_outcome")
    elif scenario == "read-transport-error":
        _validate_transport_error_contract(summary, stream, returncode)
    elif scenario == "error-before-stop":
        _require(summary["read_error_injections"] == 1
                 and summary["ordinary_after_transport_error"] == 0
                 and stream["sample_count"] == summary["publications"] == 1
                 and summary["reason"] == 6 and summary["stop_requests"] == 1
                 and stream["end_reason"] == "guard_error" and returncode > 0
                 and summary["cleanup_stop"] == summary["close"]
                 == summary["dispose"] == 1,
                 "error_before_stop_preserves_first_terminal")
    elif scenario == "pre-open-dispose-fail":
        _require(summary["reason"] == 1 and summary["phase"] == 3
                 and summary["disposed"] == 0 and summary["dispose"] == 1,
                 "dispose_failure_outcome")
    elif scenario == "pre-open-postclock-invalid":
        _require(summary["reason"] == 1 and summary["cleanup_failed"] == 1
                 and summary["disposed"] == 1 and summary["end_writes"] == 0,
                 "postfinish_clock_failure_outcome")
    elif scenario in {"stop-pre-open", "stop-layout", "stop-read", "stop-write"}:
        _require(summary["reason"] == 1, "stop_reason")

    _validate_flush_expectation(scenario, summary, stream)

    return {
        "state": "PASS_SCOPE_ONLY",
        "mode": "operational",
        "scenario": scenario,
        "samples": stream["sample_count"],
        "ends": stream["end_count"],
        "largest_elapsed_ms": stream["largest_elapsed_ms"],
        "counts": {
            "publications": summary["publications"],
            "create": summary["create"],
            "open": summary["open"],
            "close": summary["close"],
            "dispose": summary["dispose"],
            "handshake_stop": summary["handshake_stop"],
            "cleanup_stop": summary["cleanup_stop"],
            "next": summary["next"],
        },
        "publications": summary["publications"],
        "health_reason_code": summary["reason"],
        "end_reason": stream["end_reason"],
        "minimum_observed_ms": None,
        "minimum_observed_measured": False,
        "execution": "NOT_RUN_BY_VALIDATOR",
    }


def validate(mode: str, scenario: str, stdout: bytes, stderr: bytes,
             returncode: int) -> dict:
    """Validate one bounded synthetic replay capture and return a safe summary."""
    _require(type(mode) is str and mode in MODES, "mode_invalid")
    _require(type(scenario) is str, "scenario_type")
    _require(type(stdout) is bytes and type(stderr) is bytes, "capture_type")
    _require(type(returncode) is int and -255 <= returncode <= 255,
             "returncode_type_or_range")
    _require(returncode >= 0, "signal_terminated")
    _require(len(stdout) + len(stderr) <= MAX_CAPTURE_BYTES, "capture_limit")
    _scan_stderr(stderr)
    if mode == "operational":
        return _validate_operational(scenario, stdout, stderr, returncode)
    return _validate_v1(mode, scenario, stdout, stderr, returncode)
