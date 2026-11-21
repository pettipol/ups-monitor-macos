"""Opt-in schema-2 capture; importing this module starts no work."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
from threading import Event, Lock, Thread
import time
from typing import Callable, Sequence
import uuid

from continuous_capture import ID_RE, _check_private_dir
from continuous_protocol import (
    MAX_SAFE_INTEGER, OperationalEnd, OperationalSample,
    OperationalStreamValidator, ProtocolError,
)
from operational_publication import (
    AtomicOperationalPublisher, OperationalFramer, OperationalPublicationAdmissionError,
    OPERATIONAL_TERMINAL_REASONS,
)
from process_deadline import (
    DependencyPin, StreamingRunResult, retained_streaming_ownership, run_streaming,
)


_MAX_COUNTER = (1 << 63) - 1
_HASH_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_RUNNER_TRIGGERS = frozenset({
    "cancelled", "child_exited", "child_nonzero_exit", "child_unreaped",
    "cleanup_error", "clock_invalid", "clock_regression", "consumer_error",
    "consumer_backpressure", "chunk_limit", "output_counter_overflow",
    "output_rate_limit", "output_io_failed", "output_incomplete", "progress_deadline",
    "startup_deadline", "runner_error", "cleanup_unresolved",
    "worker_start_failed", "worker_error", "progress_overflow",
})
_admission = Lock()
_retained_owner: _Owner | None = None


class CaptureAdmissionError(RuntimeError):
    """Fixed-code admission rejection; no resource ownership is transferred."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OperationalCaptureResult:
    schema_version: int
    protocol: str
    state: str
    terminal_reason: str
    first_error: str | None
    publication_error: str | None
    source_id: str
    session_id: str
    started_at_unix_ms: int
    published_at_unix_ms: int | None
    sample_count: int
    end_reason: str | None
    runner_result: StreamingRunResult | None
    consumer_quiesced: bool
    publisher_quiesced: bool
    publisher_closed: bool
    terminal_published: bool
    ownership_resolved: bool


