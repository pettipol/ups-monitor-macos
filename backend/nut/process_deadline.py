#!/usr/bin/env python3
"""Run one hash-pinned executable with bounded time and captured output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import math
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time
from typing import Callable, Sequence


class RunStatus(str, Enum):
    EXITED = "exited"
    TIMED_OUT = "timed_out"
    OUTPUT_LIMIT = "output_limit"
    OUTPUT_INCOMPLETE = "output_incomplete"
    UNREAPED = "unreaped"


class RunTrigger(str, Enum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    OUTPUT_INCOMPLETE = "output_incomplete"


class RunErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    EXECUTABLE_REJECTED = "executable_rejected"
    HASH_MISMATCH = "hash_mismatch"
    OUTPUT_LOCATION_REJECTED = "output_location_rejected"
    OUTPUT_CREATION_FAILED = "output_creation_failed"
    SPAWN_FAILED = "spawn_failed"
    OUTPUT_IO_FAILED = "output_io_failed"
    CHILD_UNREAPED = "child_unreaped"


class BoundedRunError(Exception):
    """A fixed safe error code; does not include caller data or OS text."""

    def __init__(self, code: RunErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class BoundedRunResult:
    status: RunStatus
    trigger: RunTrigger
    returncode: int | None
    stdout_bytes: int
    stderr_bytes: int


_MAX_TIMEOUT_SECONDS = 600.0
_MAX_GRACE_SECONDS = 5.0
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_READ_BUDGET_PER_TURN = 256 * 1024
_POLL_SECONDS = 0.025
_KILL_REAP_SECONDS = 1.0


def run_bounded(
    argv: Sequence[str],
    *,
    executable_sha256: str,
    output_directory: str | os.PathLike[str],
    timeout_seconds: float,
    termination_grace_seconds: float = 1,
    maximum_output_bytes: int = 1_048_576,
    private_nut_environment: bool = False,
) -> BoundedRunResult:
    """Run argv[0] only after checking its absolute path and SHA-256.

    Captured output is stored as private stdout.bin and stderr.bin files in the
    newly-created output directory. No output text or caller path is returned.
    """
    normalized_argv = _validate_parameters(
        argv, executable_sha256, output_directory, timeout_seconds,
        termination_grace_seconds, maximum_output_bytes, private_nut_environment,
    )
    executable = _verify_executable(normalized_argv[0], executable_sha256)
    parent_fd, output_fd, stdout_fd, stderr_fd, child_environment = _create_output_files(
        output_directory, private_nut_environment,
    )

    process: subprocess.Popen[bytes] | None = None
    stdout_pipe = None
    stderr_pipe = None
    selector: selectors.BaseSelector | None = None
    counts = {"stdout": 0, "stderr": 0}
    trigger = RunTrigger.COMPLETED
    status = RunStatus.EXITED
    try:
        deadline = time.monotonic() + timeout_seconds
        try:
            process = subprocess.Popen(
                normalized_argv,
                executable=executable,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                env=child_environment,
            )
        except (OSError, ValueError):
            raise BoundedRunError(RunErrorCode.SPAWN_FAILED) from None

        stdout_pipe = process.stdout
        stderr_pipe = process.stderr
        assert stdout_pipe is not None and stderr_pipe is not None
        os.set_blocking(stdout_pipe.fileno(), False)
        os.set_blocking(stderr_pipe.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(stdout_pipe, selectors.EVENT_READ, ("stdout", stdout_fd))
        selector.register(stderr_pipe, selectors.EVENT_READ, ("stderr", stderr_fd))

        while True:
            if process.poll() is not None:
                overflow, incomplete = _drain_after_exit(
                    selector, counts, maximum_output_bytes,
                )
                if overflow:
                    trigger = RunTrigger.OUTPUT_LIMIT
                    status = RunStatus.OUTPUT_LIMIT
                elif incomplete:
                    trigger = RunTrigger.OUTPUT_INCOMPLETE
                    status = RunStatus.OUTPUT_INCOMPLETE
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                trigger = RunTrigger.TIMEOUT
                status = RunStatus.TIMED_OUT
                break

            events = selector.select(min(_POLL_SECONDS, remaining))
            overflow = _consume_events(events, counts, maximum_output_bytes, selector)
            if overflow:
                trigger = RunTrigger.OUTPUT_LIMIT
                status = RunStatus.OUTPUT_LIMIT
                break

        if trigger is not RunTrigger.COMPLETED:
            if not _terminate_and_reap(
                process, termination_grace_seconds,
                lambda: _close_pipes(selector, stdout_pipe, stderr_pipe),
            ):
                status = RunStatus.UNREAPED
            stdout_pipe = None
            stderr_pipe = None

        return BoundedRunResult(
            status=status,
            trigger=trigger,
            returncode=None if status is RunStatus.UNREAPED else process.poll(),
            stdout_bytes=counts["stdout"],
            stderr_bytes=counts["stderr"],
        )
    except BoundedRunError:
        if process is not None and process.poll() is None and not _terminate_and_reap(
            process, termination_grace_seconds,
            lambda: _close_pipes(selector, stdout_pipe, stderr_pipe),
        ):
            raise BoundedRunError(RunErrorCode.CHILD_UNREAPED) from None
        raise
    except OSError:
        if process is not None and process.poll() is None and not _terminate_and_reap(
            process, termination_grace_seconds,
            lambda: _close_pipes(selector, stdout_pipe, stderr_pipe),
        ):
            raise BoundedRunError(RunErrorCode.CHILD_UNREAPED) from None
        raise BoundedRunError(RunErrorCode.OUTPUT_IO_FAILED) from None
    except BaseException:
        if process is not None and process.poll() is None and not _terminate_and_reap(
            process, termination_grace_seconds,
            lambda: _close_pipes(selector, stdout_pipe, stderr_pipe),
        ):
            raise BoundedRunError(RunErrorCode.CHILD_UNREAPED) from None
        raise
    finally:
        _close_pipes(selector, stdout_pipe, stderr_pipe)
        if selector is not None:
            selector.close()
        for descriptor in (stdout_fd, stderr_fd, output_fd, parent_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _validate_parameters(
    argv: Sequence[str],
    executable_sha256: str,
    output_directory: str | os.PathLike[str],
    timeout_seconds: float,
    termination_grace_seconds: float,
    maximum_output_bytes: int,
    private_nut_environment: bool,
) -> list[str]:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if any(not isinstance(item, str) or "\0" in item for item in argv):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if not argv[0] or not os.path.isabs(argv[0]):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if not isinstance(executable_sha256, str) or len(executable_sha256) != 64:
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if any(char not in "0123456789abcdefABCDEF" for char in executable_sha256):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if not _bounded_number(timeout_seconds, 0.01, _MAX_TIMEOUT_SECONDS):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if not _bounded_number(termination_grace_seconds, 0, _MAX_GRACE_SECONDS):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if type(maximum_output_bytes) is not int or not 1 <= maximum_output_bytes <= _MAX_OUTPUT_BYTES:
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if type(private_nut_environment) is not bool:
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    try:
        output_path = os.fspath(output_directory)
    except TypeError:
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT) from None
    if not isinstance(output_path, str) or "\0" in output_path or not os.path.isabs(output_path):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    return list(argv)


def _bounded_number(value: object, minimum: float, maximum: float) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        if value < minimum or value > maximum:
            return False
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _verify_executable(path: str, expected_hash: str) -> str:
    try:
        if not os.path.isabs(path):
            raise OSError
        path_info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(path_info.st_mode) or path_info.st_mode & 0o111 == 0:
            raise OSError
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened_info = os.fstat(descriptor)
            if not stat.S_ISREG(opened_info.st_mode) or (opened_info.st_dev, opened_info.st_ino) != (path_info.st_dev, path_info.st_ino):
                raise OSError
            digest = hashlib.sha256()
            while True:
                block = os.read(descriptor, 1024 * 1024)
                if not block:
                    break
                digest.update(block)
            final_info = os.fstat(descriptor)
            current_path_info = os.stat(path, follow_symlinks=False)
            identity = (opened_info.st_dev, opened_info.st_ino, opened_info.st_size, opened_info.st_mtime_ns, opened_info.st_ctime_ns)
            final_identity = (final_info.st_dev, final_info.st_ino, final_info.st_size, final_info.st_mtime_ns, final_info.st_ctime_ns)
            path_identity = (current_path_info.st_dev, current_path_info.st_ino, current_path_info.st_size, current_path_info.st_mtime_ns, current_path_info.st_ctime_ns)
            if identity != final_identity or identity != path_identity:
                raise OSError
        finally:
            os.close(descriptor)
    except OSError:
        raise BoundedRunError(RunErrorCode.EXECUTABLE_REJECTED) from None
    if not hmac.compare_digest(digest.hexdigest(), expected_hash.lower()):
        raise BoundedRunError(RunErrorCode.HASH_MISMATCH)
    return path


def _create_output_files(
    output_directory: str | os.PathLike[str],
    private_nut_environment: bool,
) -> tuple[int, int, int, int, dict[str, str]]:
    parent_fd = output_fd = stdout_fd = stderr_fd = -1
    try:
        output_path = Path(os.path.abspath(os.fspath(output_directory)))
        if output_path.name in ("", ".", ".."):
            raise OSError
        parent_path = output_path.parent
        parent_info = os.stat(parent_path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o022
        ):
            raise OSError
        parent_fd = os.open(parent_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        opened_parent = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(opened_parent.st_mode)
            or opened_parent.st_uid != os.getuid()
            or stat.S_IMODE(opened_parent.st_mode) & 0o022
            or (opened_parent.st_dev, opened_parent.st_ino) != (parent_info.st_dev, parent_info.st_ino)
        ):
            raise OSError

        os.mkdir(output_path.name, 0o700, dir_fd=parent_fd)
        output_fd = os.open(output_path.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        os.fchmod(output_fd, 0o700)
        output_info = os.fstat(output_fd)
        path_info = os.stat(output_path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(output_info.st_mode) or stat.S_IMODE(output_info.st_mode) != 0o700:
            raise OSError
        if (output_info.st_dev, output_info.st_ino) != (path_info.st_dev, path_info.st_ino):
            raise OSError

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        stdout_fd = os.open("stdout.bin", flags, 0o600, dir_fd=output_fd)
        stderr_fd = os.open("stderr.bin", flags, 0o600, dir_fd=output_fd)
        os.fchmod(stdout_fd, 0o600)
        os.fchmod(stderr_fd, 0o600)
        if private_nut_environment:
            _create_private_subdirectory(output_fd, "state")
            _create_private_subdirectory(output_fd, "conf")
            child_environment = {
                "NUT_STATEPATH": str(output_path / "state"),
                "NUT_CONFPATH": str(output_path / "conf"),
                "NUT_DEBUG_LEVEL": "0",
                "NUT_DEBUG_SYSLOG": "stderr",
            }
        else:
            child_environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
        return parent_fd, output_fd, stdout_fd, stderr_fd, child_environment
    except FileExistsError:
        _close_descriptors(stdout_fd, stderr_fd, output_fd, parent_fd)
        raise BoundedRunError(RunErrorCode.OUTPUT_LOCATION_REJECTED) from None
    except OSError:
        _close_descriptors(stdout_fd, stderr_fd, output_fd, parent_fd)
        raise BoundedRunError(RunErrorCode.OUTPUT_CREATION_FAILED) from None


def _create_private_subdirectory(parent_fd: int, name: str) -> None:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        os.fchmod(descriptor, 0o700)
        info = os.fstat(descriptor)
        path_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise OSError
        if (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino):
            raise OSError
    finally:
        os.close(descriptor)


def _consume_events(
    events: list[tuple[selectors.SelectorKey, int]],
    counts: dict[str, int],
    maximum_output_bytes: int,
    selector: selectors.BaseSelector,
) -> bool:
    consumed_this_turn = 0
    for key, _ in events:
        if consumed_this_turn >= _READ_BUDGET_PER_TURN:
            break
        stream_name, output_fd = key.data
        remaining = maximum_output_bytes - sum(counts.values())
        requested = min(_READ_CHUNK_BYTES, _READ_BUDGET_PER_TURN - consumed_this_turn, remaining + 1)
        try:
            chunk = os.read(key.fd, requested)
        except BlockingIOError:
            continue
        if not chunk:
            _unregister_and_close(key.fileobj, selector)
            continue
        allowed = min(len(chunk), remaining)
        if allowed:
            _write_all(output_fd, chunk[:allowed])
            counts[stream_name] += allowed
            consumed_this_turn += allowed
        if len(chunk) > allowed:
            return True
    return False


def _drain_after_exit(
    selector: selectors.BaseSelector,
    counts: dict[str, int],
    maximum_output_bytes: int,
) -> tuple[bool, bool]:
    deadline = min(time.monotonic() + 0.1, time.monotonic() + _POLL_SECONDS * 4)
    while selector.get_map() and time.monotonic() < deadline:
        events = selector.select(0)
        if not events:
            break
        if _consume_events(events, counts, maximum_output_bytes, selector):
            _close_selector_pipes(selector)
            return True, True
    incomplete = bool(selector.get_map())
    _close_selector_pipes(selector)
    return False, incomplete


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError
        view = view[written:]


def _unregister_and_close(stream: object, selector: selectors.BaseSelector) -> None:
    try:
        selector.unregister(stream)
    except (KeyError, OSError, ValueError):
        pass
    try:
        stream.close()  # type: ignore[attr-defined]
    except OSError:
        pass


def _close_selector_pipes(selector: selectors.BaseSelector) -> None:
    for key in list(selector.get_map().values()):
        _unregister_and_close(key.fileobj, selector)


def _close_pipes(selector: selectors.BaseSelector | None, *streams: object | None) -> None:
    if selector is not None:
        _close_selector_pipes(selector)
    for stream in streams:
        if stream is not None:
            try:
                stream.close()  # type: ignore[attr-defined]
            except OSError:
                pass


def _signal_child(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        if _poll_child(process) is None:
            if sig is signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
    except OSError:
        pass


def _terminate_and_reap(
    process: subprocess.Popen[bytes],
    grace_seconds: float,
    close_pipes: Callable[[], None] | None = None,
) -> bool:
    if _poll_child(process) is not None:
        return True
    _signal_child(process, signal.SIGTERM)
    if close_pipes is not None:
        close_pipes()
    if _reap_with_grace(process, grace_seconds):
        return True
    _signal_child(process, signal.SIGKILL)
    return _reap_with_grace(process, _KILL_REAP_SECONDS)


def _reap_with_grace(process: subprocess.Popen[bytes], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while _poll_child(process) is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
    return True


def _poll_child(process: subprocess.Popen[bytes]) -> int | None:
    try:
        return process.poll()
    except OSError:
        return None


def _close_descriptors(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
