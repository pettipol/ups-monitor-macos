"""Synthetic policy tests. Review before executing; no hardware fixtures."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
from pathlib import Path
import selectors
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest import mock

import bounded_stream_dispatch as dispatcher
import process_deadline as runner


class VirtualDispatch:
    """Deterministic progress oracle for runner policy, not a queue test."""
    instances = []

    def __init__(self, sink, *, monotonic_clock):
        self.sink = sink
        self.clock = monotonic_clock
        self.last = None
        self.count = 0
        self.closed = False
        self.stopped = False
        self.error = None
        self.instances.append(self)

    def start(self):
        pass

    def submit(self, chunk):
        if self.sink(chunk):
            self.last = self.clock()
            self.count += 1
        return True

    def close_input(self):
        self.closed = True
        self.sink(b"")

    def request_stop(self):
        self.stopped = True

    def snapshot(self):
        return SimpleNamespace(error=self.error, last_progress_monotonic=self.last,
                               quiesced=True, queued_chunks=0)

    def join(self, timeout_seconds=2):
        return self.snapshot()


class FakePipe:
    closed = False

    def __init__(self, descriptor):
        self.descriptor = descriptor

    def fileno(self):
        return self.descriptor

    def close(self):
        self.closed = True


class ScriptedSelector:
    def __init__(self, clock, steps, stop):
        self.clock, self.steps, self.stop = clock, iter(steps), stop
        self.keys = {}
        self.pending = {}
        self.visited = []

    def register(self, pipe, events, data):
        self.keys[pipe.fileno()] = selectors.SelectorKey(pipe, pipe.fileno(), events, data)

    def unregister(self, pipe):
        return self.keys.pop(pipe.fileno())

    def get_key(self, pipe):
        return self.keys[pipe.fileno()]

    def get_map(self):
        return self.keys

    def close(self):
        pass

    def select(self, timeout):
        try:
            elapsed, stream, data = next(self.steps)
        except StopIteration:
            self.stop.set()
            return []
        self.clock[0] = elapsed
        self.visited.append(elapsed)
        if stream is None:
            return []
        descriptor = 101 if stream == "stdout" else 102
        self.pending[descriptor] = data
        return [(self.keys[descriptor], selectors.EVENT_READ)]


class StreamingPolicyTests(unittest.TestCase):
    def virtual_run(self, steps, sink=lambda data: bool(data), **budgets):
        clock = [0.0]
        stop = Event()
        process = SimpleNamespace(pid=4242, stdout=FakePipe(101), stderr=FakePipe(102))
        process.poll = mock.Mock(return_value=None)
        selector = ScriptedSelector(clock, steps, stop)

        def cleanup(child, pgid, pipes, grace):
            # Lifecycle is tested with real children in the companion file.
            process.poll.return_value = 0
            for key in list(selector.keys.values()):
                runner._unregister_and_close(key.fileobj, selector)
            pipes.eof = {"stdout": True, "stderr": True}
            pipes.dispatch.close_input()

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(dispatcher, "BoundedStreamDispatch", VirtualDispatch))
            stack.enter_context(mock.patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]))
            stack.enter_context(mock.patch.object(runner, "_verify_executable_snapshot", return_value=("/fixture", (1, 2, 3, 4, 5))))
            stack.enter_context(mock.patch.object(runner, "_assert_executable_snapshot"))
            stack.enter_context(mock.patch.object(runner, "_create_output_files", return_value=(-1, -1, -1, -1, {})))
            spawn = stack.enter_context(mock.patch.object(runner.subprocess, "Popen", return_value=process))
            stack.enter_context(mock.patch.object(runner.selectors, "DefaultSelector", return_value=selector))
            stack.enter_context(mock.patch.object(runner.os, "set_blocking"))
            stack.enter_context(mock.patch.object(runner.os, "read", side_effect=lambda fd, n: selector.pending.pop(fd)))
            stack.enter_context(mock.patch.object(runner, "_streaming_cleanup", side_effect=cleanup))
            stack.enter_context(mock.patch.object(runner, "_process_group_absent", return_value=True))
            result = runner.run_streaming(["/fixture"], executable_sha256="a" * 64,
                output_directory="/fixture/output", cancel_event=stop, on_stdout=sink, **budgets)
        self.assertEqual(spawn.call_count, 1, "one operational session must spawn exactly once")
        self.assertTrue(result.ownership_resolved)
        return result, selector

    def test_one_spawn_progress_past_120_130_and_600_seconds(self):
        steps = [(float(n), "stdout", b"valid\n") for n in range(1, 651)]
        result, selector = self.virtual_run(steps)
        self.assertEqual(result.trigger, "cancelled")
        self.assertTrue({120.0, 130.0, 600.0, 650.0}.issubset(selector.visited))

    def test_more_than_v1_lifetime_limit_in_fixed_windows(self):
        result, _ = self.virtual_run([(float(n), "stdout", b"x" * 65536) for n in range(1, 22)])
        self.assertGreater(result.stdout_bytes, 1_048_576)
        self.assertEqual(result.stdout_sha256, hashlib.sha256(b"x" * (21 * 65536)).hexdigest())
        self.assertEqual(dispatcher._QUEUE_CAPACITY, 2)
        self.assertEqual(dispatcher._MAX_CHUNK_BYTES, 65536)

    def test_combined_burst_over_rate_limit_stops(self):
        steps = [(0.1, "stdout", b"x" * 65536), (0.1, "stderr", b"x" * 65536)] * 3
        result, _ = self.virtual_run(steps)
        self.assertEqual(result.trigger, "output_rate_limit")

    def test_silent_partial_and_stderr_cannot_renew_startup(self):
        cases = [[(36.0, None, b"")],
                 [(float(n), "stdout", b"partial") for n in range(1, 37)],
                 [(float(n), "stderr", b"noise") for n in range(1, 37)]]
        for steps in cases:
            with self.subTest(steps=steps[:1]):
                result, _ = self.virtual_run(steps, sink=lambda data: False)
                self.assertEqual(result.trigger, "startup_deadline")

    def test_valid_then_stalled_progress_expires(self):
        result, _ = self.virtual_run([(1.0, "stdout", b"valid"), (17.0, None, b"")])
        self.assertEqual(result.trigger, "progress_deadline")

    def test_late_true_cannot_revive_startup_or_previous_progress(self):
        for steps, expected in (([(36.0, "stdout", b"late")], "startup_deadline"),
                                ([(1.0, "stdout", b"valid"), (17.0, "stdout", b"late")], "progress_deadline")):
            with self.subTest(expected=expected):
                result, _ = self.virtual_run(steps)
                self.assertEqual(result.trigger, expected)

    def test_valid_publication_between_snapshot_and_expiry_decision_renews_current_lease(self):
        for old, publish_at, decide_at in ((None, 34.995, 35.01), (1.0, 15.995, 16.01)):
            with self.subTest(old=old):
                event = Event()
                health = runner._StreamingHealth(lambda chunk: True, event, 35.0, 15.0)
                health.last = old
                snapshotted, renewed = Event(), Event()
                decisions, failures = [], []

                def supervisor():
                    try:
                        stale, _ = health.snapshot()
                        if stale != old:
                            raise AssertionError("regression needs the previous anchor snapshot")
                        snapshotted.set()
                        if not renewed.wait(1):
                            raise AssertionError("publication handshake did not complete")
                        decisions.append(health.check_deadline(decide_at))
                    except BaseException as error:
                        failures.append(error)

                thread = Thread(target=supervisor)
                thread.start()
                try:
                    self.assertTrue(snapshotted.wait(1))
                    with mock.patch.object(runner.time, "monotonic", return_value=publish_at):
                        self.assertTrue(health.accept(b"valid"))
                    renewed.set()
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(failures, [])
                    self.assertEqual(decisions, [(publish_at + 15.0, None)])
                    self.assertFalse(event.is_set(), "an old lease snapshot must not expire a renewed lease")
                finally:
                    renewed.set()
                    thread.join(2)

    def test_expiry_decision_latches_before_any_later_renewal(self):
        event = Event()
        health = runner._StreamingHealth(lambda chunk: True, event, 35.0, 15.0)
        health.last = 1.0
        self.assertEqual(health.check_deadline(16.0), (16.0, "progress_deadline"))
        # Even clearing the caller's event cannot clear the terminal latch.
        event.clear()
        with mock.patch.object(runner.time, "monotonic", return_value=16.01):
            self.assertFalse(health.accept(b"too late"))
        self.assertEqual(health.snapshot(), (1.0, "progress_deadline"))
        self.assertTrue(event.is_set())

    def test_stop_between_callback_clock_and_state_update_does_not_renew(self):
        event = Event()
        health = runner._StreamingHealth(lambda chunk: True, event, 35.0, 15.0)

        def stopped_clock():
            event.set()
            return 36.0

        with mock.patch.object(runner.time, "monotonic", side_effect=stopped_clock):
            self.assertTrue(health.accept(b"terminal allowed after stop"))
        self.assertEqual(health.snapshot(), (None, None), "Stop must not renew or manufacture health expiry")

    def test_constructor_faults_release_reservation_before_new_admission(self):
        for module, name in ((runner, "_StreamingHealth"), (dispatcher, "BoundedStreamDispatch"),
                             (runner, "_StreamingClock")):
            with self.subTest(constructor=name):
                event = Event()
                with mock.patch.object(module, name, side_effect=RuntimeError("synthetic constructor fault")), \
                     mock.patch.object(runner.subprocess, "Popen") as spawn:
                    with self.assertRaises(runner._StreamingFailure):
                        runner.run_streaming(["/fixture"], executable_sha256="a" * 64,
                            output_directory="/fixture/output", cancel_event=event,
                            on_stdout=lambda chunk: False)
                    spawn.assert_not_called()
                self.assertIsNone(runner.retained_streaming_ownership())
                # A complete subsequent virtual session proves new admission,
                # not merely an unlocked marker observed by this test.
                result, _ = self.virtual_run([(1.0, "stdout", b"valid")])
                self.assertTrue(result.ownership_resolved)

    def test_clock_regression_latches_fixed_failure(self):
        result, _ = self.virtual_run([(1.0, "stdout", b"valid"), (0.5, None, b"")])
        self.assertEqual(result.trigger, "clock_regression")

    def test_preset_cancellation_does_not_admit_or_spawn(self):
        stop = Event()
        stop.set()
        with mock.patch.object(runner.subprocess, "Popen") as spawn, \
             mock.patch.object(runner, "_create_output_files") as output:
            result = runner.run_streaming(["/fixture"], executable_sha256="a" * 64,
                output_directory="/fixture/output", cancel_event=stop, on_stdout=lambda chunk: False)
        self.assertTrue(result.ownership_resolved)
        spawn.assert_not_called()
        output.assert_not_called()

    def test_600_second_phase_limit_and_two_second_grace_are_closed(self):
        for options in ({"startup_timeout_seconds": 601}, {"progress_timeout_seconds": 601},
                        {"termination_grace_seconds": 2.01}, {"progress_timeout_seconds": 0},
                        {"startup_timeout_seconds": float("nan")}):
            with self.subTest(options=options), self.assertRaises(runner.BoundedRunError):
                runner.run_streaming(["/fixture"], executable_sha256="a" * 64,
                    output_directory="/fixture/output", cancel_event=Event(), on_stdout=lambda chunk: False,
                    **options)

    def test_counter_overflow_does_not_grow_counter(self):
        dispatch = VirtualDispatch(lambda data: True, monotonic_clock=lambda: 0.0)
        selector = mock.Mock()
        pipe = FakePipe(101)
        selector.select.return_value = [(selectors.SelectorKey(pipe, 101, 1, "stdout"), 1)]
        clock = runner._StreamingClock()
        state = runner._StreamingPipes(selector, dispatch, Event(), clock, 0.0)
        state.counts["stdout"] = runner._STREAM_MAX_COUNTER
        with mock.patch.object(runner.os, "read", return_value=b"x"), \
             mock.patch.object(runner.time, "monotonic", return_value=0.0):
            state.consume(0)
        self.assertEqual(state.counts["stdout"], runner._STREAM_MAX_COUNTER)
        self.assertEqual(state.failure, "output_counter_overflow")

    def test_exited_leader_live_descendant_uses_saved_group(self):
        child = SimpleNamespace(poll=lambda: 0)
        dispatch = VirtualDispatch(lambda chunk: False, monotonic_clock=lambda: 0)
        selector = mock.Mock()
        selector.get_map.return_value = {}
        state = runner._StreamingPipes(selector, dispatch, Event(), runner._StreamingClock(), 0)
        group_gone = [False]

        def signal_owned(process, sig, pgid):
            self.assertIs(process, child)
            self.assertEqual(pgid, 4242)
            self.assertEqual(sig, runner.signal.SIGTERM)
            group_gone[0] = True

        with mock.patch.object(runner, "_process_group_absent", side_effect=lambda pgid: group_gone[0]), \
             mock.patch.object(runner, "_signal_child", side_effect=signal_owned) as signals, \
             mock.patch.object(runner.os, "getpgid", side_effect=AssertionError("must not rediscover PGID")):
            runner._streaming_cleanup(child, 4242, state, 0.01)
        self.assertEqual(signals.call_count, 1)

    def test_held_open_pipe_is_not_eof_even_after_leader_reap(self):
        child = SimpleNamespace(poll=lambda: 0)
        dispatch = VirtualDispatch(lambda chunk: False, monotonic_clock=lambda: 0)
        selector = mock.Mock()
        selector.get_map.return_value = {101: object()}
        selector.select.return_value = []
        state = runner._StreamingPipes(selector, dispatch, Event(), runner._StreamingClock(), 0)
        # Deterministic elapsed final-drain budget, without sleeping or a child.
        with mock.patch.object(runner, "_process_group_absent", return_value=True), \
             mock.patch.object(runner.time, "perf_counter", side_effect=[0.0, 0.2]):
            runner._streaming_cleanup(child, 4242, state, 0.01)
        self.assertFalse(state.eof["stdout"])
        self.assertFalse(state.eof["stderr"])
        self.assertEqual(state.failure, "output_incomplete")

    def test_marker_only_retention_does_not_release_real_missing_eof(self):
        dispatch = VirtualDispatch(lambda chunk: False, monotonic_clock=lambda: 0)
        selector = mock.Mock()
        selector.select.return_value = []
        state = runner._StreamingPipes(selector, dispatch, Event(), runner._StreamingClock(), 0)
        child = SimpleNamespace(poll=lambda: 0)
        previous = runner.StreamingRunResult("output_incomplete", 0, 0, 0, "a" * 64, "b" * 64,
                                             True, True, False, False, True)
        owner = (child, 4242, dispatch, state, previous)
        with mock.patch.object(runner, "_retained_streaming_owner", owner), \
             mock.patch.object(runner, "_process_group_absent", return_value=True):
            observed = runner.retained_streaming_ownership()
            self.assertFalse(observed.ownership_resolved)
            self.assertIs(runner._retained_streaming_owner, owner)


if __name__ == "__main__":
    unittest.main()
