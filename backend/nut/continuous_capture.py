"""Offline file-tail and atomic publisher for an explicitly supplied runner."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import stat
import sys
from threading import Event, Lock, Thread
import time
from typing import Callable, Sequence
import uuid

from continuous_protocol import End, ProtocolError, Sample, StreamValidator, parse_line
from process_deadline import BoundedRunError, BoundedRunResult, RunStatus, RunTrigger, run_bounded


MAX_CAPTURE_BYTES = 1_048_576
MAX_SAMPLE_FILE_BYTES = 16_384
MAX_JOIN_SECONDS = 2.0
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)
TERMINAL_REASONS = frozenset({
    "duration_complete", "cancelled", "device_lost", "session_lost", "guard_error", "output_error",
    "protocol_error", "capture_limit", "deadline", "child_failed", "child_unreaped", "io_error",
})


@dataclass(frozen=True, slots=True)
class CaptureResult:
    state: str
    terminal_reason: str
    source_id: str
    session_id: str
    started_at_unix_ms: int
    published_at_unix_ms: int
    sample_count: int
    end_reason: str | None
    returncode: int | None
    runner_status: str
    stdout_bytes: int
    stderr_bytes: int
    publication_error: str | None
    tailer_quiesced: bool


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_uid, info.st_mode


def _has_empty_extended_acl(fd: int) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        get_acl = libc.acl_get_fd_np
        get_acl.argtypes, get_acl.restype = [ctypes.c_int, ctypes.c_int], ctypes.c_void_p
        valid_acl = libc.acl_valid
        valid_acl.argtypes, valid_acl.restype = [ctypes.c_void_p], ctypes.c_int
        get_entry = libc.acl_get_entry
        get_entry.argtypes, get_entry.restype = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int
        free_acl = libc.acl_free
        free_acl.argtypes, free_acl.restype = [ctypes.c_void_p], ctypes.c_int
        ctypes.set_errno(0)
        acl = get_acl(fd, 0x00000100)  # Darwin ACL_TYPE_EXTENDED
        if not acl:
            return ctypes.get_errno() == errno.ENOENT
        try:
            if valid_acl(acl) != 0:
                return False
            entry = ctypes.c_void_p()
            ctypes.set_errno(0)
            return get_entry(acl, 0, ctypes.byref(entry)) == -1 and ctypes.get_errno() == errno.EINVAL
        finally:
            free_acl(acl)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_mode, left.st_uid, left.st_gid, left.st_nlink) == (
        right.st_dev, right.st_ino, right.st_mode, right.st_uid, right.st_gid, right.st_nlink
    )


def _check_private_dir(path: Path) -> os.stat_result:
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise OSError("unsafe_directory")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened, named = os.fstat(fd), os.stat(path, follow_symlinks=False)
        if not _same_directory_identity(opened, named) or not _has_empty_extended_acl(fd):
            raise OSError("unsafe_directory")
    finally:
        os.close(fd)
    parent = os.stat(path.parent, follow_symlinks=False)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o022:
        raise OSError("unsafe_parent_directory")
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened, named = os.fstat(parent_fd), os.stat(path.parent, follow_symlinks=False)
        if not _same_directory_identity(opened, named) or not _has_empty_extended_acl(parent_fd):
            raise OSError("unsafe_parent_directory")
    finally:
        os.close(parent_fd)
    return info


class AtomicSamplePublisher:
    """Publish fixed-schema sample envelopes into an owner-only feed directory."""

    def __init__(self, directory: str | os.PathLike[str], source_id: str, session_id: str) -> None:
        self.directory = Path(directory)
        self.source_id, self.session_id = source_id, session_id
        _check_private_dir(self.directory)
        self.parent_directory = self.directory.parent
        self.parent_fd = os.open(self.parent_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.dir_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened = os.fstat(self.dir_fd)
        named = os.stat(self.directory, follow_symlinks=False)
        parent_opened = os.fstat(self.parent_fd)
        parent_named = os.stat(self.parent_directory, follow_symlinks=False)
        if (not _same_directory_identity(opened, named)
                or not _same_directory_identity(parent_opened, parent_named)):
            os.close(self.dir_fd)
            os.close(self.parent_fd)
            raise OSError("unsafe_directory")

    def _verify_directories(self) -> None:
        opened, named = os.fstat(self.dir_fd), os.stat(self.directory, follow_symlinks=False)
        parent_opened = os.fstat(self.parent_fd)
        parent_named = os.stat(self.parent_directory, follow_symlinks=False)
        if (not _same_directory_identity(opened, named)
                or not _same_directory_identity(parent_opened, parent_named)
                or stat.S_IMODE(opened.st_mode) != 0o700 or opened.st_uid != os.getuid()
                or stat.S_IMODE(parent_opened.st_mode) & 0o022 or parent_opened.st_uid != os.getuid()
                or not _has_empty_extended_acl(self.dir_fd)
                or not _has_empty_extended_acl(self.parent_fd)):
            raise OSError("unsafe_directory")

    def publish(self, *, state: str, started_at_unix_ms: int, terminal_reason: str | None,
                sample: dict[str, object] | None, published_at_unix_ms: int) -> None:
        if state not in ("active", "stopped", "failed"):
            raise ValueError("invalid_state")
        if (state == "active") != (terminal_reason is None):
            raise ValueError("invalid_terminal_reason")
        if terminal_reason is not None and terminal_reason not in TERMINAL_REASONS:
            raise ValueError("invalid_terminal_reason")
        self._verify_directories()
        payload = {
            "schema_version": 1,
            "protocol": "ups-monitor.continuous.v1",
            "source_id": self.source_id,
            "session_id": self.session_id,
            "state": state,
            "started_at_unix_ms": started_at_unix_ms,
            "published_at_unix_ms": published_at_unix_ms,
            "terminal_reason": terminal_reason,
            "sample": sample,
        }
        data = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
        if len(data) > MAX_SAMPLE_FILE_BYTES:
            raise OSError("capture_limit")
        self._publish_bytes(data)

    def _publish_bytes(self, data: bytes) -> None:
        """Atomically publish already serialized bytes using the v1 file guards."""
        temp_name = f".sample-{uuid.uuid4().hex}.tmp"
        fd = -1
        try:
            fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.dir_fd)
            os.fchmod(fd, 0o600)
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
                raise OSError("unsafe_file")
            if not _has_empty_extended_acl(fd):
                raise OSError("unsafe_file_acl")
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError("publication_io")
                view = view[count:]
            os.fsync(fd)
            after = os.fstat(fd)
            if ((before.st_dev, before.st_ino, before.st_uid, before.st_mode, before.st_nlink)
                    != (after.st_dev, after.st_ino, after.st_uid, after.st_mode, after.st_nlink)
                    or after.st_size != len(data) or not _has_empty_extended_acl(fd)):
                raise OSError("publication_changed")
            os.close(fd)
            fd = -1
            os.replace(temp_name, "sample.json", src_dir_fd=self.dir_fd, dst_dir_fd=self.dir_fd)
            file_fd = os.open("sample.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.dir_fd)
            try:
                final = os.fstat(file_fd)
                final_named = os.stat("sample.json", dir_fd=self.dir_fd, follow_symlinks=False)
                if (not stat.S_ISREG(final.st_mode) or final.st_uid != os.getuid()
                        or stat.S_IMODE(final.st_mode) != 0o600 or final.st_nlink != 1
                        or final.st_size != len(data)
                        or (final.st_dev, final.st_ino, final.st_mode, final.st_uid, final.st_gid, final.st_nlink)
                        != (final_named.st_dev, final_named.st_ino, final_named.st_mode, final_named.st_uid,
                            final_named.st_gid, final_named.st_nlink)):
                    raise OSError("unsafe_file")
                if not _has_empty_extended_acl(file_fd):
                    raise OSError("unsafe_file_acl")
            finally:
                os.close(file_fd)
            self._verify_directories()
            os.fsync(self.dir_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temp_name, dir_fd=self.dir_fd)
            except OSError:
                pass

    def close(self) -> None:
        if self.dir_fd >= 0:
            os.close(self.dir_fd)
            self.dir_fd = -1
        if self.parent_fd >= 0:
            os.close(self.parent_fd)
            self.parent_fd = -1


class _TailState:
    def __init__(self, validator: StreamValidator, publisher: AtomicSamplePublisher,
                 cancel_event: Event, wall_clock: Callable[[], int], mono_clock: Callable[[], int],
                 start_wall: int, expected_elapsed_ms: int) -> None:
        self.validator, self.publisher, self.cancel_event = validator, publisher, cancel_event
        self.wall_clock, self.mono_clock, self.start_wall = wall_clock, mono_clock, start_wall
        self.expected_elapsed_ms = expected_elapsed_ms
        self.lock = Lock()
        self.cleanup_lock = Lock()
        self.close_on_exit = False
        self.terminal_requested = Event()
        self.phase = "active"
        self.error: str | None = None
        self.last_sample: Sample | None = None
        self.end: End | None = None
        self.sample_count = 0
        self.quiesced = False
        self.capture = bytearray()
        self.pending = bytearray()

    def fail(self, code: str) -> None:
        with self.lock:
            if self.error is None:
                self.error = code
            self.phase = "terminal"
        self.cancel_event.set()

    def terminal(self) -> None:
        with self.lock:
            self.phase = "terminal"

    def request_terminal(self, timeout: float) -> bool:
        self.terminal_requested.set()
        if not self.lock.acquire(timeout=max(0.0, timeout)):
            return False
        try:
            self.phase = "terminal"
            return True
        finally:
            self.lock.release()

    def _close_after_exit(self) -> None:
        with self.cleanup_lock:
            if self.close_on_exit:
                self.publisher.close()

    def accept_bytes(self, new_bytes: bytes) -> None:
        self.capture.extend(new_bytes)
        if len(self.capture) > MAX_CAPTURE_BYTES:
            raise ProtocolError("capture_limit")
        self.pending.extend(new_bytes)
        while True:
            newline = self.pending.find(b"\n")
            if newline < 0:
                if len(self.pending) >= 8192:
                    raise ProtocolError("invalid_line_framing")
                return
            line = bytes(self.pending[:newline + 1])
            del self.pending[:newline + 1]
            record = parse_line(line)
            self.validator.accept(record, now_wall_ms=self.wall_clock(), now_monotonic_ms=self.mono_clock())
            if isinstance(record, Sample):
                self.last_sample = record
                self.sample_count += 1
                with self.lock:
                    if self.phase == "active" and not self.terminal_requested.is_set():
                        self.publisher.publish(
                            state="active", started_at_unix_ms=self.start_wall, terminal_reason=None,
                            sample=record.raw, published_at_unix_ms=self.wall_clock(),
                        )
            else:
                self.end = record


def _tail_capture_file(path: Path, state: _TailState, runner_done: Event) -> None:
    fd = -1
    identity: tuple[int, int, int, int] | None = None
    offset = 0
    previous = b""
    quiet = 0
    try:
        deadline = time.monotonic() + 140
        while time.monotonic() < deadline:
            try:
                named = os.stat(path, follow_symlinks=False)
            except FileNotFoundError:
                if runner_done.is_set():
                    if state.cancel_event.is_set():
                        state.quiesced = True
                        break
                    raise OSError("capture_missing")
                time.sleep(0.01)
                continue
            if fd < 0:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                opened = os.fstat(fd)
                if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                        or stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_nlink != 1
                        or _identity(opened)[:3] != _identity(named)[:3]):
                    raise OSError("unsafe_capture_file")
                identity = (opened.st_dev, opened.st_ino, opened.st_uid, opened.st_mode, opened.st_nlink)
            current = _capture_metadata(fd, path, identity, offset)
            # Confirm that bytes already consumed remain an identical prefix.
            prefix = os.pread(fd, offset, 0)
            if len(prefix) != offset or prefix != previous:
                raise OSError("capture_prefix_changed")
            if current.st_size > offset:
                chunk = os.pread(fd, current.st_size - offset, offset)
                if len(chunk) != current.st_size - offset:
                    raise OSError("capture_read_failed")
                new_offset = offset + len(chunk)
                _capture_metadata(fd, path, identity, new_offset)
                prefix_after = os.pread(fd, new_offset, 0)
                if len(prefix_after) != new_offset or prefix_after != previous + chunk:
                    raise OSError("capture_prefix_changed")
                state.accept_bytes(chunk)
                previous += chunk
                offset = new_offset
                quiet = 0
            elif runner_done.is_set():
                quiet += 1
                if quiet >= 2:
                    final_info = _capture_metadata(fd, path, identity, offset)
                    if final_info.st_size != offset:
                        quiet = 0
                        time.sleep(0.025)
                        continue
                    if state.pending:
                        raise ProtocolError("missing_newline")
                    break
            time.sleep(0.025)
        else:
            raise OSError("tailer_timeout")
        state.quiesced = True
    except ProtocolError as error:
        state.fail("capture_limit" if error.code == "capture_limit" else "protocol_error")
    except (OSError, ValueError):
        state.fail("io_error")
    except Exception:
        # Final tailer barrier: never leak a thread traceback or leave the run uncancelled.
        state.fail("io_error")
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except Exception:
                state.fail("io_error")
        state.quiesced = True
        try:
            state._close_after_exit()
        except Exception:
            state.fail("io_error")


def _capture_metadata(
    fd: int,
    path: Path,
    expected_identity: tuple[int, int, int, int, int],
    minimum_size: int,
) -> os.stat_result:
    named = os.stat(path, follow_symlinks=False)
    current = os.fstat(fd)
    named_identity = (named.st_dev, named.st_ino, named.st_uid, named.st_mode, named.st_nlink)
    current_identity = (current.st_dev, current.st_ino, current.st_uid, current.st_mode, current.st_nlink)
    if (expected_identity != named_identity or expected_identity != current_identity
            or not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid()
            or stat.S_IMODE(current.st_mode) != 0o600 or current.st_nlink != 1
            or current.st_size < minimum_size or not _has_empty_extended_acl(fd)):
        raise OSError("unsafe_capture_file")
    return current


def capture_continuous(
    argv: Sequence[str], *, executable_sha256: str, output_root: str | os.PathLike[str],
    feed_directory: str | os.PathLike[str], source_id: str, cancel_event: Event | None = None,
    runner: Callable[..., BoundedRunResult] = run_bounded, timeout_seconds: float = 135.0,
    termination_grace_seconds: float = 2.0, maximum_output_bytes: int = MAX_CAPTURE_BYTES,
    expected_elapsed_ms: int = 120_000, join_seconds: float = MAX_JOIN_SECONDS,
    wall_clock: Callable[[], int] | None = None, monotonic_clock: Callable[[], int] | None = None,
) -> CaptureResult:
    """Run one supplied hash-pinned child while a file-only tailer publishes samples.

    Production defaults preserve the frozen 135s/2s/120s contract. Tests may
    inject a fake runner and clocks; this API contains no command/profile lookup.
    """
    if not isinstance(source_id, str) or ID_RE.fullmatch(source_id) is None:
        raise ValueError("invalid_source_id")
    if type(expected_elapsed_ms) is not int or not 0 <= expected_elapsed_ms <= 120_000:
        raise ValueError("invalid_duration")
    if runner is run_bounded and (expected_elapsed_ms != 120_000 or timeout_seconds != 135.0
                                 or termination_grace_seconds != 2.0
                                 or maximum_output_bytes != MAX_CAPTURE_BYTES):
        raise ValueError("fixed_runner_limits")
    if (isinstance(join_seconds, bool) or not isinstance(join_seconds, (int, float))
            or not 0 <= join_seconds <= MAX_JOIN_SECONDS):
        raise ValueError("invalid_join_bound")
    if cancel_event is not None and not isinstance(cancel_event, Event):
        raise ValueError("invalid_cancel_event")
    cancellation = cancel_event or Event()
    output_root_path, feed_path = Path(output_root), Path(feed_directory)
    _check_private_dir(output_root_path)
    publisher = AtomicSamplePublisher(feed_path, source_id, uuid.uuid4().hex)
    session_id = publisher.session_id
    mono = monotonic_clock or (lambda: time.monotonic_ns() // 1_000_000)
    wall = wall_clock or (lambda: time.time_ns() // 1_000_000)
    state = _TailState(StreamValidator(0, 0), publisher, cancellation, wall, mono, 0, expected_elapsed_ms)
    output_directory = output_root_path / f"continuous-run-{session_id}"
    stdout_path = output_directory / "stdout.bin"
    done = Event()
    thread = Thread(target=_tail_capture_file, args=(stdout_path, state, done), daemon=True, name="continuous-file-tailer")
    started = 0
    run_result: BoundedRunResult | None = None
    run_error: str | None = None
    publication_error: str | None = None
    try:
        thread.start()
        started = int(wall())
        start_mono = int(mono())
        state.start_wall = started
        state.validator = StreamValidator(started, start_mono)
        try:
            run_result = runner(
                argv, executable_sha256=executable_sha256, output_directory=output_directory,
                timeout_seconds=timeout_seconds, termination_grace_seconds=termination_grace_seconds,
                maximum_output_bytes=maximum_output_bytes, private_nut_environment=True,
                cancel_event=cancellation,
            )
        except BoundedRunError as error:
            run_error = "child_unreaped" if error.code.value == "child_unreaped" else "io_error"
        except Exception:
            run_error = "io_error"
        terminal_lock_acquired = state.request_terminal(join_seconds)
        done.set()
        thread.join(max(0.0, min(join_seconds, MAX_JOIN_SECONDS)))
        if thread.is_alive():
            cancellation.set()
        failure = state.error or run_error
        if not terminal_lock_acquired or thread.is_alive():
            failure = failure or "io_error"
        if cancellation.is_set() and failure is None:
            failure = "cancelled"
        if run_result is None:
            failure = failure or "io_error"
        elif run_result.status is RunStatus.UNREAPED:
            failure = "child_unreaped"
        elif run_result.status is RunStatus.TIMED_OUT or run_result.trigger is RunTrigger.TIMEOUT:
            failure = "deadline"
        elif run_result.status is RunStatus.OUTPUT_LIMIT or run_result.trigger in (RunTrigger.OUTPUT_LIMIT, RunTrigger.OUTPUT_INCOMPLETE):
            failure = "capture_limit"
        elif run_result.status is RunStatus.CANCELLED or run_result.trigger is RunTrigger.CANCELLED:
            failure = failure or "cancelled"
        elif run_result.returncode != 0:
            failure = failure or "child_failed"
        end = state.end
        clean_duration = (
            failure is None and run_result is not None and run_result.status is RunStatus.EXITED
            and run_result.trigger is RunTrigger.COMPLETED and run_result.returncode == 0
            and end is not None and end.reason == "duration_complete"
            and end.elapsed_ms >= expected_elapsed_ms and state.quiesced
            and terminal_lock_acquired and not thread.is_alive()
        )
        if end is not None and end.reason == "duration_complete" and end.elapsed_ms < expected_elapsed_ms:
            failure = failure or "deadline"
        terminal_reason = "duration_complete" if clean_duration else (failure or (end.reason if end else "child_failed"))
        if terminal_reason not in TERMINAL_REASONS:
            terminal_reason = "child_failed"
        final_state = "stopped" if clean_duration else "failed"
        try:
            if not terminal_lock_acquired or thread.is_alive() or not state.quiesced:
                raise OSError("tailer_not_quiescent")
            publisher.publish(
                state=final_state, started_at_unix_ms=started, terminal_reason=terminal_reason,
                sample=None if state.last_sample is None else state.last_sample.raw,
                published_at_unix_ms=wall(),
            )
        except (OSError, ValueError):
            publication_error = "publication_failed"
            final_state, terminal_reason = "failed", "io_error"
        return CaptureResult(
            final_state, terminal_reason, source_id, session_id, started, wall(), state.sample_count,
            None if end is None else end.reason, None if run_result is None else run_result.returncode,
            "error" if run_result is None else run_result.status.value,
            0 if run_result is None else run_result.stdout_bytes,
            0 if run_result is None else run_result.stderr_bytes,
            publication_error, state.quiesced,
        )
    finally:
        if thread.is_alive():
            cancellation.set()
            done.set()
            thread.join(max(0.0, min(join_seconds, MAX_JOIN_SECONDS)))
        with state.cleanup_lock:
            if thread.is_alive():
                state.close_on_exit = True
            else:
                publisher.close()

