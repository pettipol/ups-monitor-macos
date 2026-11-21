"""One app-owned capture with a bounded, cancellation-only control pipe.

This module has no command-line entry point or operational profile registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
from os import PathLike
import re
import select
import signal
import stat
import threading
from threading import Event
from typing import Callable

from continuous_capture import CaptureResult, capture_continuous


_POLL_SECONDS = 0.025
_JOIN_SECONDS = 2.0
_active = False
_retained = False
_REAPED_STATUSES = frozenset({
    "exited", "timed_out", "output_limit", "output_incomplete", "cancelled",
})


class AppCaptureAdmissionError(RuntimeError):
    """Fixed-code rejection before descriptor ownership transfers to the adapter."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedCaptureProfile:
    """Integrator-admitted immutable argv and executable pin, never UI input."""

    argv: tuple[str, ...]
    executable_sha256: str

    def __post_init__(self) -> None:
        if (type(self.argv) is not tuple or not self.argv
                or any(type(value) is not str or not value or "\0" in value for value in self.argv)
                or not os.path.isabs(self.argv[0])
                or type(self.executable_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.executable_sha256) is None):
            raise ValueError("invalid_fixed_profile")


@dataclass(frozen=True, slots=True)
class AppCaptureReceipt:
    """Capture evidence plus control-channel cleanup; no raw exception text."""

    capture_result: CaptureResult | None
    control_reason: str | None
    adapter_error: str | None
    watcher_quiesced: bool
    ownership_resolved: bool


class _Control:
    def __init__(self, fd: int, cancellation: Event, finished: Event) -> None:
        self.fd, self.cancellation, self.finished = fd, cancellation, finished
        self.reason: str | None = None
        self.error: str | None = None
        self.signal_requested = False

    def request(self, reason: str, error: str | None = None) -> None:
        self.reason, self.error = reason, error
        self.cancellation.set()

    def watch(self) -> None:
        # Nonblocking reads are bounded even for a hostile writer. Closing the
        # owned read endpoint also releases a writer blocked on a full pipe.
        pending = bytearray()
        try:
            while not self.finished.is_set():
                if self.signal_requested:
                    self.request("signal")
                    return
                readable, _, _ = select.select([self.fd], [], [], _POLL_SECONDS)
                if not readable:
                    continue
                try:
                    data = os.read(self.fd, 5 - len(pending))
                except BlockingIOError:
                    continue
                if not data:
                    if pending:
                        self.request("invalid_control", "invalid_control")
                    else:
                        self.request("app_disconnected")
                    return
                pending.extend(data)
                if not b"STOP\n".startswith(pending):
                    self.request("invalid_control", "invalid_control")
                    return
                if pending == b"STOP\n":
                    self.request("stop")
                    return
        except BaseException:
            self.request("control_failed", "control_failed")
        finally:
            try:
                os.close(self.fd)
            except OSError:
                self.request("control_failed", "control_failed")


def run_app_controlled(
    profile: FixedCaptureProfile, *, control_read_fd: int,
    output_root: str | PathLike[str], feed_directory: str | PathLike[str], source_id: str,
    capture: Callable[..., CaptureResult] = capture_continuous,
) -> AppCaptureReceipt:
    """Consume an app-created pipe read end with one active session at a time.

    The caller must transfer its sole read descriptor and keep all write copies
    exclusively in the app. Rejected admission leaves the descriptor with the
    caller. After admission this function closes it, including on setup failure.
    The injected callable is an offline test seam, not a runtime profile switch.
    """
    global _active, _retained
    try:
        if threading.current_thread() is not threading.main_thread():
            raise AppCaptureAdmissionError("main_thread_required")
        if _active or _retained:
            raise AppCaptureAdmissionError("session_ownership_unresolved")
        if type(profile) is not FixedCaptureProfile:
            raise AppCaptureAdmissionError("invalid_fixed_profile")
        if type(control_read_fd) is not int or control_read_fd < 0:
            raise AppCaptureAdmissionError("invalid_control_pipe")
        if (not stat.S_ISFIFO(os.fstat(control_read_fd).st_mode)
                or fcntl.fcntl(control_read_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            raise AppCaptureAdmissionError("invalid_control_pipe")
        cancellation, finished = Event(), Event()
        control = _Control(control_read_fd, cancellation, finished)
    except AppCaptureAdmissionError:
        raise
    except OSError:
        raise AppCaptureAdmissionError("invalid_control_pipe") from None
    except BaseException:
        raise AppCaptureAdmissionError("admission_failed") from None

    _active = True
    watcher: threading.Thread | None = None
    started = False
    previous: dict[int, object] = {}
    result: CaptureResult | None = None
    adapter_error: str | None = None
    quiesced = False

    def request_signal(_signum: int, _frame: object) -> None:
        # Avoid Event locks inside a Python signal handler. The bounded watcher
        # translates this flag to the supervisor's cancellation event.
        control.signal_requested = True

    try:
        os.set_inheritable(control_read_fd, False)
        os.set_blocking(control_read_fd, False)
        for signum in (signal.SIGINT, signal.SIGTERM):
            old = signal.getsignal(signum)
            signal.signal(signum, request_signal)
            previous[signum] = old
        watcher = threading.Thread(target=control.watch, name="app-control-pipe", daemon=False)
        watcher.start()
        started = True
        try:
            result = capture(
                profile.argv, executable_sha256=profile.executable_sha256,
                output_root=output_root, feed_directory=feed_directory, source_id=source_id,
                cancel_event=cancellation, timeout_seconds=135.0,
                termination_grace_seconds=2.0, maximum_output_bytes=1_048_576,
                expected_elapsed_ms=120_000, join_seconds=2.0,
            )
            if type(result) is not CaptureResult:
                result = None
                adapter_error = "invalid_capture_receipt"
        except BaseException:
            # An unexpected exception is not evidence that children were reaped.
            cancellation.set()
            adapter_error = "capture_failed"
    except BaseException:
        cancellation.set()
        adapter_error = "adapter_setup_failed"
    finally:
        finished.set()
        if started:
            assert watcher is not None
            try:
                watcher.join(_JOIN_SECONDS)
                quiesced = not watcher.is_alive()
            except BaseException:
                adapter_error = "watcher_join_failed"
                quiesced = False
        else:
            try:
                os.close(control_read_fd)
            except BaseException:
                adapter_error = "control_close_failed"
            quiesced = True
        for signum, old in previous.items():
            try:
                signal.signal(signum, old)  # type: ignore[arg-type]
            except BaseException:
                adapter_error = "handler_restore_failed"
        # Conservatively retain ownership if the receipt is absent/unknown,
        # the tailer is active, or the channel worker failed to quiesce.
        _retained = not (
            result is not None and result.runner_status in _REAPED_STATUSES
            and result.tailer_quiesced and result.publication_error is None
            and quiesced and adapter_error is None
            and control.error is None
        )
        _active = False

    return AppCaptureReceipt(
        result, control.reason, adapter_error or control.error, quiesced, not _retained,
    )
