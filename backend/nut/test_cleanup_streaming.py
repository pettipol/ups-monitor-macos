"""Offline synthetic acceptance for native-stderr diagnostics (not auto-run)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from cleanup_diagnostics import CleanupDiagnosticParser, PREFIX
import process_deadline as runner
import test_process_streaming_lifecycle as lifecycle


DIAGNOSTIC = dict(v=1, reason_before=0, reason_after=3, phase_before=3,
                  health_before=1, phase_after=4, health_after=1, admitted=1,
                  stop_ok=0, released=1, complete=0, clock_ok=1,
                  cleanup_attempted=1, cleanup_failed=1, write_called=1,
                  write_kind=2, write_rc=63, cleanup_delta_ms=100)
LINE = PREFIX + json.dumps(DIAGNOSTIC, separators=(",", ":")).encode("ascii") + b"\n"
PIN = "a" * 64


def result_for(data: bytes, *, stdout_eof=True, stderr_eof=True):
    return runner.StreamingRunResult("cancelled", 0, 0, len(data),
        hashlib.sha256().hexdigest(), hashlib.sha256(data).hexdigest(),
        True, True, stdout_eof, stderr_eof, True)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ups-e28-stream-author-persist-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(os.close, self.fd)
        self.parser = CleanupDiagnosticParser()
        self.parser.accept(LINE)
        self.pipes = SimpleNamespace(cleanup_diagnostic=self.parser)

    def persist(self, result=None):
        return runner._persist_cleanup_diagnostic(self.fd, PIN, self.pipes,
                                                  result or result_for(LINE))

    def test_private_exact_schema_bounded_exclusive(self):
        self.assertTrue(self.persist())
        path = self.path / "cleanup-diagnostic.json"
        data = path.read_bytes()
        self.assertLessEqual(len(data), 4096)
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        payload = json.loads(data)
        self.assertEqual(set(payload), {"schema_version", "kind", "state", "error_code",
            "native_sha256", "stderr_eof", "stderr_bytes", "stderr_sha256", "diagnostic"})
        self.assertEqual(payload["diagnostic"], DIAGNOSTIC)
        self.assertEqual(payload["native_sha256"], PIN)
        self.assertFalse(self.persist())
        self.assertEqual(path.read_bytes(), data)
        self.assertFalse((self.path / ".cleanup-diagnostic.json.tmp").exists())

    def test_collisions_and_symlinks_are_untouched(self):
        foreign = self.path / "foreign"
        foreign.write_bytes(b"synthetic-private-foreign")
        for name in ("cleanup-diagnostic.json", ".cleanup-diagnostic.json.tmp"):
            with self.subTest(name=name):
                target = self.path / name
                target.symlink_to(foreign)
                self.assertFalse(self.persist())
                self.assertTrue(target.is_symlink())
                self.assertEqual(foreign.read_bytes(), b"synthetic-private-foreign")
                target.unlink()
                target.write_bytes(b"occupied")
                self.assertFalse(self.persist())
                self.assertEqual(target.read_bytes(), b"occupied")
                target.unlink()

    def test_write_fsync_close_and_link_faults_do_not_publish(self):
        real_close = os.close
        for operation in ("write", "fsync", "close", "link"):
            with self.subTest(operation=operation):
                def failed_close(descriptor):
                    real_close(descriptor)
                    raise OSError("synthetic close failure")
                effect = failed_close if operation == "close" else OSError("synthetic fault")
                with mock.patch.object(runner.os, operation, side_effect=effect):
                    self.assertFalse(self.persist())
                self.assertFalse((self.path / "cleanup-diagnostic.json").exists())
                self.assertFalse((self.path / ".cleanup-diagnostic.json.tmp").exists())

    def test_short_writes_complete_before_publication(self):
        original = os.write
        def short(descriptor, data):
            return original(descriptor, data[:7])
        with mock.patch.object(runner.os, "write", side_effect=short):
            self.assertTrue(self.persist())
        self.assertEqual(json.loads((self.path / "cleanup-diagnostic.json").read_bytes())["diagnostic"],
                         DIAGNOSTIC)

    def test_directory_descriptor_survives_name_move(self):
        # No path is reopened by the writer after directory admission.
        moved = self.path / "new-name"
        child = self.path / "owned"
        child.mkdir(mode=0o700)
        fd = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            child.rename(moved)
            child.symlink_to(self.path)
            self.assertTrue(runner._persist_cleanup_diagnostic(fd, PIN, self.pipes, result_for(LINE)))
            self.assertTrue((moved / "cleanup-diagnostic.json").is_file())
            self.assertFalse((self.path / "cleanup-diagnostic.json").exists())
        finally:
            os.close(fd)

    def test_either_unfinished_stream_freezes_incomplete_same_cut(self):
        self.assertTrue(self.persist(result_for(LINE, stdout_eof=False)))
        payload = json.loads((self.path / "cleanup-diagnostic.json").read_bytes())
        self.assertEqual((payload["state"], payload["error_code"], payload["diagnostic"]),
                         ("incomplete", "stream_not_final", None))
        self.assertTrue(payload["stderr_eof"])
        self.assertEqual(payload["stderr_bytes"], len(LINE))
        self.assertEqual(payload["stderr_sha256"], hashlib.sha256(LINE).hexdigest())


class PipeAccountingTests(unittest.TestCase):
    def test_foreign_and_reserved_chunks_count_even_after_clock_failure(self):
        from threading import Event
        data = b"foreign-\xff-private\n" + LINE
        dispatch = mock.Mock()
        clock = mock.Mock()
        clock.sample.side_effect = runner._StreamingFailure("clock_invalid")
        key = SimpleNamespace(data="stderr", fd=812, fileobj=object())
        selector = mock.Mock()
        selector.select.return_value = [(key, 0)]
        pipes = runner._StreamingPipes(selector, dispatch, Event(), clock, 0.0)
        # Deliberately break every prefix/JSON/LF byte across consume calls.
        with mock.patch.object(runner.os, "read", side_effect=[bytes((byte,)) for byte in data]):
            for _ in data:
                pipes.consume(0.0)
        self.assertEqual(pipes.counts["stderr"], len(data))
        self.assertEqual(pipes.hashes["stderr"].hexdigest(), hashlib.sha256(data).hexdigest())
        self.assertEqual(pipes.cleanup_diagnostic.snapshot(True)["diagnostic"], DIAGNOSTIC)
        self.assertEqual(pipes.failure, "clock_invalid")
        self.assertTrue(pipes.cancel_event.is_set())


class CleanupStreamingTests(unittest.TestCase):
    # Reuse the existing finite real-child fixture, without inheriting/rerunning
    # its already-green tests. The bounded launcher supplies that source module.
    setUpClass = classmethod(lifecycle.StreamingLifecycleTests.setUpClass.__func__)
    setUp = lifecycle.StreamingLifecycleTests.setUp
    tear_down_owned_resources = lifecycle.StreamingLifecycleTests.tear_down_owned_resources
    run_child = lifecycle.StreamingLifecycleTests.run_child

    def sidecar(self):
        return json.loads((self.parent / "output" / "cleanup-diagnostic.json").read_bytes())

    def assert_correlated(self, result, state, expected):
        payload = self.sidecar()
        self.assertEqual(payload["state"], state)
        self.assertEqual(payload["native_sha256"], self.pin)
        self.assertEqual(payload["stderr_eof"], result.stderr_eof)
        self.assertEqual(payload["stderr_bytes"], result.stderr_bytes)
        self.assertEqual(payload["stderr_sha256"], result.stderr_sha256)
        self.assertEqual(result.stderr_bytes, len(expected))
        self.assertEqual(result.stderr_sha256, hashlib.sha256(expected).hexdigest())
        self.assertEqual((self.parent / "output" / "stderr.bin").stat().st_size, 0)
        return payload

    def test_diagnostic_before_stdout_and_foreign_bytes_all_counted(self):
        foreign = b"synthetic-sensitive:" + b"q" * 70000 + b"\n"
        data = foreign + LINE + b"foreign-final\n"
        code = f"import os,signal\nsignal.alarm(8)\ndata={data!r}\nwhile data:\n n=os.write(2,data[:4096]);data=data[n:]\nos.write(1,b'terminal\\n')"
        result = self.run_child(code, sink=lambda chunk: bool(chunk))
        payload = self.assert_correlated(result, "valid", data)
        self.assertEqual(payload["diagnostic"], DIAGNOSTIC)
        self.assertNotIn(b"synthetic-sensitive", (self.parent / "output" / "cleanup-diagnostic.json").read_bytes())
        self.assertEqual(result.trigger, "child_exited")

    def test_cancel_drain_collects_stderr_after_terminal_stdout(self):
        code = f"""
