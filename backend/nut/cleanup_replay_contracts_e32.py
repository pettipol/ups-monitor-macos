"""E32 validator contracts over synthetic cleanup-diagnostic captures.

The public replay runner injects its pinned runner and validator dependencies
before collecting these tests. Fixtures are synthetic bytes, not device data.
"""
import json
import unittest
from unittest import mock

validator = orchestrator = adapter = None
NEW_CASES = (
    "diag-stop-result-false", "diag-release-result-false", "diag-complete-result-false",
    "diag-clock-result-false", "diag-all-results-false", "diag-stderr-write-fails",
    "diag-cleanup-reentry", "diag-atexit-pre-open",
)
VECTORS = ((0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 0, 1), (1, 1, 1, 0),
           (0, 0, 0, 0), (1, 1, 1, 1), (1, 1, 1, 1), (1, 1, 1, 1))
MASK_VALUES = (1, 2, 4, 8, 15, 0, 0, 0)


def line(value):
    return (json.dumps(value, separators=(",", ":")) + "\n").encode("ascii")


def sample(sequence=1, elapsed=0):
    # Full public field allowlist, with coherent 1%=1 W/VA at 100 nominal.
    fields = {}
    for name, kind in validator.legacy.protocol.FIELD_KINDS.items():
        fields[name] = dict(value="OL" if name == "ups.status" else
            ("100" if name.endswith(".nominal") else "1"), observed_ms=elapsed,
            kind=kind, state="observed")
    return line(dict(protocol="ups-monitor.continuous.v2", schema_version=2,
        type="sample", sequence=sequence, slot=elapsed // 5000,
        elapsed_ms=elapsed, missed_slots=elapsed // 5000 + 1 - sequence, fields=fields))


def fixture(scenario):
    index = NEW_CASES.index(scenario)
    pre = index == 7
    mask = MASK_VALUES[index]
    no_end = index in (3, 4, 7)
    natural = index in (5, 6)
    elapsed = 0 if pre else (10_000 if natural else 200)
    stdout = b"" if pre else sample()
    if natural:
        stdout += sample(2, 5000)
    if not no_end:
        stdout += line(dict(protocol="ups-monitor.continuous.v2", schema_version=2,
            type="end", elapsed_ms=elapsed, reason="guard_error" if mask else "cancelled"))
    summary = {key: 0 for key in validator.legacy.SUMMARY_COUNTERS | validator.legacy.SUMMARY_FLAGS}
    summary.update(schema=1, scenario=scenario, elapsed_ms=elapsed,
        create=1, dispose=1, disposed=1, finish_clock=1, stop_requests=1,
        sample_writes=0 if pre else (2 if natural else 1),
        sample_flushes=0 if pre else (2 if natural else 1),
        publications=0 if pre else (2 if natural else 1), end_writes=0 if no_end else 1,
        stdout_bytes=len(stdout), minimum_observed_ms=None,
        minimum_observed_measured=False, phase=4, reason=1)
    if not pre:
        for key in ("init", "select", "open", "layout", "close", "handshake_stop", "cleanup_stop", "init_byte"):
            summary[key] = 1
        summary["next"] = 8
    if natural:
        summary.update(read=20, wait=0, next=20)
    stop, released, complete, clock = VECTORS[index]
    diagnostic = dict(v=1, reason_before=0, reason_after=3 if mask else 0,
        phase_before=3, health_before=1, phase_after=4, health_after=1,
        admitted=0 if pre else 1, stop_ok=stop, released=released, complete=complete,
        clock_ok=clock, cleanup_attempted=0 if pre else 1, cleanup_failed=0,
        write_called=0 if pre else 1, write_kind=0 if pre else 3,
        write_rc=None if pre else 64, cleanup_delta_ms=0)
    diagnostic_line = b"" if index == 5 else b"UPS_CLEANUP_DIAG_V1 " + line(diagnostic)
    summary.update(diagnostic_write_calls=1, diagnostic_forwarded_bytes=len(diagnostic_line),
        cleanup_reentries=2 if index in (5, 6) else 0, cleanup_result_mask=mask)
    return stdout, summary, diagnostic, diagnostic_line, 1 if mask else 0


def capture(scenario, *, change_summary=None, change_diagnostic=None, extra=b""):
    stdout, summary, diagnostic, diagnostic_line, code = fixture(scenario)
    if change_diagnostic is not None:
        change_diagnostic(diagnostic)
        diagnostic_line = b"UPS_CLEANUP_DIAG_V1 " + line(diagnostic)
        summary["diagnostic_forwarded_bytes"] = len(diagnostic_line)
    if change_summary is not None:
        change_summary(summary)
    stderr = diagnostic_line + extra + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary)
    return stdout, stderr, code


class ValidatorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if validator is None or orchestrator is None or adapter is None:
            raise AssertionError("pinned E32 runner and validator dependencies must be injected")

    def validate(self, name, **options):
        return validator.validate("operational", name, *capture(name, **options))

    def test_eight_independent_positive_fixtures_and_closed_matrix41(self):
        historic = adapter.fixed_cases()
        self.assertEqual(len(historic), 33)
        self.assertEqual(len({row[0] for row in historic} | set(NEW_CASES)), 41)
        self.assertEqual(tuple(validator.EXTRA_SCENARIOS), NEW_CASES)
        self.assertEqual(tuple(orchestrator.EXTRA_SCENARIOS), NEW_CASES)
        self.assertEqual(sum(row[1] != "operational" for row in historic), 2)
        self.assertEqual(sum(row[2] == "cli-negative" for row in historic), 8)
        for name in NEW_CASES:
            with self.subTest(name=name):
                result = self.validate(name)
                self.assertEqual(result["state"], "PASS_SCOPE_ONLY")
                self.assertEqual(result["qualification"],
                    "FAULT_INJECTED_RESULT_COPY" if name in NEW_CASES[:5] else "natural")

    def test_each_of_eighteen_diagnostic_fields_is_authoritative(self):
        mutations = dict(v=2, reason_before=1, reason_after=1, phase_before=2,
            health_before=2, phase_after=3, health_after=2, admitted=0, stop_ok=1,
            released=0, complete=0, clock_ok=0, cleanup_attempted=0,
            cleanup_failed=1, write_called=0, write_kind=1, write_rc=63, cleanup_delta_ms=1)
        self.assertEqual(len(mutations), 18)
        for key, value in mutations.items():
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.validate(NEW_CASES[0], change_diagnostic=lambda record: record.update({key: value}))

    def test_diagnostic_extra_missing_duplicate_keys_and_duplicate_record_rejected(self):
        name = NEW_CASES[0]
        for mutate in (lambda d: d.update(extra=1), lambda d: d.pop("admitted")):
            with self.assertRaises(ValueError):
                self.validate(name, change_diagnostic=mutate)
        stdout, stderr, code = capture(name)
        duplicate = stderr.replace(b'"v":1,', b'"v":1,"v":1,', 1)
        with self.assertRaises(ValueError):
            validator.validate("operational", name, stdout, duplicate, code)
        with self.assertRaises(ValueError):
            self.validate(name, extra=fixture(name)[3])

    def test_summary_wrong_mask_extra_key_and_unexpected_reentry_rejected(self):
        for mutation in (lambda s: s.update(cleanup_result_mask=15),
                         lambda s: s.update(extra=1),
                         lambda s: s.update(cleanup_reentries=1)):
            with self.assertRaises(ValueError):
                self.validate(NEW_CASES[0], change_summary=mutation)
        stdout, stderr, code = capture(NEW_CASES[0])
        with self.assertRaises(ValueError):
            validator.validate("operational", NEW_CASES[0], stdout,
                b"OPERATIONAL_REPLAY_SUMMARY null\n" + stderr, code)

    def test_clock_false_rejects_even_well_formed_end_and_partial_record(self):
        for name in (NEW_CASES[3], NEW_CASES[4]):
            stdout, stderr, code = capture(name)
            end = line(dict(protocol="ups-monitor.continuous.v2", schema_version=2,
                            type="end", elapsed_ms=200, reason="guard_error"))
            _, summary, _, diagnostic_line, _ = fixture(name)
            summary.update(end_writes=1, stdout_bytes=len(stdout + end))
            amended = diagnostic_line + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary)
            with self.assertRaises(ValueError):
                validator.validate("operational", name, stdout + end, amended, code)
            with self.assertRaises(ValueError):
                validator.validate("operational", name, stdout + b'{"type":', stderr, code)

    def test_failed_writer_absence_requires_one_attempt_and_zero_forwarded(self):
        name = "diag-stderr-write-fails"
        self.assertEqual(self.validate(name)["diagnostic_state"], "absent_expected_fault")
        for mutation in (lambda s: s.update(diagnostic_write_calls=0),
                         lambda s: s.update(diagnostic_write_calls=2),
                         lambda s: s.update(diagnostic_forwarded_bytes=1)):
            with self.assertRaises(ValueError):
                self.validate(name, change_summary=mutation)

    def test_natural_case_calls_legacy_with_original_name_and_old_shape(self):
        stdout, summary, diagnostic, diagnostic_line, code = fixture(NEW_CASES[0])
        for key in tuple(validator.EXTRA_COUNTERS):
            summary.pop(key)
        summary.update(scenario="stop-before-wait", before_wait_hooks=1,
            before_published_hooks=1, next_before_wait=8, next_before_published=8)
        diagnostic.update(stop_ok=1, reason_after=0)
        stdout = stdout.replace(b'"guard_error"', b'"cancelled"')
        summary["stdout_bytes"] = len(stdout)
        stderr = b"UPS_CLEANUP_DIAG_V1 " + line(diagnostic) + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary)
        original = validator.legacy.validate
        with mock.patch.object(validator.legacy, "validate", wraps=original) as called:
            self.assertEqual(validator.validate("operational", "stop-before-wait", stdout, stderr, 0)["state"],
                             "PASS_SCOPE_ONLY")
        self.assertEqual(called.call_args.args[:2], ("operational", "stop-before-wait"))
        summary["cleanup_result_mask"] = 0
        with self.assertRaises(ValueError):
            validator.validate("operational", "stop-before-wait", stdout,
                b"UPS_CLEANUP_DIAG_V1 " + line(diagnostic) + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary), 0)

    def test_no_new_scenario_alias_or_v1_acceptance(self):
        stdout, stderr, code = capture(NEW_CASES[0])
        with self.assertRaises(ValueError):
            validator.validate("operational", "diag-stop-false-renamed", stdout, stderr, code)
        with self.assertRaises(ValueError):
            validator.validate("v1-macro-off", NEW_CASES[0], stdout, stderr, code)

    def test_natural_stops_require_elapsed_activity_and_accounting(self):
        for name in ("diag-stderr-write-fails", "diag-cleanup-reentry"):
            self.assertEqual(self.validate(name)["state"], "PASS_SCOPE_ONLY")
            self.assertEqual(self.validate(name, change_summary=lambda s: s.update(wait=1))["state"],
                             "PASS_SCOPE_ONLY")
            stdout, summary, _diagnostic, diagnostic_line, code = fixture(name)
            stdout = stdout.replace(b'"elapsed_ms":10000', b'"elapsed_ms":9999')
            summary.update(elapsed_ms=9999, stdout_bytes=len(stdout))
            stderr = diagnostic_line + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary)
            with self.assertRaisesRegex(ValueError, "natural_stop_elapsed_or_activity"):
                validator.validate("operational", name, stdout, stderr, code)
            for field in ("read", "next", "publications", "sample_flushes"):
                with self.subTest(name=name, field=field):
                    with self.assertRaises(ValueError):
                        self.validate(name, change_summary=lambda s: s.update({field: 0}))
            stdout, summary, _diagnostic, diagnostic_line, code = fixture(name)
            rows = stdout.splitlines(keepends=True)
            self.assertEqual(len(rows), 3)
            one_publication = rows[0] + rows[-1]
            summary.update(sample_writes=1, sample_flushes=1, publications=1,
                           stdout_bytes=len(one_publication))
            stderr = diagnostic_line + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary)
            with self.assertRaisesRegex(ValueError, "natural_stop_elapsed_or_activity"):
                validator.validate("operational", name, one_publication, stderr, code)

    def test_atexit_first_requires_zero_sample_end_and_transport(self):
        name = "diag-atexit-pre-open"
        stdout, stderr, code = capture(name)
        self.assertEqual(stdout, b"")
        self.assertEqual(self.validate(name)["ends"], 0)
        end = line(dict(protocol="ups-monitor.continuous.v2", schema_version=2,
                        type="end", elapsed_ms=0, reason="cancelled"))
        _, summary, _, diagnostic_line, _ = fixture(name)
        summary.update(end_writes=1, stdout_bytes=len(end))
        with self.assertRaises(ValueError):
            validator.validate("operational", name, end,
                diagnostic_line + b"OPERATIONAL_REPLAY_SUMMARY " + line(summary), code)
        for field in ("init", "open", "read", "next", "wait", "cleanup_reentries"):
            with self.assertRaises(ValueError):
                self.validate(name, change_summary=lambda s: s.update({field: 1}))
        with self.assertRaises(ValueError):
            self.validate(name, change_diagnostic=lambda d: d.update(admitted=1))
