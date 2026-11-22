from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

import process_deadline as runner


class CapturedRunMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        cls.digest = hashlib.sha256(Path(cls.python).read_bytes()).hexdigest()

    def test_receipt_hashes_match_only_captured_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="run-observation-") as temporary:
            result = runner.run_bounded(
                [self.python, "-c", "import os; os.write(1,b'out'); os.write(2,b'err')"],
                executable_sha256=self.digest,
                output_directory=Path(temporary) / "run",
                timeout_seconds=2,
                maximum_output_bytes=16,
            )
            self.assertEqual(result.status, runner.RunStatus.EXITED)
            self.assertIsNotNone(result.observation)
            metadata = result.observation
            assert metadata is not None
            directory = Path(temporary) / "run"
            self.assertEqual(metadata.stdout_sha256, hashlib.sha256((directory / "stdout.bin").read_bytes()).hexdigest())
            self.assertEqual(metadata.stderr_sha256, hashlib.sha256((directory / "stderr.bin").read_bytes()).hexdigest())
            self.assertEqual(metadata.executable_sha256, self.digest)
            self.assertLessEqual(metadata.started_at_unix_seconds, metadata.finished_at_unix_seconds)

    def test_legacy_positional_result_and_pre_spawn_cancel_have_no_metadata(self) -> None:
        legacy = runner.BoundedRunResult(runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0)
        self.assertIsNone(legacy.observation)
        with tempfile.TemporaryDirectory(prefix="run-observation-cancel-") as temporary:
            event = runner.Event()
            event.set()
            result = runner.run_bounded(
                [self.python, "-c", "pass"], executable_sha256=self.digest,
                output_directory=Path(temporary) / "run", timeout_seconds=2, cancel_event=event,
            )
        self.assertEqual(result.status, runner.RunStatus.CANCELLED)
        self.assertIsNone(result.observation)

    def test_clock_failure_or_inversion_preserves_process_outcome(self) -> None:
        for samples in (
            (OSError("clock"), 2.0),
            (True, 2.0),
            (float("inf"), 2.0),
            (10**1000, 2.0),
            (2.0, 1.0),
            (-(2**53), -(2**53) - 1),
        ):
            with self.subTest(samples=samples), tempfile.TemporaryDirectory(prefix="run-observation-clock-") as temporary:
                with mock.patch.object(runner.time, "time", side_effect=samples):
                    result = runner.run_bounded(
                        [self.python, "-c", "pass"], executable_sha256=self.digest,
                        output_directory=Path(temporary) / "run", timeout_seconds=2,
                    )
                self.assertEqual(result.status, runner.RunStatus.EXITED)
                self.assertEqual(result.returncode, 0)
                self.assertIsNone(result.observation)

    def test_exit_drain_and_output_overflow_hash_exact_saved_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="run-observation-drain-") as temporary:
            drain_dir = Path(temporary) / "drain"
            real_popen = runner.subprocess.Popen

            def launch_and_exit(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                process.wait(timeout=2)
                return process

            with mock.patch.object(runner.subprocess, "Popen", side_effect=launch_and_exit):
                drained = runner.run_bounded(
                    [self.python, "-c", "import os; os.write(1,b'drain-out'); os.write(2,b'drain-err')"],
                    executable_sha256=self.digest,
                    output_directory=drain_dir,
                    timeout_seconds=2,
                    maximum_output_bytes=32,
                )
            self.assertEqual(drained.status, runner.RunStatus.EXITED)
            self.assertIsNotNone(drained.observation)
            assert drained.observation is not None
            self.assertEqual(drained.observation.stdout_sha256, hashlib.sha256(b"drain-out").hexdigest())
            self.assertEqual(drained.observation.stderr_sha256, hashlib.sha256(b"drain-err").hexdigest())

        with tempfile.TemporaryDirectory(prefix="run-observation-overflow-") as temporary:
            cap = 17
            result = runner.run_bounded(
                [self.python, "-c", "import os; os.write(1,b'0123456789abcdefghijklmnop')"],
                executable_sha256=self.digest,
                output_directory=Path(temporary) / "run",
                timeout_seconds=2,
                maximum_output_bytes=cap,
            )
            self.assertEqual(result.status, runner.RunStatus.OUTPUT_LIMIT)
            self.assertEqual(result.stdout_bytes + result.stderr_bytes, cap)
            self.assertIsNotNone(result.observation)
            assert result.observation is not None
            saved = (Path(temporary) / "run" / "stdout.bin").read_bytes()
            self.assertEqual(len(saved), cap)
            self.assertEqual(result.observation.stdout_sha256, hashlib.sha256(saved).hexdigest())

    def test_timeout_preserves_outcome_and_attests_only_saved_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="run-observation-timeout-") as temporary:
            result = runner.run_bounded(
                [self.python, "-c", "import os,time; os.write(1,b'kept'); time.sleep(30)"],
                executable_sha256=self.digest,
                output_directory=Path(temporary) / "run",
                timeout_seconds=0.15,
                termination_grace_seconds=0.1,
                maximum_output_bytes=32,
            )
            metadata = result.observation
            self.assertEqual(result.status, runner.RunStatus.TIMED_OUT)
            self.assertIsNotNone(metadata)
            assert metadata is not None
            directory = Path(temporary) / "run"
            self.assertEqual(metadata.stdout_sha256, hashlib.sha256((directory / "stdout.bin").read_bytes()).hexdigest())
            self.assertEqual(metadata.stderr_sha256, hashlib.sha256((directory / "stderr.bin").read_bytes()).hexdigest())

    def test_cancel_attests_ready_bytes_and_excludes_cooperative_term_tail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="run-observation-cancel-tail-") as temporary:
            directory = Path(temporary) / "run"
            marker = Path(temporary) / "term-handled"
            event = threading.Event()
            children = []
            real_popen = runner.subprocess.Popen
            consume_events = runner._consume_events

            def track_child(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                children.append(process)
                return process

            def consume_and_cancel(events, counts, maximum_output_bytes, selector, capture_hashes=None):
                overflow = consume_events(events, counts, maximum_output_bytes, selector, capture_hashes)
                if counts["stdout"] == len(b"ready\n"):
                    event.set()
                return overflow

            code = f"""
import os, signal
def on_term(signum, frame):
    os.write(1, b'term-out-tail')
    os.write(2, b'term-err-tail')
    with open({str(marker)!r}, 'wb') as marker:
        marker.write(b'handled')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, on_term)
os.write(1, b'ready\\n')
signal.pause()
"""
            try:
                with mock.patch.object(runner.subprocess, "Popen", side_effect=track_child), \
                     mock.patch.object(runner, "_consume_events", side_effect=consume_and_cancel):
                    result = runner.run_bounded(
                        [self.python, "-c", code], executable_sha256=self.digest,
                        output_directory=directory, timeout_seconds=2,
                        termination_grace_seconds=0.5, maximum_output_bytes=1024,
                        cancel_event=event,
                    )
                self.assertTrue(event.is_set())
                self.assertEqual(marker.read_bytes(), b"handled")
                self.assertEqual(result.status, runner.RunStatus.CANCELLED)
                self.assertEqual(result.trigger, runner.RunTrigger.CANCELLED)
                self.assertEqual(result.returncode, 0)
                self.assertEqual((result.stdout_bytes, result.stderr_bytes), (6, 0))
                self.assertEqual((directory / "stdout.bin").read_bytes(), b"ready\n")
                self.assertEqual((directory / "stderr.bin").read_bytes(), b"")
                self.assertIsNotNone(result.observation)
                assert result.observation is not None
                self.assertEqual(result.observation.stdout_sha256, hashlib.sha256(b"ready\n").hexdigest())
                self.assertEqual(result.observation.stderr_sha256, hashlib.sha256(b"").hexdigest())
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].returncode, 0)
                with self.assertRaises(ChildProcessError):
                    os.waitpid(children[0].pid, os.WNOHANG)
            finally:
                for process in children:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
