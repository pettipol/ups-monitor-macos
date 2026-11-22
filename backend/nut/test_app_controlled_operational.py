"""Synthetic finite captures/observers only; never invoke a real producer."""
from __future__ import annotations

from dataclasses import asdict, fields, FrozenInstanceError, replace
import errno
import os
from pathlib import Path
import signal
import tempfile
import threading
import unittest
from unittest import mock

import app_controlled_operational as adapter
from operational_capture import OperationalCaptureResult
from process_deadline import DependencyPin, StreamingRunResult


def receipt(*, resolved: bool = True) -> OperationalCaptureResult:
    run = StreamingRunResult("cancelled", 0, 100, 0, "a" * 64, "b" * 64,
                             resolved, resolved, resolved, resolved, resolved)
    return OperationalCaptureResult(
        2, "ups-monitor.continuous.v2", "stopped" if resolved else "unresolved",
        "cancelled" if resolved else "cleanup_unresolved", None, None,
        "synthetic-source", "0" * 32, 0, 0 if resolved else None,
        1 if resolved else 0, "cancelled" if resolved else None, run,
        resolved, resolved, resolved, resolved, resolved,
    )


class AppControlledOperationalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = adapter.FixedOperationalProfile(("/synthetic/producer", "fixed-v2"), "a" * 64)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(adapter, "_active", False).start()
        mock.patch.object(adapter, "_retained_owner", None).start()
        # A finite injected receipt sequence determines every observer test;
        # production uses the fixed 250-ms observation interval.
        mock.patch.object(adapter, "_OBSERVATION_SECONDS", 0.001).start()

    @staticmethod
    def close_owned(fd: int) -> None:
        try:
            os.close(fd)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise

    def pipe(self) -> tuple[int, int]:
        read_fd, write_fd = os.pipe()
        self.addCleanup(self.close_owned, write_fd)
        return read_fd, write_fd

    def run_adapter(self, fd: int, capture, observer=None):
        if observer is None:
            observer = mock.Mock(side_effect=AssertionError("resolved capture must not be observed"))
        return adapter.run_app_controlled_operational(
            self.profile, control_read_fd=fd, output_root="synthetic-output",
            feed_directory="synthetic-feed", source_id="synthetic-source",
            capture=capture, ownership_observer=observer,
        )

    def cancelled_capture(self, *_args, **kwargs) -> OperationalCaptureResult:
        self.assertTrue(kwargs["cancel_event"].wait(1), "control cancellation was not delivered")
        return receipt()

    def assert_closed(self, fd: int) -> None:
        with self.assertRaises(OSError) as closed:
            os.fstat(fd)
        self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_clean_stop_keeps_complete_nested_receipt_and_restores_handlers(self) -> None:
        read_fd, write_fd = self.pipe()
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        os.write(write_fd, b"STOP\n")
        original = receipt()
        calls = []

        def capture(argv, **kwargs):
            calls.append(argv)
            self.assertTrue(kwargs["cancel_event"].wait(1))
            os.fstat(read_fd)  # STOP does not abandon control ownership early.
            return original

        result = self.run_adapter(read_fd, capture)
        self.assertEqual(calls, [self.profile.argv])
        self.assertIs(result.capture_result, original)
        self.assertEqual(result.control_reason, "stop")
        self.assertIsNone(result.adapter_error)
        self.assertTrue(result.watcher_quiesced and result.ownership_resolved)
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})
        self.assert_closed(read_fd)
        payload = asdict(result)
        self.assertEqual(set(payload), {"capture_result", "control_reason", "adapter_error",
                                        "watcher_quiesced", "ownership_resolved"})
        self.assertEqual(set(payload["capture_result"]), {item.name for item in fields(OperationalCaptureResult)})
        self.assertEqual(set(payload["capture_result"]["runner_result"]),
                         {item.name for item in fields(StreamingRunResult)})

    def test_eof_requests_cancellation_and_resolves_control(self) -> None:
        read_fd, write_fd = self.pipe()
        os.close(write_fd)
        result = self.run_adapter(read_fd, self.cancelled_capture)
        self.assertEqual(result.control_reason, "app_disconnected")
        self.assertTrue(result.ownership_resolved)
        self.assert_closed(read_fd)

    def test_malformed_partial_and_oversized_commands_are_bounded(self) -> None:
        for command in (b"stop\n", b"S", b"\n", b"X" * 4096):
            with self.subTest(command=command[:5]):
                read_fd, write_fd = self.pipe()
                os.write(write_fd, command)
                os.close(write_fd)
                result = self.run_adapter(read_fd, self.cancelled_capture)
                self.assertEqual(result.control_reason, "invalid_control")
                self.assertEqual(result.adapter_error, "invalid_control")
                self.assertTrue(result.ownership_resolved,
                                "malformed input is failure, not evidence of a live resource")
                self.assert_closed(read_fd)

    def test_fragmented_stop_and_surplus_preserve_v1_control_framing(self) -> None:
        real_read = os.read
        for size in (1, 5):
            with self.subTest(size=size):
                read_fd, write_fd = self.pipe()
                os.write(write_fd, b"STOP\nX")
                with mock.patch.object(adapter.os, "read", side_effect=lambda fd, n: real_read(fd, min(n, size))):
                    result = self.run_adapter(read_fd, self.cancelled_capture)
                self.assertEqual(result.control_reason, "stop")
                self.assertTrue(result.ownership_resolved)

    def test_no_duration_or_lifetime_output_limit_is_forwarded(self) -> None:
        read_fd, _ = self.pipe()
        pin = DependencyPin(Path("/synthetic/current"), "runtime/bin", "version",
                            Path("/synthetic/version"), "c" * 64)
        profile = adapter.FixedOperationalProfile(self.profile.argv, self.profile.executable_sha256, (pin,))
        observed = {}

        def capture(argv, **kwargs):
            self.assertEqual(argv, profile.argv)
            observed.update(kwargs)
            self.assertFalse(os.get_inheritable(read_fd))
            self.assertFalse(os.get_blocking(read_fd))
            return receipt()

        result = adapter.run_app_controlled_operational(
            profile, control_read_fd=read_fd, output_root="synthetic-output",
            feed_directory="synthetic-feed", source_id="synthetic-source", capture=capture,
        )
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(set(observed), {"executable_sha256", "dependency_pins", "output_root",
                                        "feed_directory", "source_id", "cancel_event"})
        self.assertEqual(observed["dependency_pins"], (pin,))
        with self.assertRaises(FrozenInstanceError):
            profile.executable_sha256 = "d" * 64

    def test_unresolved_then_late_cleanup_is_observed_without_retry(self) -> None:
        read_fd, write_fd = self.pipe()
        os.write(write_fd, b"STOP\n")
        initial, final = receipt(resolved=False), receipt()
        capture = mock.Mock(side_effect=self.cancelled_capture)
        calls = []

        def initial_capture(*args, **kwargs):
            capture(*args, **kwargs)
            return initial

        def observer():
            os.fstat(read_fd)  # Ownership retained throughout late cleanup.
            calls.append(1)
            return initial if len(calls) < 3 else final

        result = self.run_adapter(read_fd, initial_capture, observer)
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(len(calls), 3)
        self.assertIs(result.capture_result, final)
        self.assertTrue(result.ownership_resolved)
        self.assert_closed(read_fd)

    def test_observer_exception_none_or_invalid_result_retains_owner(self) -> None:
        for observed, code in ((None, "invalid_observer_receipt"),
                               (object(), "invalid_observer_receipt"),
                               (RuntimeError("private observer text"), "observer_failed")):
            with self.subTest(code=code), mock.patch.object(adapter, "_retained_owner", None):
                read_fd, _ = self.pipe()
                capture = mock.Mock(return_value=receipt(resolved=False))
                observer = mock.Mock(side_effect=observed) if isinstance(observed, Exception) else mock.Mock(return_value=observed)
                result = self.run_adapter(read_fd, capture, observer)
                self.assertEqual(result.adapter_error, code)
                self.assertFalse(result.ownership_resolved)
                self.assertTrue(result.watcher_quiesced)
                self.assertIsNotNone(adapter._retained_owner)
                self.assertNotIn("private", repr(result))
                self.assertEqual(capture.call_count, 1)
                self.assertEqual(observer.call_count, 1)
                self.assert_closed(read_fd)

    def test_unknown_capture_exception_or_type_returns_retained_finite_result(self) -> None:
        for capture, code in ((mock.Mock(side_effect=RuntimeError("private capture text")), "capture_failed"),
                              (mock.Mock(return_value=object()), "invalid_capture_receipt")):
            with self.subTest(code=code), mock.patch.object(adapter, "_retained_owner", None):
                read_fd, _ = self.pipe()
                result = self.run_adapter(read_fd, capture)
                self.assertEqual(result.adapter_error, code)
                self.assertIsNone(result.capture_result)
                self.assertFalse(result.ownership_resolved)
                self.assertTrue(result.watcher_quiesced)
                self.assertIsNotNone(adapter._retained_owner)
                self.assertNotIn("private", repr(result))
                self.assert_closed(read_fd)

    def test_publication_failure_can_prove_cleanup_without_becoming_stopped(self) -> None:
        read_fd, _ = self.pipe()
        failed = replace(receipt(), state="failed", terminal_reason="io_error", first_error="io_error",
                         publication_error="terminal_publication_failed", terminal_published=False,
                         published_at_unix_ms=None)
        result = self.run_adapter(read_fd, lambda *_a, **_k: failed)
        self.assertIs(result.capture_result, failed)
        self.assertEqual(result.capture_result.state, "failed")
        self.assertTrue(result.ownership_resolved)
        self.assertIsNone(adapter._retained_owner)

    def test_contradictory_cleanup_or_stopped_receipts_are_rejected(self) -> None:
        clean = receipt()
        bad = [
            replace(clean, runner_result=None),
            replace(clean, runner_result=replace(clean.runner_result, group_absent=False)),
            replace(clean, terminal_published=False),
            replace(clean, first_error="io_error"),
            replace(clean, consumer_quiesced=1),
            replace(clean, publication_error=[]),
            replace(clean, sample_count=True),
            replace(clean, sample_count=9_007_199_254_740_992),
            replace(clean, session_id="unknown"),
        ]
        for candidate in bad:
            with self.subTest(candidate=candidate), mock.patch.object(adapter, "_retained_owner", None):
                read_fd, _ = self.pipe()
                result = self.run_adapter(read_fd, lambda *_a, **_k: candidate)
                self.assertEqual(result.adapter_error, "invalid_capture_receipt")
                self.assertFalse(result.ownership_resolved)

    def test_observer_cannot_switch_identity_or_erase_known_failure(self) -> None:
        initial = replace(receipt(resolved=False), first_error="io_error")
        for candidate in (replace(receipt(), session_id="1" * 32), receipt()):
            with self.subTest(candidate=candidate), mock.patch.object(adapter, "_retained_owner", None):
                read_fd, _ = self.pipe()
                result = self.run_adapter(read_fd, lambda *_a, **_k: initial, lambda: candidate)
                self.assertEqual(result.adapter_error, "invalid_observer_receipt")
                self.assertIs(result.capture_result, initial)
                self.assertFalse(result.ownership_resolved)

    def test_recursive_or_retained_start_rejected_before_descriptor_transfer(self) -> None:
        read_fd, _ = self.pipe()
        inner_fd, _ = self.pipe()
        self.addCleanup(self.close_owned, inner_fd)

        def capture(*_a, **_k):
            with self.assertRaisesRegex(adapter.AppOperationalAdmissionError, "session_ownership_unresolved"):
                self.run_adapter(inner_fd, lambda *_a, **_k: receipt())
            os.fstat(inner_fd)
            raise RuntimeError("unknown capture state")

        self.assertFalse(self.run_adapter(read_fd, capture).ownership_resolved)
        with self.assertRaisesRegex(adapter.AppOperationalAdmissionError, "session_ownership_unresolved"):
            self.run_adapter(inner_fd, lambda *_a, **_k: receipt())
        os.fstat(inner_fd)

    def test_rejected_descriptor_and_profile_keep_caller_ownership(self) -> None:
        with tempfile.TemporaryFile() as regular:
            with self.assertRaisesRegex(adapter.AppOperationalAdmissionError, "invalid_control_pipe"):
                self.run_adapter(regular.fileno(), lambda *_a, **_k: receipt())
            os.fstat(regular.fileno())
        read_fd, write_fd = self.pipe()
        self.addCleanup(self.close_owned, read_fd)
        with self.assertRaises(adapter.AppOperationalAdmissionError):
            adapter.run_app_controlled_operational(object(), control_read_fd=read_fd,
                output_root="out", feed_directory="feed", source_id="synthetic-source")
        os.fstat(read_fd)
        with self.assertRaisesRegex(adapter.AppOperationalAdmissionError, "invalid_control_pipe"):
            self.run_adapter(write_fd, lambda *_a, **_k: receipt())
        os.fstat(write_fd)

    def test_signal_handlers_are_invoked_directly_and_restored(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum):
                read_fd, _ = self.pipe()
                before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

                def capture(*_a, **kwargs):
                    signal.getsignal(signum)(signum, None)
                    return self.cancelled_capture(**kwargs)

                result = self.run_adapter(read_fd, capture)
                self.assertEqual(result.control_reason, "signal")
                self.assertTrue(result.ownership_resolved)
                self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})

    def test_control_select_failure_cancels_but_can_resolve_resource_cleanup(self) -> None:
        read_fd, _ = self.pipe()
        with mock.patch.object(adapter.select, "select", side_effect=OSError("private select detail")):
            result = self.run_adapter(read_fd, self.cancelled_capture)
        self.assertEqual(result.control_reason, "control_failed")
        self.assertEqual(result.adapter_error, "control_failed")
        self.assertTrue(result.watcher_quiesced and result.ownership_resolved)
        self.assert_closed(read_fd)

    def test_unknown_watcher_start_retains_control_and_restores_handlers(self) -> None:
        read_fd, _ = self.pipe()
        self.addCleanup(self.close_owned, read_fd)
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        capture = mock.Mock(return_value=receipt())
        with mock.patch.object(adapter.threading.Thread, "start", side_effect=RuntimeError("private start detail")):
            result = self.run_adapter(read_fd, capture)
        capture.assert_not_called()
        self.assertEqual(result.adapter_error, "adapter_setup_failed")
        self.assertFalse(result.ownership_resolved)
        self.assertFalse(result.watcher_quiesced)
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})
        self.assertIsNotNone(adapter._retained_owner)
        os.fstat(read_fd)

    def test_start_then_raise_never_closes_a_live_watchers_descriptor(self) -> None:
        read_fd, _ = self.pipe()
        entered, release = threading.Event(), threading.Event()
        real_start = threading.Thread.start
        threads = []
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        capture = mock.Mock(return_value=receipt())

        def blocked_watch(control):
            entered.set()
            try:
                release.wait(5)
            finally:
                os.close(control.fd)
                control.closed = True

        def start_then_raise(thread):
            real_start(thread)
            threads.append(thread)
            self.assertTrue(entered.wait(1))
            raise KeyboardInterrupt()

        try:
            with mock.patch.object(adapter._Control, "watch", blocked_watch), \
                    mock.patch.object(adapter.threading.Thread, "start", start_then_raise), \
                    mock.patch.object(adapter, "_JOIN_SECONDS", 0):
                result = self.run_adapter(read_fd, capture)
            capture.assert_not_called()
            self.assertFalse(result.watcher_quiesced or result.ownership_resolved)
            self.assertIsNotNone(adapter._retained_owner)
            os.fstat(read_fd)
            self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})
        finally:
            release.set()
            for thread in threads:
                thread.join(1)
                self.assertFalse(thread.is_alive())
        self.assert_closed(read_fd)

    def test_wide_counts_are_preserved_without_v1_lifetime_limits(self) -> None:
        read_fd, _ = self.pipe()
        base = receipt()
        wide = replace(base, sample_count=(1 << 32) + 1,
                       runner_result=replace(base.runner_result, stdout_bytes=1 << 40))
        result = self.run_adapter(read_fd, lambda *_a, **_k: wide)
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(result.capture_result.sample_count, (1 << 32) + 1)
        self.assertEqual(result.capture_result.runner_result.stdout_bytes, 1 << 40)

    def test_restore_failure_does_not_skip_the_other_handler_or_free_ownership(self) -> None:
        read_fd, _ = self.pipe()
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        real_signal = signal.signal

        def restore_then_raise(signum, handler):
            previous = real_signal(signum, handler)
            if signum == signal.SIGINT and handler is before[signal.SIGINT]:
                raise OSError("private restore detail")
            return previous

        with mock.patch.object(adapter.signal, "signal", side_effect=restore_then_raise):
            result = self.run_adapter(read_fd, lambda *_a, **_k: receipt())
        self.assertEqual(result.adapter_error, "handler_restore_failed")
        self.assertFalse(result.ownership_resolved)
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})
        self.assert_closed(read_fd)

    def test_nonquiescent_watcher_is_retained_and_never_closed_by_the_caller(self) -> None:
        read_fd, _ = self.pipe()
        entered, release = threading.Event(), threading.Event()
        real_thread = threading.Thread
        threads = []

        def blocked_watch(control):
            entered.set()
            try:
                release.wait(5)
            finally:
                os.close(control.fd)
                control.closed = True

        def tracked_thread(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread

        def capture(*_a, **_k):
            self.assertTrue(entered.wait(1))
            return receipt()

        try:
            with mock.patch.object(adapter._Control, "watch", blocked_watch), \
                    mock.patch.object(adapter.threading, "Thread", side_effect=tracked_thread), \
                    mock.patch.object(adapter, "_JOIN_SECONDS", 0):
                result = self.run_adapter(read_fd, capture)
            self.assertFalse(result.watcher_quiesced or result.ownership_resolved)
            self.assertIsNotNone(adapter._retained_owner)
            os.fstat(read_fd)
        finally:
            release.set()
            for thread in threads:
                thread.join(1)
                self.assertFalse(thread.is_alive())
        self.assert_closed(read_fd)


if __name__ == "__main__":
    unittest.main()
