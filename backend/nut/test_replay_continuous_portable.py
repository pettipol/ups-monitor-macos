#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Contract counterexamples for the fake-only portable replay entry point."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from enum import Enum
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
from types import ModuleType, SimpleNamespace
from threading import Event
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("continuous_portable_contract", HERE / "replay_continuous_portable.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class PortableContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ups-portable-contract-", dir="/private/tmp")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_hash_drift_refuses_before_source_mutation(self) -> None:
        path = self.root / "input.patch"
        path.write_bytes(b"synthetic initial bytes")
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_bytes(b"synthetic changed bytes")
        with self.assertRaisesRegex(runner.ReplayError, "pinned input mismatch"):
            runner.verify(path, expected)

    def test_public_baselines_precede_full_patch_and_are_never_restored_after_it(self) -> None:
        inputs = self.root / "public-inputs"
        inputs.mkdir()
        local_pins = {}
        for name in runner.COPIED_MODULES:
            path = inputs / name
            path.write_bytes(("synthetic baseline " + name).encode("ascii"))
            local_pins[name] = runner.sha(path)
        changed = ("apcmicrolink-hidapi-native.c", "apcmicrolink-hidapi-native.h", "apcmicrolink-hidapi-shared.c")
        final = {name: ("synthetic patched " + name).encode("ascii") for name in changed}
        patch_file = inputs / "synthetic-continuous.patch"
        patch_file.write_text("--- a/drivers/apcmicrolink-hidapi-shared.c\n+++ b/drivers/apcmicrolink-hidapi-shared.c\n")
        archive = self.root / "synthetic-pristine.tar"
        with tarfile.open(archive, "w:") as stream:
            data = b"synthetic pristine main\n"
            member = tarfile.TarInfo("drivers/main.c")
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
        contract = {"archive_sha256": runner.sha(archive), "local_pins": local_pins,
                    "patches": [{"name": patch_file.name}],
                    "source_after": {"drivers/" + name: hashlib.sha256(data).hexdigest() for name, data in final.items()}}
        output = self.root / "reconstructed"
        output.mkdir()
        observed: list[bool] = []

        def apply_synthetic_patch(_helper, _argv, actual_output, _label):
            self.assertEqual(actual_output, output)
            for name in runner.COPIED_MODULES:
                self.assertEqual((output / "source/drivers" / name).read_bytes(), (inputs / name).read_bytes(),
                                 "public baseline must exist before the full patch is applied")
            for name, data in final.items():
                (output / "source/drivers" / name).write_bytes(data)
            observed.append(True)
            return "synthetic patch applied"

        with patch.object(runner, "HERE", inputs), patch.object(runner, "command", side_effect=apply_synthetic_patch):
            source = runner.reconstruct(archive, contract, output, SimpleNamespace())
        self.assertEqual(observed, [True])
        for name, data in final.items():
            self.assertEqual((source / "drivers" / name).read_bytes(), data,
                             "staged modules must retain their patched bytes")

    def test_symlink_input_and_parent_are_refused(self) -> None:
        original = self.root / "original"
        original.mkdir()
        (original / "input").write_bytes(b"synthetic")
        link = self.root / "alias"
        link.symlink_to(original, target_is_directory=True)
        with self.assertRaisesRegex(runner.ReplayError, "symlink path component"):
            runner.safe_path(link / "input")
        with self.assertRaisesRegex(runner.ReplayError, "symlink path component"):
            runner.output_location(link / "new", ())

    def test_external_existing_and_overlapping_outputs_are_refused(self) -> None:
        with self.assertRaisesRegex(runner.ReplayError, "system temporary root"):
            runner.output_location(Path("/Users/ups-portable-output-refusal-fixture"), ())
        with self.assertRaisesRegex(runner.ReplayError, "must be new"):
            runner.output_location(self.root, ())
        with self.assertRaisesRegex(runner.ReplayError, "overlaps protected"):
            runner.output_location(self.root / "new", (self.root,))

    def test_world_writable_output_parent_is_refused(self) -> None:
        shared = self.root / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        with self.assertRaisesRegex(runner.ReplayError, "privately owned"):
            runner.output_location(shared / "new", ())

    def test_patch_cannot_escape_reconstructed_tree(self) -> None:
        path = self.root / "synthetic.patch"
        path.write_text("--- a/example\n+++ b/../../outside\n@@ -1 +1 @@\n-a\n+b\n")
        with self.assertRaisesRegex(runner.ReplayError, "unsafe patch target"):
            runner.patch_targets(path)

    def test_closed_cli_refuses_device_and_arbitrary_child_flags(self) -> None:
        arguments = ["--nut-archive", "synthetic.tar", "--output-dir", "synthetic-output"]
        parsed = runner.parse_args(arguments)
        self.assertFalse(parsed.run_fake, "default must never execute a fake binary")
        for extra in (["--device", "/dev/ups"], ["--scenario", "real"], ["--run-fake", "--compile-only"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.parse_args(arguments + extra)

    def test_compile_default_does_not_call_suite(self) -> None:
        archive = self.root / "synthetic.tar"
        archive.write_bytes(b"synthetic archive")
        output = self.root / "output"
        contract = {"local_pins": {
                        "process_deadline.py": "synthetic",
                        "replay_hidapi_full_driver.py": "synthetic",
                        "apcmicrolink-hidapi-shared.c": "synthetic",
                        "apcmicrolink-hidapi-shared-host.h": "synthetic",
                        "apcmicrolink-hidapi-session.h": "synthetic",
                        "apcmicrolink-hidapi-native.c": "synthetic",
                        "apcmicrolink-hidapi-native.h": "synthetic",
                        "apcmicrolink-hid-descriptor-checked.c": "synthetic",
                        "apcmicrolink-hid-descriptor-checked.h": "synthetic",
                    },
                    "archive_sha256": "synthetic", "source_after": {}, "nut_revision": "synthetic"}
        with patch.object(runner.sys, "version_info", (3, 15, 2)), patch.object(runner.sys, "platform", "darwin"), \
             patch.object(runner, "read_contract", return_value=contract), \
             patch.object(runner, "safe_path", side_effect=lambda p, **kwargs: p), \
             patch.object(runner, "verify"), patch.object(runner, "sha", return_value="synthetic"), \
             patch.object(runner, "load_pinned", return_value=SimpleNamespace()), \
             patch.object(runner, "discover_toolchain", return_value={"clang": "/synthetic/clang", "clang_sha256": "synthetic", "xcodebuild": "/synthetic/xcodebuild", "xcodebuild_sha256": "synthetic", "sdk": "/synthetic/sdk", "sdk_settings_sha256": "synthetic"}), \
             patch.object(runner, "reconstruct", return_value=self.root), \
             patch.object(runner, "build_pair", return_value={}), \
             patch.object(runner, "run_suite", side_effect=AssertionError("unexpected fake execution")), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--nut-archive", str(archive), "--output-dir", str(output)]), 0)
        saved = json.loads((output / "manifest.json").read_text())
        self.assertEqual(saved["state"], "COMPILE_ONLY_FAKE_NOT_RUN")
        self.assertEqual(saved["suite"]["state"], "NOT_RUN")

    def test_native_hid_or_dangerous_os_import_fails_audit(self) -> None:
        binary = self.root / "synthetic-binary"
        binary.write_bytes(b"synthetic")
        defined = "\n".join("0000000000000000 T _" + name for name in runner.REQUIRED_FAKE_DEFINITIONS) + "\n"
        # The clean report must pass before changing exactly one import; a
        # missing required fake symbol cannot make these negatives pass.
        with patch.object(runner, "command", side_effect=["_malloc\n", defined, "synthetic:\n"]):
            self.assertEqual(runner.audit(binary, self.root, SimpleNamespace())["state"], "PASS_STATIC_NO_HID_LINKAGE")
        without_directory_seam = defined.replace("0000000000000000 T _fixture_chdir\n", "")
        with patch.object(runner, "command", side_effect=["_malloc\n", without_directory_seam, "synthetic:\n"]):
            with self.assertRaisesRegex(runner.ReplayError, "required fake definition absent: fixture_chdir"):
                runner.audit(binary, self.root, SimpleNamespace())
        for imported in sorted(runner.FORBIDDEN_IMPORTS | {"hid_open_path", "IOHIDDeviceOpen", "libusb_open"}):
            with self.subTest(imported=imported), patch.object(runner, "command", side_effect=["_" + imported + "\n", defined, "synthetic:\n"]):
                with self.assertRaisesRegex(runner.ReplayError, "forbidden OS import"):
                    runner.audit(binary, self.root, SimpleNamespace())

    def test_genuine_linkage_is_rejected_independently_from_symbols(self) -> None:
        binary = self.root / "synthetic-binary"
        binary.write_bytes(b"synthetic")
        defined = "\n".join("0000000000000000 T _" + name for name in runner.REQUIRED_FAKE_DEFINITIONS) + "\n"
        for library in ("libhidapi.dylib", "libusb.dylib", "IOKit.framework/IOKit", "CoreFoundation.framework/CoreFoundation"):
            linked = "synthetic:\n /synthetic/" + library + " (compatibility version 1.0.0)\n"
            with self.subTest(library=library), patch.object(runner, "command", side_effect=["_malloc\n", defined, linked]):
                with self.assertRaisesRegex(runner.ReplayError, "genuine HID or USB linkage"):
                    runner.audit(binary, self.root, SimpleNamespace())

    def test_selected_link_map_accepts_renamed_xcode_root_and_rejects_archive(self) -> None:
        developer = self.root / "Xcode_27.1.app" / "Contents" / "Developer"
        library = developer / "sdk" / "libSystem.tbd"
        library.parent.mkdir(parents=True)
        library.write_bytes(b"synthetic")
        obj = self.root / "unit.o"
        obj.write_bytes(b"synthetic")
        link_map = "# Object files:\n[ 0] " + str(obj) + "\n[ 1] " + str(library) + "\n# Sections:\n"
        runner.verify_selected_objects(link_map, [obj], developer)
        archive = self.root / "unadmitted.a"
        archive.write_bytes(b"synthetic")
        with self.assertRaisesRegex(runner.ReplayError, "unexpected portable link map"):
            runner.verify_selected_objects(link_map.replace(str(library), str(archive)), [obj], developer)

    def test_discovery_respects_explicit_developer_directory_and_version_pins(self) -> None:
        developer = self.root / "Xcode_27.1.app" / "Contents" / "Developer"
        clang = developer / "Toolchains" / "selected" / "usr" / "bin" / "clang"
        xcodebuild = developer / "usr" / "bin" / "xcodebuild"
        sdk = developer / "Platforms" / "MacOSX.platform" / "Developer" / "SDKs" / "selected.sdk"
        for tool in (clang, xcodebuild):
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.write_bytes(b"synthetic, never executed")
            tool.chmod(0o700)
        sdk.mkdir(parents=True)
        (sdk / "SDKSettings.json").write_text('{}\n')
        contract = {"toolchain": {"xcode_version": "27.1", "macos_sdk_version": "27.0"}}
        discovery = [str(clang), str(xcodebuild), str(sdk), "27.0\n", "Xcode 27.1\nBuild version synthetic\n"]
        with patch.dict(runner.os.environ, {"DEVELOPER_DIR": str(developer)}), \
             patch.object(runner, "command", side_effect=discovery) as command:
            selected = runner.discover_toolchain(self.root, contract, SimpleNamespace())
        self.assertEqual(selected["developer_dir"], str(developer))
        self.assertEqual(selected["selection"], "DEVELOPER_DIR")
        self.assertEqual(command.call_count, 5, "explicit selection must not call xcode-select")
        for call in command.call_args_list:
            self.assertEqual(call.kwargs["developer_dir"], developer)
        discovery[3] = "26.0\n"
        with patch.dict(runner.os.environ, {"DEVELOPER_DIR": str(developer)}), \
             patch.object(runner, "command", side_effect=discovery):
            with self.assertRaisesRegex(runner.ReplayError, "toolchain version differs"):
                runner.discover_toolchain(self.root, contract, SimpleNamespace())

    def test_shared_event_owns_direct_child_and_unreaped_can_never_pass(self) -> None:
        class Status(str, Enum):
            EXITED = "exited"
            UNREAPED = "unreaped"

        class Trigger(str, Enum):
            COMPLETED = "completed"

        @dataclass
        class Result:
            status: Status = Status.UNREAPED
            trigger: Trigger = Trigger.COMPLETED
            returncode: int | None = None
            stdout_bytes: int = 0
            stderr_bytes: int = 0

        module = ModuleType("synthetic_direct_child_suite")
        original_event = Event()
        seen: list[dict] = []
        pair = {}
        for mode in ("off", "on"):
            binary = self.root / ("synthetic-" + mode)
            binary.write_bytes(b"synthetic")
            binary.chmod(0o600)
            pair[mode] = {"path": str(binary), "sha256": runner.sha(binary)}

        def one_case(_case) -> None:
            arguments = [str(runner.ENV), "MLINK_CONTINUOUS_REPLAY_SCENARIO=same-payload", pair["off"]["path"],
                         "-s", "replay", "-d1", "-x", "port=auto", "-x", "hidapi_shared",
                         "-x", "guarded_monitor", "-x", "guard_vid=0001", "-x", "guard_pid=0002",
                         "-x", "guard_deadline=130", "-x", "guard_probe_attempts=1", "-x",
                         "hid_fallback=no", "-x", "monitor_stream_v1"]
            for _ in range(2):
                module.run_bounded(arguments, executable_sha256=module.ENV_SHA256,
                                   output_directory=module.run_root / "00", timeout_seconds=20,
                                   termination_grace_seconds=2, maximum_output_bytes=1_048_576,
                                   cancel_event=original_event)

        class Cases(unittest.TestCase):
            pass

        setattr(Cases, "test_00_owned_child", one_case)
        for index in range(1, 10):
            setattr(Cases, f"test_{index:02d}_unused", lambda _case: None)
        module.Cases = Cases

        def fake_supervisor(_argv, **kwargs):
            seen.append(kwargs)
            return Result()

        helper = SimpleNamespace(RunStatus=Status, run_bounded=fake_supervisor)
        contract = {"local_pins": {"test_continuous_diagnostics.py": "synthetic", "continuous_protocol.py": "synthetic"}}
        with patch.object(runner, "load_pinned", side_effect=[module, SimpleNamespace()]):
            with self.assertRaisesRegex(runner.ReplayError, "did not prove completed/reaped.*unreaped"):
                runner.run_suite(pair, self.root, contract, helper)
        self.assertEqual(len(seen), 1, "an unreaped child must abort all later spawns")
        self.assertIsNot(seen[0]["cancel_event"], original_event, "fresh suite event must be replaced by runner-owned event")
        self.assertTrue(seen[0]["cancel_event"].is_set(), "aborted suite must cancel the owned group event")
        receipt = json.loads((self.root / "diagnostic-suite/run-receipt.json").read_text())
        self.assertFalse(receipt["successful"])
        self.assertEqual(receipt["invocations"][0]["supervisor"]["status"], "unreaped")
        for item in pair.values():
            self.assertEqual(Path(item["path"]).stat().st_mode & 0o777, 0o600)

    def test_residual_generated_symlink_fails_storage_gate(self) -> None:
        link = self.root / "external"
        link.symlink_to(Path("/dev/null"))
        with self.assertRaisesRegex(runner.ReplayError, "generated symlink"):
            runner.tree_bytes(self.root)


if __name__ == "__main__":
    unittest.main()
