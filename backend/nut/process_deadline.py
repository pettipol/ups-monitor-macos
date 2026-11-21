#!/usr/bin/env python3
"""Run one hash-pinned executable with bounded time and captured output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import errno
import math
import os
from pathlib import Path
import select
import selectors
import signal
import stat
import subprocess
from threading import Event
import time
from typing import Callable, Sequence


class RunStatus(str, Enum):
    EXITED = "exited"
    TIMED_OUT = "timed_out"
    OUTPUT_LIMIT = "output_limit"
    OUTPUT_INCOMPLETE = "output_incomplete"
    CANCELLED = "cancelled"
    UNREAPED = "unreaped"


class RunTrigger(str, Enum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    OUTPUT_INCOMPLETE = "output_incomplete"
    CANCELLED = "cancelled"


class RunErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    EXECUTABLE_REJECTED = "executable_rejected"
    HASH_MISMATCH = "hash_mismatch"
    DEPENDENCY_REJECTED = "dependency_rejected"
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
    observation: CapturedRunMetadata | None = None


@dataclass(frozen=True, slots=True)
class CapturedRunMetadata:
    maximum_output_bytes: int
    executable_sha256: str
    stdout_sha256: str
    stderr_sha256: str
    started_at_unix_seconds: int | float
    finished_at_unix_seconds: int | float


@dataclass(frozen=True, slots=True)
class DependencyPin:
    """Closed pin for one loader symlink and its regular-file target."""

    link_path: Path
    loader_relative_path: str
    symlink_target: str
    resolved_path: Path
    sha256: str


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
    cancel_event: Event | None = None,
    dependency_pins: tuple[DependencyPin, ...] = (),
) -> BoundedRunResult:
    """Run argv[0] only after checking its absolute path and SHA-256.

    Captured output is stored as private stdout.bin and stderr.bin files in the
    newly-created output directory. No output text or caller path is returned.
    An optional event starts an owned process session; cancellation and cleanup
    then target that process group and require the leader reaped plus the group
    absent. Without an event, legacy direct-child behavior is unchanged.
    Dependency pins receive a second check before spawn; this narrows but
    cannot remove the loader-resolution TOCTOU window.
    """
    normalized_argv = _validate_parameters(
        argv, executable_sha256, output_directory, timeout_seconds,
        termination_grace_seconds, maximum_output_bytes, private_nut_environment,
        cancel_event, dependency_pins,
    )
    if cancel_event is not None and cancel_event.is_set():
        return BoundedRunResult(RunStatus.CANCELLED, RunTrigger.CANCELLED, None, 0, 0)

    executable_identity: tuple[int, int, int, int, int] | None = None
    dependency_identities: tuple[tuple[tuple[int, int, int, int, int], ...], ...] = ()
    if dependency_pins:
        executable, executable_identity = _verify_executable_snapshot(
            normalized_argv[0], executable_sha256,
        )
        dependency_identities = _verify_dependency_pins(dependency_pins)
    else:
        executable = _verify_executable(normalized_argv[0], executable_sha256)
    if cancel_event is not None and cancel_event.is_set():
        return BoundedRunResult(RunStatus.CANCELLED, RunTrigger.CANCELLED, None, 0, 0)

    parent_fd, output_fd, stdout_fd, stderr_fd, child_environment = _create_output_files(
        output_directory, private_nut_environment,
    )

    process: subprocess.Popen[bytes] | None = None
    owned_pgid: int | None = None
    stdout_pipe = None
    stderr_pipe = None
    selector: selectors.BaseSelector | None = None
    output_streams: list[tuple[str, object, int]] = []
    counts = {"stdout": 0, "stderr": 0}
    capture_hashes = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
    started_at = None
    trigger = RunTrigger.COMPLETED
    status = RunStatus.EXITED
    try:
        if dependency_pins:
            checked_executable, checked_identity = _verify_executable_snapshot(
                normalized_argv[0], executable_sha256,
            )
            if checked_executable != executable or checked_identity != executable_identity:
                raise BoundedRunError(RunErrorCode.EXECUTABLE_REJECTED)
            checked_dependencies = _verify_dependency_pins(dependency_pins)
            if checked_dependencies != dependency_identities:
                raise BoundedRunError(RunErrorCode.DEPENDENCY_REJECTED)
            for pin, snapshot in zip(dependency_pins, checked_dependencies, strict=True):
                _assert_dependency_snapshot(pin, snapshot)
            _assert_executable_snapshot(normalized_argv[0], executable_identity)
        if dependency_pins and cancel_event is not None and cancel_event.is_set():
            return BoundedRunResult(RunStatus.CANCELLED, RunTrigger.CANCELLED, None, 0, 0)

        deadline = time.monotonic() + timeout_seconds
        popen_kwargs = {
            "executable": executable,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "close_fds": True,
            "env": child_environment,
        }
        if cancel_event is not None:
            popen_kwargs["start_new_session"] = True

        if cancel_event is not None and cancel_event.is_set():
            return BoundedRunResult(RunStatus.CANCELLED, RunTrigger.CANCELLED, None, 0, 0)
        started_at = _timestamp_sample()
        try:
            process = subprocess.Popen(
                normalized_argv,
                **popen_kwargs,
            )
        except (OSError, ValueError):
            raise BoundedRunError(RunErrorCode.SPAWN_FAILED) from None
        if cancel_event is not None:
            # start_new_session makes this PID the process-group/session ID.
            # Keep the owned ID; never rediscover it after the leader exits.
            owned_pgid = process.pid

        stdout_pipe = process.stdout
        stderr_pipe = process.stderr
        assert stdout_pipe is not None and stderr_pipe is not None
        output_streams = [
            ("stdout", stdout_pipe, stdout_fd),
            ("stderr", stderr_pipe, stderr_fd),
        ]
        os.set_blocking(stdout_pipe.fileno(), False)
        os.set_blocking(stderr_pipe.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(stdout_pipe, selectors.EVENT_READ, ("stdout", stdout_fd))
        selector.register(stderr_pipe, selectors.EVENT_READ, ("stderr", stderr_fd))

        while True:
            if cancel_event is not None and cancel_event.is_set():
                trigger = RunTrigger.CANCELLED
                status = RunStatus.CANCELLED
                break

            if process.poll() is not None:
                overflow, incomplete = _drain_after_exit(
                    selector, counts, maximum_output_bytes, capture_hashes,
                )
                if overflow:
                    trigger = RunTrigger.OUTPUT_LIMIT
                    status = RunStatus.OUTPUT_LIMIT
                elif incomplete:
                    trigger = RunTrigger.OUTPUT_INCOMPLETE
                    status = RunStatus.OUTPUT_INCOMPLETE
                if owned_pgid is not None and not _process_group_absent(owned_pgid):
                    # A leader exit is not campaign completion while its owned
                    # session still contains a descendant or cannot be checked.
                    trigger = RunTrigger.OUTPUT_INCOMPLETE
                    status = RunStatus.OUTPUT_INCOMPLETE
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                trigger = RunTrigger.TIMEOUT
                status = RunStatus.TIMED_OUT
                break

            events = selector.select(min(_POLL_SECONDS, remaining))
            overflow = _consume_events(events, counts, maximum_output_bytes, selector, capture_hashes)
            if overflow:
                trigger = RunTrigger.OUTPUT_LIMIT
                status = RunStatus.OUTPUT_LIMIT
                break

        if trigger is not RunTrigger.COMPLETED:
            if not _terminate_and_reap(
                process, termination_grace_seconds, selector, output_streams, owned_pgid,
            ):
                status = RunStatus.UNREAPED

        finished_at = _timestamp_sample()
        observation = None
        if started_at is not None and finished_at is not None and finished_at >= started_at:
            observation = CapturedRunMetadata(
                maximum_output_bytes=maximum_output_bytes,
                executable_sha256=executable_sha256.lower(),
                stdout_sha256=capture_hashes["stdout"].hexdigest(),
                stderr_sha256=capture_hashes["stderr"].hexdigest(),
                started_at_unix_seconds=started_at,
                finished_at_unix_seconds=finished_at,
            )
        return BoundedRunResult(
            status=status,
            trigger=trigger,
            returncode=None if status is RunStatus.UNREAPED else process.poll(),
            stdout_bytes=counts["stdout"],
            stderr_bytes=counts["stderr"],
            observation=observation,
        )
    except BoundedRunError:
        if process is not None and _cleanup_needed(process, owned_pgid) and not _terminate_and_reap(
            process, termination_grace_seconds, selector, output_streams, owned_pgid,
        ):
            raise BoundedRunError(RunErrorCode.CHILD_UNREAPED) from None
        raise
    except OSError:
        if process is not None and _cleanup_needed(process, owned_pgid) and not _terminate_and_reap(
            process, termination_grace_seconds, selector, output_streams, owned_pgid,
        ):
            raise BoundedRunError(RunErrorCode.CHILD_UNREAPED) from None
        raise BoundedRunError(RunErrorCode.OUTPUT_IO_FAILED) from None
    except BaseException:
        if process is not None and _cleanup_needed(process, owned_pgid) and not _terminate_and_reap(
            process, termination_grace_seconds, selector, output_streams, owned_pgid,
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
    cancel_event: Event | None,
    dependency_pins: tuple[DependencyPin, ...],
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
    if cancel_event is not None and not isinstance(cancel_event, Event):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    if type(dependency_pins) is not tuple or any(type(pin) is not DependencyPin for pin in dependency_pins):
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


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _close_hash_descriptor(
    descriptor: int,
    error_code: RunErrorCode,
    *,
    preserve_error: bool,
) -> None:
    try:
        os.close(descriptor)
    except BaseException as close_error:
        if preserve_error:
            return
        if isinstance(close_error, OSError):
            raise BoundedRunError(error_code) from None
        raise


def _verify_executable_snapshot(
    path: str,
    expected_hash: str,
) -> tuple[str, tuple[int, int, int, int, int]]:
    descriptor = -1
    verification_succeeded = False
    try:
        if not os.path.isabs(path) or not hasattr(os, "O_NOFOLLOW"):
            raise OSError
        path_info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(path_info.st_mode) or path_info.st_mode & 0o111 == 0:
            raise OSError
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
        )
        opened_info = os.fstat(descriptor)
        if not stat.S_ISREG(opened_info.st_mode) or _identity(opened_info) != _identity(path_info):
            raise OSError
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        final_info = os.fstat(descriptor)
        current_path_info = os.stat(path, follow_symlinks=False)
        if (
            _identity(opened_info) != _identity(final_info)
            or _identity(final_info) != _identity(current_path_info)
        ):
            raise OSError
        if not hmac.compare_digest(digest.hexdigest(), expected_hash.lower()):
            raise BoundedRunError(RunErrorCode.HASH_MISMATCH)
        verification_succeeded = True
        return path, _identity(final_info)
    except BoundedRunError:
        raise
    except OSError:
        raise BoundedRunError(RunErrorCode.EXECUTABLE_REJECTED) from None
    finally:
        if descriptor >= 0:
            _close_hash_descriptor(
                descriptor,
                RunErrorCode.EXECUTABLE_REJECTED,
                preserve_error=not verification_succeeded,
            )


def _verify_dependency_pins(
    pins: tuple[DependencyPin, ...],
) -> tuple[tuple[tuple[int, int, int, int, int], ...], ...]:
    snapshots: list[tuple[tuple[int, int, int, int, int], ...]] = []
    try:
        for pin in pins:
            snapshots.append(_verify_dependency_pin(pin))
    except BoundedRunError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise BoundedRunError(RunErrorCode.DEPENDENCY_REJECTED) from None
    return tuple(snapshots)


def _verify_dependency_pin(
    pin: DependencyPin,
) -> tuple[tuple[int, int, int, int, int], ...]:
    descriptor = -1
    verification_succeeded = False
    try:
        if (
            not isinstance(pin.link_path, Path)
            or not isinstance(pin.resolved_path, Path)
            or not pin.link_path.is_absolute()
            or not pin.resolved_path.is_absolute()
            or not isinstance(pin.loader_relative_path, str)
            or not isinstance(pin.symlink_target, str)
            or not isinstance(pin.sha256, str)
            or "\0" in pin.loader_relative_path
            or "\0" in pin.symlink_target
            or len(pin.sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in pin.sha256)
            or not hasattr(os, "O_NOFOLLOW")
        ):
            raise OSError
        relative_path = Path(pin.loader_relative_path)
        if (
            relative_path.is_absolute()
            or not relative_path.parts
            or any(part in ("", ".", "..") for part in relative_path.parts)
            or str(relative_path) != pin.loader_relative_path
        ):
            raise OSError
        target_path = Path(pin.symlink_target)
        if target_path.is_absolute():
            raise OSError

        link_before = pin.link_path.lstat()
        if not stat.S_ISLNK(link_before.st_mode):
            raise OSError
        target_before = os.readlink(pin.link_path)
        if target_before != pin.symlink_target:
            raise OSError

        loader_path = pin.link_path / relative_path
        expected_resolved = (pin.link_path.parent / target_path / relative_path).resolve(strict=True)
        loader_resolved = loader_path.resolve(strict=True)
        if expected_resolved != pin.resolved_path or loader_resolved != pin.resolved_path:
            raise OSError

        target_info = pin.resolved_path.lstat()
        if not stat.S_ISREG(target_info.st_mode):
            raise OSError
        descriptor = os.open(
            pin.resolved_path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
        )
        opened_info = os.fstat(descriptor)
        if not stat.S_ISREG(opened_info.st_mode) or _identity(opened_info) != _identity(target_info):
            raise OSError
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        final_info = os.fstat(descriptor)
        target_after = pin.resolved_path.lstat()
        link_after = pin.link_path.lstat()
        target_after_link = os.readlink(pin.link_path)
        resolved_after = loader_path.resolve(strict=True)
        if (
            not stat.S_ISREG(final_info.st_mode)
            or _identity(opened_info) != _identity(final_info)
            or _identity(final_info) != _identity(target_after)
            or not stat.S_ISLNK(link_after.st_mode)
            or _identity(link_before) != _identity(link_after)
            or target_after_link != target_before
            or resolved_after != pin.resolved_path
        ):
            raise OSError
        if not hmac.compare_digest(digest.hexdigest(), pin.sha256.lower()):
            raise OSError
        verification_succeeded = True
        return (_identity(link_after), _identity(final_info))
    except (OSError, RuntimeError, TypeError, ValueError):
        raise BoundedRunError(RunErrorCode.DEPENDENCY_REJECTED) from None
    finally:
        if descriptor >= 0:
            _close_hash_descriptor(
                descriptor,
                RunErrorCode.DEPENDENCY_REJECTED,
                preserve_error=not verification_succeeded,
            )


def _assert_executable_snapshot(
    path: str,
    expected_identity: tuple[int, int, int, int, int] | None,
) -> None:
    try:
        info = os.stat(path, follow_symlinks=False)
        if (
            expected_identity is None
            or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o111 == 0
            or _identity(info) != expected_identity
        ):
            raise OSError
    except OSError:
        raise BoundedRunError(RunErrorCode.EXECUTABLE_REJECTED) from None


def _assert_dependency_snapshot(
    pin: DependencyPin,
    expected_identity: tuple[tuple[int, int, int, int, int], ...],
) -> None:
    try:
        if len(expected_identity) != 2:
            raise OSError
        link_info = pin.link_path.lstat()
        if not stat.S_ISLNK(link_info.st_mode) or _identity(link_info) != expected_identity[0]:
            raise OSError
        if os.readlink(pin.link_path) != pin.symlink_target:
            raise OSError
        loader_path = pin.link_path / pin.loader_relative_path
        if loader_path.resolve(strict=True) != pin.resolved_path:
            raise OSError
        file_info = pin.resolved_path.lstat()
        if not stat.S_ISREG(file_info.st_mode) or _identity(file_info) != expected_identity[1]:
            raise OSError
    except (OSError, RuntimeError, TypeError, ValueError):
        raise BoundedRunError(RunErrorCode.DEPENDENCY_REJECTED) from None


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
    capture_hashes: dict[str, object] | None = None,
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
            if capture_hashes is not None:
                capture_hashes[stream_name].update(chunk[:allowed])  # type: ignore[attr-defined]
            consumed_this_turn += allowed
        if len(chunk) > allowed:
            return True
    return False


def _drain_after_exit(
    selector: selectors.BaseSelector,
    counts: dict[str, int],
    maximum_output_bytes: int,
    capture_hashes: dict[str, object] | None = None,
) -> tuple[bool, bool]:
    deadline = min(time.monotonic() + 0.1, time.monotonic() + _POLL_SECONDS * 4)
    while selector.get_map() and time.monotonic() < deadline:
        events = selector.select(0)
        if not events:
            break
        if _consume_events(events, counts, maximum_output_bytes, selector, capture_hashes):
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


def _timestamp_sample() -> int | float | None:
    try:
        value = time.time()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return value
    except Exception:
        return None


def _unregister_and_close(stream: object, selector: selectors.BaseSelector | None) -> None:
    if selector is not None:
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


def _process_group_absent(owned_pgid: int) -> bool:
    """Return true only when the runner-owned group is proven absent."""
    try:
        os.killpg(owned_pgid, 0)
        return False
    except OSError as error:
        return error.errno == errno.ESRCH


def _cleanup_needed(process: subprocess.Popen[bytes], owned_pgid: int | None) -> bool:
    if _poll_child(process) is None:
        return True
    return owned_pgid is not None and not _process_group_absent(owned_pgid)


def _signal_child(
    process: subprocess.Popen[bytes], sig: signal.Signals, owned_pgid: int | None = None,
) -> None:
    if owned_pgid is not None:
        group_signal_sent = False
        try:
            os.killpg(owned_pgid, sig)
            group_signal_sent = True
        except OSError:
            pass

        signal_leader_directly = not group_signal_sent
        if group_signal_sent and _poll_child(process) is None:
            try:
                # Inspect only our waitable Popen leader, never a PID from the group.
                current_pgid = os.getpgid(process.pid)
            except OSError:
                signal_leader_directly = True
            else:
                signal_leader_directly = current_pgid != owned_pgid
            # This membership observation is best-effort: the leader can move
            # groups again after the query, so it is not an atomic safety guarantee.

        # On a failed group delivery, unavailable membership, or an observed
        # escape, fall back only through the still-owned Popen handle.
        if signal_leader_directly and _poll_child(process) is None:
            try:
                process.terminate() if sig is signal.SIGTERM else process.kill()
            except OSError:
                pass
        return
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
    selector: selectors.BaseSelector | None,
    streams: list[tuple[str, object, int]],
    owned_pgid: int | None = None,
) -> bool:
    """Bound termination; owned groups must be absent as well as leader reaped.

    Only the Popen leader is a waitable child. Descendants are signalled as an
    owned group but cannot be reaped here; uncertain group absence fails closed.
    """
    if _poll_child(process) is not None and (
        owned_pgid is None or _process_group_absent(owned_pgid)
    ):
        _drain_after_reap(selector, streams)
        return True
    _signal_child(process, signal.SIGTERM, owned_pgid)
    try:
        if _reap_with_grace(
            process, grace_seconds, selector, streams, owned_pgid=owned_pgid,
        ):
            return True
    except BaseException:
        _signal_child(process, signal.SIGKILL, owned_pgid)
        if not _reap_with_grace(process, _KILL_REAP_SECONDS, selector, streams,
                                 drain=False, owned_pgid=owned_pgid):
            return False
        raise
    _signal_child(process, signal.SIGKILL, owned_pgid)
    return _reap_with_grace(
        process, _KILL_REAP_SECONDS, selector, streams, owned_pgid=owned_pgid,
    )


def _reap_with_grace(
    process: subprocess.Popen[bytes],
    seconds: float,
    selector: selectors.BaseSelector | None,
    streams: list[tuple[str, object, int]],
    *,
    drain: bool = True,
    owned_pgid: int | None = None,
) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if _poll_child(process) is not None and (
            owned_pgid is None or _process_group_absent(owned_pgid)
        ):
            if drain:
                _drain_after_reap(selector, streams)
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if drain:
            _drain_ready_pipes(
                selector, streams, min(_POLL_SECONDS, remaining),
            )
        else:
            time.sleep(min(_POLL_SECONDS, remaining))


def _drain_ready_pipes(
    selector: selectors.BaseSelector | None,
    streams: list[tuple[str, object, int]],
    timeout: float,
) -> bool:
    active: dict[int, object] = {}
    for _, stream, _ in streams:
        if getattr(stream, "closed", True):
            continue
        try:
            active[stream.fileno()] = stream  # type: ignore[attr-defined]
        except (OSError, ValueError):
            continue

    if not active:
        time.sleep(timeout)
        return False

    readable, _, _ = select.select(list(active), [], [], timeout)
    consumed_this_turn = 0
    for descriptor in readable:
        budget_left = _READ_BUDGET_PER_TURN - consumed_this_turn
        if budget_left <= 0:
            break
        stream = active[descriptor]
        requested = min(_READ_CHUNK_BYTES, budget_left)
        try:
            chunk = os.read(descriptor, requested)
        except BlockingIOError:
            continue
        if not chunk:
            _unregister_and_close(stream, selector)
            continue

        consumed_this_turn += len(chunk)
    return bool(readable)


def _drain_after_reap(
    selector: selectors.BaseSelector | None,
    streams: list[tuple[str, object, int]],
) -> None:
    deadline = time.monotonic() + _POLL_SECONDS * 4
    while time.monotonic() < deadline:
        if not _drain_ready_pipes(selector, streams, 0):
            return


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


# Operational v2 is deliberately separate from every v1 entry point above.
# These hashes cover bytes read from pipes, never the empty capture files.
@dataclass(frozen=True, slots=True)
class StreamingRunResult:
    trigger: str
    returncode: int | None
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str
    leader_reaped: bool
    group_absent: bool
    stdout_eof: bool
    stderr_eof: bool
    consumer_quiesced: bool

    @property
    def ownership_resolved(self) -> bool:
        return all((self.leader_reaped, self.group_absent, self.stdout_eof,
                    self.stderr_eof, self.consumer_quiesced))


_STREAM_RATE_BYTES = 262_144
_STREAM_MAX_COUNTER = (1 << 63) - 1
_STREAM_DRAIN_SECONDS = 0.1


class _StreamingClock:
    def __init__(self) -> None:
        self.last: float | None = None

    def sample(self) -> float:
        value = time.monotonic()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _StreamingFailure("clock_invalid")
        value = float(value)
        if self.last is not None and value < self.last:
            raise _StreamingFailure("clock_regression")
        self.last = value
        return value


class _StreamingFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StreamingPipes:
    """Fixed-size stream accounting; actual EOF is independent of close()."""

    def __init__(self, selector, dispatch, cancel_event: Event, clock: _StreamingClock, start: float) -> None:
        # Operational-only dependency: frozen v1 execution does not import it.
        from cleanup_diagnostics import CleanupDiagnosticParser

        self.selector = selector
        self.dispatch = dispatch
        self.cancel_event = cancel_event
        self.clock = clock
        self.start = start
        self.window = 0
        self.window_bytes = 0
        self.counts = {"stdout": 0, "stderr": 0}
        self.hashes = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
        self.eof = {"stdout": False, "stderr": False}
        self.discard = False
        self.failure: str | None = None
        self.term_sent = False
        self.kill_sent = False
        self.kill_deadline: float | None = None
        self.cleanup_diagnostic = CleanupDiagnosticParser()

    def abort(self, code: str) -> None:
        if self.failure is None:
            self.failure = code
        self.cancel_event.set()
        self.discard = True
        self.dispatch.request_stop()

    def consume(self, timeout: float) -> None:
        # A bounded read per ready pipe and per turn; no queue-space waits.
        events = self.selector.select(timeout)
        consumed = 0
        for key, _ in events:
            if consumed >= _READ_BUDGET_PER_TURN:
                break
            # Cancellation is observed at every read, but terminal bytes must
            # still reach the sink during graceful Stop.
            self.cancel_event.is_set()
            name = key.data
            try:
                chunk = os.read(key.fd, min(_READ_CHUNK_BYTES, _READ_BUDGET_PER_TURN - consumed))
            except BlockingIOError:
                continue
            if not chunk:
                self.eof[name] = True
                _unregister_and_close(key.fileobj, self.selector)
                if name == "stdout" and not self.discard:
                    self.dispatch.close_input()
                continue
            consumed += len(chunk)
            # Even discarded cleanup bytes have bounded counters and hashes.
            self.hashes[name].update(chunk)
            if name == "stderr":
                self.cleanup_diagnostic.accept(chunk)
            if self.counts[name] > _STREAM_MAX_COUNTER - len(chunk):
                self.abort("output_counter_overflow")
                continue
            self.counts[name] += len(chunk)
            try:
                now = self.clock.sample()
                window = int(now - self.start)
            except _StreamingFailure as error:
                self.abort(error.code)
                continue
            if window != self.window:
                self.window = window
                self.window_bytes = 0
            if len(chunk) > _STREAM_RATE_BYTES - self.window_bytes:
                self.abort("output_rate_limit")
                continue
            self.window_bytes += len(chunk)
            if name == "stdout" and not self.discard and not self.dispatch.submit(chunk):
                self.abort(self.dispatch.snapshot().error or "consumer_error")


# At most one operational runner owns resources in this module. A failed
# cleanup retains the exact owner, including a blocked callback and saved PGID;
# it cannot be displaced by a later run. No unbounded registry/history exists.
from threading import Lock as _StreamingLock
_streaming_admission = _StreamingLock()
_retained_streaming_owner: object | None = None


class _StreamingHealth:
    """One accepted-progress anchor; a late callback cannot revive a lease."""
    def __init__(self, sink, event: Event, startup: float, progress: float) -> None:
        self.sink, self.event = sink, event
        self.startup, self.progress = startup, progress
        self.start = 0.0
        self.last: float | None = None
        self.failure: str | None = None
        self.lock = _StreamingLock()

    def accept(self, chunk: bytes) -> bool:
        # Callback and clock are both outside the state lock. This is the sole
        # consumer thread; state reads by the supervisor are short snapshots.
        accepted = self.sink(chunk)
        if type(accepted) is not bool or not accepted or not chunk or self.event.is_set():
            return accepted
        now = time.monotonic()
        with self.lock:
            if self.event.is_set():
                return accepted
            if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
                self.failure = self.failure or "clock_invalid"
            elif now < (self.last if self.last is not None else self.start):
                self.failure = self.failure or "clock_regression"
            elif now >= ((self.start + self.startup) if self.last is None else (self.last + self.progress)):
                self.failure = self.failure or ("startup_deadline" if self.last is None else "progress_deadline")
            elif self.failure is None:
                self.last = float(now)
            failed = self.failure is not None
        if failed:
            self.event.set()
            return False
        return True

    def snapshot(self) -> tuple[float | None, str | None]:
        with self.lock:
            return self.last, self.failure

    def check_deadline(self, now: float) -> tuple[float, str | None]:
        """Decide and latch expiry against the current anchor atomically.

        The supervisor samples its clock before taking this lock. A publication
        which already renewed the lease must therefore participate in this
        decision, rather than being hidden by an earlier unlocked snapshot.
        """
        with self.lock:
            deadline = ((self.start + self.startup) if self.last is None
                        else (self.last + self.progress))
            if self.failure is None and not self.event.is_set() and now >= deadline:
                self.failure = "startup_deadline" if self.last is None else "progress_deadline"
            failure = self.failure
        if failure is not None:
            self.event.set()
        return deadline, failure


def run_streaming(
    argv: Sequence[str], *, executable_sha256: str,
    output_directory: str | os.PathLike[str], cancel_event: Event,
    on_stdout: Callable[[bytes], bool],
    startup_timeout_seconds: float = 35.0,
    progress_timeout_seconds: float = 15.0,
    termination_grace_seconds: float = 2.0,
    private_nut_environment: bool = False,
    dependency_pins: tuple[DependencyPin, ...] = (),
) -> StreamingRunResult:
    """Own one session without an overall deadline or raw output persistence.

    The sink must honor cancel_event to freeze active publication while still
    admitting its terminal record. Cancellation cannot interrupt a callback.
    Unresolved ownership is retained in the single module slot, and subsequent
    operational calls fail closed. V1 execution remains independent.
    """
    global _retained_streaming_owner
    from bounded_stream_dispatch import BoundedStreamDispatch

    normalized = _validate_parameters(
        argv, executable_sha256, output_directory, 1.0,
        termination_grace_seconds, 1, private_nut_environment,
        cancel_event, dependency_pins,
    )
    if (not isinstance(cancel_event, Event) or not callable(on_stdout)
            or not _bounded_number(startup_timeout_seconds, 0.0, 600.0)
            or startup_timeout_seconds <= 0
            or not _bounded_number(progress_timeout_seconds, 0.0, 600.0)
            or progress_timeout_seconds <= 0
            or termination_grace_seconds > 2.0):
        raise BoundedRunError(RunErrorCode.INVALID_ARGUMENT)
    empty = hashlib.sha256().hexdigest()
    if cancel_event.is_set():
        return StreamingRunResult("cancelled", None, 0, 0, empty, empty, True, True, True, True, True)
    if not _streaming_admission.acquire(blocking=False):
        raise _StreamingFailure("streaming_owner_active")
    if _retained_streaming_owner is not None:
        _streaming_admission.release()
        raise _StreamingFailure("streaming_owner_retained")

    process = None
    pgid = None
    selector = None
    stdout_pipe = stderr_pipe = None
    descriptors: tuple[int, ...] = ()
    health = None
    dispatch = None
    pipes = None
    trigger = "runner_error"
    clock = None
    abnormal: BaseException | None = None
    result = None
    try:
        health = _StreamingHealth(on_stdout, cancel_event, startup_timeout_seconds, progress_timeout_seconds)
        dispatch = BoundedStreamDispatch(health.accept, monotonic_clock=lambda: time.monotonic())
        clock = _StreamingClock()
        executable, identity = _verify_executable_snapshot(normalized[0], executable_sha256)
        dependencies = _verify_dependency_pins(dependency_pins)
        if cancel_event.is_set():
            return StreamingRunResult("cancelled", None, 0, 0, empty, empty, True, True, True, True, True)
        parent_fd, output_fd, stdout_fd, stderr_fd, environment = _create_output_files(
            output_directory, private_nut_environment,
        )
        descriptors = (stdout_fd, stderr_fd, output_fd, parent_fd)
        # The same descriptor/snapshot admission as v1, including a second pin
        # check immediately before spawn. Empty capture files are never written.
        checked_executable, checked_identity = _verify_executable_snapshot(normalized[0], executable_sha256)
        checked_dependencies = _verify_dependency_pins(dependency_pins)
        if checked_executable != executable or checked_identity != identity:
            raise BoundedRunError(RunErrorCode.EXECUTABLE_REJECTED)
        if checked_dependencies != dependencies:
            raise BoundedRunError(RunErrorCode.DEPENDENCY_REJECTED)
        for pin, snapshot in zip(dependency_pins, checked_dependencies, strict=True):
            _assert_dependency_snapshot(pin, snapshot)
        _assert_executable_snapshot(normalized[0], identity)
        if cancel_event.is_set():
            return StreamingRunResult("cancelled", None, 0, 0, empty, empty, True, True, True, True, True)
        dispatch.start()
        if dispatch.snapshot().error:
            raise _StreamingFailure("consumer_error")
        start = clock.sample()
        health.start = start
        # Allocate stream state before spawn so every post-spawn exception has
        # a fixed-size owner and independent EOF facts to retain.
        selector = selectors.DefaultSelector()
        pipes = _StreamingPipes(selector, dispatch, cancel_event, clock, start)
        try:
            process = subprocess.Popen(normalized, executable=executable, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                       close_fds=True, env=environment, start_new_session=True)
        except (OSError, ValueError):
            raise BoundedRunError(RunErrorCode.SPAWN_FAILED) from None
        pgid = process.pid  # Saved once; never rediscover after leader exit.
        stdout_pipe, stderr_pipe = process.stdout, process.stderr
        assert stdout_pipe is not None and stderr_pipe is not None
        for name, pipe in (("stdout", stdout_pipe), ("stderr", stderr_pipe)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while True:
            snapshot = dispatch.snapshot()
            now = clock.sample()
            deadline, health_failure = health.check_deadline(now)
            if snapshot.error is not None:
                trigger = snapshot.error
                pipes.abort(trigger)
                break
            if health_failure is not None:
                trigger = health_failure
                break
            if cancel_event.is_set():
                _, concurrent_failure = health.snapshot()
                trigger = concurrent_failure or "cancelled"
                break
            if pipes.failure is not None:
                trigger = pipes.failure
                break
            returncode = _poll_child(process)
            if returncode is not None:
                trigger = "child_exited" if returncode == 0 else "child_nonzero_exit"
                break
            pipes.consume(min(_POLL_SECONDS, deadline - now))
        cancel_event.set()
    except BaseException as error:
        abnormal = error
        trigger = error.code if isinstance(error, _StreamingFailure) else "runner_error"
        cancel_event.set()
    finally:
        # A cleanup path is always entered after spawn, including setup errors.
        if process is not None:
            try:
                # Repair partial selector setup solely for bounded cleanup.
                for name, pipe in (("stdout", stdout_pipe), ("stderr", stderr_pipe)):
                    if pipe is not None and not pipe.closed:
                        try:
                            os.set_blocking(pipe.fileno(), False)
                            selector.get_key(pipe)
                        except KeyError:
                            selector.register(pipe, selectors.EVENT_READ, name)
                if abnormal is not None:
                    pipes.abort(trigger)
                _streaming_cleanup(process, pgid, pipes, termination_grace_seconds)
            except BaseException:
                # Cleanup exceptions must never skip escalation or retention.
                if not pipes.kill_sent:
                    pipes.kill_sent = True
                    pipes.kill_deadline = time.perf_counter() + _KILL_REAP_SECONDS
                    _signal_child(process, signal.SIGKILL, pgid)
                end = pipes.kill_deadline or time.perf_counter()
                while _cleanup_needed(process, pgid):
                    remaining = end - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(_POLL_SECONDS, remaining))
                dispatch.request_stop()
                if trigger == "cancelled":
                    trigger = "cleanup_error"
            if pipes.failure is not None and trigger in ("cancelled", "child_exited"):
                trigger = pipes.failure
        snapshot = None
        if dispatch is not None:
            if process is None or (pipes is not None and not pipes.eof["stdout"]):
                dispatch.request_stop()
            snapshot = dispatch.join(2.0)
            if not snapshot.quiesced:
                dispatch.request_stop()
            if snapshot.error is not None and trigger in ("cancelled", "child_exited"):
                trigger = snapshot.error
        if process is not None:
            result = StreamingRunResult(
                trigger, _poll_child(process), pipes.counts["stdout"], pipes.counts["stderr"],
                pipes.hashes["stdout"].hexdigest(), pipes.hashes["stderr"].hexdigest(),
                _poll_child(process) is not None, _process_group_absent(pgid),
                pipes.eof["stdout"], pipes.eof["stderr"], snapshot.quiesced,
            )
            # The admission lock excludes any retained observer at this cut.
            # No pipe reader runs on the dispatcher thread. Freeze exactly the
            # result's bytes/hash/EOF and parser state before retaining owner;
            # late observation can only change live accounting, never this file.
            _persist_cleanup_diagnostic(output_fd, executable_sha256.lower(), pipes, result)
            if not result.ownership_resolved:
                _retained_streaming_owner = (process, pgid, dispatch, pipes, result)
        elif snapshot is not None and not snapshot.quiesced:
            _retained_streaming_owner = (None, None, dispatch, pipes, None)
        if _retained_streaming_owner is None:
            _close_pipes(selector, stdout_pipe, stderr_pipe)
            if selector is not None:
                selector.close()
        _close_descriptors(*descriptors)
        _streaming_admission.release()
    if abnormal is not None:
        if process is None and isinstance(abnormal, BoundedRunError):
            raise abnormal
        if not isinstance(abnormal, (Exception,)):
            raise abnormal
    if result is None:
        raise _StreamingFailure(trigger)
    return result


def _persist_cleanup_diagnostic(
    output_fd: int, native_sha256: str, pipes: _StreamingPipes,
    result: StreamingRunResult,
) -> bool:
    """Best-effort one-shot diagnostic; never changes the runner's outcome.

    One exclusive private temporary and one no-replace hard link reserve at
    most two names. Only a completely written, synced, checked and closed file
    can become the final name. Existing temporary/final names are never removed.
    The owned output directory fd is the sole filesystem authority here.
    """
    import json

    temporary = ".cleanup-diagnostic.json.tmp"
    final = "cleanup-diagnostic.json"
    descriptor = -1
    owned_temporary = False
    try:
        diagnostic = pipes.cleanup_diagnostic.snapshot(result.stdout_eof and result.stderr_eof)
        payload = {
            "schema_version": 1, "kind": "ups-monitor.cleanup-diagnostic",
            **diagnostic, "native_sha256": native_sha256,
            "stderr_eof": result.stderr_eof, "stderr_bytes": result.stderr_bytes,
            "stderr_sha256": result.stderr_sha256,
        }
        data = (json.dumps(payload, ensure_ascii=True, allow_nan=False,
                           separators=(",", ":")) + "\n").encode("ascii")
        if (len(data) > 4096 or not 0 <= result.stderr_bytes <= _STREAM_MAX_COUNTER
                or len(native_sha256) != 64
                or any(character not in "0123456789abcdef" for character in native_sha256)):
            return False
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                             0o600, dir_fd=output_fd)
        owned_temporary = True
        os.fchmod(descriptor, 0o600)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
            return False
        _write_all(descriptor, data)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        named = os.stat(temporary, dir_fd=output_fd, follow_symlinks=False)
        if ((before.st_dev, before.st_ino, before.st_uid, before.st_mode, before.st_nlink)
                != (after.st_dev, after.st_ino, after.st_uid, after.st_mode, after.st_nlink)
                or after.st_size != len(data)
                or (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino)):
            return False
        # close() errors are ambiguous on POSIX: do not retry a possibly reused
        # descriptor, and do not publish after any failure from this close.
        closing, descriptor = descriptor, -1
        os.close(closing)
        os.link(temporary, final, src_dir_fd=output_fd, dst_dir_fd=output_fd,
                follow_symlinks=False)
        return True
    except Exception:
        # No error text/raw fallback and no lifecycle or cancellation changes.
        return False
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                pass
        if owned_temporary:
            try:
                os.unlink(temporary, dir_fd=output_fd)
            except Exception:
                pass


def retained_streaming_ownership() -> StreamingRunResult | None:
    """Observe/release the one retained owner, without signals or waiting.

    One nonblocking bounded drain can establish late real EOF. A zero-budget
    dispatcher join can establish late callback quiescence. References are
    released only after all five independent ownership facts become true.
    Calling while an operational run is active fails closed, never racing it.
    """
    global _retained_streaming_owner
    if not _streaming_admission.acquire(blocking=False):
        raise _StreamingFailure("streaming_owner_active")
    try:
        owner = _retained_streaming_owner
        if owner is None:
            return None
        process, pgid, dispatch, pipes, previous = owner
        snapshot = dispatch.join(0.0)
        if pipes is not None:
            try:
                pipes.consume(0.0)
            except (OSError, _StreamingFailure):
                pass
        empty = hashlib.sha256().hexdigest()
        result = StreamingRunResult(
            previous.trigger if previous is not None else "consumer_error",
            _poll_child(process) if process is not None else None,
            pipes.counts["stdout"] if pipes is not None else 0,
            pipes.counts["stderr"] if pipes is not None else 0,
            pipes.hashes["stdout"].hexdigest() if pipes is not None else empty,
            pipes.hashes["stderr"].hexdigest() if pipes is not None else empty,
            process is None or _poll_child(process) is not None,
            pgid is None or _process_group_absent(pgid),
            pipes is None or pipes.eof["stdout"],
            pipes is None or pipes.eof["stderr"], snapshot.quiesced,
        )
        if result.ownership_resolved:
            if pipes is not None:
                _close_selector_pipes(pipes.selector)
                pipes.selector.close()
            _retained_streaming_owner = None
        return result
    finally:
        _streaming_admission.release()


def _streaming_cleanup(process, pgid: int, pipes: _StreamingPipes, grace: float) -> None:
    """Shared signal/PGID policy; streaming-specific drain preserves EOF."""
    def resolved_process() -> bool:
        return _poll_child(process) is not None and _process_group_absent(pgid)

    def wait_phase(seconds: float) -> bool:
        # Real cleanup time is intentionally independent of virtual health
        # clocks; tests can replace this helper when exercising health time.
        end = time.perf_counter() + seconds
        while not resolved_process():
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return False
            try:
                pipes.consume(min(_POLL_SECONDS, remaining))
            except OSError:
                pipes.abort("output_io_failed")
                time.sleep(min(_POLL_SECONDS, remaining))
        return True

    if not resolved_process():
        pipes.term_sent = True
        _signal_child(process, signal.SIGTERM, pgid)
        if not wait_phase(grace):
            pipes.kill_sent = True
            pipes.kill_deadline = time.perf_counter() + _KILL_REAP_SECONDS
            _signal_child(process, signal.SIGKILL, pgid)
            if not wait_phase(max(0.0, pipes.kill_deadline - time.perf_counter())):
                pipes.abort("cleanup_unresolved")
    end = time.perf_counter() + _STREAM_DRAIN_SECONDS
    while pipes.selector.get_map():
        remaining = end - time.perf_counter()
        if remaining <= 0:
            pipes.abort("output_incomplete")
            break
        pipes.consume(min(_POLL_SECONDS, remaining))