import os,signal
signal.alarm(8)
def stop(signum,frame):
 os.write(1,b'terminal\\n')
 os.write(2,{LINE!r})
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
os.write(1,b'active\\n')
while True: signal.pause()
"""
        result = self.run_child(code)
        self.assert_correlated(result, "valid", LINE)
        self.assertEqual(result.trigger, "cancelled")
        self.assertTrue(result.ownership_resolved)

    def test_consumer_failure_keeps_failure_and_drains_diagnostic(self):
        code = f"""
import os,signal
signal.alarm(8)
def stop(signum,frame):
 os.write(2,{LINE!r})
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
os.write(1,b'active\\n')
while True: signal.pause()
"""
        def reject(_chunk):
            raise RuntimeError("synthetic consumer failure")
        result = self.run_child(code, sink=reject)
        self.assert_correlated(result, "valid", LINE)
        self.assertEqual(result.trigger, "consumer_error")

    def test_kill_before_lf_is_truncated_not_valid(self):
        partial = LINE[:-1]
        code = f"import os,signal\nsignal.alarm(8)\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nos.write(2,{partial!r})\nos.write(1,b'active\\n')\nwhile True:signal.pause()"
        result = self.run_child(code)
        payload = self.assert_correlated(result, "incomplete", partial)
        self.assertEqual(payload["error_code"], "truncated")
        self.assertEqual(result.returncode, -signal.SIGKILL)

    def test_late_observer_never_writes_or_updates_first_cut(self):
        code = f"""
