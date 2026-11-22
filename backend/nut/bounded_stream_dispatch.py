"""Bounded, single-consumer dispatch for an operational byte stream.

This component owns no process or file resources. A blocked callback cannot be
stopped safely; callers must retain the dispatcher if ``join`` reports that it
has not quiesced.
"""

from __future__ import annotations

import math
import numbers
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

_QUEUE_CAPACITY = 2
_MAX_CHUNK_BYTES = 65_536
_WORKER_POLL_SECONDS = 0.025
_MAX_COUNTER = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class DispatchSnapshot:
    started: bool
    input_closed: bool
    stop_requested: bool
    eof_delivered: bool
    quiesced: bool
    error: str | None
    accepted_progress_count: int
    last_progress_monotonic: float | None
    queued_chunks: int


class BoundedStreamDispatch:
    """Dispatch at most two chunks to one daemon worker in FIFO order."""

    def __init__(
        self,
        on_stdout: Callable[[bytes], bool],
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(on_stdout):
            raise TypeError("on_stdout must be callable")
        if not callable(monotonic_clock):
            raise TypeError("monotonic_clock must be callable")
        self._sink = on_stdout
        self._clock = monotonic_clock
        self._condition = threading.Condition()
        self._queue: deque[bytes] = deque()
        self._start_attempted = False
        self._start_completed = False
        self._started = False
        self._input_closed = False
        self._stop_requested = False
        self._eof_delivered = False
        self._quiesced = True
        self._error: str | None = None
        self._progress_count = 0
        self._last_progress: float | None = None
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._start_attempted:
                raise RuntimeError("already_started")
            self._start_attempted = True
            self._quiesced = False

        # Construction and Thread.start can block; keep both outside the state
        # condition so snapshot() and bounded join() remain responsive.
        worker: threading.Thread | None = None
        try:
            worker = threading.Thread(
                target=self._run,
                name="bounded-stream-dispatch",
                daemon=True,
            )
            worker.start()
        except BaseException:
            with self._condition:
                self._start_completed = True
                worker_started = worker is not None and worker.ident is not None
                self._worker = worker if worker_started else None
                self._started = worker_started
                if not worker_started:
                    self._quiesced = True
                self._latch_error_locked("worker_start_failed")
            return
        with self._condition:
            self._worker = worker
            self._started = True
            self._start_completed = True
            self._condition.notify_all()

    def submit(self, chunk: bytes) -> bool:
        if type(chunk) is not bytes:
            raise TypeError("chunk must be exact bytes")
        if not chunk:
            raise ValueError("chunk must be nonempty")
        with self._condition:
            if not self._start_completed:
                raise RuntimeError("not_started")
            if self._stop_requested or self._input_closed:
                return False
            if len(chunk) > _MAX_CHUNK_BYTES:
                self._latch_error_locked("chunk_limit")
                return False
            if len(self._queue) >= _QUEUE_CAPACITY:
                self._latch_error_locked("consumer_backpressure")
                return False
            self._queue.append(chunk)
            self._condition.notify()
            return True

    def close_input(self) -> None:
        with self._condition:
            if self._stop_requested or self._input_closed:
                return
            self._input_closed = True
            self._condition.notify_all()

    def request_stop(self) -> None:
        with self._condition:
            self._request_stop_locked()

    def join(self, timeout_seconds: float = 2.0) -> DispatchSnapshot:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, numbers.Real)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
            or timeout_seconds > 2.0
        ):
            raise ValueError("timeout_seconds must be finite and between 0 and 2")
        with self._condition:
            worker = self._worker
            if worker is None:
                return self._snapshot_locked()
        worker.join(float(timeout_seconds))
        with self._condition:
            return self._snapshot_locked()

    def snapshot(self) -> DispatchSnapshot:
        with self._condition:
            return self._snapshot_locked()

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    while not self._queue and not self._input_closed and not self._stop_requested:
                        self._condition.wait(_WORKER_POLL_SECONDS)
                    if self._stop_requested:
                        return
                    if self._queue:
                        chunk = self._queue.popleft()
                    elif self._input_closed:
                        chunk = None
                    else:
                        continue
                if chunk is None:
                    if not self._invoke_sink(b"", is_eof=True):
                        return
                    return
                if not self._invoke_sink(chunk, is_eof=False):
                    return
        except BaseException:
            with self._condition:
                self._latch_error_locked("worker_error")
        finally:
            with self._condition:
                self._quiesced = True
                self._condition.notify_all()

    def _invoke_sink(self, chunk: bytes, *, is_eof: bool) -> bool:
        try:
            result = self._sink(chunk)
        except BaseException:
            with self._condition:
                self._latch_error_locked("consumer_error")
            return False
        if type(result) is not bool:
            with self._condition:
                self._latch_error_locked("consumer_error")
            return False
        if is_eof:
            with self._condition:
                self._eof_delivered = True
            return True
        if not result:
            return True

        # The clock is user supplied and is deliberately called outside locks.
        try:
            sampled = self._clock()
            if (
                isinstance(sampled, bool)
                or not isinstance(sampled, numbers.Real)
                or not math.isfinite(sampled)
            ):
                raise ValueError("invalid_clock")
            sampled_float = float(sampled)
        except BaseException:
            with self._condition:
                self._latch_error_locked("clock_invalid")
            return False
        with self._condition:
            if self._stop_requested:
                return False
            if self._last_progress is not None and sampled_float < self._last_progress:
                self._latch_error_locked("clock_regression")
                return False
            if self._progress_count >= _MAX_COUNTER:
                self._latch_error_locked("progress_overflow")
                return False
            self._progress_count += 1
            self._last_progress = sampled_float
            return True

    def _request_stop_locked(self) -> None:
        self._stop_requested = True
        self._queue.clear()
        self._condition.notify_all()

    def _latch_error_locked(self, code: str) -> None:
        if self._error is None:
            self._error = code
        self._request_stop_locked()

    def _snapshot_locked(self) -> DispatchSnapshot:
        return DispatchSnapshot(
            started=self._started,
            input_closed=self._input_closed,
            stop_requested=self._stop_requested,
            eof_delivered=self._eof_delivered,
            quiesced=self._quiesced,
            error=self._error,
            accepted_progress_count=self._progress_count,
            last_progress_monotonic=self._last_progress,
            queued_chunks=len(self._queue),
        )
