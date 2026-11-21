from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import stage_managed_native_runtime as stage
import managed_native_entrypoint as entry


class AdmissionError(RuntimeError):
    pass


@dataclass
class FakeReceipt:
    capture_result: object = None
    control_reason: str | None = None
    adapter_error: str | None = None
    watcher_quiesced: bool = True
    ownership_resolved: bool = False


class ManagedNativeStagingTests(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        modules = root / "sources"
        modules.mkdir()
        for name in stage.MODULES:
            (modules / name).write_bytes(("synthetic " + name).encode())
        native = root / stage.NATIVE_NAME
        native.write_bytes(b"synthetic native bytes")
        python = root / "python"
        fd = os.open(python, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"synthetic interpreter")
        return native, modules, python, root / "new-runtime"

    def test_stages_identical_bytes_nonexecutable_and_exact_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            native_hash = hashlib.sha256(native.read_bytes()).hexdigest()
            with mock.patch.object(stage, "NATIVE_SHA256", native_hash):
                result = stage.stage(native, modules, python, destination)
            self.assertEqual(result["status"], "STAGED_NOT_EXECUTABLE")
            self.assertFalse(result["runtime_ready"])
            staged = destination / stage.NATIVE_NAME
            self.assertEqual(staged.read_bytes(), native.read_bytes())
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
            self.assertFalse(staged.stat().st_mode & 0o111)
            manifest = json.loads((destination / "runtime.json").read_text())
            self.assertEqual(set(manifest), {"schema_version", "profile", "python_path", "python_sha256", "module_sha256", "native_name", "native_sha256"})
            self.assertEqual(manifest["native_sha256"], native_hash)
            self.assertEqual(set(manifest["module_sha256"]), set(stage.MODULES))

    def test_mismatch_destination_collision_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            with self.assertRaises(ValueError):
                stage.stage(native, modules, python, destination)
            native_hash = hashlib.sha256(native.read_bytes()).hexdigest()
            with mock.patch.object(stage, "NATIVE_SHA256", native_hash):
                stage.stage(native, modules, python, destination)
                with self.assertRaises(FileExistsError):
                    stage.stage(native, modules, python, destination)
            link = Path(folder) / "native-link"
            link.symlink_to(native)
            with mock.patch.object(stage, "NATIVE_SHA256", native_hash), self.assertRaises(OSError):
                stage.stage(link, modules, python, Path(folder) / "other")

    def test_replaced_destination_is_rejected_after_copy_hashing(self):
        with tempfile.TemporaryDirectory() as folder:
            native, modules, python, destination = self.fixture(folder)
            native_hash = hashlib.sha256(native.read_bytes()).hexdigest()
            moved = destination.with_name("moved-runtime")
            original_sha = stage.sha
            replaced = False

            def sha_with_replacement(data):
                nonlocal replaced
                digest = original_sha(data)
                # Replace only once the complete staging layout exists; no
                # dependency on the number or order of individual hash calls.
                if not replaced and (destination / "runtime.json").is_file():
                    replaced = True
                    os.rename(destination, moved)
                    destination.mkdir(mode=0o700)
                return digest

            with mock.patch.object(stage, "NATIVE_SHA256", native_hash), \
                    mock.patch.object(stage, "sha", side_effect=sha_with_replacement), \
                    self.assertRaisesRegex(ValueError, "destination_replaced"):
                stage.stage(native, modules, python, destination)
            self.assertTrue(moved.is_dir())
            self.assertTrue(destination.is_dir())


class ManagedNativeValidationTests(unittest.TestCase):
    def runtime_fixture(self, root):
        root = Path(root)
        python = root / "python"
        fd = os.open(python, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"synthetic interpreter")
        pins = {}
        for name in entry.MODULES:
            data = ("synthetic " + name).encode()
            (root / name).write_bytes(data)
            pins[name] = hashlib.sha256(data).hexdigest()
        native_data = b"synthetic executable native"
        native = root / entry.NATIVE_NAME
        fd = os.open(native, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "wb") as stream:
            stream.write(native_data)
        manifest = {"schema_version": 1, "profile": entry.PROFILE, "python_path": str(python),
            "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(), "module_sha256": pins,
            "native_name": entry.NATIVE_NAME, "native_sha256": hashlib.sha256(native_data).hexdigest()}
        (root / "runtime.json").write_text(json.dumps(manifest))
        return root, python, native, manifest, hashlib.sha256(native_data).hexdigest()

    def validate_fixture(self, root, python, native_hash):
        with mock.patch.object(entry, "__file__", str(root / "managed_native_entrypoint.py")), \
                mock.patch.object(entry, "NATIVE_SHA256", native_hash), \
                mock.patch.object(entry.sys, "executable", str(python)), \
                mock.patch.object(entry.sys, "flags", SimpleNamespace(isolated=True, no_site=True)), \
                mock.patch.object(entry.sys, "dont_write_bytecode", True):
            return entry.validate_runtime()

    def test_native_hash_is_fixed_in_validator(self):
        self.assertEqual(entry.NATIVE_SHA256, "2dae6874c8cb99469a9def4a9f584898e815656d87b93dcc6fd67dba5b7d6183")
        self.assertEqual(len(entry.MODULES), 5)

    def test_bad_manifest_keys_rejected_without_project_import(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime.json"
            path.write_text(json.dumps({"unexpected": True}))
            with mock.patch.object(entry, "__file__", str(Path(folder) / "managed_native_entrypoint.py")), \
                    mock.patch.dict("sys.modules", {"app_controlled_capture": None}):
                with self.assertRaises(ValueError):
                    entry.validate_runtime()

    def test_synthetic_valid_runtime_and_manifest_tamper_matrix(self):
        with tempfile.TemporaryDirectory() as folder:
            root, python, native, manifest, native_hash = self.runtime_fixture(folder)
            self.assertEqual(self.validate_fixture(root, python, native_hash)[3], native)
            mutations = {
                "wrong schema": lambda m: m.update(schema_version=2),
                "wrong profile": lambda m: m.update(profile="other"),
                "wrong native pin": lambda m: m.update(native_sha256="0" * 64),
                "extra key": lambda m: m.update(extra=True),
                "path traversal": lambda m: m.update(python_path=str(root / ".." / "python")),
                "unknown module": lambda m: m["module_sha256"].update({"extra.py": "1" * 64}),
            }
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    changed = json.loads(json.dumps(manifest))
                    mutate(changed)
                    (root / "runtime.json").write_text(json.dumps(changed))
                    with self.assertRaises((ValueError, OSError)):
                        self.validate_fixture(root, python, native_hash)
            (root / "runtime.json").write_text(json.dumps(manifest))
            (root / "managed_native_entrypoint.py").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                self.validate_fixture(root, python, native_hash)

    def test_runtime_rejects_symlink_fifo_and_nonexecutable_native(self):
        with tempfile.TemporaryDirectory() as folder:
            root, python, native, manifest, native_hash = self.runtime_fixture(folder)
            entrypoint = root / "managed_native_entrypoint.py"
            original = entrypoint.read_bytes()
            entrypoint.unlink()
            entrypoint.symlink_to(root / "python")
            with self.assertRaises((ValueError, OSError)):
                self.validate_fixture(root, python, native_hash)
            entrypoint.unlink()
            os.mkfifo(entrypoint)
            with self.assertRaises((ValueError, OSError)):
                self.validate_fixture(root, python, native_hash)
            entrypoint.unlink()
            entrypoint.write_bytes(original)
            native.chmod(0o600)
            with self.assertRaises(ValueError):
                self.validate_fixture(root, python, native_hash)

    def test_regular_reader_rejects_symlink_and_nonregular(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            actual = root / "actual"
            actual.write_bytes(b"safe")
            link = root / "link"
            link.symlink_to(actual)
            with self.assertRaises(OSError):
                entry._read_regular(link, 20)
            with self.assertRaises((OSError, ValueError)):
                entry._read_regular(root, 20)

    def test_serve_emits_native_protocol_and_retains_unresolved_owner(self):
        calls, payloads = [], []
        adapter = SimpleNamespace(run_app_controlled=lambda *_a, **_k: FakeReceipt(
            control_reason="stop", adapter_error="capture_failed"), AppCaptureAdmissionError=AdmissionError)
        code = entry.serve(adapter, object(), Path("/synthetic/workspace"), "00000000-0000-4000-8000-000000000001",
                           writer=payloads.append, barrier=lambda: calls.append("retained"))
        self.assertEqual(code, 2)
        self.assertEqual(payloads[0]["protocol"], "ups-monitor.managed-native.v1")
        self.assertEqual(payloads[0]["adapter"]["control_reason"], "stop")
        self.assertEqual(calls, ["retained"])

    def test_serve_resolved_eof_receipt_and_pre_requested_stop(self):
        payloads, retained, cancelled, sources = [], [], [], []
        def run(_profile, **kwargs):
            sources.append(kwargs["source_id"])
            event = __import__("threading").Event()
            kwargs["capture"](cancel_event=event)
            cancelled.append(event.is_set())
            return FakeReceipt(capture_result={"state": "cancelled"}, control_reason="app_disconnected",
                               adapter_error=None, watcher_quiesced=True, ownership_resolved=True)
        adapter = SimpleNamespace(run_app_controlled=run, capture_continuous=lambda *_a, **_k: None,
                                  AppCaptureAdmissionError=AdmissionError)
        with mock.patch.object(entry, "STOP_REQUESTED", True):
            code = entry.serve(adapter, object(), Path("/synthetic/workspace"), "launch",
                               writer=payloads.append, barrier=lambda: retained.append(True))
        self.assertEqual(code, 0)
        self.assertEqual(payloads[0]["protocol"], entry.PROTOCOL)
        self.assertEqual(payloads[0]["adapter"]["control_reason"], "app_disconnected")
        self.assertEqual(sources, ["apcmicrolink-hidapi-continuous"])
        self.assertEqual(cancelled, [True])
        self.assertEqual(retained, [])

    def test_adapter_admission_error_is_reported_without_false_cleanup(self):
        payloads, retained = [], []
        def reject(*_a, **_k):
            raise AdmissionError()
        adapter = SimpleNamespace(run_app_controlled=reject, AppCaptureAdmissionError=AdmissionError)
        code = entry.serve(adapter, object(), Path("/synthetic/workspace"), "launch",
                           writer=payloads.append, barrier=lambda: retained.append(True))
        self.assertEqual(code, 2)
        self.assertFalse(payloads[0]["adapter"]["ownership_resolved"])
        self.assertEqual(retained, [])

    def test_main_builds_only_the_fixed_native_argv(self):
        captured = []
        class FixedProfile:
            def __init__(self, argv, digest):
                self.argv, self.digest = argv, digest
        adapter = SimpleNamespace(FixedCaptureProfile=FixedProfile)
        launch = "00000000-0000-4000-8000-000000000001"
        with mock.patch.object(entry.signal, "signal"), \
                mock.patch.object(entry.sys, "path", entry.sys.path.copy()), \
                mock.patch.object(entry.sys, "argv", ["entry.py", "--workspace", "/private/work", "--launch-id", launch]), \
                mock.patch.object(entry, "validate_runtime", return_value=(Path("/bundle"), Path("/python"), "p" * 64, Path("/bundle/apcmicrolink-hidapi-continuous"))), \
                mock.patch.dict("sys.modules", {"app_controlled_capture": adapter}), \
                mock.patch.object(entry, "serve", side_effect=lambda _a, profile, _w, _l: captured.append(profile.argv) or 0):
            self.assertEqual(entry.main(), 0)
        self.assertEqual(captured[0], ("/bundle/apcmicrolink-hidapi-continuous", "-s", "ups-monitor-h07", "-d1",
            "-x", "hidapi_shared", "-x", "guarded_monitor", "-x", "port=auto", "-x", "hid_fallback=no",
            "-x", "guard_probe_attempts=1", "-x", "guard_vid=051d", "-x", "guard_pid=0003",
            "-x", "guard_deadline=130", "-x", "monitor_stream_v1"))


if __name__ == "__main__":
    unittest.main()
