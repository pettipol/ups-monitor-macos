"""Copy-only v2 staging. Native bytes remain mode 0600, never enabled or run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

NATIVE_NAME = "apcmicrolink-hidapi-operational"
NATIVE_SHA256 = "d754eaa71ef19dad5532ddabfd507f084ec6848ef2642718b1cb575657f43cfc"
NATIVE_SIZE = 437_584
PROFILE = "apc-smc1500i-operational-v2"
ARCHITECTURE = "arm64"
MINIMUM_MACOS = "27.0"
MODULES = (
    "managed_operational_entrypoint.py", "app_controlled_operational.py",
    "operational_capture.py", "operational_publication.py", "continuous_capture.py",
    "continuous_protocol.py", "process_deadline.py", "bounded_stream_dispatch.py",
    "cleanup_diagnostics.py",
)
LIMIT_MODULE = 2_097_152
LIMIT_NATIVE = 2_097_152
LIMIT_PYTHON = 134_217_728


def _canonical(path: Path) -> Path:
    if (not path.is_absolute() or ".." in path.parts
            or path.resolve(strict=True) != path):
        raise ValueError("source_alias")
    return path


def read_source(path: Path, limit: int, *, executable: bool = False) -> bytes:
    _canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("source_rejected")
        if executable and not info.st_mode & 0o111:
            raise ValueError("python_not_executable")
        chunks, remaining = [], info.st_size
        while remaining:
            block = os.read(fd, min(65_536, remaining))
            if not block:
                raise ValueError("source_changed")
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(fd)
        if (os.read(fd, 1) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("source_changed")
        return b"".join(chunks)
    finally:
        os.close(fd)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(target_fd: int, name: str, content: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=target_fd)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(content)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("staged_write_failed")
            view = view[count:]
    finally:
        os.close(fd)


def _verify(target_fd: int, name: str, content: bytes) -> None:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                 | getattr(os, "O_CLOEXEC", 0), dir_fd=target_fd)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size != len(content)
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("staged_hash_mismatch")
        digest, remaining = hashlib.sha256(), info.st_size
        while remaining:
            block = os.read(fd, min(65_536, remaining))
            if not block:
                raise ValueError("staged_hash_mismatch")
            digest.update(block)
            remaining -= len(block)
        if os.read(fd, 1) or digest.hexdigest() != sha(content):
            raise ValueError("staged_hash_mismatch")
    finally:
        os.close(fd)


def stage(native_path: Path, modules_dir: Path, python_path: Path, destination: Path) -> dict[str, object]:
    native_path, modules_dir, python_path = map(_canonical, (native_path, modules_dir, python_path))
    modules_fd = os.open(modules_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                         | getattr(os, "O_CLOEXEC", 0))
    try:
        if not stat.S_ISDIR(os.fstat(modules_fd).st_mode):
            raise ValueError("modules_directory_rejected")
    finally:
        os.close(modules_fd)
    sources = [native_path, python_path, *(modules_dir / name for name in MODULES)]
    identities = []
    for source in sources:
        _canonical(source)
        info = os.stat(source, follow_symlinks=False)
        identity = (info.st_dev, info.st_ino)
        if identity in identities:
            raise ValueError("source_alias")
        identities.append(identity)
    if (not destination.is_absolute() or ".." in destination.parts
            or destination.name in {"", ".", ".."}):
        raise ValueError("destination_rejected")
    parent = _canonical(destination.parent)
    target = parent / destination.name
    if any(target == source or target in source.parents or source in target.parents for source in sources):
        raise ValueError("destination_alias")
    if target == modules_dir or modules_dir in target.parents or target in modules_dir.parents:
        raise ValueError("destination_alias")
    native = read_source(native_path, LIMIT_NATIVE)
    if len(native) != NATIVE_SIZE or sha(native) != NATIVE_SHA256:
        raise ValueError("native_pin_mismatch")
    module_data = {name: read_source(modules_dir / name, LIMIT_MODULE) for name in MODULES}
    python_data = read_source(python_path, LIMIT_PYTHON, executable=True)
    pins = {name: sha(content) for name, content in module_data.items()}
    manifest = {"schema_version": 2, "profile": PROFILE, "python_path": str(python_path),
                "python_sha256": sha(python_data), "module_sha256": pins, "native_name": NATIVE_NAME,
                "native_sha256": NATIVE_SHA256, "architecture": ARCHITECTURE, "minimum_macos": MINIMUM_MACOS}
    manifest_data = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if len(manifest_data) > 16_384:
        raise ValueError("manifest_limit")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    target_fd = None
    try:
        # Existing names (including symlinks) are never overwritten or adopted.
        os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
        target_fd = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                            | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd)
        created = os.fstat(target_fd)
        named = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(named.st_mode)
                or (created.st_dev, created.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError("destination_replaced")
        payloads = {NATIVE_NAME: native, **module_data, "runtime.json": manifest_data}
        for name, content in payloads.items():
            _write(target_fd, name, content)
        for name, content in payloads.items():
            _verify(target_fd, name, content)
        named = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(named.st_mode)
                or (created.st_dev, created.st_ino) != (named.st_dev, named.st_ino)
                or _canonical(parent) != parent):
            raise ValueError("destination_replaced")
        return {"status": "STAGED_NOT_EXECUTABLE", "runtime_ready": False,
                "native_sha256": NATIVE_SHA256, "module_sha256": pins,
                "python_sha256": sha(python_data)}
    finally:
        # Partial evidence is left intact on failure; no recursive deletion.
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--modules", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = stage(args.native, args.modules, args.python, args.destination)
    except (OSError, ValueError):
        print(json.dumps({"status": "STAGING_REJECTED"}, separators=(",", ":")))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
