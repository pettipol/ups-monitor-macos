"""Pure E29 diagnostic assertions layered on the unchanged E27 validator.

The admission loader injects ``legacy`` and ``cleanup_parser``. This module
does not import project code, open files, sample clocks or start processes.
"""
import json

legacy = None
cleanup_parser = None
PREFIX = b"UPS_CLEANUP_DIAG_V1 "
MAX_CAPTURE = 1_048_576
EXTRA_SCENARIOS = (
    "diag-stop-result-false", "diag-release-result-false",
    "diag-complete-result-false", "diag-clock-result-false",
    "diag-all-results-false", "diag-stderr-write-fails",
    "diag-cleanup-reentry", "diag-atexit-pre-open",
)
MASKS = dict(zip(EXTRA_SCENARIOS[:5], (1, 2, 4, 8, 15)))
EXTRA_COUNTERS = frozenset({"diagnostic_write_calls", "diagnostic_forwarded_bytes",
                            "cleanup_reentries", "cleanup_result_mask"})
END_CODES = {"cancelled": 0, "device_lost": 1, "session_lost": 2,
             "guard_error": 3, "output_error": 4}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def _admitted():
    require(legacy is not None and cleanup_parser is not None, "dependencies_not_injected")


def _diagnostic(stderr, *, absent=False):
    parser = cleanup_parser.CleanupDiagnosticParser()
    parser.accept(stderr)
    snapshot = parser.snapshot(True)
    # Detect a misplaced reserved prefix too: the streaming parser correctly
    # ignores foreign lines, but the closed full-driver formatter must not hide
    # its record inside a foreign line or emit it twice anywhere in stderr.
    occurrences = stderr.count(PREFIX)
    require(occurrences == (0 if absent else 1), "diagnostic_occurrences")
    require(snapshot["state"] == ("absent" if absent else "valid"),
            "diagnostic_parser_state")
    if absent:
        return None, 0
    candidate = None
    for line, terminated in legacy._iter_lines(stderr, False):
        if PREFIX in line:
            require(candidate is None and line.startswith(PREFIX) and terminated,
                    "diagnostic_record_position")
            require(len(line) + 1 <= 1024 and line.isascii(), "diagnostic_record_bounds")
            candidate = line
    require(candidate is not None, "diagnostic_record_missing")
    return snapshot["diagnostic"], len(candidate) + 1


def _expected(scenario, summary):
    pre = scenario in {"stop-pre-open", "pre-open-dispose-fail",
                       "pre-open-postclock-invalid", "stop-layout", "diag-atexit-pre-open"}
    cancelled = scenario in legacy.EXPECTED_CANCELLED or scenario in {
        "cleanup-short", "cleanup-late", "pre-open-dispose-fail",
        "pre-open-postclock-invalid", *EXTRA_SCENARIOS,
    }
    vector = [1, 1, 1, 1]
    if scenario in {"cleanup-short", "cleanup-late"}:
        vector = [0, 1, 0, 1]
    elif scenario == "pre-open-dispose-fail":
        vector = [1, 0, 0, 1]
    elif scenario == "pre-open-postclock-invalid":
        vector = [1, 1, 0, 0]
    mask = MASKS.get(scenario, 0)
    vector = [value if not mask & (1 << bit) else 0 for bit, value in enumerate(vector)]
    before = 0 if cancelled else 3
    after = before if all(vector) else 3
    called = 0 if pre else 1
    kind = 0 if pre else (2 if scenario == "cleanup-short" else 3)
    rc = None if pre else (63 if scenario == "cleanup-short" else 64)
    return dict(v=1, reason_before=before, reason_after=after,
        phase_before=3, health_before=summary["reason"],
        phase_after=summary["phase"], health_after=summary["reason"],
        admitted=0 if pre else 1,
        stop_ok=vector[0], released=vector[1], complete=vector[2], clock_ok=vector[3],
        cleanup_attempted=called, cleanup_failed=summary["cleanup_failed"],
        write_called=called, write_kind=kind, write_rc=rc,
        cleanup_delta_ms=None if scenario == "pre-open-postclock-invalid" else
            (2000 if scenario == "cleanup-late" else 0))


def _new_summary(stderr, scenario):
    found = None
    count = 0
    for line, terminated in legacy._iter_lines(stderr, False):
        if legacy.SUMMARY_PREFIX in line:
            count += 1
            require(count == 1 and line.startswith(legacy.SUMMARY_PREFIX), "summary_count_or_position")
            require(terminated and len(line) + 1 <= legacy.MAX_RECORD_BYTES, "summary_bounds")
            try:
                found = json.loads(line[len(legacy.SUMMARY_PREFIX):].decode("ascii"),
                    object_pairs_hook=legacy._reject_duplicate_pairs,
                    parse_constant=legacy._reject_json_constant)
            except Exception:
                raise ValueError("summary_json") from None
    require(type(found) is dict and set(found) == legacy.SUMMARY_KEYS | EXTRA_COUNTERS,
            "summary_shape")
    for name in EXTRA_COUNTERS:
        high = 15 if name == "cleanup_result_mask" else legacy.MAX_COUNTER
        require(legacy._exact_int(found[name], 0, high), "diagnostic_counter_range")
    require(found["scenario"] == scenario, "summary_scenario")
    return found


