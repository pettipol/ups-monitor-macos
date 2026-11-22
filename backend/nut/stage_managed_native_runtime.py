"""Copy-only offline staging for the pinned host-local H07 runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

NATIVE_NAME = "apcmicrolink-hidapi-continuous"
NATIVE_SHA256 = "2dae6874c8cb99469a9def4a9f584898e815656d87b93dcc6fd67dba5b7d6183"
PROFILE = "apc-smc1500i-120s-v1"
PROTOCOL = "ups-monitor.managed-native.v1"
SOURCE_ID = "apcmicrolink-hidapi-continuous"
MODULES = ("managed_native_entrypoint.py", "app_controlled_capture.py", "continuous_capture.py", "continuous_protocol.py", "process_deadline.py")
LIMIT_MODULE = 2_097_152
LIMIT_NATIVE = 2_097_152
LIMIT_PYTHON = 134_217_728
def read_source(path: Path, limit: int, *, executable: bool = False) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
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
        if os.read(fd, 1):
            raise ValueError("source_changed")
        return b"".join(chunks)
    finally:
        os.close(fd)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage(native_path: Path, modules_dir: Path, python_path: Path, destination: Path) -> dict[str, object]:
    native = read_source(native_path, LIMIT_NATIVE)
    if sha(native) != NATIVE_SHA256:
        raise ValueError("native_pin_mismatch")
    modules_fd = os.open(modules_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        if not stat.S_ISDIR(os.fstat(modules_fd).st_mode):
            raise ValueError("modules_directory_rejected")
    finally:
        os.close(modules_fd)
    module_data = {name: read_source(modules_dir / name, LIMIT_MODULE) for name in MODULES}
    python_data = read_source(python_path, LIMIT_PYTHON, executable=True)
    sources = [native_path.resolve(strict=True), python_path.resolve(strict=True), *((modules_dir / n).resolve(strict=True) for n in MODULES)]
    parent = destination.parent.resolve(strict=True)
    destination_name = destination.name
    if destination_name in {"", ".", ".."}:
        raise ValueError("destination_rejected")
    target = parent / destination_name
    if any(target == source or target in source.parents or source in target.parents for source in sources):
        raise ValueError("destination_alias")
    parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        os.mkdir(destination_name, mode=0o700, dir_fd=parent_fd)
        target_fd = os.open(destination_name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd)
    except BaseException:
        os.close(parent_fd)
        raise
    try:
        target_info = os.fstat(target_fd)
        named_info = os.stat(destination_name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(target_info.st_mode) or not stat.S_ISDIR(named_info.st_mode)
                or (target_info.st_dev, target_info.st_ino) != (named_info.st_dev, named_info.st_ino)):
            raise ValueError("destination_replaced")
        payloads = {NATIVE_NAME: native, **module_data}
        for file_name, content in payloads.items():
            fd = os.open(file_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=target_fd)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
        pins = {file_name: sha(content) for file_name, content in module_data.items()}
        manifest = {"schema_version": 1, "profile": PROFILE, "python_path": str(python_path.absolute()),
            "python_sha256": sha(python_data), "module_sha256": pins, "native_name": NATIVE_NAME,
            "native_sha256": NATIVE_SHA256}
        manifest_data = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open("runtime.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=target_fd)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(manifest_data)
        for file_name, content in payloads.items():
            staged_fd = os.open(file_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0), dir_fd=target_fd)
            try:
                info = os.fstat(staged_fd)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= (LIMIT_NATIVE if file_name == NATIVE_NAME else LIMIT_MODULE):
                    raise ValueError("staged_hash_mismatch")
                staged, remaining = [], info.st_size
                while remaining:
                    block = os.read(staged_fd, min(65_536, remaining))
                    if not block:
                        raise ValueError("staged_hash_mismatch")
                    staged.append(block)
                    remaining -= len(block)
            finally:
                os.close(staged_fd)
            if sha(b"".join(staged)) != sha(content):
                raise ValueError("staged_hash_mismatch")
        try:
            current_info = os.stat(destination_name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            raise ValueError("destination_replaced") from None
        created_info = os.fstat(target_fd)
        if (not stat.S_ISDIR(current_info.st_mode)
                or (created_info.st_dev, created_info.st_ino) != (current_info.st_dev, current_info.st_ino)):
            raise ValueError("destination_replaced")
        return {"status": "STAGED_NOT_EXECUTABLE", "runtime_ready": False, "native_sha256": NATIVE_SHA256,
                "module_sha256": pins, "python_sha256": sha(python_data)}
    except BaseException:
        # Keep partial evidence for inspection; never overwrite or recursively remove user data.
        raise
    finally:
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
