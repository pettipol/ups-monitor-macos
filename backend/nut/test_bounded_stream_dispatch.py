from __future__ import annotations

import math
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from bounded_stream_dispatch import BoundedStreamDispatch


class BoundedStreamDispatchTests(unittest.TestCase):
    @contextmanager
    def running(self, sink, *, clock=None, releases=()):
        kwargs = {} if clock is None else {"monotonic_clock": clock}
        dispatcher = BoundedStreamDispatch(sink, **kwargs)
        try:
            dispatcher.start()
            yield dispatcher
        finally:
            for event in releases:
                event.set()
            dispatcher.request_stop()
            state = dispatcher.join(2.0)
            self.assertTrue(state.quiesced, "test-owned dispatcher worker leaked")

    def test_fifo_exact_chunk_capacity_and_eof_after_drain(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        calls: list[bytes] = []

        def sink(data: bytes) -> bool:
            calls.append(data)
            if data == b"first":
                entered.set()
                if not release.wait(1.0):
                    raise RuntimeError("test release timed out")
            return True

        with self.running(sink, releases=(release,)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"first"))
            self.assertTrue(entered.wait(1.0))
            self.assertTrue(dispatcher.submit(b"x" * 65_536))
            self.assertTrue(dispatcher.submit(b"third"))
            self.assertEqual(dispatcher.snapshot().queued_chunks, 2)
            release.set()
            dispatcher.close_input()
            dispatcher.close_input()
            state = dispatcher.join(1.0)
            self.assertTrue(state.quiesced)
            self.assertEqual(calls, [b"first", b"x" * 65_536, b"third", b""])
            self.assertTrue(state.eof_delivered)
            self.assertEqual(state.accepted_progress_count, 3)

    def test_queue_full_latches_first_error_drops_queue_and_never_calls_submitter(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        calls: list[bytes] = []

        def sink(data: bytes) -> bool:
            calls.append(data)
            if data == b"inflight":
                entered.set()
                if not release.wait(1.0):
                    raise RuntimeError("test release timed out")
            return True

        with self.running(sink, releases=(release,)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"inflight"))
            self.assertTrue(entered.wait(1.0))
            self.assertTrue(dispatcher.submit(b"queued-1"))
            self.assertTrue(dispatcher.submit(b"queued-2"))
            self.assertFalse(dispatcher.submit(b"overflow"))
            state = dispatcher.snapshot()
            self.assertEqual(state.error, "consumer_backpressure")
            self.assertTrue(state.stop_requested)
            self.assertEqual(state.queued_chunks, 0)
            self.assertEqual(calls, [b"inflight"])
            release.set()
            self.assertTrue(dispatcher.join(1.0).quiesced)
            self.assertEqual(calls, [b"inflight"])

    def test_oversized_input_aborts_and_invalid_type_is_argument_error(self) -> None:
        with self.running(lambda _data: True) as dispatcher:
            with self.assertRaises(TypeError):
                dispatcher.submit(bytearray(b"x"))  # type: ignore[arg-type]
            self.assertFalse(dispatcher.submit(b"x" * 65_537))
            state = dispatcher.join(1.0)
            self.assertEqual(state.error, "chunk_limit")
            self.assertTrue(state.stop_requested)
            self.assertEqual(state.queued_chunks, 0)

    def test_sink_invalid_return_or_exception_is_fixed_consumer_error(self) -> None:
        sinks = (
            lambda _data: 1,
            lambda _data: (_ for _ in ()).throw(RuntimeError("private")),
            lambda _data: (_ for _ in ()).throw(SystemExit("private")),
        )
        for sink in sinks:
            with self.subTest(sink=sink):
                with self.running(sink) as dispatcher:
                    self.assertTrue(dispatcher.submit(b"sample"))
                    state = dispatcher.join(1.0)
                    self.assertEqual(state.error, "consumer_error")
                    self.assertTrue(state.stop_requested)
                    self.assertEqual(state.accepted_progress_count, 0)
                    self.assertFalse(dispatcher.submit(b"after-error"))

    def test_false_return_does_not_renew_progress_and_equal_clock_is_allowed(self) -> None:
        values = iter((4.0, 4.0))
        calls: list[bytes] = []

        def sink(data: bytes) -> bool:
            calls.append(data)
            return data != b"partial"

        with self.running(sink, clock=lambda: next(values)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"partial"))
            self.assertTrue(dispatcher.submit(b"accepted"))
            dispatcher.close_input()
            state = dispatcher.join(1.0)
            self.assertEqual(calls, [b"partial", b"accepted", b""])
            self.assertIsNone(state.error)
            self.assertEqual(state.accepted_progress_count, 1)
            self.assertEqual(state.last_progress_monotonic, 4.0)

    def test_eof_false_is_delivered_once_and_never_renews_progress(self) -> None:
        calls: list[bytes] = []

        def sink(data: bytes) -> bool:
            calls.append(data)
            return False

        with self.running(sink) as dispatcher:
            self.assertTrue(dispatcher.submit(b"data"))
            dispatcher.close_input()
            state = dispatcher.join(1.0)
            self.assertEqual(calls, [b"data", b""])
            self.assertTrue(state.eof_delivered)
            self.assertEqual(state.accepted_progress_count, 0)
            self.assertIsNone(state.last_progress_monotonic)

    def test_invalid_clock_latches_fixed_error(self) -> None:
        for value in (math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value):
                with self.running(lambda _data: True, clock=lambda: value) as dispatcher:
                    self.assertTrue(dispatcher.submit(b"accepted"))
                    state = dispatcher.join(1.0)
                    self.assertEqual(state.error, "clock_invalid")
                    self.assertTrue(state.stop_requested)
                    self.assertEqual(state.accepted_progress_count, 0)

    def test_regressing_clock_latches_error(self) -> None:
        values = iter((5.0, 4.0))
        with self.running(lambda _data: True, clock=lambda: next(values)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"one"))
            self.assertTrue(dispatcher.submit(b"two"))
            state = dispatcher.join(1.0)
            self.assertEqual(state.error, "clock_regression")
            self.assertEqual(state.accepted_progress_count, 1)

    def test_stop_while_sink_blocked_has_no_post_stop_progress(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def sink(_data: bytes) -> bool:
            entered.set()
            if not release.wait(1.0):
                raise RuntimeError("test release timed out")
            return True

        with self.running(sink, releases=(release,)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"sample"))
            self.assertTrue(entered.wait(1.0))
            dispatcher.request_stop()
            blocked = dispatcher.join(0.0)
            self.assertFalse(blocked.quiesced)
            self.assertTrue(blocked.stop_requested)
            self.assertEqual(blocked.accepted_progress_count, 0)
            release.set()
            final = dispatcher.join(1.0)
            self.assertTrue(final.quiesced)
            self.assertEqual(final.accepted_progress_count, 0)

    def test_stop_while_clock_blocked_has_no_post_stop_progress(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def clock() -> float:
            entered.set()
            if not release.wait(1.0):
                raise RuntimeError("test release timed out")
            return 7.0

        with self.running(lambda _data: True, clock=clock, releases=(release,)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"sample"))
            self.assertTrue(entered.wait(1.0))
            dispatcher.request_stop()
            blocked = dispatcher.join(0.0)
            self.assertFalse(blocked.quiesced)
            release.set()
            final = dispatcher.join(1.0)
            self.assertTrue(final.quiesced)
            self.assertEqual(final.accepted_progress_count, 0)

    def test_close_submit_race_uses_two_party_timed_barrier_and_cleanup(self) -> None:
        dispatcher = BoundedStreamDispatch(lambda _data: True)
        barrier = threading.Barrier(2)
        results: list[bool] = []

        def submitter() -> None:
            try:
                barrier.wait(timeout=1.0)
                results.append(dispatcher.submit(b"racing"))
            except threading.BrokenBarrierError:
                return

        thread = threading.Thread(target=submitter)
        try:
            dispatcher.start()
            thread.start()
            barrier.wait(timeout=1.0)
            dispatcher.close_input()
            thread.join(1.0)
            self.assertFalse(thread.is_alive())
            state = dispatcher.join(1.0)
            self.assertTrue(state.quiesced)
            self.assertTrue(state.eof_delivered)
            self.assertIn(results, ([True], [False]))
            self.assertFalse(dispatcher.submit(b"after-close"))
        finally:
            barrier.abort()
            dispatcher.request_stop()
            thread.join(1.0)
            state = dispatcher.join(2.0)
            self.assertTrue(state.quiesced, "test-owned dispatcher worker leaked")
            self.assertFalse(thread.is_alive(), "test submitter thread leaked")

    def test_callback_failure_after_backpressure_preserves_first_error(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def sink(data: bytes) -> bool:
            if data == b"inflight":
                entered.set()
                if not release.wait(1.0):
                    raise RuntimeError("test release timed out")
                raise SystemExit("private")
            return True

        with self.running(sink, releases=(release,)) as dispatcher:
            self.assertTrue(dispatcher.submit(b"inflight"))
            self.assertTrue(entered.wait(1.0))
            self.assertTrue(dispatcher.submit(b"queued-1"))
            self.assertTrue(dispatcher.submit(b"queued-2"))
            self.assertFalse(dispatcher.submit(b"full"))
            release.set()
            state = dispatcher.join(1.0)
            self.assertTrue(state.quiesced)
            self.assertEqual(state.error, "consumer_backpressure")
            self.assertEqual(state.queued_chunks, 0)

    def test_start_once_before_start_errors_stop_idempotence_and_join_validation(self) -> None:
        dispatcher = BoundedStreamDispatch(lambda _data: True)
        with self.assertRaisesRegex(RuntimeError, "not_started"):
            dispatcher.submit(b"early")
        initial = dispatcher.snapshot()
        self.assertTrue(initial.quiesced)
        self.assertFalse(initial.started)
        self.assertTrue(dispatcher.join(0.0).quiesced)
        try:
            dispatcher.start()
            with self.assertRaisesRegex(RuntimeError, "already_started"):
                dispatcher.start()
            dispatcher.request_stop()
            dispatcher.request_stop()
            self.assertFalse(dispatcher.submit(b"stopped"))
            self.assertTrue(dispatcher.join(1.0).quiesced)
            for invalid in (True, -0.1, 2.1, math.inf, math.nan):
                with self.subTest(timeout=invalid):
                    with self.assertRaises(ValueError):
                        dispatcher.join(invalid)
        finally:
            dispatcher.request_stop()
            self.assertTrue(dispatcher.join(2.0).quiesced)

    def test_start_failure_is_latched_and_not_retried(self) -> None:
        dispatcher = BoundedStreamDispatch(lambda _data: True)
        try:
            with patch.object(threading.Thread, "start", side_effect=RuntimeError("start failure")):
                dispatcher.start()
            state = dispatcher.snapshot()
            self.assertEqual(state.error, "worker_start_failed")
            self.assertTrue(state.quiesced)
            self.assertFalse(state.started)
            with self.assertRaisesRegex(RuntimeError, "already_started"):
                dispatcher.start()
            self.assertEqual(dispatcher.join(1.0).error, "worker_start_failed")
        finally:
            dispatcher.request_stop()
            self.assertTrue(dispatcher.join(2.0).quiesced)

    def test_start_is_outside_state_lock_and_join_zero_does_not_join_unstarted_thread(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        call_start = threading.Event()
        original_start = threading.Thread.start

        def delayed_start(thread: threading.Thread) -> None:
            entered.set()
            if not release.wait(1.0):
                raise RuntimeError("test release timed out")
            original_start(thread)

        dispatcher = BoundedStreamDispatch(lambda _data: True)
        def start_after_patch() -> None:
            if call_start.wait(1.0):
                dispatcher.start()

        starter = threading.Thread(target=start_after_patch)
        try:
            starter.start()
            with patch.object(threading.Thread, "start", delayed_start):
                call_start.set()
                self.assertTrue(entered.wait(1.0))
                state = dispatcher.join(0.0)
                self.assertFalse(state.quiesced)
                self.assertFalse(state.started)
                self.assertFalse(dispatcher.snapshot().quiesced)
                dispatcher.request_stop()
                release.set()
                starter.join(1.0)
                self.assertFalse(starter.is_alive())
                self.assertTrue(dispatcher.join(1.0).quiesced)
        finally:
            call_start.set()
            release.set()
            dispatcher.request_stop()
            starter.join(1.0)
            state = dispatcher.join(2.0)
            self.assertTrue(state.quiesced, "test-owned dispatcher worker leaked")
            self.assertFalse(starter.is_alive(), "test starter thread leaked")

    def test_start_exception_after_worker_exit_preserves_quiescence(self) -> None:
        dispatcher = BoundedStreamDispatch(lambda _data: True)
        original_start = threading.Thread.start
        original_join = threading.Thread.join
        workers: list[threading.Thread] = []
        terminated_before_raise = threading.Event()

        def start_then_exit_then_raise(worker: threading.Thread) -> None:
            workers.append(worker)
            original_start(worker)
            original_join(worker, 1.0)
            if not worker.is_alive():
                terminated_before_raise.set()
            raise RuntimeError("start raised after worker exit")

        try:
            dispatcher.request_stop()
            with patch.object(threading.Thread, "start", start_then_exit_then_raise):
                dispatcher.start()
            self.assertTrue(terminated_before_raise.is_set(), "worker must exit before start raises")
            self.assertEqual(len(workers), 1)
            state = dispatcher.snapshot()
            self.assertTrue(state.started)
            self.assertTrue(state.quiesced, "start failure must preserve the worker finally's proof")
            self.assertTrue(state.stop_requested)
            self.assertEqual(state.error, "worker_start_failed")
            self.assertFalse(dispatcher.submit(b"after-error"))
            with self.assertRaisesRegex(RuntimeError, "already_started"):
                dispatcher.start()
            self.assertTrue(dispatcher.join(1.0).quiesced)
            self.assertEqual(len(workers), 1, "start failure must not trigger a retry")
        finally:
            dispatcher.request_stop()
            for worker in workers:
                if worker.ident is not None:
                    original_join(worker, 2.0)
                    self.assertFalse(worker.is_alive(), "test-owned worker thread leaked")
            self.assertTrue(dispatcher.join(2.0).quiesced, "test-owned dispatcher worker leaked")

    def test_baseexception_from_clock_latches_and_stops_worker(self) -> None:
        with self.running(
            lambda _data: True,
            clock=lambda: (_ for _ in ()).throw(SystemExit("private")),
        ) as dispatcher:
            self.assertTrue(dispatcher.submit(b"sample"))
            state = dispatcher.join(1.0)
            self.assertEqual(state.error, "clock_invalid")
            self.assertTrue(state.stop_requested)
            self.assertTrue(state.quiesced)
            self.assertFalse(dispatcher.submit(b"after-error"))


if __name__ == "__main__":
    unittest.main()
