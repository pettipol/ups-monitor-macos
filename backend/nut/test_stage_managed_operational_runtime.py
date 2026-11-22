"""Copy-only tests with generated inert bytes; no native artifact is opened."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import stage_managed_operational_runtime as stage


class StagingTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("subprocess.Popen", side_effect=AssertionError("process_launch_forbidden"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def fixture(self, folder):
        root = Path(folder).resolve()
        modules = root / "sources"
        modules.mkdir()
        for name in stage.MODULES:
            (modules / name).write_bytes(("inert module " + name).encode())
        native = root / stage.NATIVE_NAME
        native.write_bytes(b"inert native bytes, never executed")
        native.chmod(0o600)
        python = root / "python"
        python.write_bytes(b"inert interpreter bytes, never executed")
        python.chmod(0o700)
        return native, modules, python, root / "new-runtime"

    def stage_fixture(self, native, modules, python, destination):
        with mock.patch.object(stage, "NATIVE_SHA256", hashlib.sha256(native.read_bytes()).hexdigest()), \
                mock.patch.object(stage, "NATIVE_SIZE", native.stat().st_size):
            return stage.stage(native, modules, python, destination)

    def test_fixed_contract(self):
        self.assertEqual(stage.NATIVE_SHA256, "d754eaa71ef19dad5532ddabfd507f084ec6848ef2642718b1cb575657f43cfc")
        self.assertEqual(stage.NATIVE_SIZE, 437584)
        self.assertEqual(len(stage.MODULES), 9)
        self.assertEqual(stage.PROFILE, "apc-smc1500i-operational-v2")
        self.assertEqual((stage.ARCHITECTURE, stage.MINIMUM_MACOS), ("arm64", "27.0"))

    def test_identical_copy_disabled_and_exact_nine_key_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            original_mode = stat.S_IMODE(native.stat().st_mode)
            original_hash = hashlib.sha256(native.read_bytes()).hexdigest()
            result = self.stage_fixture(native, modules, python, destination)
            self.assertEqual(result["status"], "STAGED_NOT_EXECUTABLE")
            self.assertIs(result["runtime_ready"], False)
            self.assertEqual(native.read_bytes(), (destination / stage.NATIVE_NAME).read_bytes())
            self.assertEqual(stat.S_IMODE(native.stat().st_mode), original_mode)
            self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(), original_hash)
            manifest = json.loads((destination / "runtime.json").read_bytes())
            self.assertEqual(set(manifest), {"schema_version", "profile", "python_path", "python_sha256",
                "module_sha256", "native_name", "native_sha256", "architecture", "minimum_macos"})
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["native_sha256"], original_hash)
            self.assertEqual(manifest["python_path"], str(python))
            self.assertEqual(manifest["module_sha256"], {
                name: hashlib.sha256((modules / name).read_bytes()).hexdigest() for name in stage.MODULES})
            self.assertEqual(set(path.name for path in destination.iterdir()),
                             set(stage.MODULES) | {stage.NATIVE_NAME, "runtime.json"})
            for path in destination.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)

    def test_wrong_pin_and_wrong_size_reject_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            with self.assertRaisesRegex(ValueError, "native_pin_mismatch"):
                stage.stage(native, modules, python, destination)
            self.assertFalse(destination.exists())
            with mock.patch.object(stage, "NATIVE_SHA256", hashlib.sha256(native.read_bytes()).hexdigest()), \
                    self.assertRaisesRegex(ValueError, "native_pin_mismatch"):
                stage.stage(native, modules, python, destination)
            self.assertFalse(destination.exists())

    def test_no_overwrite_and_destination_alias_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            self.stage_fixture(native, modules, python, destination)
            before = (destination / "runtime.json").read_bytes()
            with self.assertRaises(FileExistsError):
                self.stage_fixture(native, modules, python, destination)
            self.assertEqual((destination / "runtime.json").read_bytes(), before)
            for alias in (native, python, modules, modules / "nested", modules.parent):
                with self.subTest(alias=str(alias)), self.assertRaises((OSError, ValueError)):
                    self.stage_fixture(native, modules, python, alias)

    def test_symlink_aliases_and_hardlinked_sources_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            root = native.parent
            links = []
            for name, target in (("native-link", native), ("modules-link", modules), ("python-link", python)):
                link = root / name
                link.symlink_to(target)
                links.append(link)
            for arguments in [(links[0], modules, python, destination),
                              (native, links[1], python, destination),
                              (native, modules, links[2], destination),
                              (native, modules, python, links[1] / "child")]:
                with self.subTest(arguments=arguments), self.assertRaises((OSError, ValueError)):
                    self.stage_fixture(*arguments)
            module = modules / stage.MODULES[0]
            module.unlink()
            os.link(python, module)
            with self.assertRaisesRegex(ValueError, "source_alias"):
                self.stage_fixture(native, modules, python, destination)
            self.assertFalse(destination.exists())

    def test_module_closure_missing_symlink_and_fifo_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            module = modules / "bounded_stream_dispatch.py"
            original = module.read_bytes()
            module.unlink()
            with self.assertRaises(OSError):
                self.stage_fixture(native, modules, python, destination)
            module.symlink_to(python)
            with self.assertRaises((OSError, ValueError)):
                self.stage_fixture(native, modules, python, destination)
            module.unlink()
            os.mkfifo(module)
            with self.assertRaises(ValueError):
                self.stage_fixture(native, modules, python, destination)
            module.unlink()
            module.write_bytes(original)
            python.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "python_not_executable"):
                self.stage_fixture(native, modules, python, destination)
            self.assertFalse(destination.exists())

    def test_regular_file_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "source"
            source.write_bytes(b"bounded")
            with self.assertRaises(ValueError):
                stage.read_source(source, 2)
            source.write_bytes(b"")
            with self.assertRaises(ValueError):
                stage.read_source(source, stage.LIMIT_MODULE)
            with self.assertRaises(ValueError):
                stage.read_source(root, stage.LIMIT_MODULE)

    def test_replaced_destination_rejected_and_partial_evidence_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            moved = destination.with_name("moved-runtime")
            verify = stage._verify
            replaced = False
            def replace_after_verify(fd, name, content):
                nonlocal replaced
                verify(fd, name, content)
                if not replaced:
                    replaced = True
                    destination.rename(moved)
                    destination.mkdir(mode=0o700)
            with mock.patch.object(stage, "_verify", side_effect=replace_after_verify), \
                    self.assertRaisesRegex(ValueError, "destination_replaced"):
                self.stage_fixture(native, modules, python, destination)
            self.assertTrue(destination.is_dir())
            self.assertEqual((moved / stage.NATIVE_NAME).read_bytes(), native.read_bytes())
            self.assertEqual(stat.S_IMODE((moved / stage.NATIVE_NAME).stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
