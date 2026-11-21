"""Inert fixtures only. No test starts an interpreter, native driver or app."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import managed_operational_entrypoint as entry

LAUNCH = "00000000-0000-4000-8000-000000000001"


class AdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Runner:
    trigger: str = "child_nonzero_exit"
    returncode: int = 1
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_sha256: str = "0" * 64
    stderr_sha256: str = "0" * 64
    leader_reaped: bool = True
    group_absent: bool = True
    stdout_eof: bool = True
    stderr_eof: bool = True
    consumer_quiesced: bool = True


@dataclass(frozen=True)
class Capture:
    schema_version: int = 2
    protocol: str = "ups-monitor.continuous.v2"
    state: str = "failed"
    terminal_reason: str = "child_failed"
    first_error: str | None = "child_failed"
    publication_error: str | None = None
    source_id: str = entry.NATIVE_NAME
    session_id: str = "0" * 32
    started_at_unix_ms: int = 1
    published_at_unix_ms: int | None = None
    sample_count: int = 0
    end_reason: str | None = None
    runner_result: Runner = field(default_factory=Runner)
    consumer_quiesced: bool = True
    publisher_quiesced: bool = True
    publisher_closed: bool = True
    terminal_published: bool = False
    ownership_resolved: bool = True


@dataclass(frozen=True)
class Receipt:
    capture_result: Capture | None = None
    control_reason: str | None = None
    adapter_error: str | None = None
    watcher_quiesced: bool = True
    ownership_resolved: bool = False


class NoProcessTests(unittest.TestCase):
    def setUp(self):
        # These author tests intentionally have no real-process escape path.
        patcher = mock.patch("subprocess.Popen", side_effect=AssertionError("process_launch_forbidden"))
        patcher.start()
        self.addCleanup(patcher.stop)


class RuntimeValidationTests(NoProcessTests):
    def fixture(self, folder):
        root = Path(folder).resolve()
        python = root / "python"
        python.write_bytes(b"inert interpreter bytes")
        python.chmod(0o700)
        pins = {}
        for name in entry.MODULES:
            data = ("inert " + name).encode()
            (root / name).write_bytes(data)
            pins[name] = hashlib.sha256(data).hexdigest()
        native = root / entry.NATIVE_NAME
        native.write_bytes(b"inert native bytes, never executed")
        native.chmod(0o700)
        manifest = {"schema_version": 2, "profile": entry.PROFILE, "python_path": str(python),
                    "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
                    "module_sha256": pins, "native_name": entry.NATIVE_NAME,
                    "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                    "architecture": "arm64", "minimum_macos": "27.0"}
        (root / "runtime.json").write_text(json.dumps(manifest))
        return root, python, native, manifest

    def validate(self, root, python, native, manifest):
        with mock.patch.object(entry, "__file__", str(root / "managed_operational_entrypoint.py")), \
                mock.patch.object(entry, "NATIVE_SHA256", manifest["native_sha256"]), \
                mock.patch.object(entry, "NATIVE_SIZE", len(native.read_bytes())), \
                mock.patch.object(entry.sys, "executable", str(python)), \
                mock.patch.object(entry.sys, "flags", SimpleNamespace(isolated=True, no_site=True)), \
                mock.patch.object(entry.sys, "dont_write_bytecode", True), \
                mock.patch.object(entry.platform, "system", return_value="Darwin"), \
                mock.patch.object(entry.platform, "machine", return_value="arm64"), \
                mock.patch.object(entry.platform, "mac_ver", return_value=("27.0", (), "")):
            return entry.validate_runtime()

    def test_fixed_contract(self):
        self.assertEqual(entry.NATIVE_SHA256, "d754eaa71ef19dad5532ddabfd507f084ec6848ef2642718b1cb575657f43cfc")
        self.assertEqual(entry.NATIVE_SIZE, 437584)
        self.assertEqual(entry.PROFILE, "apc-smc1500i-operational-v2")
        self.assertEqual(entry.MODULES, frozenset({
            "managed_operational_entrypoint.py", "app_controlled_operational.py", "operational_capture.py",
            "operational_publication.py", "continuous_capture.py", "continuous_protocol.py",
            "process_deadline.py", "bounded_stream_dispatch.py", "cleanup_diagnostics.py"}))

    def test_exact_manifest_and_full_module_closure(self):
        with tempfile.TemporaryDirectory() as folder:
            root, python, native, manifest = self.fixture(folder)
            self.assertEqual(self.validate(root, python, native, manifest)[3], native)
            changes = {
                "old schema": lambda m: m.update(schema_version=1),
                "boolean schema": lambda m: m.update(schema_version=True),
                "profile": lambda m: m.update(profile="apc-smc1500i-120s-v1"),
                "native": lambda m: m.update(native_name="other"),
                "pin": lambda m: m.update(native_sha256="0" * 64),
                "arch": lambda m: m.update(architecture="x86_64"),
                "macos": lambda m: m.update(minimum_macos="14.0"),
                "extra": lambda m: m.update(extra=1),
                "traversal": lambda m: m.update(python_path=str(root / ".." / "python")),
                "hash type": lambda m: m.update(python_sha256=1),
                "missing module": lambda m: m["module_sha256"].pop("bounded_stream_dispatch.py"),
                "extra module": lambda m: m["module_sha256"].update({"extra.py": "0" * 64}),
            }
            for label, mutate in changes.items():
                with self.subTest(label=label):
                    changed = json.loads(json.dumps(manifest))
                    mutate(changed)
                    (root / "runtime.json").write_text(json.dumps(changed))
                    with self.assertRaises((ValueError, OSError)):
                        self.validate(root, python, native, manifest)
            duplicate = json.dumps(manifest).replace('"schema_version": 2', '"schema_version": 2, "schema_version": 2', 1)
            (root / "runtime.json").write_text(duplicate)
            with self.assertRaisesRegex(ValueError, "invalid_manifest"):
                self.validate(root, python, native, manifest)

    def test_missing_and_tampered_module_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, python, native, manifest = self.fixture(folder)
            for name in entry.MODULES:
                with self.subTest(module=name):
                    source = root / name
                    original = source.read_bytes()
                    source.write_bytes(b"tampered")
                    with self.assertRaisesRegex(ValueError, "module_rejected"):
                        self.validate(root, python, native, manifest)
                    source.unlink()
                    with self.assertRaises(OSError):
                        self.validate(root, python, native, manifest)
                    source.write_bytes(original)

    def test_host_and_isolation_matrix(self):
        for system, machine, version, expected in [
            ("Darwin", "arm64", "27.0", True), ("Darwin", "arm64", "27.1.2", True),
            ("Darwin", "arm64", "28.0", True), ("Darwin", "arm64", "26.9", False),
            ("Darwin", "x86_64", "27.0", False), ("Linux", "arm64", "27.0", False),
            ("Darwin", "arm64", "", False), ("Darwin", "arm64", "27garbage", False),
        ]:
            with self.subTest(host=(system, machine, version)), \
                    mock.patch.object(entry.platform, "system", return_value=system), \
                    mock.patch.object(entry.platform, "machine", return_value=machine), \
                    mock.patch.object(entry.platform, "mac_ver", return_value=(version, (), "")):
                self.assertEqual(entry._host_admitted(), expected)
        with tempfile.TemporaryDirectory() as folder:
            root, python, native, manifest = self.fixture(folder)
            for flag in ("isolated", "no_site"):
                flags = SimpleNamespace(isolated=True, no_site=True)
                setattr(flags, flag, False)
                with self.subTest(flag=flag), mock.patch.object(entry, "__file__", str(root / "managed_operational_entrypoint.py")), \
                        mock.patch.object(entry, "NATIVE_SHA256", manifest["native_sha256"]), \
                        mock.patch.object(entry, "NATIVE_SIZE", native.stat().st_size), \
                        mock.patch.object(entry, "_host_admitted", return_value=True), \
                        mock.patch.object(entry.sys, "executable", str(python)), \
                        mock.patch.object(entry.sys, "flags", flags), \
                        mock.patch.object(entry.sys, "dont_write_bytecode", True), \
                        self.assertRaisesRegex(ValueError, "interpreter_rejected"):
                    entry.validate_runtime()

    def test_bounded_no_follow_and_disabled_native(self):
        with tempfile.TemporaryDirectory() as folder:
            root, python, native, manifest = self.fixture(folder)
            native.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "native_rejected"):
                self.validate(root, python, native, manifest)
            regular = root / "regular"
            regular.write_bytes(b"bounded")
            link = root / "link"
            link.symlink_to(regular)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            for path, bound in [(regular, 1), (link, 100), (fifo, 100), (root, 100)]:
                with self.subTest(path=path.name), self.assertRaises((ValueError, OSError)):
                    entry._read_regular(path, bound)

    def test_preloaded_closure_rejected(self):
        with mock.patch.dict(entry.sys.modules, {"bounded_stream_dispatch": object()}), \
                mock.patch.object(entry.importlib, "import_module") as importer, \
                self.assertRaisesRegex(ValueError, "preloaded_backend_rejected"):
            entry._load_adapter(Path("/inert"))
        importer.assert_not_called()


class ServeTests(NoProcessTests):
    def adapter(self, result):
        return SimpleNamespace(
            AppOperationalAdmissionError=AdmissionError, AppOperationalReceipt=Receipt,
            _capture_receipt=lambda value, source: type(value) is Capture and value.source_id == source,
            run_app_controlled_operational=mock.Mock(return_value=result),
            capture_operational=mock.Mock(return_value=None))

    def serve(self, adapter, *, quiet=True, writer=None):
        payloads, retained = [], []
        with mock.patch.object(entry, "_quiet_workers", return_value=quiet):
            code = entry.serve(adapter, object(), Path("/inert/workspace"), LAUNCH,
                               writer=writer or payloads.append, barrier=lambda: retained.append(True))
        return code, payloads, retained

    def test_resolved_failed_preserves_nested_dataclass_and_returns_zero(self):
        adapter = self.adapter(Receipt(Capture(), "app_disconnected", None, True, True))
        code, payloads, retained = self.serve(adapter)
        self.assertEqual((code, retained), (0, []))
        self.assertEqual(set(payloads[0]), {"protocol", "schema_version", "launch_id", "adapter"})
        self.assertEqual(payloads[0]["protocol"], entry.PROTOCOL)
        self.assertEqual(payloads[0]["launch_id"], LAUNCH)
        self.assertEqual(payloads[0]["adapter"]["capture_result"]["state"], "failed")
        adapter.run_app_controlled_operational.assert_called_once()
        self.assertEqual(adapter.run_app_controlled_operational.call_args.kwargs["source_id"], entry.NATIVE_NAME)

    def test_stop_before_capture_sets_same_cancellation_event(self):
        adapter = self.adapter(Receipt(Capture(), "signal", None, True, True))
        event = threading.Event()
        def run(_profile, **kwargs):
            kwargs["capture"](cancel_event=event)
            return Receipt(Capture(), "signal", None, True, True)
        adapter.run_app_controlled_operational.side_effect = run
        with mock.patch.object(entry, "STOP_REQUESTED", True):
            self.assertEqual(self.serve(adapter)[0], 0)
        self.assertTrue(event.is_set())
        self.assertIs(adapter.capture_operational.call_args.kwargs["cancel_event"], event)

    def test_unresolved_receipt_is_preserved_and_retained_without_retry(self):
        capture = replace(Capture(), state="unresolved", ownership_resolved=False)
        adapter = self.adapter(Receipt(capture, "stop", "observer_failed", True, False))
        code, payloads, retained = self.serve(adapter)
        self.assertEqual((code, retained), (2, [True]))
        self.assertEqual(payloads[0]["adapter"]["capture_result"]["state"], "unresolved")
        self.assertEqual(payloads[0]["adapter"]["adapter_error"], "observer_failed")
        adapter.run_app_controlled_operational.assert_called_once()

    def test_unknown_receipts_and_exceptions_retain_owner(self):
        for result in (None, object(), {"ownership_resolved": True}, Receipt(ownership_resolved=True),
                       Receipt(adapter_error="invented_wire_error"), Receipt(watcher_quiesced=1)):
            with self.subTest(result=result):
                code, payloads, retained = self.serve(self.adapter(result))
                self.assertEqual((code, retained), (2, [True]))
                self.assertEqual(payloads[0]["adapter"]["adapter_error"], "capture_failed")
        adapter = self.adapter(None)
        adapter.run_app_controlled_operational.side_effect = RuntimeError("unknown")
        self.assertEqual(self.serve(adapter)[2], [True])

    def test_admission_rejection_exits_only_with_quiet_workers(self):
        adapter = self.adapter(None)
        adapter.run_app_controlled_operational.side_effect = AdmissionError()
        self.assertEqual(self.serve(adapter)[2], [])
        self.assertEqual(self.serve(adapter, quiet=False)[2], [True])

    def test_worker_liveness_overrides_cleanup_without_new_wire_code(self):
        adapter = self.adapter(Receipt(Capture(), None, None, True, True))
        code, payloads, retained = self.serve(adapter, quiet=False)
        self.assertEqual((code, retained), (2, [True]))
        self.assertFalse(payloads[0]["adapter"]["ownership_resolved"])
        self.assertEqual(payloads[0]["adapter"]["adapter_error"], "capture_failed")
        self.assertEqual(payloads[0]["adapter"]["capture_result"]["state"], "failed")

    def test_writer_failure_cannot_release_unresolved_owner(self):
        writer = mock.Mock(side_effect=OSError("inert writer failure"))
        self.assertEqual(self.serve(self.adapter(Receipt()), writer=writer)[2], [True])
        self.assertEqual(self.serve(self.adapter(Receipt(Capture(), None, None, True, True)), writer=writer)[2], [])

    def test_emit_is_bounded_single_line_and_partial_writes_complete(self):
        chunks = []
        def write(_fd, data):
            block = bytes(data[:7])
            chunks.append(block)
            return len(block)
        with mock.patch.object(entry.os, "write", side_effect=write):
            entry.emit({"protocol": entry.PROTOCOL, "message": "è"})
        encoded = b"".join(chunks)
        self.assertEqual(encoded.count(b"\n"), 1)
        self.assertEqual(json.loads(encoded)["message"], "è")
        with mock.patch.object(entry.os, "write") as writer, self.assertRaises(ValueError):
            entry.emit({"too_large": "x" * entry.MAX_RECEIPT_BYTES})
        writer.assert_not_called()


class MainTests(NoProcessTests):
    def test_fixed_argv_and_single_adapter_selection(self):
        native = Path("/inert/apcmicrolink-hidapi-operational")
        constructor = mock.Mock(return_value=object())
        with mock.patch.object(entry.signal, "signal"), \
                mock.patch.object(entry.sys, "argv", ["entry.py", "--workspace", "/inert/work", "--launch-id", LAUNCH]), \
                mock.patch.object(entry, "validate_runtime", return_value=(Path("/inert"), Path("/python"), "0" * 64, native)), \
                mock.patch.object(entry, "_load_adapter", return_value=SimpleNamespace(FixedOperationalProfile=constructor)), \
                mock.patch.object(entry, "serve", return_value=0) as serve:
            self.assertEqual(entry.main(), 0)
        constructor.assert_called_once_with((str(native), "-s", "ups-monitor-operational-v2", "-d1",
            "-x", "hidapi_shared", "-x", "guarded_monitor", "-x", "port=auto", "-x", "hid_fallback=no",
            "-x", "guard_probe_attempts=1", "-x", "guard_vid=051d", "-x", "guard_pid=0003",
            "-x", "guard_deadline=35", "-x", "monitor_stream_v2"), entry.NATIVE_SHA256)
        serve.assert_called_once()

    def test_preflight_rejects_before_backend_import(self):
        for arguments in [
            ["--workspace", "/inert", "--launch-id", LAUNCH, "--profile", "other"],
            ["--workspace", "relative", "--launch-id", LAUNCH],
            ["--workspace", "/inert", "--launch-id", LAUNCH.upper().replace("00000000", "ABCDEF00", 1)],
            ["--workspace", "/inert", "--launch-id", "invalid"],
        ]:
            with self.subTest(arguments=arguments), mock.patch.object(entry.signal, "signal"), \
                    mock.patch.object(entry.sys, "argv", ["entry.py", *arguments]), \
                    mock.patch.object(entry, "validate_runtime") as validate, \
                    mock.patch.object(entry, "_load_adapter") as importer, \
                    mock.patch.object(entry, "_quiet_workers", return_value=True), \
                    mock.patch.object(entry, "emit") as emit:
                self.assertEqual(entry.main(), 2)
                validate.assert_not_called()
                importer.assert_not_called()
                self.assertEqual(emit.call_args.args[0]["adapter"]["adapter_error"], "adapter_setup_failed")
        with mock.patch.object(entry.signal, "signal"), \
                mock.patch.object(entry.sys, "argv", ["entry.py", "--workspace", "/inert", "--launch-id", LAUNCH]), \
                mock.patch.object(entry, "validate_runtime", side_effect=ValueError("missing closure")), \
                mock.patch.object(entry, "_load_adapter") as importer, \
                mock.patch.object(entry, "_quiet_workers", return_value=True), \
                mock.patch.object(entry, "emit"):
            self.assertEqual(entry.main(), 2)
        importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
