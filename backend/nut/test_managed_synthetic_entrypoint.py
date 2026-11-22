from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest import mock

import managed_synthetic_entrypoint as entry


@dataclass
class FakeReceipt:
    capture_result: dict | None
    control_reason: str | None = None
    adapter_error: str | None = None
    watcher_quiesced: bool = True
    ownership_resolved: bool = True


class AdmissionError(RuntimeError):
    pass


class ManagedSyntheticEntrypointTests(unittest.TestCase):
    def fake_adapter(self, result=None, error=None):
        def capture(*_args, **kwargs):
            self.assertEqual(kwargs["control_read_fd"], 0)
            self.assertEqual(kwargs["source_id"], "synthetic-app-session")
            self.assertEqual(kwargs["output_root"].name, "capture")
            self.assertEqual(kwargs["feed_directory"].name, "feed")
            if error is not None:
                raise error
            return result
        return SimpleNamespace(run_app_controlled=capture, AppCaptureAdmissionError=AdmissionError)

    def test_resolved_receipt_returns_only_after_adapter_evidence(self):
        payloads, retained = [], []
        result = FakeReceipt({"runner_status": "cancelled", "state": "failed", "terminal_reason": "cancelled"})
        code = entry.serve(self.fake_adapter(result), object(), Path("synthetic-workspace"), "synthetic-launch",
                           writer=payloads.append, barrier=lambda: retained.append(True))
        self.assertEqual(code, 0)
        self.assertEqual(retained, [])
        self.assertEqual(payloads[0]["adapter"]["capture_result"]["terminal_reason"], "cancelled")

    def test_unresolved_receipt_is_emitted_then_supervisor_is_retained(self):
        calls = []
        result = FakeReceipt({"runner_status": "unreaped"}, ownership_resolved=False)
        code = entry.serve(self.fake_adapter(result), object(), Path("synthetic-workspace"), "synthetic-launch",
                           writer=lambda p: calls.append(("receipt", p["adapter"]["ownership_resolved"])),
                           barrier=lambda: calls.append(("barrier", True)))
        self.assertEqual(code, 2)
        self.assertEqual(calls, [("receipt", False), ("barrier", True)])

    def test_unexpected_adapter_exception_retains_without_raw_text(self):
        payloads, retained = [], []
        entry.serve(self.fake_adapter(error=RuntimeError("synthetic sensitive text")), object(), Path("synthetic-workspace"),
                    "synthetic-launch", writer=payloads.append, barrier=lambda: retained.append(True))
        self.assertEqual(retained, [True])
        self.assertNotIn("sensitive", json.dumps(payloads))
        self.assertFalse(payloads[0]["adapter"]["ownership_resolved"])

    def test_pre_admission_rejection_can_exit_without_fabricating_cleanup_receipt(self):
        payloads, retained = [], []
        code = entry.serve(self.fake_adapter(error=AdmissionError()), object(), Path("synthetic-workspace"),
                           "synthetic-launch", writer=payloads.append, barrier=lambda: retained.append(True))
        self.assertEqual(code, 2)
        self.assertEqual(retained, [])
        self.assertFalse(payloads[0]["adapter"]["ownership_resolved"])

    def test_live_worker_overrides_resolved_boolean_and_retains(self):
        payloads, retained = [], []
        worker = SimpleNamespace(is_alive=lambda: True)
        with mock.patch.object(entry.threading, "enumerate", return_value=[threading.current_thread(), worker]):
            entry.serve(self.fake_adapter(FakeReceipt({})), object(), Path("synthetic-workspace"), "synthetic-launch",
                        writer=payloads.append, barrier=lambda: retained.append(True))
        self.assertEqual(retained, [True])
        self.assertEqual(payloads[0]["adapter"]["adapter_error"], "workers_not_quiescent")

    def test_broken_receipt_pipe_cannot_exit_unresolved_supervisor(self):
        retained = []
        def broken(_payload):
            raise BrokenPipeError
        code = entry.serve(self.fake_adapter(FakeReceipt({}, ownership_resolved=False)), object(),
                           Path("synthetic-workspace"), "synthetic-launch", writer=broken,
                           barrier=lambda: retained.append(True))
        self.assertEqual(code, 2)
        self.assertEqual(retained, [True])

    def test_emit_has_hard_cap_and_handles_partial_writes_without_logging(self):
        with mock.patch.object(entry.os, "write") as write:
            with self.assertRaises(ValueError):
                entry.emit({"oversized": "x" * entry.MAX_RECEIPT_BYTES})
            write.assert_not_called()
        blocks = []
        def partial(fd, data):
            self.assertEqual(fd, 1)
            blocks.append(bytes(data[:3]))
            return len(blocks[-1])
        with mock.patch.object(entry.os, "write", side_effect=partial):
            entry.emit({"synthetic": True})
        self.assertEqual(json.loads(b"".join(blocks)), {"synthetic": True})

    def test_pre_admission_signal_is_cancelled_before_real_capture_delegation(self):
        cancellation = threading.Event()
        observed = []
        def delegate(*_args, **kwargs):
            observed.append(kwargs["cancel_event"].is_set())
        def run(_profile, **kwargs):
            kwargs["capture"](cancel_event=cancellation)
            return FakeReceipt({})
        adapter = SimpleNamespace(run_app_controlled=run, capture_continuous=delegate,
                                  AppCaptureAdmissionError=AdmissionError)
        with mock.patch.object(entry, "STOP_REQUESTED", True):
            entry.serve(adapter, object(), Path("synthetic-workspace"), "synthetic-launch",
                        writer=lambda _: None, barrier=lambda: self.fail("resolved fake must not retain"))
        self.assertEqual(observed, [True])

    def test_main_installs_nonterminating_handlers_before_preflight(self):
        with mock.patch.object(entry.signal, "signal") as install, \
                mock.patch.object(entry.sys, "argv", ["synthetic-entry"]), \
                mock.patch.object(entry, "emit"):
            self.assertEqual(entry.main(), 2)
        self.assertEqual([call.args[1] for call in install.call_args_list], [entry.request_stop, entry.request_stop])

    def runtime_fixture(self, folder):
        directory = Path(folder)
        content = b"synthetic module; never executed"
        python = directory / "fake-python"
        python.write_bytes(content)
        pins = {}
        for name in entry.MODULES:
            (directory / name).write_bytes(content)
            pins[name] = hashlib.sha256(content).hexdigest()
        manifest = {"python_path": str(python), "python_sha256": hashlib.sha256(content).hexdigest(), "module_sha256": pins}
        (directory / "runtime.json").write_text(json.dumps(manifest))
        return directory, python, manifest

    def test_exact_seven_module_pins_are_verified_before_project_imports(self):
        with tempfile.TemporaryDirectory(prefix="managed-entry-") as folder:
            directory, python, _ = self.runtime_fixture(folder)
            with mock.patch.object(entry, "__file__", str(directory / "managed_synthetic_entrypoint.py")), \
                    mock.patch.object(entry.sys, "executable", str(python)), \
                    mock.patch.object(entry.sys, "flags", SimpleNamespace(isolated=True, no_site=True)), \
                    mock.patch.object(entry.sys, "dont_write_bytecode", True):
                self.assertEqual(entry.validate_runtime(), (directory, python, hashlib.sha256(python.read_bytes()).hexdigest()))
                (directory / "synthetic_continuous_stream.py").write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    entry.validate_runtime()
        self.assertEqual(len(entry.MODULES), 7)

    def test_manifest_unknown_module_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="managed-entry-") as folder:
            directory, python, manifest = self.runtime_fixture(folder)
            manifest["module_sha256"]["unexpected.py"] = "a" * 64
            (directory / "runtime.json").write_text(json.dumps(manifest))
            with mock.patch.object(entry, "__file__", str(directory / "managed_synthetic_entrypoint.py")):
                with self.assertRaises(ValueError):
                    entry.validate_runtime()

    def test_regular_reader_uses_nonblocking_nofollow_admission(self):
        with mock.patch.object(entry.os, "open", side_effect=OSError) as opening:
            with self.assertRaises(OSError):
                entry._read_regular(Path("synthetic-file"), 16_384)
        flags = opening.call_args.args[1]
        self.assertTrue(flags & entry.os.O_NONBLOCK)
        self.assertTrue(flags & entry.os.O_NOFOLLOW)


if __name__ == "__main__":
    unittest.main()
