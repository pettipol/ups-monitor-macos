"""Fixed, host-local managed H07 native capture entrypoint."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import threading
import uuid

PROTOCOL = "ups-monitor.managed-native.v1"
PROFILE = "apc-smc1500i-120s-v1"
NATIVE_NAME = "apcmicrolink-hidapi-continuous"
NATIVE_SHA256 = "2dae6874c8cb99469a9def4a9f584898e815656d87b93dcc6fd67dba5b7d6183"
MODULES = frozenset({"managed_native_entrypoint.py", "app_controlled_capture.py", "continuous_capture.py", "continuous_protocol.py", "process_deadline.py"})
MAX_RECEIPT_BYTES = 65_536
STOP_REQUESTED = False


def request_stop(_signal: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("unsafe_runtime_file")
        chunks, remaining = [], info.st_size
        while remaining:
            block = os.read(fd, min(65_536, remaining))
            if not block:
                raise ValueError("runtime_file_changed")
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _digest_regular(path: Path, limit: int, code: str) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError(code)
        digest, remaining = hashlib.sha256(), info.st_size
        while remaining:
            block = os.read(fd, min(65_536, remaining))
            if not block:
                raise ValueError(code)
            digest.update(block)
            remaining -= len(block)
        return digest.hexdigest()
    finally:
        os.close(fd)


def validate_runtime() -> tuple[Path, Path, str, Path]:
    directory = Path(__file__).absolute().parent
    manifest = json.loads(_read_regular(directory / "runtime.json", 16_384))
    keys = {"schema_version", "profile", "python_path", "python_sha256", "module_sha256", "native_name", "native_sha256"}
    if type(manifest) is not dict or set(manifest) != keys:
        raise ValueError("invalid_manifest")
    python_text, python_hash, pins = manifest["python_path"], manifest["python_sha256"], manifest["module_sha256"]
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["profile"] != PROFILE or manifest["native_name"] != NATIVE_NAME
            or manifest["native_sha256"] != NATIVE_SHA256
            or type(python_text) is not str or not python_text.startswith("/") or "\0" in python_text
            or ".." in Path(python_text).parts
            or type(python_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", python_hash) is None
            or type(pins) is not dict or set(pins) != MODULES):
        raise ValueError("invalid_manifest")
    python = Path(python_text)
    if (python.is_symlink() or Path(sys.executable).resolve() != python.resolve()
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or _digest_regular(python, 134_217_728, "interpreter_rejected") != python_hash):
        raise ValueError("interpreter_rejected")
    for name in sorted(MODULES):
        expected = pins[name]
        if type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError("invalid_manifest")
        if hashlib.sha256(_read_regular(directory / name, 2_097_152)).hexdigest() != expected:
            raise ValueError("module_rejected")
    native = directory / NATIVE_NAME
    digest = _digest_regular(native, 2_097_152, "native_rejected")
    info = os.stat(native, follow_symlinks=False)
    if digest != NATIVE_SHA256 or not info.st_mode & 0o111:
        raise ValueError("native_rejected")
    return directory, python, python_hash, native


def retain() -> None:
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


def serve(adapter, profile, workspace: Path, launch_id: str, *, writer=emit, barrier=retain) -> int:
    result = None
    admission_rejected = False
    def capture(*args, **kwargs):
        if STOP_REQUESTED:
            kwargs["cancel_event"].set()
        return adapter.capture_continuous(*args, **kwargs)
    try:
        result = adapter.run_app_controlled(profile, control_read_fd=0,
            output_root=workspace / "capture", feed_directory=workspace / "feed",
            source_id="apcmicrolink-hidapi-continuous", capture=capture)
    except adapter.AppCaptureAdmissionError:
        admission_rejected = True
    except BaseException:
        pass
    quiet = not any(t is not threading.current_thread() and t.is_alive() for t in threading.enumerate())
    receipt = asdict(result) if result is not None else {"capture_result": None, "control_reason": None,
        "adapter_error": "capture_failed", "watcher_quiesced": quiet, "ownership_resolved": False}
    if not quiet:
        receipt["ownership_resolved"] = False
        receipt["adapter_error"] = "workers_not_quiescent"
    resolved = receipt["ownership_resolved"] is True and quiet
    payload = {"protocol": PROTOCOL, "schema_version": 1, "launch_id": launch_id, "adapter": receipt}
    try:
        writer(payload)
    except BaseException:
        if not resolved and (not admission_rejected or not quiet): barrier()
        return 2
    if not resolved and (not admission_rejected or not quiet):
        barrier()
        return 2
    return 0 if resolved else 2


def main() -> int:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)
    launch_id = sys.argv[4] if len(sys.argv) == 5 else "invalid-launch"
    try:
        if (len(sys.argv) != 5 or sys.argv[1] != "--workspace" or sys.argv[3] != "--launch-id"
                or re.fullmatch(r"[a-f0-9-]{36}", launch_id) is None
                or str(uuid.UUID(launch_id)) != launch_id
                or not sys.argv[2].startswith("/") or "\0" in sys.argv[2]):
            raise ValueError("invalid_arguments")
        directory, python, digest, native = validate_runtime()
        sys.path.insert(0, str(directory))
        import app_controlled_capture as adapter
        argv = (str(native), "-s", "ups-monitor-h07", "-d1", "-x", "hidapi_shared", "-x", "guarded_monitor",
                "-x", "port=auto", "-x", "hid_fallback=no", "-x", "guard_probe_attempts=1", "-x", "guard_vid=051d",
                "-x", "guard_pid=0003", "-x", "guard_deadline=130", "-x", "monitor_stream_v1")
        profile = adapter.FixedCaptureProfile(argv, NATIVE_SHA256)
    except BaseException:
        try:
            emit({"protocol": PROTOCOL, "schema_version": 1, "launch_id": launch_id,
                  "adapter": {"capture_result": None, "control_reason": None, "adapter_error": "preflight_failed",
                              "watcher_quiesced": True, "ownership_resolved": False}})
        except BaseException:
            pass
        return 2
    return serve(adapter, profile, Path(sys.argv[2]), launch_id)


if __name__ == "__main__":
    raise SystemExit(main())
