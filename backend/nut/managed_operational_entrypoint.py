"""Explicit, fixed host-local operational v2 entrypoint; never retry a session."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import sys
import threading
from typing import Any, Callable
import uuid

PROTOCOL = "ups-monitor.managed-operational.v2"
PROFILE = "apc-smc1500i-operational-v2"
NATIVE_NAME = "apcmicrolink-hidapi-operational"
NATIVE_SHA256 = "d754eaa71ef19dad5532ddabfd507f084ec6848ef2642718b1cb575657f43cfc"
NATIVE_SIZE = 437_584
ARCHITECTURE = "arm64"
MINIMUM_MACOS = "27.0"
MODULES = frozenset({
    "managed_operational_entrypoint.py", "app_controlled_operational.py",
    "operational_capture.py", "operational_publication.py", "continuous_capture.py",
    "continuous_protocol.py", "process_deadline.py", "bounded_stream_dispatch.py",
    "cleanup_diagnostics.py",
})
MAX_RECEIPT_BYTES = 65_536
STOP_REQUESTED = False
_CONTROL_REASONS = {"stop", "app_disconnected", "invalid_control", "signal", "control_failed"}
_ADAPTER_ERRORS = {
    "invalid_capture_receipt", "capture_failed", "observer_failed", "invalid_observer_receipt",
    "adapter_setup_failed", "watcher_join_failed", "control_close_failed", "handler_restore_failed",
    "invalid_control", "control_failed",
}


def request_stop(_signal: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("unsafe_runtime_file")
        chunks, remaining = [], before.st_size
        while remaining:
            block = os.read(fd, min(65_536, remaining))
            if not block:
                raise ValueError("runtime_file_changed")
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(fd)
        if (os.read(fd, 1) or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                              before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
                                                     after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("runtime_file_changed")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _host_admitted() -> bool:
    version = platform.mac_ver()[0]
    if platform.system() != "Darwin" or platform.machine() != ARCHITECTURE:
        return False
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version) is None:
        return False
    parts = tuple(int(part) for part in version.split("."))
    return parts >= (27, 0)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_manifest")
        result[key] = value
    return result


def validate_runtime() -> tuple[Path, Path, str, Path]:
    directory = Path(__file__).absolute().parent
    # Reject symlinked runtime/interpreter ancestors as well as leaf symlinks.
    if directory.resolve(strict=True) != directory:
        raise ValueError("runtime_directory_rejected")
    manifest = json.loads(_read_regular(directory / "runtime.json", 16_384), object_pairs_hook=_unique_object)
    keys = {"schema_version", "profile", "python_path", "python_sha256", "module_sha256",
            "native_name", "native_sha256", "architecture", "minimum_macos"}
    if type(manifest) is not dict or set(manifest) != keys:
        raise ValueError("invalid_manifest")
    python_text, python_hash, pins = manifest["python_path"], manifest["python_sha256"], manifest["module_sha256"]
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 2
            or manifest["profile"] != PROFILE or manifest["native_name"] != NATIVE_NAME
            or manifest["native_sha256"] != NATIVE_SHA256
            or manifest["architecture"] != ARCHITECTURE or manifest["minimum_macos"] != MINIMUM_MACOS
            or type(python_text) is not str or not python_text.startswith("/") or "\0" in python_text
            or ".." in Path(python_text).parts
            or type(python_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", python_hash) is None
            or type(pins) is not dict or set(pins) != MODULES):
        raise ValueError("invalid_manifest")
    if not _host_admitted():
        raise ValueError("host_rejected")
    python = Path(python_text)
    if (python.resolve(strict=True) != python or Path(sys.executable).resolve() != python
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or not os.stat(python, follow_symlinks=False).st_mode & 0o111
            or hashlib.sha256(_read_regular(python, 134_217_728)).hexdigest() != python_hash):
        raise ValueError("interpreter_rejected")
    for name in sorted(MODULES):
        expected = pins[name]
        if type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("invalid_manifest")
        if hashlib.sha256(_read_regular(directory / name, 2_097_152)).hexdigest() != expected:
            raise ValueError("module_rejected")
    native = directory / NATIVE_NAME
    native_data = _read_regular(native, 2_097_152)
    if (len(native_data) != NATIVE_SIZE or hashlib.sha256(native_data).hexdigest() != NATIVE_SHA256
            or not os.stat(native, follow_symlinks=False).st_mode & 0o111):
        raise ValueError("native_rejected")
    return directory, python, python_hash, native


def _load_adapter(directory: Path) -> Any:
    # A fresh isolated process must not reuse unchecked project-module objects.
    if any(name[:-3] in sys.modules for name in MODULES if name != Path(__file__).name):
        raise ValueError("preloaded_backend_rejected")
    sys.path.insert(0, str(directory))
    return importlib.import_module("app_controlled_operational")


def fixed_argv(native: Path) -> tuple[str, ...]:
    return (str(native), "-s", "ups-monitor-operational-v2", "-d1",
            "-x", "hidapi_shared", "-x", "guarded_monitor", "-x", "port=auto",
            "-x", "hid_fallback=no", "-x", "guard_probe_attempts=1", "-x", "guard_vid=051d",
            "-x", "guard_pid=0003", "-x", "guard_deadline=35", "-x", "monitor_stream_v2")


def retain() -> None:
    """Keep uncertain E10 ownership in this process; do not restart or retry."""
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signal, _frame: None)
    threading.Event().wait()


def emit(payload: dict[str, object]) -> None:
    data = (json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt_limit")
    view = memoryview(data)
    while view:
        count = os.write(1, view)
        if count <= 0:
            raise OSError("receipt_write_failed")
        view = view[count:]


def _quiet_workers() -> bool:
    return not any(t is not threading.current_thread() and t.is_alive() for t in threading.enumerate())


def _receipt_known(adapter: Any, result: object) -> bool:
    if type(result) is not adapter.AppOperationalReceipt:
        return False
    if (type(result.watcher_quiesced) is not bool or type(result.ownership_resolved) is not bool
            or result.control_reason is not None and (
                type(result.control_reason) is not str or result.control_reason not in _CONTROL_REASONS)
            or result.adapter_error is not None and (
                type(result.adapter_error) is not str or result.adapter_error not in _ADAPTER_ERRORS)):
        return False
    if result.capture_result is not None and not adapter._capture_receipt(result.capture_result, NATIVE_NAME):
        return False
    return not result.ownership_resolved or bool(
        result.watcher_quiesced and result.capture_result is not None
        and result.capture_result.ownership_resolved)


def serve(adapter: Any, profile: Any, workspace: Path, launch_id: str, *,
          writer: Callable[[dict[str, object]], None] = emit,
          barrier: Callable[[], None] = retain) -> int:
    result = None
    admission_rejected = False

    def capture(*args, **kwargs):
        if STOP_REQUESTED:
            kwargs["cancel_event"].set()
        return adapter.capture_operational(*args, **kwargs)

    try:
        candidate = adapter.run_app_controlled_operational(
            profile, control_read_fd=0, output_root=workspace / "capture",
            feed_directory=workspace / "feed", source_id=NATIVE_NAME, capture=capture)
        if _receipt_known(adapter, candidate):
            result = candidate
    except adapter.AppOperationalAdmissionError:
        admission_rejected = True
    except BaseException:
        pass
    quiet = _quiet_workers()
    receipt = asdict(result) if result is not None else {
        "capture_result": None, "control_reason": None, "adapter_error": "capture_failed",
        "watcher_quiesced": quiet, "ownership_resolved": False,
    }
    if not quiet:
        receipt["ownership_resolved"] = False
        receipt["adapter_error"] = "capture_failed"
    resolved = receipt["ownership_resolved"] is True and quiet
    must_retain = not resolved and (not admission_rejected or not quiet)
    payload = {"protocol": PROTOCOL, "schema_version": 2, "launch_id": launch_id, "adapter": receipt}
    try:
        writer(payload)
    except BaseException:
        if must_retain:
            barrier()
        return 2
    if must_retain:
        barrier()
    # Measurement state remains in the nested receipt, independent of cleanup.
    return 0 if resolved else 2


def main() -> int:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)
    launch_id = sys.argv[4] if len(sys.argv) == 5 else "invalid-launch"
    try:
        if (len(sys.argv) != 5 or sys.argv[1] != "--workspace" or sys.argv[3] != "--launch-id"
                or re.fullmatch(r"[a-f0-9-]{36}", launch_id) is None
                or str(uuid.UUID(launch_id)) != launch_id
                or not sys.argv[2].startswith("/") or "\0" in sys.argv[2]
                or ".." in Path(sys.argv[2]).parts):
            raise ValueError("invalid_arguments")
        directory, _python, _digest, native = validate_runtime()
        adapter = _load_adapter(directory)
        profile = adapter.FixedOperationalProfile(fixed_argv(native), NATIVE_SHA256)
    except BaseException:
        try:
            emit({"protocol": PROTOCOL, "schema_version": 2, "launch_id": launch_id,
                  "adapter": {"capture_result": None, "control_reason": None,
                              "adapter_error": "adapter_setup_failed",
                              "watcher_quiesced": _quiet_workers(), "ownership_resolved": False}})
        except BaseException:
            pass
        if not _quiet_workers():
            retain()
        return 2
    return serve(adapter, profile, Path(sys.argv[2]), launch_id)


if __name__ == "__main__":
    raise SystemExit(main())
