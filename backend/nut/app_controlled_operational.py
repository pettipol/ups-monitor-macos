"""One opt-in operational capture and one cancellation-only app control FIFO.

No CLI, profile registry, process launch, retry or stdout output lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
from os import PathLike
from pathlib import Path
import re
import select
import signal
import stat
import threading
from threading import Event
from typing import Callable

from continuous_capture import ID_RE
from continuous_protocol import MAX_SAFE_INTEGER
from operational_capture import (
    OperationalCaptureResult, _receipt as _valid_runner_receipt,
    capture_operational, observe_operational_ownership,
)
from operational_publication import OPERATIONAL_TERMINAL_REASONS
from process_deadline import DependencyPin

_POLL_SECONDS = 0.025
_OBSERVATION_SECONDS = 0.250
_JOIN_SECONDS = 2.0
_HASH_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_SESSION_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
_FIRST_ERRORS = OPERATIONAL_TERMINAL_REASONS | {"runner_error"}
_PUBLICATION_ERRORS = frozenset({
    "active_publication_failed", "terminal_publication_failed", "publisher_close_failed",
    "finalizer_start_failed", "terminal_clock_invalid",
})
_active = False
_retained_owner: _Owner | None = None


class AppOperationalAdmissionError(RuntimeError):
    """Fixed-code rejection before control descriptor ownership transfers."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedOperationalProfile:
    """Integrator-admitted immutable argv/hash/pins; never a UI command."""

    argv: tuple[str, ...]
    executable_sha256: str
    dependency_pins: tuple[DependencyPin, ...] = ()

    def __post_init__(self) -> None:
        if (type(self.argv) is not tuple or not self.argv
                or any(type(v) is not str or not v or "\0" in v for v in self.argv)
                or not os.path.isabs(self.argv[0])
                or type(self.executable_sha256) is not str
                or _HASH_RE.fullmatch(self.executable_sha256) is None
                or type(self.dependency_pins) is not tuple):
            raise ValueError("invalid_fixed_profile")
        for pin in self.dependency_pins:
            if (type(pin) is not DependencyPin
                    or not isinstance(pin.link_path, Path) or not pin.link_path.is_absolute()
                    or not isinstance(pin.resolved_path, Path) or not pin.resolved_path.is_absolute()
                    or any(type(v) is not str or not v or "\0" in v
                           for v in (pin.loader_relative_path, pin.symlink_target))
                    or type(pin.sha256) is not str or _HASH_RE.fullmatch(pin.sha256) is None):
                raise ValueError("invalid_fixed_profile")


@dataclass(frozen=True, slots=True)
class AppOperationalReceipt:
    capture_result: OperationalCaptureResult | None
    control_reason: str | None
    adapter_error: str | None
    watcher_quiesced: bool
    ownership_resolved: bool


