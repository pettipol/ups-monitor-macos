"""Developer-only, fixed synthetic app session. No hardware or arbitrary argv."""
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

PROTOCOL = "ups-monitor.managed-synthetic.v1"
MODULES = frozenset({
    "managed_synthetic_entrypoint.py", "app_controlled_capture.py",
    "continuous_capture.py", "continuous_protocol.py", "process_deadline.py",
    "synthetic_continuous_feed.py", "synthetic_continuous_stream.py",
})
MAX_RECEIPT_BYTES = 65_536
STOP_REQUESTED = False


def request_stop(_signal: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True  # Safe before admission and after a retained receipt.


def _read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("unsafe_runtime_file")
        data = os.read(fd, limit)
        if len(data) != info.st_size:
            raise ValueError("runtime_file_changed")
        return data
    finally:
        os.close(fd)


def _executable_digest(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 134_217_728:
            raise ValueError("interpreter_rejected")
        digest, remaining = hashlib.sha256(), info.st_size
        while remaining:
            block = os.read(fd, min(65_536, remaining))
            if not block:
                raise ValueError("interpreter_rejected")
            digest.update(block)
            remaining -= len(block)
        return digest.hexdigest()
    finally:
        os.close(fd)


def validate_runtime() -> tuple[Path, Path, str]:
    """Only stdlib has been imported when all executable/module pins are checked."""
    directory = Path(__file__).absolute().parent
    manifest = json.loads(_read_regular(directory / "runtime.json", 16_384))
    if type(manifest) is not dict or set(manifest) != {"python_path", "python_sha256", "module_sha256"}:
        raise ValueError("invalid_manifest")
    python, digest, pins = manifest["python_path"], manifest["python_sha256"], manifest["module_sha256"]
    if (type(python) is not str or not python.startswith("/") or "\0" in python
            or type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(pins) is not dict or set(pins) != MODULES):
        raise ValueError("invalid_manifest")
    executable = Path(python)
    if (Path(sys.executable).resolve() != executable.resolve()
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or executable.is_symlink()):
        raise ValueError("interpreter_rejected")
    if _executable_digest(executable) != digest:
        raise ValueError("interpreter_rejected")
    for name, expected in pins.items():
        if (type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None
                or hashlib.sha256(_read_regular(directory / name, 2_097_152)).hexdigest() != expected):
            raise ValueError("module_rejected")
    return directory, executable, digest


def retain() -> None:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signal, _frame: None)
    threading.Event().wait()  # No retry, restart, log loop, or process termination.


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
    """One real adapter invocation; injected adapter/writer/barrier are test seams."""
    result = None
    admission_rejected = False

    def capture(*args, **kwargs):
        if STOP_REQUESTED:
            kwargs["cancel_event"].set()  # Outside the signal handler, before spawn.
        return adapter.capture_continuous(*args, **kwargs)

    try:
        result = adapter.run_app_controlled(
            profile, control_read_fd=0, output_root=workspace / "capture",
            feed_directory=workspace / "feed", source_id="synthetic-app-session",
            capture=capture,
        )
    except adapter.AppCaptureAdmissionError:
        admission_rejected = True  # No child/worker ownership was transferred.
    except BaseException:
        pass  # Unexpected failure is never evidence of cleanup.
    quiet = not any(thread is not threading.current_thread() and thread.is_alive()
                    for thread in threading.enumerate())
    receipt = asdict(result) if result is not None else {
        "capture_result": None, "control_reason": None, "adapter_error": "capture_failed",
        "watcher_quiesced": quiet, "ownership_resolved": False,
    }
    if not quiet:
        receipt["ownership_resolved"] = False
        receipt["adapter_error"] = "workers_not_quiescent"
    resolved = receipt["ownership_resolved"] is True and quiet
    payload = {"protocol": PROTOCOL, "schema_version": 1, "launch_id": launch_id, "adapter": receipt}
    try:
        writer(payload)
    except BaseException:
        if not resolved and (not admission_rejected or not quiet):
            barrier()
        return 2
    if not resolved and (not admission_rejected or not quiet):
        barrier()
        return 2  # Only reachable with an injected test barrier.
    return 0 if resolved else 2


def main() -> int:
    # Adapter restoration must never restore a terminating handler while an
    # unresolved child/worker still belongs to this Python supervisor.
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)
    launch_id = sys.argv[4] if len(sys.argv) == 5 else "invalid-launch"
    try:
        if (len(sys.argv) != 5 or sys.argv[1] != "--workspace" or sys.argv[3] != "--launch-id"
                or re.fullmatch(r"[a-f0-9-]{36}", launch_id) is None
                or not sys.argv[2].startswith("/") or "\0" in sys.argv[2]):
            raise ValueError("invalid_arguments")
        directory, python, digest = validate_runtime()
        sys.path.insert(0, str(directory))
        import app_controlled_capture as adapter
        bootstrap = ("import runpy; runpy.run_path(" + repr(str(directory / MODULE_ENTRY))
                     + ",run_name='__synthetic_stream__')")
        profile = adapter.FixedCaptureProfile((str(python), "-I", "-S", "-B", "-c", bootstrap), digest)
    except BaseException:
        try:
            emit({"protocol": PROTOCOL, "schema_version": 1, "launch_id": launch_id,
                  "adapter": {"capture_result": None, "control_reason": None,
                              "adapter_error": "preflight_failed", "watcher_quiesced": True,
                              "ownership_resolved": False}})
        except BaseException:
            pass
        return 2  # Project code was not invoked; no child can have been started.
    return serve(adapter, profile, Path(sys.argv[2]), launch_id)


MODULE_ENTRY = "managed_synthetic_entrypoint.py"
if __name__ == "__synthetic_stream__":
    directory, _, _ = validate_runtime()
    sys.path.insert(0, str(directory))
    import synthetic_continuous_stream
    sys.argv = ["synthetic-stream"]
    raise SystemExit(synthetic_continuous_stream.main())
if __name__ == "__main__":
    raise SystemExit(main())
