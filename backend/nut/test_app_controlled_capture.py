from __future__ import annotations

import errno
from dataclasses import replace
import os
import signal
import threading
import unittest
from unittest import mock

import app_controlled_capture as adapter
from continuous_capture import CaptureResult


def receipt(*, status: str = "exited", reason: str = "duration_complete",
            quiesced: bool = True) -> CaptureResult:
    return CaptureResult(
        "stopped" if reason == "duration_complete" else "failed", reason,
        "synthetic-source", "synthetic-session", 0, 1, 0, reason, 0,
        status, 0, 0, None, quiesced,
    )


class AppControlledCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = adapter.FixedCaptureProfile(("/synthetic/producer", "fixed"), "a" * 64)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(adapter, "_active", False).start()
        mock.patch.object(adapter, "_retained", False).start()

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
        # Only the write endpoint stays owned by this test after admission.
        return read_fd, write_fd

    def run_adapter(self, fd: int, capture):
        return adapter.run_app_controlled(
            self.profile, control_read_fd=fd, output_root="synthetic-output",
            feed_directory="synthetic-feed", source_id="synthetic-source", capture=capture,
        )

    def cancelled_capture(self, *_args, **kwargs) -> CaptureResult:
        if not kwargs["cancel_event"].wait(1):
            raise AssertionError("control request did not reach the bounded capture")
        return receipt(status="cancelled", reason="cancelled")

    def assert_closed(self, fd: int) -> None:
        with self.assertRaises(OSError) as closed:
            os.fstat(fd)
        self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_stop_delivers_cancellation_and_preserves_capture_receipt(self) -> None:
        read_fd, write_fd = self.pipe()
        os.write(write_fd, b"STOP\n")
        result = self.run_adapter(read_fd, self.cancelled_capture)
        self.assertEqual(result.control_reason, "stop")
        self.assertIsNone(result.adapter_error)
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(result.capture_result.terminal_reason, "cancelled")
        self.assertEqual(result.capture_result.state, "failed")
        self.assert_closed(read_fd)

    def test_eof_requests_cancellation_for_lost_app(self) -> None:
        read_fd, write_fd = self.pipe()
        os.close(write_fd)
        result = self.run_adapter(read_fd, self.cancelled_capture)
        self.assertEqual(result.control_reason, "app_disconnected")
        self.assertTrue(result.ownership_resolved)

    def test_malformed_partial_and_oversized_commands_fail_closed(self) -> None:
        for data in (b"stop\n", b"S", b"\n", b"X" * 4096):
            with self.subTest(data=data[:6]), mock.patch.object(adapter, "_retained", False):
                read_fd, write_fd = self.pipe()
                os.write(write_fd, data)
                os.close(write_fd)
                result = self.run_adapter(read_fd, self.cancelled_capture)
                self.assertEqual(result.adapter_error, "invalid_control")
                self.assertFalse(result.ownership_resolved)
                self.assertEqual(result.capture_result.terminal_reason, "cancelled")

    def test_fragmented_exact_stop_is_accepted(self) -> None:
        read_fd, write_fd = self.pipe()
        real_read = os.read

        def single_byte(fd, count):
            return real_read(fd, min(count, 1))

        os.write(write_fd, b"STOP\n")
        with mock.patch.object(adapter.os, "read", side_effect=single_byte):
            result = self.run_adapter(read_fd, self.cancelled_capture)
        self.assertEqual(result.control_reason, "stop")
        self.assertTrue(result.ownership_resolved)

    def test_stop_frame_with_surplus_is_independent_of_read_fragmentation(self) -> None:
        real_read = os.read
        for chunk_size in (1, 4096):
            with self.subTest(chunk_size=chunk_size):
                read_fd, write_fd = self.pipe()
                os.write(write_fd, b"STOP\nX")

                def fragmented_read(fd, count):
                    return real_read(fd, min(count, chunk_size))

                with mock.patch.object(adapter.os, "read", side_effect=fragmented_read):
                    result = self.run_adapter(read_fd, self.cancelled_capture)
                self.assertEqual(result.control_reason, "stop")
                self.assertIsNone(result.adapter_error)
                self.assertTrue(result.ownership_resolved)

    def test_normal_completion_closes_reader_without_waiting_for_app_eof(self) -> None:
        read_fd, _ = self.pipe()
        original = receipt()
        result = self.run_adapter(read_fd, lambda *_a, **_k: original)
        self.assertIs(result.capture_result, original)
        self.assertIsNone(result.control_reason)
        self.assertTrue(result.watcher_quiesced)
        self.assertTrue(result.ownership_resolved)
        self.assert_closed(read_fd)

    def test_fixed_limits_and_noninheritable_read_end_are_forwarded(self) -> None:
        read_fd, _ = self.pipe()
        observed = {}

        def capture(argv, **kwargs):
            observed.update(kwargs)
            self.assertEqual(argv, self.profile.argv)
            self.assertFalse(os.get_inheritable(read_fd))
            self.assertFalse(os.get_blocking(read_fd))
            return receipt()

        result = self.run_adapter(read_fd, capture)
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(observed["timeout_seconds"], 135.0)
        self.assertEqual(observed["termination_grace_seconds"], 2.0)
        self.assertEqual(observed["expected_elapsed_ms"], 120_000)
        self.assertEqual(observed["maximum_output_bytes"], 1_048_576)
        self.assertEqual(observed["join_seconds"], 2.0)

    def test_recursive_start_rejected_before_descriptor_transfer(self) -> None:
        read_fd, _ = self.pipe()
        inner_fd, _ = self.pipe()
        try:
            def capture(*_a, **_k):
                with self.assertRaisesRegex(adapter.AppCaptureAdmissionError, "session_ownership_unresolved"):
                    self.run_adapter(inner_fd, lambda *_a, **_k: receipt())
                os.fstat(inner_fd)
                return receipt()

            self.assertTrue(self.run_adapter(read_fd, capture).ownership_resolved)
        finally:
            os.close(inner_fd)

    def test_explicit_later_start_permitted_after_resolved_receipt(self) -> None:
        for _ in range(2):
            read_fd, _ = self.pipe()
            self.assertTrue(self.run_adapter(read_fd, lambda *_a, **_k: receipt()).ownership_resolved)

    def test_unreaped_is_preserved_and_new_start_is_refused(self) -> None:
        read_fd, _ = self.pipe()
        original = receipt(status="unreaped", reason="child_unreaped")
        result = self.run_adapter(read_fd, lambda *_a, **_k: original)
        self.assertIs(result.capture_result, original)
        self.assertFalse(result.ownership_resolved)
        second_fd, _ = self.pipe()
        try:
            with self.assertRaisesRegex(adapter.AppCaptureAdmissionError, "session_ownership_unresolved"):
                self.run_adapter(second_fd, lambda *_a, **_k: receipt())
            os.fstat(second_fd)
        finally:
            os.close(second_fd)

    def test_live_tailer_receipt_retains_ownership(self) -> None:
        read_fd, _ = self.pipe()
        result = self.run_adapter(read_fd, lambda *_a, **_k: receipt(quiesced=False))
        self.assertFalse(result.ownership_resolved)

    def test_publication_failure_retains_ownership_even_with_quiesced_flag(self) -> None:
        read_fd, _ = self.pipe()
        original = replace(
            receipt(status="exited", quiesced=True), state="failed",
            terminal_reason="io_error", publication_error="publication_failed",
        )
        result = self.run_adapter(read_fd, lambda *_a, **_k: original)
        self.assertIs(result.capture_result, original)
        self.assertFalse(result.ownership_resolved)
        self.assertTrue(adapter._retained)

    def test_capture_exception_is_private_and_retains_ownership(self) -> None:
        read_fd, _ = self.pipe()

        def failing_capture(*_a, **_k):
            raise RuntimeError("synthetic sensitive error text")

        result = self.run_adapter(read_fd, failing_capture)
        self.assertEqual(result.adapter_error, "capture_failed")
        self.assertNotIn("sensitive", repr(result))
        self.assertFalse(result.ownership_resolved)
        self.assertTrue(result.watcher_quiesced)
        self.assert_closed(read_fd)

    def test_invalid_capture_receipt_retains_ownership(self) -> None:
        read_fd, _ = self.pipe()
        result = self.run_adapter(read_fd, lambda *_a, **_k: object())
        self.assertEqual(result.adapter_error, "invalid_capture_receipt")
        self.assertFalse(result.ownership_resolved)

    def test_control_worker_exception_cancels_capture_and_retains_failure(self) -> None:
        read_fd, _ = self.pipe()
        with mock.patch.object(adapter.select, "select", side_effect=OSError("synthetic detail")):
            result = self.run_adapter(read_fd, self.cancelled_capture)
        self.assertEqual(result.adapter_error, "control_failed")
        self.assertFalse(result.ownership_resolved)
        self.assertTrue(result.watcher_quiesced)
        self.assert_closed(read_fd)

    def test_signal_cancellation_and_original_handlers_restored(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum):
                read_fd, _ = self.pipe()
                before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

                def capture(*_args, **kwargs):
                    signal.getsignal(signum)(signum, None)
                    return self.cancelled_capture(**kwargs)

                result = self.run_adapter(read_fd, capture)
                self.assertEqual(result.control_reason, "signal")
                self.assertTrue(result.ownership_resolved)
                self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})

    def test_handlers_restored_after_capture_exception(self) -> None:
        read_fd, _ = self.pipe()
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

        def failing_capture(*_a, **_k):
            raise ValueError("synthetic")

        self.run_adapter(read_fd, failing_capture)
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})

    def test_setup_failure_closes_owned_fd_and_restores_partial_handlers(self) -> None:
        read_fd, _ = self.pipe()
        before = signal.getsignal(signal.SIGINT)
        real_signal = signal.signal

        def fail_term(signum, handler):
            if signum == signal.SIGTERM:
                raise OSError("synthetic")
            return real_signal(signum, handler)

        with mock.patch.object(adapter.signal, "signal", side_effect=fail_term):
            result = self.run_adapter(read_fd, lambda *_a, **_k: receipt())
        self.assertEqual(result.adapter_error, "adapter_setup_failed")
        self.assertEqual(signal.getsignal(signal.SIGINT), before)
        self.assertFalse(result.ownership_resolved)
        self.assert_closed(read_fd)

    def test_blocked_writer_released_by_reader_cleanup_without_drain(self) -> None:
        read_fd, write_fd = self.pipe()
        os.set_blocking(write_fd, False)
        while True:
            try:
                os.write(write_fd, b"X" * 4096)
            except BlockingIOError:
                break
        os.set_blocking(write_fd, True)
        writer_started, writer_finished = threading.Event(), threading.Event()
        errors = []

        def write_blocked():
            writer_started.set()
            try:
                os.write(write_fd, b"X" * 4096)
            except BrokenPipeError:
                errors.append("broken_pipe")
            finally:
                writer_finished.set()

        writer = threading.Thread(target=write_blocked, daemon=False)
        writer.start()
        self.assertTrue(writer_started.wait(1))
        try:
            result = self.run_adapter(read_fd, self.cancelled_capture)
            self.assertTrue(writer_finished.wait(1))
            self.assertEqual(errors, ["broken_pipe"])
            self.assertEqual(result.adapter_error, "invalid_control")
            self.assertFalse(result.ownership_resolved)
        finally:
            writer.join(1)
        self.assertFalse(writer.is_alive(), "owned writer thread did not quiesce")

    def test_setup_close_exception_still_restores_handlers_and_retains_latch(self) -> None:
        read_fd, _ = self.pipe()
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        real_signal, real_close = signal.signal, os.close

        def fail_term(signum, handler):
            if signum == signal.SIGTERM:
                raise OSError("synthetic setup failure")
            return real_signal(signum, handler)

        def close_then_raise(fd):
            real_close(fd)
            raise RuntimeError("synthetic close failure")

        with mock.patch.object(adapter.signal, "signal", side_effect=fail_term), \
                mock.patch.object(adapter.os, "close", side_effect=close_then_raise):
            result = self.run_adapter(read_fd, lambda *_a, **_k: receipt())
        self.assertEqual(result.adapter_error, "control_close_failed")
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})
        self.assertFalse(adapter._active)
        self.assertTrue(adapter._retained)
        self.assertFalse(result.ownership_resolved)

    def test_handler_restore_exception_does_not_skip_other_handler_or_latch(self) -> None:
        read_fd, _ = self.pipe()
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        real_signal = signal.signal

        def restore_then_raise(signum, handler):
            value = real_signal(signum, handler)
            if signum == signal.SIGINT and handler is before[signal.SIGINT]:
                raise RuntimeError("synthetic restore failure")
            return value

        with mock.patch.object(adapter.signal, "signal", side_effect=restore_then_raise):
            result = self.run_adapter(read_fd, lambda *_a, **_k: receipt())
        self.assertEqual(result.adapter_error, "handler_restore_failed")
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})
        self.assertFalse(adapter._active)
        self.assertTrue(adapter._retained)
        self.assertFalse(result.ownership_resolved)

    def test_nonquiescent_watcher_fd_is_not_closed_by_caller(self) -> None:
        read_fd, _ = self.pipe()
        real_thread = threading.Thread
        release, entered = threading.Event(), threading.Event()
        owned_threads = []

        def blocked_watch(control):
            entered.set()
            release.wait(1)
            os.close(control.fd)

        def tracked_thread(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            owned_threads.append(thread)
            return thread

        def capture(*_a, **_k):
            if not entered.wait(1):
                raise AssertionError("watcher not started")
            return receipt()

        try:
            with mock.patch.object(adapter._Control, "watch", blocked_watch), \
                    mock.patch.object(adapter.threading, "Thread", side_effect=tracked_thread), \
                    mock.patch.object(adapter, "_JOIN_SECONDS", 0):
                result = self.run_adapter(read_fd, capture)
            self.assertFalse(result.watcher_quiesced)
            self.assertFalse(result.ownership_resolved)
            os.fstat(read_fd)  # The live watcher still owns this descriptor.
        finally:
            release.set()
            for thread in owned_threads:
                thread.join(1)
        self.assert_closed(read_fd)

    def test_off_main_thread_is_rejected_without_descriptor_transfer(self) -> None:
        read_fd, _ = self.pipe()
        errors = []

        def call():
            try:
                self.run_adapter(read_fd, lambda *_a, **_k: receipt())
            except adapter.AppCaptureAdmissionError as error:
                errors.append(error.code)

        thread = threading.Thread(target=call)
        thread.start()
        thread.join(1)
        try:
            self.assertEqual(errors, ["main_thread_required"])
            os.fstat(read_fd)
        finally:
            os.close(read_fd)

    def test_invalid_profile_api_rejection_preserves_caller_read_fd(self) -> None:
        read_fd, _ = self.pipe()
        try:
            with self.assertRaises(adapter.AppCaptureAdmissionError) as rejected:
                adapter.run_app_controlled(
                    object(), control_read_fd=read_fd, output_root="synthetic-output",
                    feed_directory="synthetic-feed", source_id="synthetic-source",
                )
            self.assertEqual(rejected.exception.code, "invalid_fixed_profile")
            os.fstat(read_fd)
            self.assertFalse(adapter._active)
        finally:
            os.close(read_fd)

    def test_unexpected_admission_failure_preserves_caller_read_fd(self) -> None:
        read_fd, _ = self.pipe()
        try:
            with mock.patch.object(adapter.os, "fstat", side_effect=KeyboardInterrupt):
                with self.assertRaises(adapter.AppCaptureAdmissionError) as rejected:
                    self.run_adapter(read_fd, lambda *_a, **_k: receipt())
            self.assertEqual(rejected.exception.code, "admission_failed")
            os.fstat(read_fd)
            self.assertFalse(adapter._active)
        finally:
            os.close(read_fd)

    def test_wrong_pipe_endpoint_rejection_preserves_caller_fds(self) -> None:
        read_fd, write_fd = self.pipe()
        try:
            with self.assertRaises(adapter.AppCaptureAdmissionError) as rejected:
                self.run_adapter(write_fd, lambda *_a, **_k: receipt())
            self.assertEqual(rejected.exception.code, "invalid_control_pipe")
            os.fstat(read_fd)
            os.fstat(write_fd)
        finally:
            os.close(read_fd)

    def test_profiles_are_immutable_and_reject_mutable_argv(self) -> None:
        with self.assertRaises(ValueError):
            adapter.FixedCaptureProfile(["/synthetic/producer"], "a" * 64)
        with self.assertRaises(AttributeError):
            self.profile.argv = ("/synthetic/other",)


if __name__ == "__main__":
    unittest.main()