def _timestamp(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_SAFE_INTEGER


def _envelope_reason(diagnostic: str) -> str:
    """Keep diagnostic-only codes out of the publisher's closed vocabulary."""
    return diagnostic if diagnostic in OPERATIONAL_TERMINAL_REASONS else "io_error"


def _receipt(value: object) -> bool:
    if (type(value) is not StreamingRunResult or type(value.trigger) is not str
            or value.trigger not in _RUNNER_TRIGGERS):
        return False
    return (
        (value.returncode is None or (type(value.returncode) is int
                                     and -(1 << 31) <= value.returncode < (1 << 31)))
        and all(type(n) is int and 0 <= n <= _MAX_COUNTER
                for n in (value.stdout_bytes, value.stderr_bytes))
        and all(type(h) is str and _HASH_RE.fullmatch(h) is not None
                for h in (value.stdout_sha256, value.stderr_sha256))
        and all(type(b) is bool for b in (
            value.leader_reaped, value.group_absent, value.stdout_eof,
            value.stderr_eof, value.consumer_quiesced,
        ))
    )


class _Owner:
    """One constant-size owner, retained until worker and descriptor resolution."""

    def __init__(self, publisher, source_id: str, session_id: str, cancellation: Event,
                 wall: Callable[[], int], mono: Callable[[], int],
                 started: int, start_mono: int, observer: Callable[[], object]) -> None:
        self.publisher = publisher
        self.source_id, self.session_id = source_id, session_id
        self.cancellation = cancellation
        self.wall, self.mono, self.started = wall, mono, started
        self.observer = observer
        self.lock = Lock()
        self.validator = OperationalStreamValidator(started, start_mono)
        self.framer = OperationalFramer(self.record)
        self.first_error: str | None = None
        self.publication_error: str | None = None
        self.observed_fields: frozenset[str] = frozenset()
        self.minimum_observed_ms: int | None = None
        self.published_at: int | None = None
        self.run_result: StreamingRunResult | None = None
        self.runner_started = False
        self.inflight = False
        self.accepting = True
        self.last_record_monotonic_ms = start_mono
        self.finalizer: Thread | None = None
        self.finalizer_admission_attempted = False
        self.finalizer_started = False
        self.finalize_requested = Event()
        self.finalizer_done = Event()
        self.terminal_attempted = False
        self.terminal_published = False
        self.publisher_closed = False
        self.terminal_state = "failed"
        self.terminal_reason = "cleanup_unresolved"

    def fail(self, reason: str, *, publication: str | None = None) -> None:
        with self.lock:
            self.first_error = self.first_error or reason
            self.publication_error = self.publication_error or publication
            self.accepting = False
        self.cancellation.set()

    def accept(self, chunk: bytes) -> bool:
        try:
            accepted = self.framer.accept(chunk)
            return accepted and not self.cancellation.is_set()
        except ProtocolError:
            self.fail("protocol_error")
        except Exception:
            self.fail("io_error")
        return False

    def record(self, record: OperationalSample | OperationalEnd) -> bool:
        # Injected clocks and publisher I/O are deliberately outside our lock.
        now_wall, now_mono = self.wall(), self.mono()
        with self.lock:
            self.validator.accept(record, now_wall_ms=now_wall, now_monotonic_ms=now_mono)
            self.last_record_monotonic_ms = now_mono
            if type(record) is OperationalEnd:
                if record.reason != "cancelled":
                    self.first_error = self.first_error or record.reason
                    self.accepting = False
                is_end = True
                eligible = False
            else:
                is_end = False
                fields = frozenset(name for name, item in record.fields.items()
                                   if item.kind != "static" and item.state == "observed")
                status = record.fields["ups.status"]
                minimum = min((record.fields[name].observed_ms for name in fields), default=None)
                # Union even on an ineligible record: a temporarily absent field
                # cannot be erased from the health baseline by another sample.
                no_shrink = self.observed_fields.issubset(fields)
                self.observed_fields = self.observed_fields | fields
                elapsed_now = now_mono - self.validator.started_monotonic_ms
                eligible = (
                    status.state == "observed" and status.observed_ms is not None
                    and 0 <= elapsed_now - status.observed_ms <= 10_000
                    and minimum is not None and no_shrink
                    and (self.minimum_observed_ms is None
                         or minimum > self.minimum_observed_ms)
                )
                if (not eligible or not self.accepting or self.cancellation.is_set()):
                    return False
                # This bounded reservation is the active-operation start. Stop
                # cannot revoke I/O admitted here, but admits no later active.
                self.inflight = True
        if is_end:
            if record.reason != "cancelled":
                self.cancellation.set()
            return False
        try:
            self.publisher.publish(
                state="active", started_at_unix_ms=self.started, terminal_reason=None,
                sample=record.raw, published_at_unix_ms=now_wall,
            )
        except Exception:
            self.fail("io_error", publication="active_publication_failed")
            return False
        finally:
            with self.lock:
                self.inflight = False
        with self.lock:
            self.published_at = now_wall
            self.minimum_observed_ms = minimum
            return self.accepting and not self.cancellation.is_set()

    def set_receipt(self, result: object) -> None:
        if not _receipt(result):
            self.fail("runner_error")
            return
        with self.lock:
            self.run_result = result
            self.accepting = False
            if result.trigger != "cancelled":
                if result.trigger in ("startup_deadline", "progress_deadline"):
                    reason = "deadline"
                elif result.trigger in ("output_rate_limit", "output_counter_overflow", "chunk_limit"):
                    reason = "capture_limit"
                else:
                    reason = "child_failed"
                self.first_error = self.first_error or reason
            if result.returncode not in (0, None):
                self.first_error = self.first_error or "child_failed"

    def prepare_finalizer(self) -> bool:
        """Capture-only, once: own the worker before the runner can own a child."""
        with self.lock:
            if self.finalizer_admission_attempted:
                return self.finalizer_started
            self.finalizer_admission_attempted = True
        try:
            # Construction/start can wait or fail, so neither belongs in the
            # observer, in a state lock or outside the retained-owner lifetime.
            thread = Thread(target=self.await_finalization, daemon=True,
                            name="operational-final-publication")
            with self.lock:
                self.finalizer = thread
            thread.start()
        except Exception:
            self.fail("io_error", publication="finalizer_start_failed")
            return False
        with self.lock:
            self.finalizer_started = True
        return True

    def await_finalization(self) -> None:
        # A missing runner receipt leaves this explicitly retained worker idle;
        # it cannot close/publish until quiescence is independently established.
        self.finalize_requested.wait()
        self.finalize()

    def maybe_finalize(self) -> None:
        # Receipt quiescence is independent of an in-flight flag. This method
        # only updates bounded state and notifies the already-owned worker.
        with self.lock:
            result = self.run_result
            if (not self.finalizer_started or self.terminal_attempted or result is None
                    or not result.consumer_quiesced or self.inflight):
                return
            self.accepting = False
            clean = (
                self.first_error is None and self.cancellation.is_set()
                and result.trigger == "cancelled" and result.returncode == 0
                and result.ownership_resolved
                and self.validator.end is not None
                and self.validator.end.reason == "cancelled"
            )
            self.terminal_state = "stopped" if clean else "failed"
            self.terminal_reason = ("cancelled" if clean else _envelope_reason(
                self.first_error or ("cleanup_unresolved" if not result.ownership_resolved
                                     else "child_failed")))
            self.terminal_attempted = True
        self.finalize_requested.set()

    def finalize(self) -> None:
        try:
            try:
                published, now_mono = self.wall(), self.mono()
                if (not _timestamp(published) or not _timestamp(now_mono)
                        or published < self.started
                        or (self.published_at is not None and published < self.published_at)
                        or now_mono < self.last_record_monotonic_ms
                        or abs((published - self.started)
                               - (now_mono - self.validator.started_monotonic_ms)) > 1_000):
                    raise ProtocolError("clock_discontinuity")
                self.publisher.publish(
                    state=self.terminal_state, started_at_unix_ms=self.started,
                    terminal_reason=self.terminal_reason,
                    sample=self.validator.last_sample.raw if self.validator.last_sample else None,
                    published_at_unix_ms=published,
                )
                with self.lock:
                    self.published_at = published
                    self.terminal_published = True
            except ProtocolError:
                self.fail("protocol_error", publication="terminal_clock_invalid")
            except Exception:
                self.fail("io_error", publication="terminal_publication_failed")
            try:
                self.publisher.close()
                with self.lock:
                    self.publisher_closed = True
            except Exception:
                self.fail("io_error", publication="publisher_close_failed")
        finally:
            self.finalizer_done.set()

    def snapshot(self) -> OperationalCaptureResult:
        with self.lock:
            run = self.run_result
            # done is set only after all publisher I/O and close have finished.
            publisher_quiesced = (self.finalizer_done.is_set()
                                   and self.finalizer is not None
                                   and not self.finalizer.is_alive())
            resolved = bool(run is not None and run.ownership_resolved
                            and publisher_quiesced and self.publisher_closed)
            state = self.terminal_state if resolved else "unresolved"
            if resolved and self.first_error is not None:
                state = "failed"
            reason = (_envelope_reason(self.first_error) if self.first_error is not None
                      else self.terminal_reason if resolved else "cleanup_unresolved")
            return OperationalCaptureResult(
                2, "ups-monitor.continuous.v2", state, reason, self.first_error,
                self.publication_error, self.source_id, self.session_id, self.started,
                self.published_at, self.validator.sample_count,
                self.validator.end.reason if self.validator.end else None,
                run, bool(run is not None and run.consumer_quiesced),
                publisher_quiesced, self.publisher_closed, self.terminal_published, resolved,
            )


def capture_operational(
    argv: Sequence[str], *, executable_sha256: str,
    output_root: str | os.PathLike[str], feed_directory: str | os.PathLike[str],
    source_id: str, cancel_event: Event,
    dependency_pins: tuple[DependencyPin, ...] = (),
    runner: Callable[..., StreamingRunResult] = run_streaming,
    ownership_observer: Callable[[], object] = retained_streaming_ownership,
    publisher_factory: Callable[..., object] = AtomicOperationalPublisher,
    wall_clock: Callable[[], int] | None = None,
    monotonic_clock: Callable[[], int] | None = None,
    finalization_join_seconds: float = 2.0,
) -> OperationalCaptureResult:
    """Run exactly one opt-in stream with fixed 35/15/2-second health policy.

    Stop is cancel_event.set(), which never takes our locks or waits for I/O.
    An admitted active write may complete after Stop; it cannot renew progress.
    Fake runner/publisher/clock injection is for source-only synthetic tests.
    The caller must preserve this module and observe retained ownership before
    allowing another session; no app/native profile is enabled by this API.
    """
    global _retained_owner
    if (not isinstance(source_id, str) or ID_RE.fullmatch(source_id) is None
            or not isinstance(cancel_event, Event)
            or isinstance(finalization_join_seconds, bool)
            or not isinstance(finalization_join_seconds, (int, float))
            or not math.isfinite(finalization_join_seconds)
            or not 0 <= finalization_join_seconds <= 2.0):
        raise ValueError("invalid_capture_argument")
    if not _admission.acquire(blocking=False):
        raise CaptureAdmissionError("capture_active")
    try:
        if _retained_owner is not None:
            raise CaptureAdmissionError("capture_ownership_unresolved")
        wall = wall_clock or (lambda: time.time_ns() // 1_000_000)
        mono = monotonic_clock or (lambda: time.monotonic_ns() // 1_000_000)
        started, start_mono = wall(), mono()
        if not _timestamp(started) or not _timestamp(start_mono):
            raise ValueError("invalid_capture_clock")
        if publisher_factory is AtomicOperationalPublisher:
            _check_private_dir(Path(output_root))
        session_id = uuid.uuid4().hex
        try:
            publisher = publisher_factory(feed_directory, source_id, session_id)
        except OperationalPublicationAdmissionError as error:
            if error.publisher is not None:
                owner = _Owner(error.publisher, source_id, session_id, cancel_event,
                               wall, mono, started, start_mono, ownership_observer)
                owner.fail("io_error", publication="publisher_close_failed")
                _retained_owner = owner
                return owner.snapshot()
            raise CaptureAdmissionError("publication_admission_failed") from None
        except Exception:
            raise CaptureAdmissionError("publication_admission_failed") from None
        owner = _Owner(publisher, source_id, session_id, cancel_event,
                       wall, mono, started, start_mono, ownership_observer)
        # Retain before invoking the runner: even an unexpected runner exception
        # cannot discard a sink that may still be executing on another thread.
        _retained_owner = owner
        if not owner.prepare_finalizer():
            return owner.snapshot()
        owner.runner_started = True
        try:
            run = runner(
                argv, executable_sha256=executable_sha256,
                output_directory=Path(output_root) / f"operational-run-{session_id}",
                cancel_event=cancel_event, on_stdout=owner.accept,
                startup_timeout_seconds=35.0, progress_timeout_seconds=15.0,
                termination_grace_seconds=2.0, private_nut_environment=True,
                dependency_pins=dependency_pins,
            )
        except Exception:
            owner.fail("runner_error")
        else:
            owner.set_receipt(run)
        owner.maybe_finalize()
        if (owner.terminal_attempted and owner.finalizer is not None
                and owner.finalizer.ident is not None):
            owner.finalizer.join(finalization_join_seconds)
        result = owner.snapshot()
        if result.ownership_resolved:
            _retained_owner = None
        return result
    finally:
        _admission.release()


def observe_operational_ownership() -> OperationalCaptureResult | None:
    """Nonwaiting observation: no signals, retry, publication call or worker join.

    The default runner observer performs one bounded nonblocking drain. A late
    quiescent receipt notifies the finalizer already started by capture, whose
    completion can be seen later. No construction/start/join or publisher I/O
    runs in this observer. No final publication is ever attempted twice.
    """
    global _retained_owner
    if not _admission.acquire(blocking=False):
        raise CaptureAdmissionError("capture_active")
    try:
        owner = _retained_owner
        if owner is None:
            return None
        run = owner.run_result
        if owner.runner_started and (run is None or not run.ownership_resolved):
            try:
                observed = owner.observer()
            except Exception:
                owner.fail("runner_error")
            else:
                if observed is not None:
                    owner.set_receipt(observed)
        owner.maybe_finalize()
        result = owner.snapshot()
        if result.ownership_resolved:
            _retained_owner = None
        return result
    finally:
        _admission.release()
