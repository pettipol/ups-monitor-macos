from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from continuous_capture import ID_RE, AtomicSamplePublisher, _has_empty_extended_acl, capture_continuous
from continuous_protocol import FIELD_KINDS, Sample, parse_line
from process_deadline import BoundedRunResult, RunStatus, RunTrigger, run_bounded
from synthetic_continuous_feed import create_feed


def sample_bytes():
    values = {
        "ups.status": "OL", "battery.charge": "93.5", "battery.runtime": "1280",
        "battery.voltage": "27.4", "battery.temperature": "24.0", "ups.temperature": "24.0",
        "input.voltage": "231.2", "input.frequency": "50.0", "output.voltage": "229.8",
        "output.current": "1.10", "output.frequency": "50.0", "ups.load": "31.5",
        "experimental.ups.load.apparent": "42.0", "ups.realpower.nominal": "650",
        "ups.power.nominal": "900", "ups.realpower": "204.75", "ups.power": "378",
    }
    fields = {name: {"value": values[name], "observed_ms": 0, "kind": kind, "state": "observed"}
              for name, kind in FIELD_KINDS.items()}
    return (json.dumps({"protocol": "ups-monitor.continuous.v1", "schema_version": 1, "type": "sample",
                        "sequence": 1, "slot": 0, "elapsed_ms": 0, "missed_slots": 0, "fields": fields},
                       separators=(",", ":")) + "\n").encode()


END = b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":0,"reason":"duration_complete"}\n'


class ContinuousCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.output = self.root / "outputs"
        self.feed = self.root / "feed"
        self.output.mkdir(mode=0o700)
        self.feed.mkdir(mode=0o700)
        self.interpreter = Path(sys.executable).resolve()
        self.digest = hashlib.sha256(self.interpreter.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def run_code(self, code, **kwargs):
        runner = kwargs.pop("runner", self.synthetic_runner)
        return capture_continuous(
            [str(self.interpreter), "-c", code], executable_sha256=self.digest,
            output_root=self.output, feed_directory=self.feed, source_id="synthetic-test",
            runner=runner,
            expected_elapsed_ms=0, wall_clock=lambda: 100_000, monotonic_clock=lambda: 10_000,
            **kwargs,
        )

    @staticmethod
    def synthetic_runner(*args, **kwargs):
        return run_bounded(*args, **kwargs)

    @staticmethod
    def writer(payload: bytes) -> str:
        return "import os; os.write(1, bytes.fromhex('" + payload.hex() + "'))"

    def envelope(self):
        return json.loads((self.feed / "sample.json").read_text(encoding="utf-8"))

    def test_synthetic_child_publishes_valid_terminal_sample(self):
        result = self.run_code(self.writer(sample_bytes() + END), timeout_seconds=4)
        self.assertEqual((result.state, result.terminal_reason), ("stopped", "duration_complete"))
        self.assertTrue(result.tailer_quiesced)
        envelope = self.envelope()
        self.assertEqual(envelope["state"], "stopped")
        self.assertEqual(envelope["sample"]["sequence"], 1)
        self.assertEqual((self.feed.stat().st_mode & 0o777, (self.feed / "sample.json").stat().st_mode & 0o777), (0o700, 0o600))

    def test_malformed_stream_fails_and_cancels_owned_child(self):
        bad = b'{"protocol":"wrong"}\n'
        code = self.writer(bad) + "; import time; time.sleep(3)"
        result = self.run_code(code, timeout_seconds=5)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.terminal_reason, "protocol_error")
        self.assertEqual(self.envelope()["state"], "failed")

    def test_missing_newline_is_protocol_failure(self):
        truncated = sample_bytes()[:-1]
        result = self.run_code(self.writer(truncated), timeout_seconds=4)
        self.assertEqual(result.terminal_reason, "protocol_error")

    def test_invalid_end_type_cancels_runner_as_protocol_error(self):
        bad_end = b'{"protocol":"ups-monitor.continuous.v1","schema_version":1,"type":"end","elapsed_ms":0,"reason":[]}\n'
        payload = sample_bytes() + bad_end

        def synthetic_runner(_argv, *, output_directory, cancel_event, **_kwargs):
            output_directory.mkdir(mode=0o700)
            target = output_directory / "stdout.bin"
            target.write_bytes(payload)
            target.chmod(0o600)
            cancelled = cancel_event.wait(0.5)
            return BoundedRunResult(
                RunStatus.CANCELLED if cancelled else RunStatus.EXITED,
                RunTrigger.CANCELLED if cancelled else RunTrigger.COMPLETED,
                -15 if cancelled else 0, len(payload), 0, None,
            )

        result = self.run_code("pass", runner=synthetic_runner, timeout_seconds=2)
        self.assertEqual((result.state, result.terminal_reason), ("failed", "protocol_error"))

    def test_unexpected_tailer_exception_cancels_without_thread_traceback(self):
        from continuous_protocol import StreamValidator
        payload = sample_bytes() + END
        with patch.object(StreamValidator, "accept", side_effect=TypeError("synthetic malformed value")):
            result = self.run_code(self.writer(payload) + "; import time; time.sleep(3)", timeout_seconds=5)
        self.assertEqual((result.state, result.terminal_reason), ("failed", "io_error"))

    @unittest.skipUnless(sys.platform == "darwin", "Darwin ACL API is required")
    def test_capture_acl_added_after_open_is_detected_and_cancels(self):
        payload = sample_bytes() + END

        def synthetic_runner(_argv, *, output_directory, cancel_event, **_kwargs):
            output_directory.mkdir(mode=0o700)
            target = output_directory / "stdout.bin"
            target.write_bytes(sample_bytes())
            target.chmod(0o600)
            deadline = time.monotonic() + 1
            while not (self.feed / "sample.json").exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            applied = subprocess.run(["/bin/chmod", "+a", "everyone allow read", str(target)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if applied.returncode != 0:
                raise RuntimeError("synthetic_acl_fixture_failed")
            with target.open("ab") as stream:
                stream.write(END)
            cancelled = cancel_event.wait(0.5)
            return BoundedRunResult(
                RunStatus.CANCELLED if cancelled else RunStatus.EXITED,
                RunTrigger.CANCELLED if cancelled else RunTrigger.COMPLETED,
                -15 if cancelled else 0, len(payload), 0, None,
            )

        result = self.run_code("pass", runner=synthetic_runner, timeout_seconds=2)
        self.assertEqual((result.state, result.terminal_reason), ("failed", "io_error"))

    def test_deadline_is_terminal_failure(self):
        result = self.run_code("import time; time.sleep(2)", timeout_seconds=0.1, termination_grace_seconds=0.2)
        self.assertEqual((result.state, result.terminal_reason), ("failed", "deadline"))

    def test_pre_cancel_does_not_launch_child(self):
        cancellation = Event()
        cancellation.set()
        result = self.run_code("raise SystemExit(99)", cancel_event=cancellation, timeout_seconds=2)
        self.assertEqual((result.state, result.terminal_reason), ("failed", "cancelled"))

    def test_combined_output_cap_fails_closed(self):
        result = self.run_code("import os; os.write(2, b'x' * 1200000)", timeout_seconds=4)
        self.assertEqual((result.state, result.terminal_reason), ("failed", "capture_limit"))

    def test_stderr_is_drained_with_stdout(self):
        payload = sample_bytes() + END
        code = "import os; os.write(2, b'x' * 700000); os.write(1, bytes.fromhex('" + payload.hex() + "'))"
        result = self.run_code(code, timeout_seconds=5)
        self.assertEqual(result.state, "stopped")
        self.assertEqual(result.stderr_bytes, 700000)

    def test_standalone_synthetic_feed_is_parseable(self):
        self.assertEqual(create_feed(self.feed, duration_seconds=1, once=True), 0)
        envelope = self.envelope()
        self.assertEqual((envelope["source_id"], envelope["state"]), ("synthetic-ups-feed", "active"))
        self.assertIsNotNone(ID_RE.fullmatch(envelope["source_id"]))
        self.assertIsNotNone(ID_RE.fullmatch(envelope["session_id"]))
        record = envelope["sample"]
        parsed = parse_line((json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8"))
        self.assertIsInstance(parsed, Sample)

    def test_publisher_rechecks_directory_after_open(self):
        publisher = AtomicSamplePublisher(self.feed, "synthetic-test", "test-session")
        try:
            os.chmod(self.feed, 0o750)
            with self.assertRaises(OSError):
                publisher.publish(state="active", started_at_unix_ms=1, terminal_reason=None,
                                  sample=None, published_at_unix_ms=2)
        finally:
            publisher.close()

    @unittest.skipUnless(sys.platform == "darwin", "Darwin ACL API is required")
    def test_nonempty_extended_acl_is_rejected_on_owned_synthetic_file(self):
        target = self.feed / "acl-fixture.bin"
        target.write_bytes(b"synthetic-only")
        os.chmod(target, 0o600)
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            self.assertTrue(_has_empty_extended_acl(fd))
        finally:
            os.close(fd)
        import subprocess
        applied = subprocess.run(["/bin/chmod", "+a", "everyone allow read", str(target)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        self.assertEqual(applied.returncode, 0)
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            self.assertFalse(_has_empty_extended_acl(fd))
        finally:
            os.close(fd)

    def test_terminal_lock_timeout_never_closes_busy_publisher_or_reports_success(self):
        payload = sample_bytes()
        record = json.loads(payload)
        record["slot"], record["elapsed_ms"], record["missed_slots"] = 1, 6000, 1
        for field in record["fields"].values():
            if field["state"] == "observed":
                field["observed_ms"] = 6000
        second = json.loads(payload)
        second["sequence"], second["slot"], second["elapsed_ms"] = 2, 2, 10000
        second["missed_slots"] = 1
        for field in second["fields"].values():
            if field["state"] == "observed":
                field["observed_ms"] = 10000
        end = json.loads(END)
        end["elapsed_ms"] = 10000
        feed = b"".join((json.dumps(value, separators=(",", ":")) + "\n").encode()
                        for value in (record, second, end))
        entered, release, closed = Event(), Event(), Event()
        published = []

        class BlockingPublisher:
            session_id = "synthetic-session"

            def __init__(self, *_args):
                pass

            def publish(self, **kwargs):
                if kwargs["state"] == "active" and kwargs["sample"] is not None:
                    entered.set()
                    release.wait(2)
                published.append(kwargs["state"])

            def close(self):
                closed.set()

        mono_values = iter((10000, 16000, 20000, 20000))
        wall_values = iter((100000, 106000, 106000, 110000, 110000, 110000))
        last_mono, last_wall = 20000, 110000

        def mono_clock():
            nonlocal last_mono
            last_mono = next(mono_values, last_mono)
            return last_mono

        def wall_clock():
            nonlocal last_wall
            last_wall = next(wall_values, last_wall)
            return last_wall

        def fake_runner(_argv, *, output_directory, **_kwargs):
            output_directory.mkdir(mode=0o700)
            target = output_directory / "stdout.bin"
            target.write_bytes(feed)
            target.chmod(0o600)
            if not entered.wait(1):
                raise RuntimeError("synthetic_barrier_not_reached")
            return BoundedRunResult(RunStatus.EXITED, RunTrigger.COMPLETED, 0,
                                    len(feed), 0, None)

        with patch("continuous_capture.AtomicSamplePublisher", BlockingPublisher):
            result = capture_continuous(
                [str(self.interpreter), "-c", "pass"], executable_sha256=self.digest,
                output_root=self.output, feed_directory=self.feed, source_id="synthetic-race",
                runner=fake_runner, expected_elapsed_ms=10000, join_seconds=0.05,
                wall_clock=wall_clock, monotonic_clock=mono_clock,
            )
        self.assertEqual((result.state, result.publication_error), ("failed", "publication_failed"))
        self.assertFalse(result.tailer_quiesced)
        self.assertFalse(closed.is_set())
        release.set()
        self.assertTrue(closed.wait(2))
        self.assertEqual(published, ["active"])


if __name__ == "__main__":
    unittest.main()

