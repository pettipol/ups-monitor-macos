from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import MappingProxyType
from unittest import mock
from uuid import UUID

import operator_session as session
import operator_stop
import process_deadline as runner


_CHILD_SOURCE = r"""
import atexit, os, pathlib, signal, sys, time
root = pathlib.Path(sys.argv[1])
parent = os.getppid()
ready = root / 'child-ready'
term_started = root / 'term-started'
release = root / 'release-child'
atexit.register(lambda: (root / 'child-exited').touch())
def on_term(_signum, _frame):
    term_started.touch()
    os.write(1, b'term\n')
    deadline = time.monotonic() + 8
    while not release.exists() and os.getppid() == parent and time.monotonic() < deadline:
        time.sleep(0.005)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, on_term)
os.write(1, b'ready\n')
ready.touch()
deadline = time.monotonic() + 8
while not term_started.exists() and os.getppid() == parent and time.monotonic() < deadline:
    time.sleep(0.005)
"""


_CONTROLLER_SOURCE = r"""
import contextlib, hashlib, io, json, os, pathlib, signal, sys, threading
sys.path.insert(0, {module_dir!r})
import operator_session, operator_stop, process_deadline
root = pathlib.Path(sys.argv[1])
output_parent = root / 'output-parent'
output_parent.mkdir(mode=0o700)
os.chmod(output_parent, 0o700)
python = str(pathlib.Path(sys.executable).resolve(strict=True))
digest = hashlib.sha256(pathlib.Path(python).read_bytes()).hexdigest()
child = {child_source!r}
profile = operator_session.OperatorProfile(
    argv=(python, '-c', child, str(root)),
    executable_sha256=digest,
    output_parent=output_parent,
    timeout_seconds=12,
    termination_grace_seconds=3,
    maximum_output_bytes=2048,
)
operator_session.PROFILES = {{'synthetic': profile}}

real_signal = signal.signal
in_signal_handler = [False]
def tracked_signal(signum, handler):
    if signum == signal.SIGINT and callable(handler) and handler not in (signal.default_int_handler, signal.SIG_DFL, signal.SIG_IGN):
        callback = handler
        def tracked_handler(received_signal, frame):
            in_signal_handler[0] = True
            try:
                return callback(received_signal, frame)
            finally:
                in_signal_handler[0] = False
        handler = tracked_handler
    return real_signal(signum, handler)
signal.signal = tracked_signal

base_event = operator_stop.Event
class TrackedEvent(base_event):
    def set(self):
        if threading.current_thread() is not threading.main_thread() or in_signal_handler[0]:
            raise AssertionError('cancellation event must be set by main loop, outside signal handler')
        super().set()
        (root / 'event-set-main').touch()
operator_stop.Event = TrackedEvent

original_popen = process_deadline.subprocess.Popen
spawn_count = [0]
def counted_popen(*args, **kwargs):
    spawn_count[0] += 1
    (root / 'spawn-count').write_text(str(spawn_count[0]), encoding='ascii')
    return original_popen(*args, **kwargs)
process_deadline.subprocess.Popen = counted_popen

before_handler = signal.getsignal(signal.SIGINT)
(root / 'controller-ready').touch()
capture = io.StringIO()
with contextlib.redirect_stdout(capture):
    cli_return = operator_session.main(['--profile', 'synthetic', '--execute'])
raw_response = capture.getvalue()
payload = json.loads(raw_response)
run_dirs = list(output_parent.iterdir())
run_dir = run_dirs[0] if len(run_dirs) == 1 else None
stdout_data = (run_dir / 'stdout.bin').read_bytes() if run_dir else b''
stderr_data = (run_dir / 'stderr.bin').read_bytes() if run_dir else b''
report = {{
    'cli_return': cli_return,
    'payload': payload,
    'handler_restored': signal.getsignal(signal.SIGINT) is before_handler,
    'spawn_count': spawn_count[0],
    'run_dir_count': len(run_dirs),
    'run_dir_mode': (run_dir.stat().st_mode & 0o777) if run_dir else None,
    'stdout_mode': ((run_dir / 'stdout.bin').stat().st_mode & 0o777) if run_dir else None,
    'stderr_mode': ((run_dir / 'stderr.bin').stat().st_mode & 0o777) if run_dir else None,
    'state_mode': ((run_dir / 'state').stat().st_mode & 0o777) if run_dir else None,
    'conf_mode': ((run_dir / 'conf').stat().st_mode & 0o777) if run_dir else None,
    'stdout_is_ready': stdout_data == b'ready\n',
    'stderr_size': len(stderr_data),
    'raw_response_single_json_line': raw_response.count('\n') == 1,
}}
(root / 'controller-result.json').write_text(json.dumps(report), encoding='ascii')
"""


class OperatorSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        cls.python_sha256 = hashlib.sha256(Path(cls.python).read_bytes()).hexdigest()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="operator-session-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def profile(self, parent: Path | None = None) -> session.OperatorProfile:
        output_parent = parent or self.root / "runs"
        output_parent.mkdir(mode=0o700, exist_ok=True)
        os.chmod(output_parent, 0o700)
        return session.OperatorProfile(
            argv=(self.python, "-c", "pass"),
            executable_sha256=self.python_sha256,
            output_parent=output_parent,
            timeout_seconds=4,
            termination_grace_seconds=2,
            maximum_output_bytes=4096,
        )

    def invoke(self, args: list[str]) -> tuple[int, dict[str, object], str]:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            return_code = session.main(args)
        raw = stream.getvalue()
        payload = json.loads(raw)
        self.assertEqual(tuple(payload), session._JSON_FIELDS)
        self.assertIs(payload["data_qualified"], False)
        return return_code, payload, raw

    def test_distributed_registry_is_empty_immutable_and_default_is_not_run(self) -> None:
        self.assertEqual(dict(session.PROFILES), {})
        unused_profile = session.OperatorProfile(
            argv=(self.python,),
            executable_sha256=self.python_sha256,
            output_parent=self.root / "no-create",
            timeout_seconds=1,
            termination_grace_seconds=1,
            maximum_output_bytes=128,
        )
        with self.assertRaises(TypeError):
            session.PROFILES["unexpected"] = unused_profile  # type: ignore[index]

        code, payload, _ = self.invoke([])
        self.assertEqual(code, 0)
        self.assertEqual((payload["status"], payload["trigger"]), ("not_run", "none"))
        self.assertIsNone(payload["error"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_empty_distributed_registry_rejects_execute_without_runner_or_output(self) -> None:
        with mock.patch.object(session, "run_operator_controlled") as run:
            code, payload, raw = self.invoke(["--profile", "synthetic", "--execute"])

        self.assertEqual(code, 2)
        self.assertEqual((payload["status"], payload["error"]), ("rejected", "unknown_profile"))
        self.assertNotIn(str(self.root), raw)
        run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_preview_missing_unknown_extra_and_help_never_call_runner(self) -> None:
        parent = self.root / "runs"
        profile = self.profile(parent)
        cases = [
            ([], 0, "not_run", None),
            (["--profile", "synthetic"], 0, "not_run", None),
            (["--execute"], 2, "rejected", "profile_required"),
            (["--profile", "unknown", "--execute"], 2, "rejected", "unknown_profile"),
            (["--profile", "synthetic", "--execute", str(self.root / "secret")], 2, "rejected", "invalid_arguments"),
            (["--profile", "synthetic", "--execute", "--extra"], 2, "rejected", "invalid_arguments"),
            (["--help"], 0, "not_run", "usage: operator_session --profile ID [--execute]"),
        ]
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})), \
             mock.patch.object(session, "run_operator_controlled") as run:
            for args, expected_code, expected_status, expected_error in cases:
                with self.subTest(args=args):
                    code, payload, raw = self.invoke(args)
                    self.assertEqual(code, expected_code)
                    self.assertEqual(payload["status"], expected_status)
                    self.assertEqual(payload["error"], expected_error)
                    self.assertNotIn("secret", raw)
                    self.assertNotIn(str(self.root), raw)
                    run.assert_not_called()
        self.assertEqual(list(parent.iterdir()), [])

    def test_default_and_preview_response_write_or_flush_failure_return_nonzero(self) -> None:
        class BrokenOutput:
            def __init__(self, failure: str) -> None:
                self.failure = failure
                self.write_count = 0
                self.flush_count = 0

            def write(self, text: str) -> int:
                self.write_count += 1
                if self.failure == "write":
                    raise OSError("private output failure")
                return len(text)

            def flush(self) -> None:
                self.flush_count += 1
                if self.failure == "flush":
                    raise OSError("private flush failure")

        profile = session.OperatorProfile(
            argv=(self.python,),
            executable_sha256=self.python_sha256,
            output_parent=self.root / "not-created",
            timeout_seconds=1,
            termination_grace_seconds=1,
            maximum_output_bytes=128,
        )
        for args, registry in (([], MappingProxyType({})),
                               (["--profile", "synthetic"], MappingProxyType({"synthetic": profile}))):
            for failure in ("write", "flush"):
                with self.subTest(args=args, failure=failure):
                    output = BrokenOutput(failure)
                    with mock.patch.object(session, "PROFILES", registry), \
                         mock.patch.object(session.sys, "stdout", output), \
                         mock.patch.object(session, "run_operator_controlled") as run:
                        code = session.main(args)
                    self.assertEqual(code, 1)
                    self.assertEqual(output.write_count, 1)
                    self.assertEqual(output.flush_count, 0 if failure == "write" else 1)
                    run.assert_not_called()
        self.assertFalse((self.root / "not-created").exists())

    def test_execute_response_failure_returns_nonzero_without_retrying_runner(self) -> None:
        class FlushFailure:
            def __init__(self) -> None:
                self.write_count = 0
                self.flush_count = 0

            def write(self, text: str) -> int:
                self.write_count += 1
                return len(text)

            def flush(self) -> None:
                self.flush_count += 1
                raise OSError("private flush failure")

        profile = self.profile()
        result = runner.BoundedRunResult(runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0)
        output = FlushFailure()
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})), \
             mock.patch.object(session.sys, "stdout", output), \
             mock.patch.object(session, "run_operator_controlled", return_value=result) as run:
            code = session.main(["--profile", "synthetic", "--execute"])

        self.assertEqual(code, 1)
        self.assertEqual((output.write_count, output.flush_count), (1, 1))
        run.assert_called_once()

    def test_exact_profile_is_forwarded_once_with_new_uuid_output_name(self) -> None:
        parent = self.root / "private-output"
        profile = self.profile(parent)
        expected = runner.BoundedRunResult(runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 21, 5)
        with mock.patch.object(session, "PROFILES", MappingProxyType({"fixed": profile})), \
             mock.patch.object(session, "run_operator_controlled", return_value=expected) as run:
            code, payload, raw = self.invoke(["--profile", "fixed", "--execute"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "exited")
        self.assertEqual(payload["trigger"], "completed")
        self.assertEqual((payload["returncode"], payload["stdout_bytes"], payload["stderr_bytes"]), (0, 21, 5))
        self.assertIs(payload["data_qualified"], False)
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args, (profile.argv,))
        self.assertEqual(kwargs["executable_sha256"], profile.executable_sha256)
        self.assertEqual(kwargs["timeout_seconds"], profile.timeout_seconds)
        self.assertEqual(kwargs["termination_grace_seconds"], profile.termination_grace_seconds)
        self.assertEqual(kwargs["maximum_output_bytes"], profile.maximum_output_bytes)
        self.assertIs(kwargs["private_nut_environment"], True)
        output_path = Path(kwargs["output_directory"])
        self.assertEqual(output_path.parent, parent)
        suffix = output_path.name.removeprefix("operator-session-")
        self.assertEqual(len(suffix), 32)
        self.assertEqual(UUID(hex=suffix).hex, suffix)
        self.assertNotIn(str(output_path), raw)
        self.assertEqual(list(parent.iterdir()), [])

    def test_all_runner_statuses_and_exit_semantics_remain_explicit(self) -> None:
        profile = self.profile()
        cases = [
            (runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, "exited", 0),
            (runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 3, "exited", 1),
            (runner.RunStatus.TIMED_OUT, runner.RunTrigger.TIMEOUT, -15, "timed_out", 1),
            (runner.RunStatus.OUTPUT_LIMIT, runner.RunTrigger.OUTPUT_LIMIT, -15, "output_limit", 1),
            (runner.RunStatus.OUTPUT_INCOMPLETE, runner.RunTrigger.OUTPUT_INCOMPLETE, 0, "output_incomplete", 1),
            (runner.RunStatus.CANCELLED, runner.RunTrigger.CANCELLED, 0, "cancelled", 1),
            (runner.RunStatus.UNREAPED, runner.RunTrigger.CANCELLED, None, "unreaped", 1),
        ]
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})):
            for status, trigger, returncode, expected_status, expected_exit in cases:
                result = runner.BoundedRunResult(status, trigger, returncode, 4, 2)
                with self.subTest(status=status.value, returncode=returncode), \
                     mock.patch.object(session, "run_operator_controlled", return_value=result):
                    code, payload, _ = self.invoke(["--profile", "synthetic", "--execute"])
                    self.assertEqual(code, expected_exit)
                    self.assertEqual(payload["status"], expected_status)
                    self.assertEqual(payload["trigger"], trigger.value)
                    self.assertEqual((payload["returncode"], payload["stdout_bytes"], payload["stderr_bytes"]), (returncode, 4, 2))
                    self.assertIs(payload["data_qualified"], False)

    def test_bounded_errors_keep_only_fixed_codes_and_unreaped_is_explicit(self) -> None:
        profile = self.profile()
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})):
            for error_code in runner.RunErrorCode:
                with self.subTest(error=error_code.value), \
                     mock.patch.object(session, "run_operator_controlled", side_effect=runner.BoundedRunError(error_code)):
                    code, payload, raw = self.invoke(["--profile", "synthetic", "--execute"])
                    self.assertEqual(code, 1)
                    self.assertEqual(payload["error"], error_code.value)
                    expected_status = "unreaped" if error_code is runner.RunErrorCode.CHILD_UNREAPED else "error"
                    self.assertEqual(payload["status"], expected_status)
                    self.assertEqual((payload["returncode"], payload["stdout_bytes"], payload["stderr_bytes"]), (None, 0, 0))
                    self.assertNotIn(str(self.root), raw)

            with mock.patch.object(session, "run_operator_controlled", side_effect=RuntimeError(str(self.root))):
                code, payload, raw = self.invoke(["--profile", "synthetic", "--execute"])
                self.assertEqual(code, 1)
                self.assertEqual((payload["status"], payload["error"]), ("error", "internal_error"))
                self.assertNotIn(str(self.root), raw)

    def test_real_hash_mismatch_prevents_spawn_and_output_creation(self) -> None:
        marker = self.root / "spawned"
        fake = self.root / "synthetic-executable"
        fake.write_text(f"#!/bin/sh\nprintf spawned > {marker}\n", encoding="utf-8")
        fake.chmod(0o700)
        parent = self.root / "private-output"
        parent.mkdir(mode=0o700)
        profile = session.OperatorProfile(
            argv=(str(fake),),
            executable_sha256="0" * 64,
            output_parent=parent,
            timeout_seconds=2,
            termination_grace_seconds=1,
            maximum_output_bytes=512,
        )
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})):
            code, payload, _ = self.invoke(["--profile", "synthetic", "--execute"])
        self.assertEqual(code, 1)
        self.assertEqual((payload["status"], payload["error"]), ("error", "hash_mismatch"))
        self.assertFalse(marker.exists())
        self.assertEqual(list(parent.iterdir()), [])

    def test_missing_output_parent_is_rejected_without_spawn_or_creation(self) -> None:
        parent = self.root / "missing-parent"
        profile = session.OperatorProfile(
            argv=(self.python, "-c", "raise SystemExit('must not run')"),
            executable_sha256=self.python_sha256,
            output_parent=parent,
            timeout_seconds=2,
            termination_grace_seconds=1,
            maximum_output_bytes=512,
        )
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            code, payload, raw = self.invoke(["--profile", "synthetic", "--execute"])

        self.assertEqual(code, 1)
        self.assertEqual((payload["status"], payload["error"]), ("error", "output_creation_failed"))
        self.assertNotIn(str(parent), raw)
        popen.assert_not_called()
        self.assertFalse(parent.exists())

    def test_real_synthetic_success_creates_private_output_files(self) -> None:
        parent = self.root / "private-output"
        parent.mkdir(mode=0o700)
        os.chmod(parent, 0o700)
        profile = session.OperatorProfile(
            argv=(self.python, "-c", "import os; os.write(1,b'ok\\n'); os.write(2,b'err\\n')"),
            executable_sha256=self.python_sha256,
            output_parent=parent,
            timeout_seconds=3,
            termination_grace_seconds=1,
            maximum_output_bytes=128,
        )
        with mock.patch.object(session, "PROFILES", MappingProxyType({"synthetic": profile})):
            code, payload, raw = self.invoke(["--profile", "synthetic", "--execute"])

        self.assertEqual(code, 0)
        self.assertEqual((payload["status"], payload["trigger"], payload["returncode"]), ("exited", "completed", 0))
        self.assertIs(payload["data_qualified"], False)
        self.assertEqual((payload["stdout_bytes"], payload["stderr_bytes"]), (3, 4))
        self.assertNotIn(str(parent), raw)
        run_dirs = list(parent.iterdir())
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]
        self.assertEqual(os.stat(run_dir).st_mode & 0o777, 0o700)
        for name in ("stdout.bin", "stderr.bin"):
            self.assertEqual(os.stat(run_dir / name).st_mode & 0o777, 0o600)
        for name in ("state", "conf"):
            self.assertEqual(os.stat(run_dir / name).st_mode & 0o777, 0o700)

    def _controller_source(self) -> str:
        return _CONTROLLER_SOURCE.format(
            module_dir=str(Path(__file__).resolve().parent),
            child_source=_CHILD_SOURCE,
        )

    def _start_controller(self) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [self.python, "-c", self._controller_source(), str(self.root)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        self.addCleanup(self._reap_controller, process)
        return process

    def _wait_for(self, marker: Path) -> None:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(marker.exists(), f"synthetic controller did not reach {marker.name}")

    def _wait_for_captured_ready(self, output_parent: Path) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run_dirs = list(output_parent.iterdir())
            self.assertLessEqual(len(run_dirs), 1, "synthetic run created more than one output directory")
            if run_dirs:
                stdout_path = run_dirs[0] / "stdout.bin"
                if stdout_path.exists():
                    captured = stdout_path.read_bytes()
                    if captured:
                        self.assertEqual(captured, b"ready\n", "unexpected output before cancellation")
                        return
            time.sleep(0.005)
        self.fail("bounded wait expired before ready output was captured")

    def _reap_controller(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            (self.root / "release-child").touch()
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def test_sigint_through_main_adapter_cancels_only_its_synthetic_child(self) -> None:
        controller = self._start_controller()
        self._wait_for(self.root / "controller-ready")
        self._wait_for(self.root / "child-ready")
        self._wait_for_captured_ready(self.root / "output-parent")
        controller.send_signal(signal.SIGINT)
        self._wait_for(self.root / "event-set-main")
        self._wait_for(self.root / "term-started")
        (self.root / "release-child").touch()

        stdout, stderr = controller.communicate(timeout=8)
        self.assertEqual(controller.returncode, 0, (stdout, stderr))
        self.assertEqual(stderr, b"")
        report = json.loads((self.root / "controller-result.json").read_text(encoding="ascii"))
        payload = report["payload"]
        self.assertEqual(report["cli_return"], 1)
        self.assertEqual((payload["status"], payload["trigger"], payload["returncode"]), ("cancelled", "cancelled", 0))
        self.assertIs(payload["data_qualified"], False)
        self.assertEqual((payload["stdout_bytes"], payload["stderr_bytes"]), (6, 0))
        self.assertEqual(report["spawn_count"], 1)
        self.assertEqual(report["run_dir_count"], 1)
        self.assertTrue(report["stdout_is_ready"])
        self.assertEqual(report["stderr_size"], 0)
        self.assertTrue(report["raw_response_single_json_line"])
        self.assertTrue(report["handler_restored"])
        self.assertTrue((self.root / "child-exited").exists())
        self.assertEqual(report["run_dir_mode"], 0o700)
        self.assertEqual((report["stdout_mode"], report["stderr_mode"]), (0o600, 0o600))
        self.assertEqual((report["state_mode"], report["conf_mode"]), (0o700, 0o700))
        self.assertEqual(controller.poll(), 0)


if __name__ == "__main__":
    unittest.main()
