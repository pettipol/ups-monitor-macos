"""Finite real-child tests; never run implicitly or against hardware."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import signal
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest import mock

import process_deadline as runner


COOPERATIVE = """
import os, signal
signal.alarm(8)
def stop(signum, frame):
    os.write(1, b'terminal\\n')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
os.write(1, b'active\\n')
while True:
    signal.pause()
"""


class StreamingLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.python = str(Path(sys.executable).resolve(strict=True))
        cls.pin = hashlib.sha256(Path(cls.python).read_bytes()).hexdigest()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="streaming-synthetic-")
        self.parent = Path(self.temporary.name)
        self.children = []
        self.releases = []
        self.stop = Event()
        original = runner.subprocess.Popen

        def tracked(*args, **kwargs):
            child = original(*args, **kwargs)
            self.children.append(child)
            return child

        self.spawn_patch = mock.patch.object(runner.subprocess, "Popen", side_effect=tracked)
        self.spawn = self.spawn_patch.start()
        self.addCleanup(self.tear_down_owned_resources)

    def tear_down_owned_resources(self):
        # Every test-created worker and child is released even after assertions.
        self.stop.set()
        for release in self.releases:
            release.set()
        for child in self.children:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.kill()
            child.wait(timeout=2)
        deadline = time.perf_counter() + 2
        while time.perf_counter() < deadline:
            snapshot = runner.retained_streaming_ownership()
            if snapshot is None or snapshot.ownership_resolved:
                break
            time.sleep(0.005)
        self.spawn_patch.stop()
        self.temporary.cleanup()
        self.assertIsNone(runner._retained_streaming_owner, "test must resolve every retained owner")

    def run_child(self, code=COOPERATIVE, sink=None, **options):
        if sink is None:
            def sink(chunk):
                if chunk:
                    self.stop.set()
                return bool(chunk)
        return runner.run_streaming([self.python, "-c", code], executable_sha256=self.pin,
            output_directory=self.parent / "output", cancel_event=self.stop,
            on_stdout=sink, startup_timeout_seconds=options.pop("startup_timeout_seconds", 2),
            progress_timeout_seconds=options.pop("progress_timeout_seconds", 1),
            termination_grace_seconds=options.pop("termination_grace_seconds", 0.1), **options)

    def test_user_stop_preserves_term_terminal_record_and_real_eofs(self):
        chunks = []

        def sink(chunk):
            chunks.append(chunk)
            if b"active\n" in chunk:
                self.stop.set()
            return bool(chunk)

        started = time.perf_counter()
        result = self.run_child(sink=sink)
        self.assertLess(time.perf_counter() - started, 4)
        self.assertEqual(result.trigger, "cancelled")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(b"".join(chunks), b"active\nterminal\n")
        self.assertEqual(chunks[-1], b"")
        self.assertEqual(chunks.count(b""), 1)
        self.assertEqual(result.stdout_sha256, hashlib.sha256(b"active\nterminal\n").hexdigest())
        self.assertEqual((self.parent / "output" / "stdout.bin").stat().st_size, 0)
        self.assertEqual((self.parent / "output" / "stderr.bin").stat().st_size, 0)
        self.assertEqual(self.spawn.call_count, 1)

    def test_ignored_term_escalates_once_and_reaps(self):
        code = "import os,signal\nsignal.alarm(8)\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nos.write(1,b'active')\nwhile True: signal.pause()"
        with mock.patch.object(runner, "_signal_child", wraps=runner._signal_child) as signals:
            result = self.run_child(code)
        self.assertEqual([call.args[1] for call in signals.call_args_list], [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(self.spawn.call_count, 1)

    def test_exception_and_invalid_callback_result_stop_owned_child(self):
        def throwing(chunk):
            raise RuntimeError("synthetic private exception must not escape")

        result = self.run_child(sink=throwing)
        self.assertEqual(result.trigger, "consumer_error")
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(self.spawn.call_count, 1)

    def test_non_boolean_callback_result_is_fixed_consumer_error(self):
        result = self.run_child(sink=lambda chunk: 1)
        self.assertEqual(result.trigger, "consumer_error")
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(self.spawn.call_count, 1)

    def test_blocked_callback_retains_then_releases_exact_owner(self):
        entered, release = Event(), Event()
        self.releases.append(release)

        def sink(chunk):
            if chunk:
                entered.set()
                release.wait(10)
            return bool(chunk)

        try:
            started = time.perf_counter()
            result = self.run_child(sink=sink, startup_timeout_seconds=0.2)
            self.assertTrue(entered.is_set())
            self.assertLess(time.perf_counter() - started, 4)
            self.assertFalse(result.consumer_quiesced)
            self.assertTrue(result.leader_reaped)
            self.assertFalse(result.ownership_resolved)
            self.assertIsNotNone(runner._retained_streaming_owner)
            self.stop.clear()
            with self.assertRaises(runner._StreamingFailure) as failure:
                self.run_child(sink=lambda chunk: False)
            self.assertEqual(failure.exception.code, "streaming_owner_retained")
            self.assertEqual(self.spawn.call_count, 1)
        finally:
            release.set()

    def test_queue_backpressure_is_bounded_and_no_retry(self):
        entered, release = Event(), Event()
        self.releases.append(release)

        def blocked(chunk):
            if chunk:
                entered.set()
                release.wait(10)
            return bool(chunk)

        gate = self.parent / "flood-gate"
        code = f"""