import os,signal
signal.alarm(8)
def stop(signum,frame):
 os.write(2,{LINE!r})
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
os.write(1,b'active\\n')
while True:signal.pause()
"""
        def leave_unread(process, pgid, pipes, grace):
            runner._signal_child(process, signal.SIGTERM, pgid)
            process.wait(timeout=2)
        with mock.patch.object(runner, "_streaming_cleanup", side_effect=leave_unread):
            result = self.run_child(code)
        path = self.parent / "output" / "cleanup-diagnostic.json"
        before, info = path.read_bytes(), path.stat()
        self.assertFalse(result.stderr_eof)
        self.assertEqual(self.sidecar()["state"], "incomplete")
        with mock.patch.object(runner, "_persist_cleanup_diagnostic", side_effect=AssertionError("observer wrote")):
            for _ in range(8):
                observed = runner.retained_streaming_ownership()
                if observed is None or observed.ownership_resolved:
                    break
        self.assertIsNone(runner._retained_streaming_owner)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, info.st_mtime_ns)
        self.assertEqual(observed.stderr_bytes, len(LINE))

    def test_failed_persistence_does_not_change_cancel_outcome(self):
        with mock.patch.object(runner.os, "fsync", side_effect=OSError("synthetic fsync fault")):
            result = self.run_child()
        self.assertEqual(result.trigger, "cancelled")
        self.assertTrue(result.ownership_resolved)
        self.assertFalse((self.parent / "output" / "cleanup-diagnostic.json").exists())