def _timestamp(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_SAFE_INTEGER


def _capture_receipt(value: object, source_id: str) -> bool:
    """Validate scalar shape and independent cleanup claims, never infer them."""
    if type(value) is not OperationalCaptureResult:
        return False
    if (type(value.schema_version) is not int or value.schema_version != 2
            or type(value.protocol) is not str or value.protocol != "ups-monitor.continuous.v2"
            or type(value.state) is not str or value.state not in ("unresolved", "stopped", "failed")
            or type(value.terminal_reason) is not str or value.terminal_reason not in OPERATIONAL_TERMINAL_REASONS
            or value.first_error is not None and (
                type(value.first_error) is not str or value.first_error not in _FIRST_ERRORS)
            or value.publication_error is not None and (
                type(value.publication_error) is not str or value.publication_error not in _PUBLICATION_ERRORS)
            or type(value.source_id) is not str or value.source_id != source_id
            or type(value.session_id) is not str or _SESSION_RE.fullmatch(value.session_id) is None
            or not _timestamp(value.started_at_unix_ms)
            or value.published_at_unix_ms is not None and (
                not _timestamp(value.published_at_unix_ms)
                or value.published_at_unix_ms < value.started_at_unix_ms)
            or type(value.sample_count) is not int or not 0 <= value.sample_count <= MAX_SAFE_INTEGER
            or value.end_reason is not None and (
                type(value.end_reason) is not str or value.end_reason not in (
                    "cancelled", "device_lost", "session_lost", "guard_error", "output_error"))
            or any(type(v) is not bool for v in (
                value.consumer_quiesced, value.publisher_quiesced, value.publisher_closed,
                value.terminal_published, value.ownership_resolved))):
        return False
    run = value.runner_result
    if run is not None and not _valid_runner_receipt(run):
        return False
    if value.consumer_quiesced != (run is not None and run.consumer_quiesced):
        return False
    cleanup = bool(run is not None and run.ownership_resolved
                   and value.publisher_quiesced and value.publisher_closed)
    if value.ownership_resolved != cleanup or (value.state == "unresolved") == cleanup:
        return False
    if value.terminal_published and value.published_at_unix_ms is None:
        return False
    if value.state == "stopped":
        return bool(cleanup and value.terminal_reason == "cancelled"
                    and value.end_reason == "cancelled" and run is not None
                    and run.trigger == "cancelled" and run.returncode == 0
                    and value.first_error is None and value.publication_error is None
                    and value.terminal_published)
    return True


def _successor(previous: OperationalCaptureResult, current: OperationalCaptureResult) -> bool:
    if ((previous.source_id, previous.session_id, previous.started_at_unix_ms)
            != (current.source_id, current.session_id, current.started_at_unix_ms)
            or current.sample_count < previous.sample_count):
        return False
    if (previous.published_at_unix_ms is not None
            and (current.published_at_unix_ms is None
                 or current.published_at_unix_ms < previous.published_at_unix_ms)):
        return False
    if (previous.first_error is not None and current.first_error != previous.first_error
            or previous.publication_error is not None and current.publication_error != previous.publication_error
            or previous.runner_result is not None and current.runner_result is None):
        return False
    if previous.runner_result is not None and current.runner_result is not None:
        if (current.runner_result.stdout_bytes < previous.runner_result.stdout_bytes
                or current.runner_result.stderr_bytes < previous.runner_result.stderr_bytes):
            return False
    return True


class _Control:
    def __init__(self, fd: int, cancellation: Event, finished: Event) -> None:
        self.fd, self.cancellation, self.finished = fd, cancellation, finished
        self.reason: str | None = None
        self.error: str | None = None
        self.signal_requested = False
        self.closed = False

    def request(self, reason: str, error: str | None = None) -> None:
        self.reason = self.reason or reason
        self.error = self.error or error
        self.cancellation.set()

    def watch(self) -> None:
        pending = bytearray()
        try:
            while not self.finished.is_set():
                if self.signal_requested and self.reason is None:
                    self.request("signal")
                if self.reason is not None:
                    # STOP/EOF/error ends command parsing, not FD ownership.
                    self.finished.wait(_POLL_SECONDS)
                    continue
                readable, _, _ = select.select([self.fd], [], [], _POLL_SECONDS)
                if not readable:
                    continue
                try:
                    chunk = os.read(self.fd, 5 - len(pending))
                except BlockingIOError:
                    continue
                if not chunk:
                    self.request("invalid_control", "invalid_control") if pending else self.request("app_disconnected")
                    continue
                pending.extend(chunk)
                if not b"STOP\n".startswith(pending):
                    self.request("invalid_control", "invalid_control")
                elif pending == b"STOP\n":
                    self.request("stop")
        except BaseException:
            self.request("control_failed", "control_failed")
            self.finished.wait()
        finally:
            try:
                os.close(self.fd)
                self.closed = True
            except BaseException:
                self.error = self.error or "control_close_failed"
                self.cancellation.set()


class _Owner:
    """Bounded retained references, including an uncertain watcher if needed."""

    def __init__(self, control: _Control) -> None:
        self.control = control
        self.watcher: threading.Thread | None = None
        self.capture_result: OperationalCaptureResult | None = None


def run_app_controlled_operational(
    profile: FixedOperationalProfile, *, control_read_fd: int,
    output_root: str | PathLike[str], feed_directory: str | PathLike[str], source_id: str,
    capture: Callable[..., OperationalCaptureResult] = capture_operational,
    ownership_observer: Callable[[], OperationalCaptureResult | None] = observe_operational_ownership,
) -> AppOperationalReceipt:
    """Transfer one read FIFO only after admission and invoke capture once.

    Valid unresolved capture receipts are observed on this same invocation at
    250-ms intervals until cleanup settles; cancellation never starts a retry.
    Unknown capture/observer outcomes return one unresolved receipt, cancel and
    close/quiesce control, restore handlers, and retain the owner in this module.
    The future entrypoint must keep that process alive; no new observer or
    replacement worker is created here. Rejected admission preserves caller FD.
    """
    global _active, _retained_owner
    try:
        if threading.current_thread() is not threading.main_thread():
            raise AppOperationalAdmissionError("main_thread_required")
        if _active or _retained_owner is not None:
            raise AppOperationalAdmissionError("session_ownership_unresolved")
        if type(profile) is not FixedOperationalProfile:
            raise AppOperationalAdmissionError("invalid_fixed_profile")
        if (type(source_id) is not str or ID_RE.fullmatch(source_id) is None
                or not callable(capture) or not callable(ownership_observer)):
            raise AppOperationalAdmissionError("invalid_capture_argument")
        if (type(control_read_fd) is not int or control_read_fd < 0
                or not stat.S_ISFIFO(os.fstat(control_read_fd).st_mode)
                or fcntl.fcntl(control_read_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            raise AppOperationalAdmissionError("invalid_control_pipe")
        cancellation, finished = Event(), Event()
        control = _Control(control_read_fd, cancellation, finished)
        owner = _Owner(control)
    except AppOperationalAdmissionError:
        raise
    except OSError:
        raise AppOperationalAdmissionError("invalid_control_pipe") from None
    except BaseException:
        raise AppOperationalAdmissionError("admission_failed") from None

    _active = True
    _retained_owner = owner
    previous: dict[int, object] = {}
    started = False
    start_attempted = False
    adapter_error: str | None = None
    quiesced = False
    handlers_restored = True

    def request_signal(_signum: int, _frame: object) -> None:
        # No Event lock or resource operation inside the signal handler.
        control.signal_requested = True

    try:
        os.set_inheritable(control_read_fd, False)
        os.set_blocking(control_read_fd, False)
        for signum in (signal.SIGINT, signal.SIGTERM):
            old = signal.getsignal(signum)
            previous[signum] = old
            signal.signal(signum, request_signal)
        owner.watcher = threading.Thread(target=control.watch,
                                         name="app-operational-control", daemon=False)
        start_attempted = True
        owner.watcher.start()
        started = True
        try:
            result = capture(
                profile.argv, executable_sha256=profile.executable_sha256,
                dependency_pins=profile.dependency_pins, output_root=output_root,
                feed_directory=feed_directory, source_id=source_id, cancel_event=cancellation,
            )
        except BaseException:
            cancellation.set()
            adapter_error = "capture_failed"
        else:
            if not _capture_receipt(result, source_id):
                cancellation.set()
                adapter_error = "invalid_capture_receipt"
            else:
                owner.capture_result = result
                while not owner.capture_result.ownership_resolved:
                    cancellation.set()
                    # Do not wait on cancellation: it is already set and would
                    # create a busy loop. The distinct finish event stays clear.
                    finished.wait(_OBSERVATION_SECONDS)
                    try:
                        observed = ownership_observer()
                    except BaseException:
                        adapter_error = "observer_failed"
                        break
                    if (not _capture_receipt(observed, source_id)
                            or not _successor(owner.capture_result, observed)):
                        adapter_error = "invalid_observer_receipt"
                        break
                    owner.capture_result = observed
    except BaseException:
        cancellation.set()
        adapter_error = adapter_error or "adapter_setup_failed"
    finally:
        finished.set()
        if start_attempted:
            assert owner.watcher is not None
            try:
                # start() may start its worker and then raise. Never use only
                # its return as evidence that the caller still owns the FD.
                observable = owner.watcher.ident is not None or owner.watcher.is_alive()
                if started or observable:
                    owner.watcher.join(_JOIN_SECONDS)
                    quiesced = not owner.watcher.is_alive()
                # Unknown start remains owned, even if no identity is visible.
                # Do not close from the caller while a late worker may enter.
            except BaseException:
                adapter_error = adapter_error or "watcher_join_failed"
        else:
            try:
                os.close(control_read_fd)
                control.closed = True
            except BaseException:
                adapter_error = adapter_error or "control_close_failed"
            quiesced = True
        for signum, old in previous.items():
            try:
                signal.signal(signum, old)  # type: ignore[arg-type]
            except BaseException:
                handlers_restored = False
                adapter_error = adapter_error or "handler_restore_failed"
        _active = False

    result = owner.capture_result
    resolved = bool(result is not None and result.ownership_resolved
                    and quiesced and control.closed and handlers_restored)
    if resolved:
        _retained_owner = None
    return AppOperationalReceipt(result, control.reason, adapter_error or control.error,
                                  quiesced, resolved)
