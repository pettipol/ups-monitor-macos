"""Deliver SIGINT cancellation to a bounded child from the main thread."""

from __future__ import annotations

import queue
import signal
import threading
from threading import Event
from os import PathLike
from typing import Sequence

from process_deadline import BoundedRunResult, DependencyPin, run_bounded


_POLL_SECONDS = 0.025
_active = False


def run_operator_controlled(
    argv: Sequence[str],
    *,
    executable_sha256: str,
    output_directory: str | PathLike[str],
    timeout_seconds: float,
    termination_grace_seconds: float = 1,
    maximum_output_bytes: int = 1_048_576,
    private_nut_environment: bool = False,
    dependency_pins: tuple[DependencyPin, ...] = (),
) -> BoundedRunResult:
    """Run one bounded child, translating main-thread SIGINT into cancellation.

    This adapter temporarily owns SIGINT and is restricted to one main-thread
    invocation at a time. It does not handle SIGTERM or process descendants.
    """
    global _active
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("operator control requires the main thread")
    if _active:
        raise RuntimeError("operator control is not reentrant")

    previous_handler = signal.getsignal(signal.SIGINT)
    if previous_handler not in (signal.default_int_handler, signal.SIG_DFL):
        raise RuntimeError("operator control requires the default SIGINT handler")

    handler_installed = False
    worker: threading.Thread | None = None
    cancel_event: Event | None = None
    active_marked = False

    try:
        active_marked = True
        _active = True
        stop_requested = False
        cancel_event = Event()
        outcome: queue.Queue[tuple[bool, BoundedRunResult | BaseException]] = queue.Queue(maxsize=1)

        def request_stop(_signum: int, _frame: object) -> None:
            nonlocal stop_requested
            stop_requested = True

        def run_child() -> None:
            try:
                result = run_bounded(
                    argv,
                    executable_sha256=executable_sha256,
                    output_directory=output_directory,
                    timeout_seconds=timeout_seconds,
                    termination_grace_seconds=termination_grace_seconds,
                    maximum_output_bytes=maximum_output_bytes,
                    private_nut_environment=private_nut_environment,
                    cancel_event=cancel_event,
                    dependency_pins=dependency_pins,
                )
            except BaseException as error:
                outcome.put((False, error))
            else:
                outcome.put((True, result))

        signal.signal(signal.SIGINT, request_stop)
        handler_installed = True
        worker = threading.Thread(target=run_child, name="bounded-child", daemon=False)
        worker.start()

        cancellation_delivered = False
        while True:
            if stop_requested and not cancellation_delivered:
                cancel_event.set()
                cancellation_delivered = True
            try:
                succeeded, value = outcome.get(timeout=_POLL_SECONDS)
                break
            except queue.Empty:
                continue

        worker.join()
        if succeeded:
            if not isinstance(value, BoundedRunResult):
                raise RuntimeError("bounded runner returned an invalid result")
            return value
        if not isinstance(value, BaseException):
            raise RuntimeError("bounded runner returned an invalid error")
        raise value
    except BaseException:
        if worker is not None and worker.ident is not None and worker.is_alive():
            if cancel_event is not None:
                cancel_event.set()
            worker.join()
        raise
    finally:
        if active_marked:
            _active = False
        if handler_installed:
            signal.signal(signal.SIGINT, previous_handler)
