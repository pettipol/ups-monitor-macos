from __future__ import annotations

import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import operator_stop as adapter
import process_deadline as runner


_CHILD_FIXTURE = r"""
import atexit, os, pathlib, signal, sys, time
root = pathlib.Path(sys.argv[1])
ready = root / 'child-ready'
term_started = root / 'term-started'
release = root / 'release-child'
parent = os.getppid()
atexit.register(lambda: (root / 'child-exited').write_text('done'))
def on_term(_signum, _frame):
    term_started.touch()
    os.write(1, b'o' * 32768)
    os.write(2, b'e' * 32768)
    deadline = time.monotonic() + 8
    while not release.exists() and os.getppid() == parent and time.monotonic() < deadline:
        time.sleep(0.005)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, on_term)
ready.write_text(str(os.getpid()))
deadline = time.monotonic() + 8
while not term_started.exists() and os.getppid() == parent and time.monotonic() < deadline:
    time.sleep(0.005)
"""


_CONTROLLER_TEMPLATE = r"""
import hashlib, json, pathlib, signal, sys, threading, time
sys.path.insert(0, {module_dir!r})
import operator_stop, process_deadline
root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
real_signal = signal.signal
in_handler = [False]
def track_sigint_install(signum, handler):
    if signum == signal.SIGINT and handler not in (signal.default_int_handler, signal.SIG_DFL, signal.SIG_IGN):
        callback = handler
        def monitored_handler(received_signal, frame):
            in_handler[0] = True
            try:
                return callback(received_signal, frame)
            finally:
                in_handler[0] = False
        handler = monitored_handler
    previous = real_signal(signum, handler)
    if signum == signal.SIGINT:
        active = root / 'handler-active'
        if handler in (signal.default_int_handler, signal.SIG_DFL, signal.SIG_IGN):
            active.unlink(missing_ok=True)
        else:
            active.touch()
    return previous
signal.signal = track_sigint_install
base_event = operator_stop.Event
class AcknowledgedEvent(base_event):
    def set(self):
        if threading.current_thread() is not threading.main_thread() or in_handler[0]:
            raise AssertionError('Event.set must run in main context outside signal handler')
        super().set()
        (root / 'event-set-in-main').touch()
operator_stop.Event = AcknowledgedEvent
python = str(pathlib.Path(sys.executable).resolve(strict=True))
digest = hashlib.sha256(pathlib.Path(python).read_bytes()).hexdigest()
child = {child_source!r}
output = root / 'output'
before_handler = signal.getsignal(signal.SIGINT)
if mode == 'before-hash':
    verify = process_deadline._verify_executable
    def wait_during_hash(path, expected):
        (root / 'at-hash').touch()
        deadline = time.monotonic() + 5
        while not (root / 'release-hash').exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('hash barrier timed out')
            time.sleep(0.005)
        return verify(path, expected)
    process_deadline._verify_executable = wait_during_hash
(root / 'controller-ready').touch()
try:
    result = operator_stop.run_operator_controlled(
        [python, '-c', child, str(root)],
        executable_sha256=digest,
        output_directory=output,
        timeout_seconds=3,
        termination_grace_seconds=2,
        maximum_output_bytes=1024,
    )
    report = {{
        'status': result.status.value,
        'trigger': result.trigger.value,
        'returncode': result.returncode,
        'stdout_bytes': result.stdout_bytes,
        'stderr_bytes': result.stderr_bytes,
        'handler_restored': signal.getsignal(signal.SIGINT) is before_handler,
    }}
    (root / 'result.json').write_text(json.dumps(report), encoding='ascii')
except BaseException as error:
    (root / 'error.txt').write_text(type(error).__name__, encoding='ascii')
    raise
"""


class ProcessDeadlineOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        cls.python_sha256 = hashlib.sha256(Path(cls.python).read_bytes()).hexdigest()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="operator-stop-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def arguments(self, name: str = "run") -> dict[str, object]:
        return {
            "argv": [self.python, "-c", "pass"],
            "executable_sha256": self.python_sha256,
            "output_directory": self.root / name,
            "timeout_seconds": 2,
        }

    def test_result_is_preserved_and_default_handler_restored(self) -> None:
        expected = runner.BoundedRunResult(runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0)
        previous = signal.getsignal(signal.SIGINT)
        with mock.patch.object(adapter, "run_bounded", return_value=expected) as run:
            self.assertIs(adapter.run_operator_controlled(**self.arguments()), expected)
        self.assertIs(signal.getsignal(signal.SIGINT), previous)
        supplied_event = run.call_args.kwargs["cancel_event"]
        self.assertIsInstance(supplied_event, threading.Event)
        self.assertFalse(supplied_event.is_set())

    def test_worker_base_exception_is_propagated_and_handler_restored(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        with mock.patch.object(adapter, "run_bounded", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                adapter.run_operator_controlled(**self.arguments())
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_unreaped_result_is_returned_without_reinterpretation(self) -> None:
        expected = runner.BoundedRunResult(runner.RunStatus.UNREAPED, runner.RunTrigger.CANCELLED, None, 0, 0)
        with mock.patch.object(adapter, "run_bounded", return_value=expected):
            self.assertIs(adapter.run_operator_controlled(**self.arguments()), expected)

    def test_non_main_thread_is_rejected_before_runner_or_signal_changes(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                adapter.run_operator_controlled(**self.arguments())
            except BaseException as error:
                errors.append(error)

        with mock.patch.object(adapter, "run_bounded") as run:
            worker = threading.Thread(target=invoke)
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            run.assert_not_called()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_nested_call_is_rejected_before_starting_another_worker(self) -> None:
        original_start = threading.Thread.start
        nested_errors: list[BaseException] = []

        def start_with_nested_attempt(thread: threading.Thread) -> None:
            if thread.name == "bounded-child":
                try:
                    adapter.run_operator_controlled(**self.arguments("nested"))
                except BaseException as error:
                    nested_errors.append(error)
            original_start(thread)

        with mock.patch.object(adapter, "run_bounded", return_value=runner.BoundedRunResult(
            runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0,
        )), mock.patch.object(threading.Thread, "start", new=start_with_nested_attempt):
            adapter.run_operator_controlled(**self.arguments())
        self.assertEqual(len(nested_errors), 1)
        self.assertIsInstance(nested_errors[0], RuntimeError)

    def test_custom_sigint_handler_is_rejected_without_replacement(self) -> None:
        previous = signal.getsignal(signal.SIGINT)

        def custom_handler(_signum: int, _frame: object) -> None:
            return None

        try:
            signal.signal(signal.SIGINT, custom_handler)
            with mock.patch.object(adapter, "run_bounded") as run:
                with self.assertRaises(RuntimeError):
                    adapter.run_operator_controlled(**self.arguments())
                run.assert_not_called()
            self.assertIs(signal.getsignal(signal.SIGINT), custom_handler)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_sigint_ignore_is_rejected_without_replacement(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            with mock.patch.object(adapter, "run_bounded") as run:
                with self.assertRaises(RuntimeError):
                    adapter.run_operator_controlled(**self.arguments())
                run.assert_not_called()
            self.assertIs(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_interrupt_during_event_or_queue_setup_releases_reentrancy_guard(self) -> None:
        expected = runner.BoundedRunResult(runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0)
        for target in ("event", "queue"):
            with self.subTest(target=target):
                patcher = (
                    mock.patch.object(adapter, "Event", side_effect=KeyboardInterrupt)
                    if target == "event"
                    else mock.patch.object(adapter.queue, "Queue", side_effect=KeyboardInterrupt)
                )
                with patcher:
                    with self.assertRaises(KeyboardInterrupt):
                        adapter.run_operator_controlled(**self.arguments())
                with mock.patch.object(adapter, "run_bounded", return_value=expected):
                    self.assertIs(adapter.run_operator_controlled(**self.arguments()), expected)

    def test_restore_interrupt_resets_guard_before_handler_restoration(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        real_signal = signal.signal
        expected = runner.BoundedRunResult(runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0)

        def interrupt_restore(signum: int, handler: object):
            if signum == signal.SIGINT and handler is previous:
                self.assertFalse(adapter._active)
                raise KeyboardInterrupt
            return real_signal(signum, handler)

        try:
            with mock.patch.object(adapter, "run_bounded", return_value=expected), \
                 mock.patch.object(adapter.signal, "signal", side_effect=interrupt_restore):
                with self.assertRaises(KeyboardInterrupt):
                    adapter.run_operator_controlled(**self.arguments())
                self.assertFalse(adapter._active)
        finally:
            real_signal(signal.SIGINT, previous)

        with mock.patch.object(adapter, "run_bounded", return_value=expected):
            self.assertIs(adapter.run_operator_controlled(**self.arguments()), expected)

    def controller_source(self) -> str:
        return _CONTROLLER_TEMPLATE.format(
            module_dir=str(Path(__file__).resolve().parent),
            child_source=_CHILD_FIXTURE,
        )

    def start_controller(self, mode: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [self.python, "-c", self.controller_source(), str(self.root), mode],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        self.addCleanup(self.reap_controller, process)
        return process

    @staticmethod
    def reap_controller(process: subprocess.Popen[bytes]) -> None:
        try:
            if process.poll() is None:
                root = Path(process.args[3])
                (root / "release-hash").touch()
                (root / "release-child").touch()
                if (root / "handler-active").exists():
                    try:
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        finally:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def wait_for(self, path: Path) -> None:
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(path.exists(), f"fixture did not reach {path.name}")

    def finish_controller(self, process: subprocess.Popen[bytes]) -> dict[str, object]:
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, (stdout, stderr))
        self.assertEqual(stderr, b"")
        return json.loads((self.root / "result.json").read_text(encoding="ascii"))

    def test_sigint_before_hash_completion_prevents_child_launch(self) -> None:
        process = self.start_controller("before-hash")
        self.wait_for(self.root / "at-hash")
        process.send_signal(signal.SIGINT)
        self.wait_for(self.root / "event-set-in-main")
        (self.root / "release-hash").touch()
        result = self.finish_controller(process)
        self.assertEqual((result["status"], result["trigger"]), ("cancelled", "cancelled"))
        self.assertIsNone(result["returncode"])
        self.assertFalse((self.root / "child-ready").exists())
        self.assertFalse((self.root / "output").exists())
        self.assertTrue(result["handler_restored"])

    def test_sigint_after_child_ready_and_repeated_during_grace(self) -> None:
        process = self.start_controller("child")
        self.wait_for(self.root / "child-ready")
        process.send_signal(signal.SIGINT)
        self.wait_for(self.root / "event-set-in-main")
        self.wait_for(self.root / "term-started")
        process.send_signal(signal.SIGINT)
        process.send_signal(signal.SIGINT)
        self.assertIsNone(process.poll())
        (self.root / "release-child").touch()
        result = self.finish_controller(process)
        self.assertEqual((result["status"], result["trigger"]), ("cancelled", "cancelled"))
        self.assertEqual(result["returncode"], 0)
        self.assertTrue((self.root / "child-exited").exists())
        self.assertLessEqual(result["stdout_bytes"] + result["stderr_bytes"], 1024)
        self.assertTrue(result["handler_restored"])


if __name__ == "__main__":
    unittest.main()
