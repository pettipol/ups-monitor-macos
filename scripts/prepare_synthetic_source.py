#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy a bounded working tree into an isolated synthetic or explicit real preview."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import select
import stat
import subprocess
import time
from typing import Any

MAX_NAMES = 1024 * 1024
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_SECONDS = 30
OLD_BUNDLE = b"org.openupsmonitor.mac.preview"
PIN_RE = re.compile(
    rb'// Generated candidate pin; canonical release pin remains nil\.\n'
    rb'enum FrozenOperationalReleasePins \{\n'
    rb'    static let manifestSHA256: String\? = "([0-9a-f]{64})"\n'
    rb'\}\n'
)
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+\.(?:synthetic|real)\Z")


class PrepareError(ValueError):
    """Closed error code suitable for a public receipt or CLI message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _need(ok: Any, code: str) -> None:
    if not ok:
        raise PrepareError(code)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _deadline(start: float) -> None:
    _need(time.monotonic() - start <= MAX_SECONDS, "deadline")


def _pin_bytes(path: Path, expected: str) -> bytes:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            component_info = current.lstat()
        except OSError as error:
            raise PrepareError("pin_file") from error
        _need(not stat.S_ISLNK(component_info.st_mode), "pin_file")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 256, "pin_file")
            raw = stream.read(info.st_size + 1)
            _need(len(raw) == info.st_size, "pin_file")
    except OSError as error:
        raise PrepareError("pin_file") from error
    match = PIN_RE.fullmatch(raw)
    _need(match is not None and match.group(1).decode("ascii") == expected, "pin_format")
    return raw


def _git_names(checkout: Path, start: float) -> list[str]:
    try:
        top = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
        process = subprocess.Popen(
            ["git", "-C", str(checkout), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        output = bytearray()
        deadline = time.monotonic() + 10
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise PrepareError("git_list")
            ready, _, _ = select.select([process.stdout], [], [], min(remaining, 0.1))
            if not ready:
                continue
            chunk = os.read(process.stdout.fileno(), min(65536, MAX_NAMES + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_NAMES:
                process.kill()
                process.wait()
                raise PrepareError("git_list")
        process.stdout.close()
        try:
            returncode = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise PrepareError("git_list") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PrepareError("git_list") from error
    try:
        git_root = Path(os.fsdecode(top.stdout.strip())).resolve(strict=True)
    except OSError as error:
        raise PrepareError("git_list") from error
    _need(top.returncode == 0 and git_root == checkout and returncode == 0, "git_list")
    names: list[str] = []
    seen: set[str] = set()
    for item in bytes(output).split(b"\0"):
        if not item:
            continue
        try:
            name = item.decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise PrepareError("git_name") from error
        parts = PurePosixPath(name).parts
        _need(not name.startswith("/") and parts and all(p not in ("", ".", "..") for p in parts), "git_name")
        _need(".git" not in parts, "git_name")
        if "AGENTS.md" in parts:
            continue
        if name not in seen:
            names.append(name)
            seen.add(name)
    _need(len(names) <= MAX_ENTRIES, "entry_limit")
    _deadline(start)
    return sorted(names)


def _read_source(root: Path, names: list[str], start: float) -> dict[str, tuple[bytes, int]]:
    snapshot: dict[str, tuple[bytes, int]] = {}
    total = 0
    for name in names:
        _deadline(start)
        path = root
        for component in PurePosixPath(name).parts:
            path = path / component
            try:
                info = path.lstat()
            except OSError as error:
                raise PrepareError("source_path") from error
            _need(not stat.S_ISLNK(info.st_mode), "source_symlink")
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o7000, "source_file")
        _need(info.st_size <= MAX_FILE, "file_limit")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise PrepareError("source_read") from error
        _need(len(raw) == info.st_size, "source_changed")
        total += len(raw)
        _need(total <= MAX_TOTAL, "total_limit")
        mode = stat.S_IMODE(info.st_mode)
        _need(mode in (0o600, 0o644, 0o755), "source_mode")
        snapshot[name] = (raw, mode)
    return snapshot


def _tree_digest(snapshot: dict[str, tuple[bytes, int]]) -> str:
    digest = hashlib.sha256()
    for name in sorted(snapshot):
        raw, mode = snapshot[name]
        digest.update(name.encode("utf-8") + b"\0" + f"{mode:04o}".encode("ascii") + b"\0")
        digest.update(hashlib.sha256(raw).digest())
    return digest.hexdigest()


def _private_output_parent(output: Path, checkout: Path, inputs: tuple[Path, ...]) -> Path:
    _need(not output.exists() and not output.is_symlink(), "destination_occupied")
    parent = output.parent.resolve(strict=True)
    info = parent.stat()
    _need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
          and not info.st_mode & 0o022, "destination_parent")
    temp_roots = {Path("/private/tmp").resolve(), Path(os.getenv("TMPDIR", "/tmp")).resolve()}
    _need(any(parent == root or root in parent.parents for root in temp_roots), "destination_not_temp")
    candidate = parent / output.name
    for other in (checkout, *inputs):
        resolved = other.resolve(strict=True)
        _need(candidate != resolved and candidate not in resolved.parents and resolved not in candidate.parents,
              "path_overlap")
    _need(output.name not in ("", ".", ".."), "destination_path")
    return candidate


def _copy_file(root: Path, name: str, raw: bytes, mode: int) -> None:
    target = root.joinpath(*PurePosixPath(name).parts)
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    parent = target.parent
    while parent != root:
        os.chmod(parent, 0o755)
        parent = parent.parent
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _read_copied(root: Path, names: list[str], start: float) -> dict[str, tuple[bytes, int]]:
    found: dict[str, tuple[bytes, int]] = {}
    for name in names:
        _deadline(start)
        path = root.joinpath(*PurePosixPath(name).parts)
        try:
            parent = root
            for component in PurePosixPath(name).parts[:-1]:
                parent = parent / component
                parent_info = parent.lstat()
                _need(stat.S_ISDIR(parent_info.st_mode), "destination_corrupt")
            info = path.lstat()
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "destination_corrupt")
            raw = path.read_bytes()
        except OSError as error:
            raise PrepareError("destination_corrupt") from error
        found[name] = (raw, stat.S_IMODE(info.st_mode))
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for item in root.rglob("*"):
        _deadline(start)
        relative = item.relative_to(root).as_posix()
        info = item.lstat()
        _need(not stat.S_ISLNK(info.st_mode), "destination_corrupt")
        if stat.S_ISDIR(info.st_mode):
            actual_dirs.add(relative)
        elif stat.S_ISREG(info.st_mode):
            actual_files.add(relative)
        else:
            raise PrepareError("destination_corrupt")
    expected_dirs = {"/".join(PurePosixPath(name).parts[:index])
                     for name in names for index in range(1, len(PurePosixPath(name).parts))}
    _need(actual_files == set(names) and actual_dirs == expected_dirs, "destination_corrupt")
    return found


def _inventory(snapshot: dict[str, tuple[bytes, int]]) -> list[dict[str, Any]]:
    return [
        {"path": name, "size": len(raw), "mode": f"{mode:04o}", "sha256": _sha(raw)}
        for name, (raw, mode) in sorted(snapshot.items())
    ]


def _canonical_pin_is_nil(raw: bytes, enum_name: bytes) -> bool:
    forms = {
        b"FrozenOperationalReleasePins": (
            b"/// Populated only in a separately reviewed packaging copy.\n"
            b"enum FrozenOperationalReleasePins {\n"
            b"    static let manifestSHA256: String? = nil\n}\n"
        ),
        b"BundledOperationalReleasePins": (
            b"/// A reviewed packaging build replaces this nil only in its isolated source copy.\n"
            b"/// No manifest, environment variable or UI input can enable the public default.\n"
            b"enum BundledOperationalReleasePins {\n"
            b"    static let manifestSHA256: String? = nil\n}\n"
        ),
    }
    return enum_name in forms and raw == forms[enum_name]


def prepare_source(checkout: Path, pin_file: Path, manifest_sha256: str,
                   bundle_identifier: str, output_root: Path, *, real_preview: bool = False) -> dict[str, Any]:
    start = time.monotonic()
    _need(re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is not None, "manifest_hash")
    _need(len(bundle_identifier) <= 255 and IDENTIFIER_RE.fullmatch(bundle_identifier) is not None
          and bundle_identifier.endswith(".real" if real_preview else ".synthetic")
          and not bundle_identifier.startswith("org.openupsmonitor.mac.preview"), "bundle_identifier")
    checkout = checkout.resolve(strict=True)
    _need(checkout.is_dir() and not checkout.is_symlink(), "checkout")
    pin_file = Path(pin_file)
    _need(pin_file.is_absolute(), "pin_file")
    output = _private_output_parent(Path(output_root), checkout, (pin_file,))
    pin_raw = _pin_bytes(pin_file, manifest_sha256)
    names = _git_names(checkout, start)
    snapshot = _read_source(checkout, names, start)
    frozen_path = "Sources/UPSRuntime/FrozenOperationalReleasePins.swift"
    bundled_path = "Sources/UPSRuntime/BundledOperationalReleasePins.swift"
    project_path = "UPSMonitor.xcodeproj/project.pbxproj"
    _need(frozen_path in snapshot and bundled_path in snapshot and project_path in snapshot, "required_source")
    _need(_canonical_pin_is_nil(snapshot[frozen_path][0], b"FrozenOperationalReleasePins")
          and _canonical_pin_is_nil(snapshot[bundled_path][0], b"BundledOperationalReleasePins"), "canonical_pin")
    project_raw, project_mode = snapshot[project_path]
    _need(project_raw.count(OLD_BUNDLE) == 8, "bundle_occurrences")
    replacement = bundle_identifier.encode("ascii")
    _need(replacement not in project_raw, "bundle_collision")
    project_new = project_raw.replace(OLD_BUNDLE, replacement)
    _need(project_new.count(replacement) == 8, "bundle_replacements")

    changes = {
        frozen_path: (snapshot[frozen_path][0], pin_raw, snapshot[frozen_path][1]),
        project_path: (project_raw, project_new, project_mode),
    }
    prepared_bytes = sum(len(changes[name][1] if name in changes else raw)
                         for name, (raw, _) in snapshot.items())
    _need(len(project_new) <= MAX_FILE and prepared_bytes <= MAX_TOTAL, "prepared_size")
    _need(output.mkdir(mode=0o700) is None, "destination_create")
    os.chmod(output, 0o700)
    source_root = output / "source"
    source_root.mkdir(mode=0o755)
    os.chmod(source_root, 0o755)
    for name in names:
        _deadline(start)
        raw, mode = snapshot[name]
        if name in changes:
            raw = changes[name][1]
        _copy_file(source_root, name, raw, mode)
    copied = _read_copied(source_root, names, start)
    _need(len(copied) == len(snapshot), "destination_corrupt")
    for name in names:
        expected = changes[name][1] if name in changes else snapshot[name][0]
        _need(copied[name] == (expected, snapshot[name][1]), "destination_corrupt")
    current_names = _git_names(checkout, start)
    current = _read_source(checkout, current_names, start)
    _need(current == snapshot, "source_changed")
    _need(_tree_digest(copied) == _tree_digest({
        name: (changes[name][1], snapshot[name][1]) if name in changes else snapshot[name]
        for name in names}), "destination_corrupt")
    receipt = {
        "schema_version": 1,
        "status": "SOURCE_PREPARED_NOT_BUILT",
        "source_entries": len(names),
        "source_bytes": sum(len(raw) for raw, _ in snapshot.values()),
        "source_tree_sha256": _tree_digest(snapshot),
        "prepared_tree_sha256": _tree_digest(copied),
        "source_before": _inventory(snapshot),
        "source_after": _inventory(current),
        "destination": _inventory(copied),
        "manifest_sha256": manifest_sha256,
        "bundle_identifier": bundle_identifier,
        "deltas": [
            {"path": frozen_path, "before_sha256": _sha(changes[frozen_path][0]),
             "after_sha256": _sha(changes[frozen_path][1])},
            {"path": project_path, "before_sha256": _sha(project_raw),
             "after_sha256": _sha(project_new)},
        ],
        "limits": {"cooperative_deadline_seconds": MAX_SECONDS, "race_proof": False},
    }
    receipt_raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(output / "receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as stream:
        stream.write(receipt_raw)
    _deadline(start)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--pin-file", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--bundle-identifier", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--real-preview", action="store_true",
                        help="Prepare a .real identifier in the source copy. Does not build or launch anything.")
    args = parser.parse_args()
    try:
        receipt = prepare_source(args.checkout, args.pin_file, args.manifest_sha256,
                                 args.bundle_identifier, args.output_root, real_preview=args.real_preview)
    except PrepareError as error:
        parser.error(error.code)
    except OSError:
        parser.error("io")
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
