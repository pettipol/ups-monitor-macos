"""Synthetic contract tests for the E31 public full-driver replay adapter."""
from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from enum import Enum
import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
from threading import Thread
import time
import unittest
from threading import Event
from unittest.mock import Mock, patch

ADAPTER_PATH = Path(__file__).with_name("replay_operational_portable_e31.py")
SPEC = importlib.util.spec_from_file_location("e31_adapter_under_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
exec(compile(ADAPTER_PATH.read_bytes(), str(ADAPTER_PATH), "exec"), adapter.__dict__)


def baseline_fixture() -> dict:
    return {"schema": 1, "local_pins": {
        "process_deadline.py": "a" * 64,
        "continuous_protocol.py": "b" * 64,
        "other.py": "c" * 64,
    }, "patches": []}


def overrides_fixture() -> dict:
    return {
        "process_deadline.py": {"before": "a" * 64, "after": "d" * 64},
        "continuous_protocol.py": {"before": "b" * 64, "after": "e" * 64},
    }


class ContractTests(unittest.TestCase):
    def test_e31_process_deadline_override_is_exact_and_old_pin_is_rejected(self):
        manifest = json.loads(ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json").read_text())
        row = manifest["baseline_overrides"]["process_deadline.py"]
        self.assertEqual(row["before"], "e53afffbb3a3525e90a6ca3576a335ea6d797a62b22754218fbde569e138cb7a")
        self.assertEqual(row["after"], "e84b48400e0e5f9561bb2f2fa733b828f52fe6bf80cb9833710ad1f985c10b01")
        baseline = {"schema": 1, "local_pins": {
            "process_deadline.py": row["before"],
            "continuous_protocol.py": manifest["baseline_overrides"]["continuous_protocol.py"]["before"],
        }}
        effective = adapter.apply_overrides(baseline, manifest["baseline_overrides"])
        self.assertEqual(effective["local_pins"]["process_deadline.py"], row["after"])
        for bad_pin in ("515c19a7100ea03732788d114cec49209dccbba7f0181e15d0d4599c3604c640", "0" * 64):
            altered = dict(manifest["baseline_overrides"])
            altered["process_deadline.py"] = {**row, "after": bad_pin}
            with self.assertRaisesRegex(adapter.ReplayError, "E31 process deadline pin differs"):
                adapter.validate_process_deadline_override(altered)

    def test_manifest_pins_all_required_backend_inputs_including_v1_host(self):
        manifest_path = ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["new_pins"]), adapter.REQUIRED_NEW_PINS)
        self.assertIn("replay_continuous_pacing.c", manifest["new_pins"])
        self.assertEqual(manifest["limits"], adapter.LIMITS)

    def test_archive_admission_uses_frozen_flat_baseline_keys(self):
        manifest = json.loads(ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json").read_text())
        baseline = {"nut_revision": manifest["archive"]["revision"],
                    "archive_sha256": manifest["archive"]["sha256"]}
        archive = Path("/synthetic/nut.tar")
        r = Mock()
        adapter.admit_archive(r, archive, baseline, manifest)
        r.verify.assert_called_once_with(archive, baseline["archive_sha256"])
        bad_manifest = dict(manifest, archive={**manifest["archive"], "sha256": "0" * 64})
        with self.assertRaisesRegex(adapter.ReplayError, "archive provenance"):
            adapter.admit_archive(r, archive, baseline, bad_manifest)

    def test_main_preflight_uses_real_frozen_archive_field_shape(self):
        manifest = json.loads(ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json").read_text())
        baseline = {"nut_revision": manifest["archive"]["revision"],
                    "archive_sha256": manifest["archive"]["sha256"]}

        class PreflightComplete(Exception):
            pass

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            backend = root / "backend"
            backend.mkdir()
            archive = root / "nut.tar"
            archive.write_bytes(b"synthetic archive placeholder")
            runner = Mock()
            runner.output_location.side_effect = PreflightComplete
            args = Namespace(backend_dir=backend, nut_archive=archive, output_dir=root / "output",
                             run_fake=False)
            with patch.object(adapter, "require_runtime"), \
                    patch.object(adapter, "parse_args", return_value=args), \
                    patch.object(adapter, "verify"), \
                    patch.object(adapter, "load_portable", return_value=runner), \
                    patch.object(adapter, "read_inputs", return_value=(baseline, {})):
                with self.assertRaises(PreflightComplete):
                    adapter.main([])
            runner.verify.assert_called_once_with(archive, baseline["archive_sha256"])

    def test_checked_module_ignores_matching_timestamp_stale_bytecode(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / "fixture_module.py"
            source.write_text("origin = 'source'\n", encoding="utf-8")
            info = source.stat()
            stale_code = compile("origin = 'pyc'\n", str(source), "exec")
            cache = Path(importlib.util.cache_from_source(str(source)))
            cache.parent.mkdir(parents=True)
            cache.write_bytes(importlib.util.MAGIC_NUMBER + struct.pack("<I", 0)
                              + struct.pack("<II", int(info.st_mtime), info.st_size)
                              + marshal.dumps(stale_code))
            name = f"e31_cache_counterexample_{id(self)}"
            module = adapter.checked_module(name, source, adapter.sha(source))
            try:
                self.assertEqual(module.origin, "source")
            finally:
                sys.modules.pop(name, None)

    def test_baseline_runner_changed_buffer_is_never_executed(self):
        manifest = json.loads(ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json").read_text())
        with tempfile.TemporaryDirectory() as folder:
            backend = Path(folder).resolve()
            source = backend / "replay_continuous_portable.py"
            source.write_bytes(b"marker = 'unadmitted execution'\n")
            # The earlier file verification succeeds; only the buffer intended
            # for compile differs, so this is not a preflight mismatch test.
            with patch.object(adapter, "verify") as verified:
                with self.assertRaisesRegex(adapter.ReplayError, "changed before execution"):
                    adapter.load_portable(backend, manifest)
            self.assertEqual(verified.call_args_list[-1].args,
                             (source, adapter.BASELINE_RUNNER_PIN))
            self.assertNotIn("e31_portable_runner", sys.modules)

    def test_changed_helper_bytes_are_rejected_against_e31_override_pin(self):
        expected = "e84b48400e0e5f9561bb2f2fa733b828f52fe6bf80cb9833710ad1f985c10b01"
        with tempfile.TemporaryDirectory() as folder:
            helper = Path(folder).resolve() / "process_deadline.py"
            helper.write_text("changed = True\n", encoding="utf-8")
            with self.assertRaisesRegex(adapter.ReplayError, "pinned input mismatch"):
                adapter.checked_module(f"e31_altered_helper_{id(self)}", helper, expected)

    def test_read_inputs_wires_exact_helper_gate_before_effective_pin_verification(self):
        manifest = json.loads(ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json").read_text())
        baseline_pins = {
            "process_deadline.py": manifest["baseline_overrides"]["process_deadline.py"]["before"],
            "continuous_protocol.py": manifest["baseline_overrides"]["continuous_protocol.py"]["before"],
        }
        for name in adapter.PATCH_ORDER:
            baseline_pins[name] = manifest["new_pins"][name]
        baseline = {
            "schema": 1,
            "local_pins": baseline_pins,
            "patches": [{"name": name, "sha256": baseline_pins[name]} for name in adapter.PATCH_ORDER],
        }

        with tempfile.TemporaryDirectory() as folder:
            backend = Path(folder).resolve()
            baseline_path = backend / "replay_continuous_portable_inputs.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            helper = backend / "process_deadline.py"
            helper.write_text("synthetic admitted helper bytes\n", encoding="utf-8")
            helper_hash = hashlib.sha256(helper.read_bytes()).hexdigest()

            class Verifier:
                def __init__(self):
                    self.calls = []
                    self.enforce_helper = False

                def verify(self, path, expected):
                    path = Path(path)
                    self.calls.append((path, expected))
                    if self.enforce_helper and path == helper:
                        self_test_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                        if self_test_hash != expected:
                            raise adapter.ReplayError("pinned input mismatch: process_deadline.py")

            verifier = Verifier()
            with patch.object(adapter, "validate_patch_entry"), \
                    patch.object(adapter, "safe", side_effect=lambda path, **_kwargs: Path(path)):
                effective, _ = adapter.read_inputs(verifier, backend, manifest)
                self.assertEqual(effective["local_pins"]["process_deadline.py"],
                                 "e84b48400e0e5f9561bb2f2fa733b828f52fe6bf80cb9833710ad1f985c10b01")

                legacy = json.loads(json.dumps(manifest))
                legacy["baseline_overrides"]["process_deadline.py"]["after"] = \
                    "515c19a7100ea03732788d114cec49209dccbba7f0181e15d0d4599c3604c640"
                verifier.calls.clear()
                with self.assertRaisesRegex(adapter.ReplayError, "E31 process deadline pin differs"):
                    adapter.read_inputs(verifier, backend, legacy)
                self.assertFalse(any(path == helper for path, _pin in verifier.calls),
                                 "legacy helper gate must reject before backend helper verification")

                altered = json.loads(json.dumps(manifest))
                altered["baseline_overrides"]["process_deadline.py"]["after"] = helper_hash
                verifier.calls.clear()
                verifier.enforce_helper = True
                with self.assertRaisesRegex(adapter.ReplayError, "E31 process deadline pin differs"):
                    adapter.read_inputs(verifier, backend, altered)
                self.assertFalse(any(path == helper for path, _pin in verifier.calls),
                                 "altered helper bytes matching their proposed pin must still fail the E31 gate")

    def test_late_cancel_after_last_verification_fails_main_without_storage_fault(self):
        manifest = json.loads(ADAPTER_PATH.with_name("replay_operational_portable_inputs_e31.json").read_text())
        baseline = {"nut_revision": manifest["archive"]["revision"],
                    "archive_sha256": manifest["archive"]["sha256"]}
        baseline_pins = {
            "process_deadline.py": "d" * 64,
            "replay_hidapi_full_driver.py": "e" * 64,
            "continuous_protocol.py": "f" * 64,
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            backend = root / "backend"
            backend.mkdir()
            archive = root / "nut.tar"
            archive.write_bytes(b"synthetic archive")
            output = root / "output"
            args = Namespace(backend_dir=backend, nut_archive=archive, output_dir=output, run_fake=False)

            class ForeignReplayError(RuntimeError):
                pass

            runner = Mock()
            runner.ReplayError = ForeignReplayError
            runner.output_location.return_value = output
            runner.tree_bytes.return_value = 0
            sdk = root / "sdk"
            settings = sdk / "SDKSettings.json"
            toolchain = {"clang": str(root / "clang"), "clang_sha256": "a" * 64,
                         "xcodebuild": str(root / "xcodebuild"), "xcodebuild_sha256": "b" * 64,
                         "sdk": str(sdk), "sdk_settings_sha256": "c" * 64}
            runner.discover_toolchain.return_value = toolchain
            handlers = {}
            cancelled_at_final_verify = []

            def fake_signal(signum, handler):
                handlers[signum] = handler
                return None

            def verified(path, _expected):
                if path == settings:
                    cancelled_at_final_verify.append(True)
                    handlers[adapter.signal.SIGINT](adapter.signal.SIGINT, None)

            with patch.object(adapter, "require_runtime"), \
                    patch.object(adapter, "parse_args", return_value=args), \
                    patch.object(adapter, "verify", side_effect=verified), \
                    patch.object(adapter, "load_portable", return_value=runner), \
                    patch.object(adapter, "read_inputs", return_value=(baseline, baseline_pins)), \
                    patch.object(adapter, "checked_module", return_value=SimpleNamespace(
                        run_pure_mutation_selfchecks=lambda: {},
                        run_transport_error_mutation_selfchecks=lambda: {})), \
                    patch.object(adapter, "install_cancel_bridge", return_value=lambda: None), \
                    patch.object(adapter, "stage_source", return_value=(root / "source", manifest["expected_source_after"], {})), \
                    patch.object(adapter, "snapshot", return_value=manifest["expected_source_after"]), \
                    patch.object(adapter, "build", return_value={}), \
                    patch.object(adapter, "admit_adapter"), \
                    patch.object(adapter.signal, "signal", side_effect=fake_signal), \
                    patch.object(adapter, "write_final_receipt", wraps=adapter.write_final_receipt) as final:
                self.assertEqual(adapter.main([]), 1)
            self.assertEqual(cancelled_at_final_verify, [True])
            self.assertEqual(final.call_args.args[2]["state"], "STOPPED_NOT_QUALIFIED")
            self.assertFalse((output / "manifest.json").exists())
            self.assertEqual(runner.tree_bytes.side_effect, None, "no storage fault accompanies late cancellation")

    def test_foreign_baseline_tree_error_cancels_storage_guard(self):
        class ForeignReplayError(RuntimeError):
            pass

        class FakeRunner:
            ReplayError = ForeignReplayError

            @staticmethod
            def tree_bytes(_output):
                raise ForeignReplayError("synthetic tree limit")

        event = Event()
        self.assertFalse(adapter.check_tree_bytes(FakeRunner, Path("/synthetic"), event))
        self.assertTrue(event.is_set())

    def test_cancel_bridge_propagates_shared_event_to_frozen_runner_event(self):
        shared = Event()
        entered = Event()
        received = []

        class Helper:
            def run_bounded(self, *, cancel_event):
                received.append(cancel_event)
                entered.set()
                return cancel_event.wait(2)

        class Runner:
            def command(self, *_args, **_kwargs):
                return "unused"

        runner, helper = Runner(), Helper()
        restore = adapter.install_cancel_bridge(runner, helper, shared)
        local = Event()
        result = []
        worker = Thread(target=lambda: result.append(helper.run_bounded(cancel_event=local)))
        try:
            worker.start()
            self.assertTrue(entered.wait(1))
            shared.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertIs(received[0], local)
            self.assertTrue(local.is_set())
            self.assertEqual(result, [True])
        finally:
            shared.set()
            worker.join(2)
            restore()

    def test_cancelled_command_does_not_invoke_frozen_runner(self):
        shared = Event()
        command = Mock(return_value="unused")

        class Helper:
            run_bounded = Mock()

        class Runner:
            pass

        runner, helper = Runner(), Helper()
        runner.command = command
        restore = adapter.install_cancel_bridge(runner, helper, shared)
        shared.set()
        try:
            with self.assertRaisesRegex(adapter.ReplayError, "cancelled"):
                runner.command(helper, ["compile"])
            command.assert_not_called()
        finally:
            restore()

    def test_exact_two_overrides_copy_without_mutating_baseline(self):
        baseline = baseline_fixture()
        result = adapter.apply_overrides(baseline, overrides_fixture())
        self.assertEqual(result["local_pins"]["process_deadline.py"], "d" * 64)
        self.assertEqual(result["local_pins"]["continuous_protocol.py"], "e" * 64)
        self.assertEqual(baseline["local_pins"]["process_deadline.py"], "a" * 64)
        self.assertEqual(result["local_pins"]["other.py"], "c" * 64)

    def test_missing_extra_and_changed_override_preimage_fail(self):
        rows = overrides_fixture()
        with self.assertRaises(adapter.ReplayError):
            adapter.apply_overrides(baseline_fixture(), {"process_deadline.py": rows["process_deadline.py"]})
        extra = dict(rows, surprise={"before": "f" * 64, "after": "0" * 64})
        with self.assertRaises(adapter.ReplayError):
            adapter.apply_overrides(baseline_fixture(), extra)
        changed = dict(rows)
        changed["process_deadline.py"] = {"before": "0" * 64, "after": "d" * 64}
        with self.assertRaises(adapter.ReplayError):
            adapter.apply_overrides(baseline_fixture(), changed)

    def test_patch_contract_rejects_wrong_targets_and_incomplete_images(self):
        r = Mock()
        r.patch_targets.return_value = {"drivers/apcmicrolink.c"}
        good = {"targets": ["drivers/apcmicrolink.c"],
                "before": {"drivers/apcmicrolink.c": "a" * 64},
                "after": {"drivers/apcmicrolink.c": "b" * 64}}
        adapter.validate_patch_entry(r, Path("/synthetic/backend"), "patch", good)
        wrong = dict(good, targets=["drivers/main.c"])
        with self.assertRaises(adapter.ReplayError):
            adapter.validate_patch_entry(r, Path("/synthetic/backend"), "patch", wrong)
        incomplete = dict(good, after={})
        with self.assertRaises(adapter.ReplayError):
            adapter.validate_patch_entry(r, Path("/synthetic/backend"), "patch", incomplete)

    def test_final_source_closure_is_exact(self):
        expected = {"drivers/apcmicrolink.c": "a" * 64, "drivers/main.c": "b" * 64}
        adapter.require_snapshot(dict(expected), expected)
        with self.assertRaises(adapter.ReplayError):
            adapter.require_snapshot({**expected, "extra.c": "c" * 64}, expected)
        with self.assertRaises(adapter.ReplayError):
            adapter.require_snapshot({"drivers/apcmicrolink.c": "d" * 64,
                                      "drivers/main.c": "b" * 64}, expected)

    def test_fixed_matrix_is_exactly_33_and_closed(self):
        cases = adapter.fixed_cases()
        self.assertEqual(len(cases), 33)
        self.assertEqual(len({row[0] for row in cases}), 33)
        self.assertEqual(sum(mode == "operational" and scenario != "cli-negative"
                             for _, mode, scenario, _ in cases), 23)
        self.assertEqual(sum(scenario == "cli-negative" for _, _, scenario, _ in cases), 8)
        self.assertEqual(sum(mode.startswith("v1-") for _, mode, _, _ in cases), 2)

    def test_fake_units_preserve_pins_and_refuse_missing_changed_or_shadow_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            backend = root / "backend"
            backend.mkdir()
            pins = {}
            for name in adapter.FAKE_UNITS:
                raw = ("/* synthetic " + name + " */\n").encode()
                (backend / name).write_bytes(raw)
                pins[name] = hashlib.sha256(raw).hexdigest()
            for fault in ("none", "missing", "changed", "shadow-header"):
                with self.subTest(fault=fault):
                    output = root / fault
                    output.mkdir()
                    staged = adapter.stage_fake_units(backend, output, pins)
                    self.assertTrue(all(path.read_bytes() == (backend / name).read_bytes()
                                        for name, path in staged.items()))
                    if fault == "none":
                        adapter.verify_fake_units(staged, pins)
                        continue
                    if fault == "missing":
                        staged[adapter.FAKE_UNITS[0]].unlink()
                    elif fault == "changed":
                        staged[adapter.FAKE_UNITS[0]].write_bytes(b"changed\n")
                    else:
                        (output / "fake-units" / "apcmicrolink-hidapi-session.h").write_bytes(b"shadow\n")
                    with self.assertRaises(adapter.ReplayError):
                        adapter.verify_fake_units(staged, pins)

    def test_fake_host_dependencies_require_patched_headers_and_refuse_backend_preimages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source, backend = root / "source", root / "backend"
            (source / "drivers").mkdir(parents=True)
            backend.mkdir()
            headers = ("apcmicrolink-hidapi-native.h", "apcmicrolink-hidapi-session.h",
                       "apcmicrolink-hidapi-shared-host.h")
            for name in headers:
                (source / "drivers" / name).write_bytes(b"patched\n")
                (backend / name).write_bytes(b"preimage\n")
            unit = root / "fake-units" / "replay_operational_native.c"
            correct = [str(source / "drivers" / name) for name in headers]
            adapter.require_fake_header_provenance(unit, correct, source, backend)
            for wrong in (correct[:-1], [str(backend / name) for name in headers],
                          correct + [str(backend / headers[1])]):
                with self.subTest(dependencies=wrong):
                    with self.assertRaisesRegex(adapter.ReplayError, "header"):
                        adapter.require_fake_header_provenance(unit, wrong, source, backend)

    def test_build_compiles_pinned_fake_copy_with_patched_source_include_before_backend(self):
        class FirstFakeCompile(Exception):
            pass

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source, backend, output = (root / name for name in ("source", "backend", "output"))
            for directory in (source / "drivers", source / "include", source / "common", backend, output):
                directory.mkdir(parents=True, exist_ok=True)
            public = tuple("drivers/public-" + str(index) + ".c" for index in range(11))
            for name in public + tuple("drivers/" + name for name in (
                    "apcmicrolink-continuous.c", "apcmicrolink-hidapi-shared.c",
                    "apcmicrolink-hid-descriptor-checked.c", "apcmicrolink-operational-freshness.c")):
                (source / name).write_bytes(b"/* synthetic source */\n")
            pins = {}
            for name in adapter.FAKE_UNITS:
                raw = ("/* synthetic " + name + " */\n").encode()
                (backend / name).write_bytes(raw)
                pins[name] = hashlib.sha256(raw).hexdigest()
            for name in ("test_hidapi_full_config.h", "test_hidapi_full_version.h"):
                (backend / name).write_bytes(b"/* synthetic config */\n")
            # This is the causal trap: a quote include beside the original TU
            # would choose this frozen preimage before any -I source directory.
            (backend / "apcmicrolink-hidapi-session.h").write_bytes(b"preimage\n")
            runner = Mock()
            runner.PUBLIC_UNITS = public
            commands = []

            def compile_command(_helper, argv, _output, _label, **_kwargs):
                unit = Path(argv[argv.index("-c") + 1])
                commands.append(argv)
                if unit.name in adapter.FAKE_UNITS:
                    self.assertEqual(unit, output / "fake-units" / "replay_operational_native.c")
                    self.assertEqual(unit.read_bytes(), (backend / unit.name).read_bytes())
                    self.assertLess(argv.index(str(source / "drivers")), argv.index(str(backend)))
                    self.assertNotIn(str(backend / unit.name), argv)
                    raise FirstFakeCompile()
                Path(argv[argv.index("-MF") + 1]).write_text(
                    "ups_full_fake_dependency_target: " + str(unit) + "\n", encoding="utf-8")

            runner.command.side_effect = compile_command
            tools = {"clang": str(root / "toolchain/bin/clang"), "sdk": str(root / "sdk"),
                     "developer_dir": str(root / "developer"), "clang_sha256": "a" * 64}
            with self.assertRaises(FirstFakeCompile):
                adapter.build(runner, source, output, {}, pins, Mock(), Mock(), tools,
                              backend, {"new_pins": {}}, Event())
            self.assertEqual(len(commands), 16, "the first 15 driver units remain in their original positions")

    def test_cli_defaults_to_compile_only_and_rejects_arbitrary_scenario(self):
        args = adapter.parse_args(["--backend-dir", "/b", "--nut-archive", "/a", "--output-dir", "/o"])
        self.assertFalse(args.run_fake)
        with self.assertRaises(SystemExit):
            adapter.parse_args(["--backend-dir", "/b", "--nut-archive", "/a",
                                "--output-dir", "/o", "--scenario", "anything"])


class Status(str, Enum):
    EXITED = "exited"
    UNREAPED = "unreaped"


class Trigger(str, Enum):
    COMPLETED = "completed"
    OUTPUT_INCOMPLETE = "output_incomplete"


@dataclass
class Observation:
    maximum_output_bytes: int
    executable_sha256: str
    stdout_sha256: str
    stderr_sha256: str
    started_at_unix_seconds: int
    finished_at_unix_seconds: int


@dataclass
class Bounded:
    status: Status
    trigger: Trigger
    returncode: int | None
    stdout_bytes: int
    stderr_bytes: int
    observation: Observation | None


class FakeHelper:
    RunStatus = Status
    RunTrigger = Trigger

    def __init__(self, event: Event, status: Status = Status.EXITED,
                 bad_hash: bool = False, set_event_on_call: bool = False):
        self.event = event
        self.status = status
        self.bad_hash = bad_hash
        self.set_event_on_call = set_event_on_call
        self.calls = 0

    def run_bounded(self, argv, *, output_directory, cancel_event, **kwargs):
        self.calls += 1
        case_dir = Path(output_directory)
        case_dir.mkdir(mode=0o700)
        (case_dir / "stdout.bin").write_bytes(b"")
        (case_dir / "stderr.bin").write_bytes(b"")
        if self.calls == 1 and self.set_event_on_call:
            self.event.set()
        empty = hashlib.sha256(b"").hexdigest()
        observation = Observation(1_048_576, kwargs.get("executable_sha256", ""),
                                  "0" * 64 if self.bad_hash else empty, empty, 0, 0)
        trigger = Trigger.COMPLETED if self.status == Status.EXITED else Trigger.OUTPUT_INCOMPLETE
        return Bounded(self.status, trigger, 0, 0, 0, observation)


class SuiteGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.binary = self.root / "fake"
        self.binary.write_bytes(b"synthetic executable placeholder")
        self.binary.chmod(0o600)
        digest = adapter.sha(self.binary)
        self.pair = {mode: {"path": str(self.binary), "sha256": digest}
                     for mode in adapter.MODES}
        self.manifest = {"extra_definitions": ["mlink_operational_replay_fwrite",
                                                "mlink_operational_replay_fflush",
                                                "mlink_operational_replay_checkpoint"]}

    def tearDown(self):
        self.temp.cleanup()

    def test_cancellation_prevents_second_fake_child(self):
        event = Event()
        helper = FakeHelper(event, set_event_on_call=True)
        validator = Mock()
        validator.validate.return_value = {"state": "PASS_SCOPE_ONLY"}
        receipt = adapter.new_suite_receipt()
        with self.assertRaises(adapter.ReplayError):
            adapter.run_suite(self.pair, self.root, helper, validator, self.manifest,
                              event, time.monotonic(), adapter.sha(adapter.ENV_PATH), receipt)
        self.assertEqual(helper.calls, 1)
        self.assertEqual(receipt["state"], "STOPPED_NOT_QUALIFIED")
        self.assertEqual(receipt["attempted_cases"], 1)
        self.assertEqual(receipt["validated_cases"], 1)
        self.assertTrue((self.root / "01-healthy-700s.receipt.json").is_file())
        self.assertFalse((self.root / "02-high-absolute-anchor.receipt.json").exists())

    def test_unreaped_or_capture_hash_mismatch_refuses_followup(self):
        for index, (status, bad_hash, reason) in enumerate((
                (Status.UNREAPED, False, "did not exit and reap"),
                (Status.EXITED, True, "capture length or hash"))):
            with self.subTest(status=status, bad_hash=bad_hash):
                event = Event()
                event.clear()
                helper = FakeHelper(event, status=status, bad_hash=bad_hash,
                                    set_event_on_call=False)
                validator = Mock()
                validator.validate.return_value = {"state": "PASS_SCOPE_ONLY"}
                case_root = self.root / f"rejection-{index}"
                case_root.mkdir()
                receipt = adapter.new_suite_receipt()
                with self.assertRaisesRegex(adapter.ReplayError, reason):
                    adapter.run_suite(self.pair, case_root, helper, validator, self.manifest,
                                      event, time.monotonic(), adapter.sha(adapter.ENV_PATH), receipt)
                self.assertEqual(helper.calls, 1)
                self.assertEqual(receipt["state"], "STOPPED_NOT_QUALIFIED")
                self.assertTrue((case_root / "01-healthy-700s.receipt.json").is_file())
                self.binary.chmod(0o600)

    def test_validator_must_return_scope_only_and_failure_is_aggregated(self):
        event = Event()
        helper = FakeHelper(event)
        validator = Mock()
        validator.validate.return_value = {"state": "PASS_FAKE_ONLY"}
        receipt = adapter.new_suite_receipt()
        with self.assertRaisesRegex(adapter.ReplayError, "PASS_SCOPE_ONLY"):
            adapter.run_suite(self.pair, self.root, helper, validator, self.manifest,
                              event, time.monotonic(), adapter.sha(adapter.ENV_PATH), receipt)
        self.assertEqual(helper.calls, 1)
        self.assertEqual(receipt["completed_cases"], 1)
        self.assertEqual(receipt["validated_cases"], 0)
        self.assertEqual(receipt["results"][0]["failure"], "validator_state")

    def test_suite_deadline_reserves_cleanup_window_and_launches_no_child(self):
        event = Event()
        helper = FakeHelper(event)
        validator = Mock()
        receipt = adapter.new_suite_receipt()
        with self.assertRaisesRegex(adapter.ReplayError, "no bounded child window"):
            adapter.run_suite(self.pair, self.root, helper, validator, self.manifest,
                              event, time.monotonic() - 598.5,
                              adapter.sha(adapter.ENV_PATH), receipt)
        self.assertEqual(helper.calls, 0)
        self.assertEqual(receipt["state"], "STOPPED_NOT_QUALIFIED")
        self.assertEqual(receipt["attempted_cases"], 0)

    def test_unjoined_deadline_monitor_cannot_promote_success(self):
        class UnjoinedMonitor:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

            def join(self, timeout):
                pass

            def is_alive(self):
                return True

        event = Event()
        helper = FakeHelper(event)
        validator = Mock()
        validator.validate.return_value = {"state": "PASS_SCOPE_ONLY"}
        receipt = adapter.new_suite_receipt()
        with patch.object(adapter, "Thread", UnjoinedMonitor):
            with self.assertRaisesRegex(adapter.ReplayError, "complete success"):
                adapter.run_suite(self.pair, self.root, helper, validator, self.manifest,
                                  event, time.monotonic(), adapter.sha(adapter.ENV_PATH), receipt)
        self.assertEqual(helper.calls, 33, "monitor join is the sole injected fault")
        self.assertEqual(receipt["validated_cases"], 33)
        self.assertEqual(receipt["state"], "STOPPED_NOT_QUALIFIED")
        self.assertEqual(receipt["error"], "suite_deadline_monitor_unjoined")
        self.assertTrue(event.is_set())

    def test_main_success_gate_refuses_failed_or_partial_suite(self):
        receipt = {"state": "PASS_FAKE_ONLY", "expected_cases": 33,
                   "attempted_cases": 33, "completed_cases": 33, "validated_cases": 33}
        adapter.require_suite_success(receipt)
        for key, value in (("state", "STOPPED_NOT_QUALIFIED"), ("validated_cases", 32)):
            with self.subTest(key=key):
                with self.assertRaisesRegex(adapter.ReplayError, "complete success"):
                    adapter.require_suite_success({**receipt, key: value})

    def test_final_storage_error_cannot_keep_pass_or_write_unmeasured_tree(self):
        class ForeignReplayError(RuntimeError):
            pass

        runner = Mock()
        runner.ReplayError = ForeignReplayError
        runner.tree_bytes.side_effect = ForeignReplayError("synthetic storage fault")
        receipt = {"state": "PASS_FAKE_ONLY"}
        state = adapter.write_final_receipt(runner, self.root, receipt)
        self.assertEqual(state, "STOPPED_NOT_QUALIFIED")
        self.assertEqual(receipt["error"], "final_storage_unavailable")
        self.assertFalse((self.root / "manifest.json").exists())

    def test_final_manifest_reserves_exact_encoded_bytes(self):
        class ForeignReplayError(RuntimeError):
            pass

        runner = Mock()
        runner.ReplayError = ForeignReplayError
        receipt = {"state": "PASS_FAKE_ONLY", "padding": "é" * 400}
        runner.tree_bytes.return_value = 0
        # A complete manifest exceeds this budget, while the bounded failure
        # summary fits. The sole fault is manifest-size reservation.
        with patch.object(adapter, "MAX_TREE_BYTES", 1024):
            state = adapter.write_final_receipt(runner, self.root, receipt)
        self.assertEqual(state, "STOPPED_NOT_QUALIFIED")
        final = self.root / "manifest.json"
        self.assertLessEqual(2 * final.stat().st_size, 1024)
        self.assertEqual(final.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(final.read_text())["error"], "final_manifest_storage_limit")

    def test_no_manifest_write_when_even_failure_receipt_cannot_fit(self):
        class ForeignReplayError(RuntimeError):
            pass

        runner = Mock()
        runner.ReplayError = ForeignReplayError
        runner.tree_bytes.return_value = adapter.MAX_TREE_BYTES - 1
        receipt = {"state": "COMPILE_ONLY_FAKE_NOT_RUN"}
        self.assertEqual(adapter.write_final_receipt(runner, self.root, receipt),
                         "STOPPED_NOT_QUALIFIED")
        self.assertFalse((self.root / "manifest.json").exists())

    def test_atomic_manifest_preparation_faults_never_publish_pass(self):
        class ForeignReplayError(RuntimeError):
            pass

        for fault in ("fchmod", "fsync"):
            with self.subTest(fault=fault):
                output = self.root / fault
                output.mkdir()
                runner = Mock()
                runner.ReplayError = ForeignReplayError
                runner.tree_bytes.return_value = 0
                receipt = {"state": "PASS_FAKE_ONLY"}
                with patch.object(adapter.os, fault, side_effect=OSError("synthetic prepare fault")):
                    state = adapter.write_final_receipt(runner, output, receipt)
                self.assertEqual(state, "STOPPED_NOT_QUALIFIED")
                self.assertFalse((output / "manifest.json").exists())
                self.assertFalse((output / ".manifest.pending").exists())

    def test_atomic_manifest_does_not_overwrite_existing_receipt(self):
        class ForeignReplayError(RuntimeError):
            pass

        runner = Mock()
        runner.ReplayError = ForeignReplayError
        runner.tree_bytes.return_value = 0
        final = self.root / "manifest.json"
        final.write_bytes(b"existing receipt, never replaced\n")
        receipt = {"state": "PASS_FAKE_ONLY"}
        self.assertEqual(adapter.write_final_receipt(runner, self.root, receipt), "STOPPED_NOT_QUALIFIED")
        self.assertEqual(final.read_bytes(), b"existing receipt, never replaced\n")


if __name__ == "__main__":
    unittest.main()