import os, signal, time
signal.alarm(8)
os.write(1, b'r')
gate = {str(gate)!r}
deadline = time.monotonic() + 3
while not os.path.exists(gate):
    if time.monotonic() >= deadline:
        raise SystemExit(4)
    time.sleep(0.005)
for n in range(31):
    os.write(1, b'x' * 8192)
os.write(1, b'x' * 8191)
while True:
    signal.pause()
"""
        results, failures = [], []

        def run():
            try:
                results.append(self.run_child(code, sink=blocked))
            except BaseException as error:
                failures.append(error)

        thread = Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(2), "callback must enter before the child flood is authorized")
            gate.touch()
            thread.join(4)
            self.assertFalse(thread.is_alive(), "bounded runner must return while callback stays blocked")
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.trigger, "consumer_backpressure")
            self.assertTrue(result.leader_reaped)
            self.assertFalse(result.consumer_quiesced)
            self.assertEqual(self.spawn.call_count, 1)
        finally:
            release.set()
            self.stop.set()
            thread.join(6)
        self.assertFalse(thread.is_alive())

    def test_group_check_denial_is_retained_until_real_absence_observed(self):
        with mock.patch.object(runner, "_process_group_absent", return_value=False):
            result = self.run_child()
        self.assertFalse(result.group_absent)
        self.assertFalse(result.ownership_resolved)
        self.assertIsNotNone(runner._retained_streaming_owner)
        observed = runner.retained_streaming_ownership()
        self.assertIsNotNone(observed)
        self.assertTrue(observed.ownership_resolved)
        self.assertEqual(self.spawn.call_count, 1)

    def test_second_active_call_is_rejected_before_spawn(self):
        ready = Event()
        returned = []

        def sink(chunk):
            if chunk:
                ready.set()
            return bool(chunk)

        def run_first():
            returned.append(self.run_child(sink=sink))

        thread = Thread(target=run_first)
        thread.start()
        try:
            self.assertTrue(ready.wait(2))
            with self.assertRaises(runner._StreamingFailure) as failure:
                self.run_child(sink=lambda chunk: False)
            self.assertEqual(failure.exception.code, "streaming_owner_active")
            self.assertEqual(self.spawn.call_count, 1)
        finally:
            self.stop.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(returned), 1)
        self.assertTrue(returned[0].ownership_resolved)


if __name__ == "__main__":
    unittest.main()
