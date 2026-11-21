from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import process_deadline as runner


class ProcessCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        digest = hashlib.sha256()
        with open(cls.python, "rb") as executable:
            for block in iter(lambda: executable.read(1024 * 1024), b""):
                digest.update(block)
        cls.python_sha256 = digest.hexdigest()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="process-cancel-")
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self._registered_children: set[int] = set()

    def _register_child_cleanup(self, process: subprocess.Popen[bytes]) -> None:
        identity = id(process)
        if identity in self._registered_children:
            return
        self._registered_children.add(identity)
        self.addCleanup(self._reap_child, process)

    @staticmethod
    def _reap_child(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait(timeout=2)

    def run_python(
        self,
        code: str,
        *,
        name: str = "run",
        timeout: float = 2,
        grace: float = 0.1,
        maximum_output_bytes: int = 16_384,
        cancel_event: threading.Event | None = None,
    ) -> runner.BoundedRunResult:
        current_popen = runner.subprocess.Popen

        def tracked_popen(*args, **kwargs):
            process = current_popen(*args, **kwargs)
            self._register_child_cleanup(process)
            return process

        with mock.patch.object(runner.subprocess, "Popen", side_effect=tracked_popen):
            return runner.run_bounded(
                [self.python, "-c", code],
                executable_sha256=self.python_sha256,
                output_directory=self.parent / name,
                timeout_seconds=timeout,
                termination_grace_seconds=grace,
                maximum_output_bytes=maximum_output_bytes,
                cancel_event=cancel_event,
            )

    def launch_when_ready(self, ready: Path, event: threading.Event):
        real_popen = subprocess.Popen
        children: list[subprocess.Popen[bytes]] = []

        def launch(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            self._register_child_cleanup(process)
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            if not ready.exists():
                process.kill()
                process.wait(timeout=2)
                raise AssertionError("synthetic child did not become ready")
            event.set()
            return process

        return children, launch

    def test_preset_event_returns_before_hash_output_or_spawn(self) -> None:
        event = threading.Event()
        event.set()
        output = self.parent / "never-created"
        with mock.patch.object(runner, "_verify_executable") as verify, \
             mock.patch.object(runner, "_create_output_files") as create, \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run_bounded(
                [self.python, "-c", "pass"],
                executable_sha256=self.python_sha256,
                output_directory=output,
                timeout_seconds=1,
                cancel_event=event,
            )
        self.assertEqual(result, runner.BoundedRunResult(
            runner.RunStatus.CANCELLED, runner.RunTrigger.CANCELLED, None, 0, 0,
        ))
        verify.assert_not_called()
        create.assert_not_called()
        popen.assert_not_called()
        self.assertFalse(output.exists())

    def test_cancel_during_hash_prevents_output_creation(self) -> None:
        event = threading.Event()
        output = self.parent / "hash-cancelled"
        verify_executable = runner._verify_executable

        def verify_then_cancel(path: str, digest: str) -> str:
            verified = verify_executable(path, digest)
            event.set()
            return verified

        with mock.patch.object(runner, "_verify_executable", side_effect=verify_then_cancel), \
             mock.patch.object(runner, "_create_output_files") as create, \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run_bounded(
                [self.python, "-c", "pass"],
                executable_sha256=self.python_sha256,
                output_directory=output,
                timeout_seconds=1,
                cancel_event=event,
            )
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertIsNone(result.returncode)
        self.assertEqual((result.stdout_bytes, result.stderr_bytes), (0, 0))
        create.assert_not_called()
        popen.assert_not_called()
        self.assertFalse(output.exists())

    def test_cancel_after_output_setup_prevents_popen(self) -> None:
        event = threading.Event()
        output = self.parent / "pre-spawn-cancelled"
        create_outputs = runner._create_output_files
        output_descriptors: list[int] = []

        def create_then_cancel(*args, **kwargs):
            descriptors = create_outputs(*args, **kwargs)
            output_descriptors.extend(descriptors[:4])
            event.set()
            return descriptors

        with mock.patch.object(runner, "_create_output_files", side_effect=create_then_cancel), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run_bounded(
                [self.python, "-c", "pass"],
                executable_sha256=self.python_sha256,
                output_directory=output,
                timeout_seconds=1,
                cancel_event=event,
            )
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertIsNone(result.returncode)
        self.assertEqual((result.stdout_bytes, result.stderr_bytes), (0, 0))
        popen.assert_not_called()
        self.assertEqual(len(output_descriptors), 4)
        for descriptor in output_descriptors:
            with self.assertRaises(OSError) as closed:
                os.fstat(descriptor)
            self.assertEqual(closed.exception.errno, errno.EBADF)
        self.assertEqual((output / "stdout.bin").read_bytes(), b"")
        self.assertEqual((output / "stderr.bin").read_bytes(), b"")

    def test_cancel_set_after_child_creation_is_observed_after_pipe_setup(self) -> None:
        ready = self.parent / "ready"
        event = threading.Event()
        children, launch = self.launch_when_ready(ready, event)
        code = f"import os,time; open({str(ready)!r}, 'wb').close(); time.sleep(30)"
        with mock.patch.object(runner.subprocess, "Popen", side_effect=launch) as popen:
            result = self.run_python(code, cancel_event=event)
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertEqual(result.returncode, -signal.SIGTERM)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual((result.stdout_bytes, result.stderr_bytes), (0, 0))
        self.assertEqual(len(children), 1)

    def cooperative_child(self, ready: Path, marker: Path, *, ignore_term: bool = False) -> str:
        return f"""
import atexit, os, signal
ready = {str(ready)!r}
marker = {str(marker)!r}
atexit.register(lambda: open(marker, 'wb').write(b'exited'))
def write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]
def on_term(signum, frame):
    write_all(1, b'o' * 131072)
    write_all(2, b'e' * 131072)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN if {ignore_term!r} else on_term)
open(ready, 'wb').close()
signal.pause()
"""

    def test_cancel_drains_cooperative_term_flood_and_runs_atexit(self) -> None:
        ready = self.parent / "ready"
        marker = self.parent / "atexit"
        event = threading.Event()
        children, launch = self.launch_when_ready(ready, event)
        code = self.cooperative_child(ready, marker)
        with mock.patch.object(runner.subprocess, "Popen", side_effect=launch):
            result = self.run_python(
                code, timeout=2, grace=0.5, maximum_output_bytes=1024,
                cancel_event=event,
            )
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(marker.read_bytes(), b"exited")
        self.assertEqual(result.stdout_bytes + result.stderr_bytes, 0)
        self.assertEqual((self.parent / "run" / "stdout.bin").read_bytes(), b"")
        self.assertEqual((self.parent / "run" / "stderr.bin").read_bytes(), b"")
        self.assertEqual(len(children), 1)

    def test_cancel_uses_kill_after_grace_for_child_ignoring_term(self) -> None:
        ready = self.parent / "ready"
        marker = self.parent / "atexit"
        event = threading.Event()
        _children, launch = self.launch_when_ready(ready, event)
        code = self.cooperative_child(ready, marker, ignore_term=True)
        with mock.patch.object(runner.subprocess, "Popen", side_effect=launch):
            result = self.run_python(code, timeout=2, grace=0.1, cancel_event=event)
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(marker.exists())

    def test_cancel_wins_when_event_is_set_before_first_poll_of_exited_child(self) -> None:
        event = threading.Event()
        real_popen = subprocess.Popen

        def launch_and_exit(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            self._register_child_cleanup(process)
            process.wait(timeout=2)
            event.set()
            return process

        with mock.patch.object(runner.subprocess, "Popen", side_effect=launch_and_exit):
            result = self.run_python("print('done')", cancel_event=event)
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((result.stdout_bytes, result.stderr_bytes), (0, 0))
        output = self.parent / "run"
        self.assertEqual((output / "stdout.bin").read_bytes(), b"")
        self.assertEqual((output / "stderr.bin").read_bytes(), b"")

    def test_cancel_after_loop_has_captured_output_preserves_that_output(self) -> None:
        event = threading.Event()
        consume_events = runner._consume_events

        def consume_and_cancel(events, counts, maximum_output_bytes, selector, capture_hashes=None):
            overflow = consume_events(events, counts, maximum_output_bytes, selector, capture_hashes)
            if counts["stdout"] > 0:
                event.set()
            return overflow

        with mock.patch.object(runner, "_consume_events", side_effect=consume_and_cancel):
            result = self.run_python(
                "import os,time; os.write(1, b'ready\\n'); time.sleep(30)",
                cancel_event=event,
            )
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
        self.assertEqual(result.returncode, -signal.SIGTERM)
        self.assertEqual((result.stdout_bytes, result.stderr_bytes), (6, 0))
        output = self.parent / "run"
        self.assertEqual((output / "stdout.bin").read_bytes(), b"ready\n")
        self.assertEqual((output / "stderr.bin").read_bytes(), b"")
        self.assertIsNotNone(result.observation)
        assert result.observation is not None
        self.assertEqual(result.observation.stdout_sha256, hashlib.sha256(b"ready\n").hexdigest())
        self.assertEqual(result.observation.stderr_sha256, hashlib.sha256(b"").hexdigest())
        self.assertEqual(len(self._registered_children), 1)

    def test_cancel_reports_unreaped_when_bounded_cleanup_fails(self) -> None:
        ready = self.parent / "ready"
        event = threading.Event()
        children, launch = self.launch_when_ready(ready, event)
        code = f"import os,time; open({str(ready)!r}, 'wb').close(); time.sleep(30)"
        try:
            with mock.patch.object(runner.subprocess, "Popen", side_effect=launch), \
                 mock.patch.object(runner, "_terminate_and_reap", return_value=False):
                result = self.run_python(code, cancel_event=event)
            self.assertEqual(result.status, runner.RunStatus.UNREAPED)
            self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
            self.assertIsNone(result.returncode)
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)

    def test_new_session_is_used_only_when_cancellation_is_enabled(self) -> None:
        real_popen = subprocess.Popen
        kwargs_seen: list[dict[str, object]] = []

        def record_kwargs(*args, **kwargs):
            kwargs_seen.append(dict(kwargs))
            process = real_popen(*args, **kwargs)
            self._register_child_cleanup(process)
            return process

        with mock.patch.object(runner.subprocess, "Popen", side_effect=record_kwargs):
            legacy = self.run_python("pass", name="legacy")
            cancellable = self.run_python(
                "pass", name="cancellable", cancel_event=threading.Event(),
            )
        self.assertEqual(legacy.status, runner.RunStatus.EXITED)
        self.assertEqual(cancellable.status, runner.RunStatus.EXITED)
        self.assertNotIn("start_new_session", kwargs_seen[0])
        self.assertIs(kwargs_seen[1].get("start_new_session"), True)

    def test_timeout_trigger_is_not_replaced_by_event_during_cleanup(self) -> None:
        event = threading.Event()
        terminate_and_reap = runner._terminate_and_reap

        def set_event_then_cleanup(*args, **kwargs):
            event.set()
            return terminate_and_reap(*args, **kwargs)

        with mock.patch.object(runner, "_terminate_and_reap", side_effect=set_event_then_cleanup):
            result = self.run_python("import time; time.sleep(30)", timeout=0.15, cancel_event=event)
        self.assertEqual(result.status, runner.RunStatus.TIMED_OUT)
        self.assertEqual(result.trigger, runner.RunTrigger.TIMEOUT)
        self.assertIsNotNone(result.returncode)

    def test_output_limit_trigger_is_not_replaced_by_event_during_cleanup(self) -> None:
        event = threading.Event()
        terminate_and_reap = runner._terminate_and_reap

        def set_event_then_cleanup(*args, **kwargs):
            event.set()
            return terminate_and_reap(*args, **kwargs)

        with mock.patch.object(runner, "_terminate_and_reap", side_effect=set_event_then_cleanup):
            result = self.run_python(
                "import os,time; os.write(1, b'x' * 8192); time.sleep(30)",
                timeout=2, maximum_output_bytes=1024, cancel_event=event,
            )
        self.assertEqual(result.status, runner.RunStatus.OUTPUT_LIMIT)
        self.assertEqual(result.trigger, runner.RunTrigger.OUTPUT_LIMIT)
        self.assertIsNotNone(result.returncode)

    def test_non_event_cancel_argument_is_rejected(self) -> None:
        with self.assertRaises(runner.BoundedRunError) as invalid:
            self.run_python("pass", cancel_event=object())  # type: ignore[arg-type]
        self.assertEqual(invalid.exception.code, runner.RunErrorCode.INVALID_ARGUMENT)


if __name__ == "__main__":
    unittest.main()