def _new_contract(scenario, summary, stream, stdout, returncode, diagnostic_bytes):
    # The legacy generic checker is deliberately given the ORIGINAL new name.
    # No scenario aliasing, changes to the legacy closed matrix or catch/ignore.
    legacy._check_operational_summary(summary, scenario, stdout, returncode)
    require(summary["anchor_ms"] == 0 and summary["regressions"] == 0,
            "new_anchor_or_regression")
    require(summary["create"] == summary["dispose"] == summary["disposed"]
            == summary["finish_clock"] == summary["stop_requests"] == 1,
            "new_lifecycle")
    require(summary["cleanup_failed"] == 0 and summary["phase"] == 4
            and summary["reason"] == 1 and summary["cleanup_restop"] == 0,
            "new_shared_health")
    require(summary["sample_writes"] == summary["sample_flushes"] == stream["sample_count"]
            and summary["end_writes"] == stream["end_count"]
            and summary["publications"] <= stream["sample_count"], "new_output_accounting")
    require(summary["elapsed_ms"] >= stream["largest_elapsed_ms"], "new_elapsed_order")
    legacy._validate_end_summary_time(summary, stream)
    mask = MASKS.get(scenario, 0)
    require(summary["cleanup_result_mask"] == mask, "diagnostic_result_mask")
    require(summary["diagnostic_write_calls"] == 1, "diagnostic_attempt_count")
    require(summary["diagnostic_forwarded_bytes"] == diagnostic_bytes, "diagnostic_forwarded_bytes")
    require(summary["cleanup_reentries"] == (2 if scenario in {
        "diag-stderr-write-fails", "diag-cleanup-reentry"} else 0), "cleanup_reentries")
    no_end = scenario in {"diag-clock-result-false", "diag-all-results-false", "diag-atexit-pre-open"}
    require(stream["end_count"] == (0 if no_end else 1), "new_end_count")
    require(returncode == (1 if mask else 0), "new_exit_status")
    if not no_end:
        require(stream["end_reason"] == ("guard_error" if mask else "cancelled"), "new_end_reason")
    if scenario == "diag-atexit-pre-open":
        require(all(summary[name] == 0 for name in (
            "init", "select", "open", "layout", "close", "handshake_stop",
            "cleanup_stop", "init_byte", "read", "next", "wait", "publications")),
            "atexit_pre_open_activity")
        require(stream["sample_count"] == 0 and stdout == b"", "atexit_pre_open_sample")
    else:
        require(all(summary[name] == 1 for name in (
            "init", "select", "open", "layout", "close", "handshake_stop",
            "cleanup_stop", "init_byte")), "new_admitted_lifecycle")
        require(summary["next"] > 0 and summary["publications"] >= 1,
                "new_admitted_publication")
        if mask:
            require(summary["sample_writes"] == summary["sample_flushes"]
                    == summary["publications"] == 1 and summary["wait"] == 0,
                    "mask_first_before_wait_boundary")
        else:
            require(summary["elapsed_ms"] >= 10_000
                    and summary["read"] > 0
                    and summary["publications"] >= 2,
                    "natural_stop_elapsed_or_activity")


def validate(mode: str, scenario: str, stdout: bytes, stderr: bytes, returncode: int) -> dict:
    """Validate closed legacy/new replay captures; return only bounded facts."""
    _admitted()
    require(type(mode) is str and mode in legacy.MODES, "mode_invalid")
    require(type(scenario) is str and type(stdout) is bytes and type(stderr) is bytes,
            "capture_type")
    require(len(stdout) + len(stderr) <= MAX_CAPTURE, "capture_limit")
    require(type(returncode) is int and 0 <= returncode <= 255, "returncode_invalid")
    legacy._scan_stderr(stderr)
    if scenario not in EXTRA_SCENARIOS:
        # All 33 historical expectations run unchanged before E29 assertions.
        result = dict(legacy.validate(mode, scenario, stdout, stderr, returncode))
        absent = mode != "operational" or scenario == "cli-negative"
        record, _ = _diagnostic(stderr, absent=absent)
        if record is not None:
            summary = legacy._read_operational_summary(stderr, scenario)
            require(record == _expected(scenario, summary), "diagnostic_values")
            stream = legacy._parse_wire(stdout, 2, allow_empty=True)
            if stream["end_count"]:
                require(record["reason_after"] == END_CODES[stream["end_reason"]],
                        "diagnostic_end_reason")
        result.update(diagnostic_state="absent" if absent else "valid", qualification="natural")
        return result
    require(mode == "operational", "new_scenario_mode")
    summary = _new_summary(stderr, scenario)
    absent = scenario == "diag-stderr-write-fails"
    record, diagnostic_bytes = _diagnostic(stderr, absent=absent)
    stream = legacy._parse_wire(stdout, 2, allow_empty=True, require_dynamic_observed=True)
    _new_contract(scenario, summary, stream, stdout, returncode, diagnostic_bytes)
    if record is not None:
        require(record == _expected(scenario, summary), "diagnostic_values")
        if stream["end_count"]:
            require(record["reason_after"] == END_CODES[stream["end_reason"]], "diagnostic_end_reason")
    return dict(state="PASS_SCOPE_ONLY", mode=mode, scenario=scenario,
        diagnostic_state="absent_expected_fault" if absent else "valid",
        qualification="FAULT_INJECTED_RESULT_COPY" if scenario in MASKS else "natural",
        samples=stream["sample_count"], ends=stream["end_count"],
        execution="NOT_RUN_BY_VALIDATOR", hardware="NOT_RUN")
