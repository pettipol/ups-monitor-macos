"""Synthetic lifecycle tests: no child, native library, build or USB access."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from threading import Event, Thread, get_ident
import unittest
from unittest.mock import patch

import operational_capture as capture
import operational_publication as publication
from continuous_protocol import FIELD_KINDS
from process_deadline import StreamingRunResult


def receipt(**changes) -> StreamingRunResult:
    empty = hashlib.sha256().hexdigest()
    return replace(StreamingRunResult("cancelled", 0, 0, 0, empty, empty,
                                      True, True, True, True, True), **changes)


def sample(sequence: int, elapsed: int, *, observed: int | None = None,
           drop_charge: bool = False, status_observed: int | None = None,
           add_voltage: int | None = None) -> bytes:
    observation = elapsed if observed is None else observed
    fields = {name: {"value": None, "observed_ms": None, "kind": kind,
                     "state": "unavailable"} for name, kind in FIELD_KINDS.items()}
    fields["ups.status"].update(value="OL", observed_ms=(observation if status_observed is None
                                                       else status_observed), state="observed")
    if not drop_charge:
        fields["battery.charge"].update(value="90", observed_ms=observation, state="observed")
    if add_voltage is not None:
        fields["input.voltage"].update(value="230", observed_ms=add_voltage, state="observed")
    record = {"protocol": "ups-monitor.continuous.v2", "schema_version": 2,
              "type": "sample", "sequence": sequence, "slot": elapsed // 5000,
              "elapsed_ms": elapsed, "missed_slots": elapsed // 5000 + 1 - sequence,
              "fields": fields}
    return (json.dumps(record, separators=(",", ":")) + "\n").encode("ascii")


def end(elapsed: int, reason: str = "cancelled") -> bytes:
    return (json.dumps({"protocol": "ups-monitor.continuous.v2", "schema_version": 2,
                       "type": "end", "elapsed_ms": elapsed, "reason": reason})
            + "\n").encode("ascii")


class Clock:
    def __init__(self) -> None:
        self.elapsed = 0

    def wall(self) -> int:
        return 1_000_000 + self.elapsed

    def mono(self) -> int:
        return self.elapsed


class Publisher:
    """Fixed retained state; tests intentionally do not collect sample history."""

    def __init__(self) -> None:
        self.active_count = 0
        self.terminal_count = 0
        self.last_state = None
        self.last_reason = None
        self.closed = False
        self.close_count = 0
        self.fail_active = False
        self.fail_terminal = False
        self.fail_close = False
        self.active_entered = Event()
        self.active_release: Event | None = None
        self.terminal_entered = Event()
        self.terminal_release: Event | None = None
        self.forbidden_thread_id: int | None = None

    def publish(self, **envelope) -> None:
        if get_ident() == self.forbidden_thread_id:
            raise AssertionError("publisher I/O executed in the observer caller")
        state, reason = envelope["state"], envelope["terminal_reason"]
        if ((state == "active" and reason is not None)
                or (state == "stopped" and reason != "cancelled")
                or (state == "failed" and reason not in publication.OPERATIONAL_TERMINAL_REASONS)
                or state not in ("active", "stopped", "failed")):
            raise AssertionError("terminal vocabulary differs from the real publisher")
        if self.closed:
            raise AssertionError("publisher was closed before its callback finished")
        if envelope["state"] == "active":
            self.active_count += 1
            self.active_entered.set()
            if self.active_release is not None:
                if not self.active_release.wait(2):
                    raise AssertionError("test did not release active publisher")
            if self.fail_active:
                raise OSError("synthetic secret must not escape")
        else:
            self.terminal_count += 1
            self.terminal_entered.set()
            if self.terminal_release is not None:
                if not self.terminal_release.wait(2):
                    raise AssertionError("test did not release terminal publisher")
            if self.fail_terminal:
                raise OSError("synthetic secret must not escape")
        if self.closed:
            raise AssertionError("descriptor owner closed during publication")
        self.last_state = envelope["state"]
        self.last_reason = envelope["terminal_reason"]

    def close(self) -> None:
        if get_ident() == self.forbidden_thread_id:
            raise AssertionError("publisher close executed in the observer caller")
        self.close_count += 1
        if self.fail_close:
            raise OSError("synthetic close failure")
        self.closed = True


class OperationalCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNone(capture._retained_owner, "previous test leaked an owned session")
        self.clock = Clock()
        self.publisher = Publisher()
        self.stop = Event()
        self.calls = 0

    def tearDown(self) -> None:
        owner = capture._retained_owner
        if owner is not None:
            if owner.finalizer_started and not owner.terminal_attempted:
                # The tests own only fake runners. Their absent receipt cases
                # get a teardown-only fake quiescence proof to release the
                # retained waiting worker, never a production registry reset
                # while a worker is still alive.
                owner.set_receipt(receipt(trigger="runner_error"))
                owner.maybe_finalize()
            if owner.finalizer is not None and owner.finalizer.ident is not None:
                owner.finalizer.join(1)
                self.assertFalse(owner.finalizer.is_alive(), "test leaked finalizer")
            # Only fake ownership is reset, after each test released its workers.
            capture._retained_owner = None

    def run_capture(self, runner, *, observer=lambda: None, join=1.0):
        def counted(*args, **kwargs):
            self.calls += 1
            self.assertIs(kwargs["cancel_event"], self.stop)
            self.assertEqual(kwargs["startup_timeout_seconds"], 35.0)
            self.assertEqual(kwargs["progress_timeout_seconds"], 15.0)
            self.assertEqual(kwargs["termination_grace_seconds"], 2.0)
            self.assertTrue(kwargs["private_nut_environment"])
            self.assertNotIn("timeout_seconds", kwargs)
            return runner(*args, **kwargs)
        return capture.capture_operational(
            ["synthetic-driver"], executable_sha256="0" * 64,
            output_root="synthetic-output", feed_directory="synthetic-feed",
            source_id="synthetic-ups", cancel_event=self.stop, runner=counted,
            ownership_observer=observer,
            publisher_factory=lambda *_args: self.publisher,
            wall_clock=self.clock.wall, monotonic_clock=self.clock.mono,
            finalization_join_seconds=join,
        )

    def test_virtual_700_seconds_one_runner_and_constant_retained_state(self) -> None:
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            owner = sink.__self__
            initial_keys = set(owner.__dict__)
            for sequence, elapsed in enumerate(range(0, 700_001, 5000), 1):
                self.clock.elapsed = elapsed
                self.assertTrue(sink(sample(sequence, elapsed)), "fresh published sample must renew health")
                self.assertEqual(set(owner.__dict__), initial_keys)
                self.assertFalse(hasattr(owner.validator, "samples"))
                self.assertEqual(owner.framer.pending_bytes, 0)
                self.assertEqual(len(owner.observed_fields), 2)
            self.stop.set()
            self.assertFalse(sink(end(self.clock.elapsed)))
            self.assertFalse(sink(b""))
            return receipt()
        result = self.run_capture(runner)
        self.assertEqual(self.calls, 1)
        self.assertEqual(result.sample_count, 141)
        self.assertEqual(self.publisher.active_count, 141)
        self.assertEqual(result.schema_version, 2)
        self.assertEqual(result.state, "stopped")
        self.assertTrue(result.ownership_resolved)
        self.assertTrue(result.terminal_published)
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)

    def test_cached_stale_and_field_shrink_cannot_renew_progress(self) -> None:
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            self.assertTrue(sink(sample(1, 0)))
            self.clock.elapsed = 5000
            self.assertFalse(sink(sample(2, 5000, observed=0)), "cached fields cannot renew")
            self.clock.elapsed = 10_000
            self.assertFalse(sink(sample(3, 10_000, drop_charge=True)), "field shrink cannot renew")
            self.clock.elapsed = 15_000
            self.assertFalse(sink(sample(4, 15_000, status_observed=0)), "stale status cannot renew")
            self.clock.elapsed = 20_000
            self.assertFalse(sink(sample(5, 20_000, add_voltage=0)), "old expanded field holds minimum")
            self.clock.elapsed = 25_000
            self.assertFalse(sink(sample(6, 25_000)), "expanded field cannot then disappear")
            self.clock.elapsed = 30_000
            self.assertTrue(sink(sample(7, 30_000, add_voltage=30_000)))
            self.stop.set()
            sink(end(30_000))
            sink(b"")
            return receipt()
        result = self.run_capture(runner)
        self.assertEqual(self.publisher.active_count, 2)
        self.assertEqual(result.state, "stopped")

    def test_invalid_record_fails_and_cannot_be_cleaned_into_success(self) -> None:
        def runner(*_args, **kwargs):
            self.assertFalse(kwargs["on_stdout"](b"invalid\n"))
            self.assertTrue(self.stop.is_set())
            return receipt()
        result = self.run_capture(runner)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.first_error, "protocol_error")
        self.assertEqual(self.publisher.last_reason, "protocol_error")

    def test_stop_blocks_new_active_even_when_valid_samples_arrive(self) -> None:
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            self.assertTrue(sink(sample(1, 0)))
            self.stop.set()
            self.clock.elapsed = 5000
            self.assertFalse(sink(sample(2, 5000)))
            sink(end(5000))
            sink(b"")
            return receipt()
        result = self.run_capture(runner)
        self.assertEqual(self.publisher.active_count, 1)
        self.assertEqual(result.state, "stopped")

    def test_stop_inflight_retains_worker_then_observation_finalizes_once(self) -> None:
        release = Event()
        self.publisher.active_release = release
        worker_done = Event()
        worker_progress = []
        worker = None
        def runner(*_args, **kwargs):
            nonlocal worker
            sink = kwargs["on_stdout"]
            def consume():
                try:
                    worker_progress.append(sink(sample(1, 0)))
                    sink(end(0))
                    sink(b"")
                finally:
                    worker_done.set()
            worker = Thread(target=consume)
            worker.start()
            self.assertTrue(self.publisher.active_entered.wait(1))
            self.stop.set()
            return receipt(consumer_quiesced=False)
        def observer():
            return receipt(consumer_quiesced=worker_done.is_set())
        try:
            result = self.run_capture(runner, observer=observer, join=0)
            self.assertEqual(result.state, "unresolved")
            self.assertFalse(result.consumer_quiesced)
            self.assertFalse(result.publisher_closed)
            self.assertEqual(self.publisher.terminal_count, 0)
            with self.assertRaises(capture.CaptureAdmissionError) as rejected:
                self.run_capture(lambda *_args, **_kwargs: receipt())
            self.assertEqual(rejected.exception.code, "capture_ownership_unresolved")
            self.assertEqual(self.calls, 1, "second start must not invoke a runner")
            interim = capture.observe_operational_ownership()
            self.assertEqual(interim.state, "unresolved")
            self.assertFalse(self.publisher.closed)
        finally:
            release.set()
            if worker is not None:
                worker.join(1)
                self.assertFalse(worker.is_alive(), "test must release blocked sink")
        self.assertEqual(worker_progress, [False], "completion after Stop cannot renew")
        owner = capture._retained_owner
        capture.observe_operational_ownership()
        self.assertTrue(owner.finalizer_done.wait(1))
        owner.finalizer.join(1)
        final = capture.observe_operational_ownership()
        # The first observation may already have consumed a completed finalizer.
        if final is not None:
            self.assertEqual(final.state, "stopped")
            self.assertTrue(final.ownership_resolved)
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)
        self.assertIsNone(capture.observe_operational_ownership())

    def test_missing_end_nonzero_and_each_cleanup_fact_prevent_clean_stop(self) -> None:
        cases = [("missing_end", receipt(), False),
                 ("nonzero", receipt(returncode=7), True)]
        for name in ("leader_reaped", "group_absent", "stdout_eof", "stderr_eof"):
            cases.append((name, receipt(**{name: False}), True))
        for name, run_result, has_end in cases:
            with self.subTest(name=name):
                self.publisher = Publisher()
                self.stop = Event()
                def runner(*_args, **kwargs):
                    sink = kwargs["on_stdout"]
                    sink(sample(1, 0))
                    self.stop.set()
                    if has_end:
                        sink(end(0))
                    sink(b"")
                    return run_result
                result = self.run_capture(runner)
                self.assertNotEqual(result.state, "stopped")
                self.assertEqual(self.publisher.last_state, "failed")
                self.assertTrue(result.consumer_quiesced)
                self.assertTrue(result.publisher_closed)
                if not run_result.ownership_resolved:
                    self.assertFalse(result.ownership_resolved)
                    capture._retained_owner = None  # fake receipt deliberately cannot resolve

    def test_unrequested_child_exit_with_cancelled_end_is_failure(self) -> None:
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            sink(sample(1, 0))
            sink(end(0))
            sink(b"")
            self.stop.set()  # real runner also sets cancellation on every exit
            return receipt(trigger="child_exited")
        result = self.run_capture(runner)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.first_error, "child_failed")

    def test_native_failure_end_retains_first_failure(self) -> None:
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            sink(sample(1, 0))
            sink(end(0, "device_lost"))
            sink(b"")
            return receipt(trigger="child_nonzero_exit", returncode=5)
        result = self.run_capture(runner)
        self.assertEqual(result.first_error, "device_lost")
        self.assertEqual(self.publisher.last_reason, "device_lost")

    def test_active_publisher_failure_closes_after_quiescence_preserving_error(self) -> None:
        self.publisher.fail_active = True
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            self.assertFalse(sink(sample(1, 0)))
            sink(end(0))
            sink(b"")
            return receipt(trigger="consumer_error")
        result = self.run_capture(runner)
        self.assertEqual(result.first_error, "io_error")
        self.assertEqual(result.publication_error, "active_publication_failed")
        self.assertEqual(result.state, "failed")
        self.assertTrue(result.publisher_closed)
        self.assertTrue(result.ownership_resolved)
        self.assertNotIn("secret", repr(result))

    def test_blocked_terminal_publisher_is_retained_and_observer_never_duplicates(self) -> None:
        release = Event()
        self.publisher.terminal_release = release
        def runner(*_args, **kwargs):
            sink = kwargs["on_stdout"]
            sink(sample(1, 0))
            self.stop.set()
            sink(end(0))
            sink(b"")
            return receipt()
        owner = None
        try:
            result = self.run_capture(runner, join=0)
            owner = capture._retained_owner
            self.assertTrue(self.publisher.terminal_entered.wait(1))
            self.assertEqual(result.state, "unresolved")
            self.assertTrue(result.consumer_quiesced)
            self.assertFalse(result.publisher_quiesced)
            self.assertFalse(result.publisher_closed)
            self.assertFalse(result.terminal_published)
            for _ in range(20):
                observed = capture.observe_operational_ownership()
                self.assertEqual(observed.state, "unresolved")
            self.assertEqual(self.publisher.terminal_count, 1)
            self.assertEqual(self.publisher.close_count, 0)
            with self.assertRaises(capture.CaptureAdmissionError):
                self.run_capture(runner)
        finally:
            release.set()
            if owner is not None:
                self.assertTrue(owner.finalizer_done.wait(1))
                owner.finalizer.join(1)
        result = capture.observe_operational_ownership()
        self.assertEqual(result.state, "stopped")
        self.assertTrue(result.ownership_resolved)
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)

    def test_terminal_failure_does_not_attest_publication_and_close_failure_retains(self) -> None:
        for close_failure in (False, True):
            with self.subTest(close_failure=close_failure):
                self.publisher = Publisher()
                self.publisher.fail_terminal = True
                self.publisher.fail_close = close_failure
                self.stop = Event()
                def runner(*_args, **kwargs):
                    self.stop.set()
                    kwargs["on_stdout"](end(0))
                    kwargs["on_stdout"](b"")
                    return receipt()
                result = self.run_capture(runner)
                self.assertFalse(result.terminal_published)
                self.assertEqual(result.publication_error, "terminal_publication_failed")
                self.assertEqual(result.first_error, "io_error")
                self.assertEqual(result.ownership_resolved, not close_failure)
                if close_failure:
                    capture.observe_operational_ownership()
                    self.assertEqual(self.publisher.close_count, 1, "observation cannot retry close")
                    self.assertEqual(self.publisher.terminal_count, 1)
                    capture._retained_owner = None  # fake close intentionally fails forever

    def test_runner_exception_without_cleanup_receipt_keeps_unknown_owner(self) -> None:
        def runner(*_args, **_kwargs):
            raise RuntimeError("synthetic secret")
        result = self.run_capture(runner, join=0)
        self.assertEqual(result.state, "unresolved")
        self.assertEqual(result.first_error, "runner_error")
        self.assertFalse(self.publisher.closed)
        self.assertFalse(result.ownership_resolved)
        self.assertEqual(self.publisher.terminal_count, 0)

    def test_publisher_admission_with_ambiguous_close_retains_without_runner_observation(self) -> None:
        observations = []
        def factory(*_args):
            raise publication.OperationalPublicationAdmissionError(self.publisher)
        result = capture.capture_operational(
            ["synthetic-driver"], executable_sha256="0" * 64,
            output_root="synthetic-output", feed_directory="synthetic-feed",
            source_id="synthetic-ups", cancel_event=self.stop,
            runner=lambda *_args, **_kwargs: self.fail("admission failure must not start runner"),
            ownership_observer=lambda: observations.append(True),
            publisher_factory=factory, wall_clock=self.clock.wall,
            monotonic_clock=self.clock.mono,
        )
        self.assertEqual(result.state, "unresolved")
        self.assertFalse(result.ownership_resolved)
        capture.observe_operational_ownership()
        self.assertEqual(observations, [], "cannot adopt another runner's receipt")
        self.assertEqual(self.publisher.close_count, 0, "ambiguous close cannot be retried")

    def test_output_incomplete_receipt_and_late_eof_keep_trigger_and_finalize_once(self) -> None:
        def runner(*_args, **kwargs):
            self.stop.set()
            kwargs["on_stdout"](end(0))
            return receipt(trigger="output_incomplete", stdout_eof=False)
        result = self.run_capture(
            runner, observer=lambda: receipt(trigger="output_incomplete"))
        self.assertEqual(result.state, "unresolved")
        self.assertEqual(result.runner_result.trigger, "output_incomplete")
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)
        final = capture.observe_operational_ownership()
        self.assertEqual(final.state, "failed")
        self.assertTrue(final.ownership_resolved)
        self.assertEqual(final.runner_result.trigger, "output_incomplete")
        self.assertTrue(final.terminal_published)
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)
        self.assertIsNone(capture.observe_operational_ownership())

    def test_finalizer_constructor_failure_is_owned_and_never_retried(self) -> None:
        constructions = []
        def constructor(*args, **kwargs):
            constructions.append(True)
            if len(constructions) == 1:
                raise RuntimeError("synthetic constructor failure")
            return Thread(*args, **kwargs)
        with patch.object(capture, "Thread", side_effect=constructor):
            result = self.run_capture(lambda *_args, **_kwargs: receipt())
            self.assertEqual(result.state, "unresolved")
            self.assertEqual(result.first_error, "io_error")
            self.assertEqual(result.publication_error, "finalizer_start_failed")
            self.assertEqual(self.calls, 0, "runner cannot start without its owned finalizer")
            for _ in range(5):
                observed = capture.observe_operational_ownership()
                self.assertEqual(observed.first_error, "io_error")
                self.assertEqual(observed.state, "unresolved")
            self.assertEqual(len(constructions), 1, "available constructor cannot be retried")
        self.assertEqual(self.publisher.terminal_count, 0)
        self.assertEqual(self.publisher.close_count, 0)

    def test_late_observer_only_notifies_prestarted_worker_without_thread_operations_or_io(self) -> None:
        def runner(*_args, **kwargs):
            self.stop.set()
            kwargs["on_stdout"](end(0))
            return receipt(consumer_quiesced=False)
        self.run_capture(runner, observer=lambda: receipt(), join=0)
        owner = capture._retained_owner
        self.assertTrue(owner.finalizer_started)
        self.assertTrue(owner.finalizer.is_alive())
        self.assertFalse(owner.finalize_requested.is_set())
        self.publisher.forbidden_thread_id = get_ident()
        try:
            with patch.object(capture, "Thread", side_effect=AssertionError("observer constructed Thread")), \
                    patch.object(owner.finalizer, "start", side_effect=AssertionError("observer started Thread")), \
                    patch.object(owner.finalizer, "join", side_effect=AssertionError("observer joined Thread")):
                capture.observe_operational_ownership()
            self.assertTrue(owner.finalize_requested.is_set())
        finally:
            # Every test-created worker is released/joined outside the observer
            # spies even if an assertion failed above.
            if not owner.terminal_attempted:
                owner.set_receipt(receipt())
                owner.maybe_finalize()
            self.assertTrue(owner.finalizer_done.wait(1))
            owner.finalizer.join(1)
            self.publisher.forbidden_thread_id = None
        final = capture.observe_operational_ownership()
        if final is not None:
            self.assertEqual(final.state, "stopped")
            self.assertTrue(final.ownership_resolved)
        self.assertTrue(owner.snapshot().terminal_published)
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)

    def test_runner_and_observer_errors_map_closed_terminal_reason_after_late_receipt(self) -> None:
        observations = []
        def runner(*_args, **_kwargs):
            raise RuntimeError("synthetic runner failure")
        def observer():
            observations.append(True)
            if len(observations) == 1:
                raise RuntimeError("synthetic observer failure")
            return receipt()
        initial = self.run_capture(runner, observer=observer, join=0)
        self.assertEqual(initial.first_error, "runner_error")
        self.assertEqual(initial.terminal_reason, "io_error")
        owner = capture._retained_owner
        self.assertTrue(owner.finalizer.is_alive(), "unknown receipt must retain its waiting worker")
        self.assertFalse(owner.finalize_requested.is_set())
        interim = capture.observe_operational_ownership()
        self.assertEqual(interim.first_error, "runner_error")
        self.assertFalse(owner.finalize_requested.is_set())
        capture.observe_operational_ownership()
        self.assertTrue(owner.finalizer_done.wait(1))
        owner.finalizer.join(1)
        final = capture.observe_operational_ownership() or owner.snapshot()
        self.assertEqual(final.state, "failed")
        self.assertEqual(final.first_error, "runner_error")
        self.assertEqual(final.terminal_reason, "io_error")
        self.assertTrue(final.terminal_published)
        self.assertTrue(final.ownership_resolved)
        self.assertEqual(self.publisher.last_reason, "io_error")
        self.assertEqual(self.publisher.terminal_count, 1)
        self.assertEqual(self.publisher.close_count, 1)

    def test_terminal_clock_pair_rejects_wall_before_start_or_discontinuous_wall(self) -> None:
        for terminal_wall, terminal_mono in ((0, 0), (1_010_000, 0), (1_000_000, -1)):
            with self.subTest(wall=terminal_wall, monotonic=terminal_mono):
                self.publisher = Publisher()
                self.stop = Event()
                self.clock = Clock()
                terminal = Event()
                def wall():
                    return terminal_wall if terminal.is_set() else self.clock.wall()
                def mono():
                    return terminal_mono if terminal.is_set() else self.clock.mono()
                def runner(*_args, **kwargs):
                    self.stop.set()
                    kwargs["on_stdout"](end(0))
                    terminal.set()
                    return receipt()
                result = capture.capture_operational(
                    ["synthetic-driver"], executable_sha256="0" * 64,
                    output_root="synthetic-output", feed_directory="synthetic-feed",
                    source_id="synthetic-ups", cancel_event=self.stop, runner=runner,
                    publisher_factory=lambda *_args: self.publisher,
                    wall_clock=wall, monotonic_clock=mono,
                )
                self.assertEqual(result.state, "failed")
                self.assertEqual(result.first_error, "protocol_error")
                self.assertEqual(result.publication_error, "terminal_clock_invalid")
                self.assertFalse(result.terminal_published)
                self.assertIsNone(result.published_at_unix_ms)
                self.assertTrue(result.ownership_resolved)
                self.assertEqual(self.publisher.terminal_count, 0)
                self.assertEqual(self.publisher.close_count, 1)


class OperationalPublisherAdmissionTests(unittest.TestCase):
    def make_publisher(self):
        return publication.AtomicOperationalPublisher("synthetic-feed", "synthetic-ups", "1" * 32)

    def test_second_open_failure_closes_parent_exactly_once(self) -> None:
        with patch.object(publication, "_check_private_dir"), \
                patch.object(publication.os, "open", side_effect=[101, OSError("open failed")]), \
                patch.object(publication.os, "close") as close:
            with self.assertRaises(publication.OperationalPublicationAdmissionError) as caught:
                self.make_publisher()
            self.assertIsNone(caught.exception.publisher)
            close.assert_called_once_with(101)

    def test_identity_failure_closes_each_owned_descriptor_without_retry(self) -> None:
        with patch.object(publication, "_check_private_dir"), \
                patch.object(publication.os, "open", side_effect=[101, 102]), \
                patch.object(publication.os, "fstat", return_value=object()), \
                patch.object(publication.os, "stat", return_value=object()), \
                patch.object(publication, "_same_directory_identity", return_value=False), \
                patch.object(publication.os, "close") as close:
            with self.assertRaises(publication.OperationalPublicationAdmissionError) as caught:
                self.make_publisher()
            self.assertIsNone(caught.exception.publisher)
            self.assertEqual([call.args[0] for call in close.call_args_list], [102, 101])

    def test_ambiguous_close_detaches_number_retains_owner_and_is_never_retried(self) -> None:
        with patch.object(publication, "_check_private_dir"), \
                patch.object(publication.os, "open", side_effect=[101, OSError("open failed")]), \
                patch.object(publication.os, "close", side_effect=OSError("already consumed")) as close:
            with self.assertRaises(publication.OperationalPublicationAdmissionError) as caught:
                self.make_publisher()
            owner = caught.exception.publisher
            self.assertIsNotNone(owner)
            self.assertEqual(owner.parent_fd, -1)
            self.assertEqual(owner.dir_fd, -1)
            with self.assertRaisesRegex(OSError, "publication_cleanup_unresolved"):
                owner.close()
            close.assert_called_once_with(101)

    def test_successful_close_is_idempotent(self) -> None:
        with patch.object(publication, "_check_private_dir"), \
                patch.object(publication.os, "open", side_effect=[101, 102]), \
                patch.object(publication.os, "fstat", return_value=object()), \
                patch.object(publication.os, "stat", return_value=object()), \
                patch.object(publication, "_same_directory_identity", return_value=True), \
                patch.object(publication.os, "close") as close:
            owner = self.make_publisher()
            owner.close()
            owner.close()
            self.assertEqual([call.args[0] for call in close.call_args_list], [102, 101])


if __name__ == "__main__":
    unittest.main()
