#!/usr/bin/env python3
"""Stage a patched copy of the pinned H03 NUT source tree; never edit inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


PATCH = Path(__file__).with_name("nut-hidapi-continuous-73c4502.patch")
INVENTORY_SHA256 = "22f5cb265db94204707326cc63f25981d803f310d769a5a4500e72f33435e26e"
PATCH_SHA256 = "f57a3cebd4cc70701be8d40c3af2484f3bf8a9f5b0c9ddde3af15f58e20e6aa8"


class StageError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _check_path_components(path: Path, final_kind: str) -> None:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for index, component in enumerate(absolute.parts[1:], start=1):
        current = current / component
        try:
            info = current.lstat()
        except OSError as exc:
            raise StageError(f"path component unavailable: {current}") from exc
        final = index == len(absolute.parts) - 1
        if stat.S_ISLNK(info.st_mode):
            raise StageError(f"symlink path component refused: {current}")
        if not final and not stat.S_ISDIR(info.st_mode):
            raise StageError(f"non-directory path component: {current}")
        if final and final_kind == "directory" and not stat.S_ISDIR(info.st_mode):
            raise StageError(f"not a directory: {current}")
        if final and final_kind == "file" and not stat.S_ISREG(info.st_mode):
            raise StageError(f"not a regular file: {current}")


def verify_source(source: Path, inventory_path: Path) -> dict[str, dict[str, object]]:
    # Input locations are supplied by the caller; neither is embedded in this
    # repository tool or its help output.
    source = _absolute(source)
    inventory_path = _absolute(inventory_path)
    _check_path_components(source, "directory")
    _check_path_components(inventory_path, "file")
    if sha256(inventory_path) != INVENTORY_SHA256:
        raise StageError("H03 source inventory hash mismatch")
    manifest = json.loads(inventory_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for root, directories, files in os.walk(source, topdown=True, followlinks=False):
        base = Path(root)
        for name in list(directories):
            path = base / name
            relative = path.relative_to(source).as_posix()
            found.add(relative)
            if path.is_symlink():
                directories.remove(name)
        for name in files:
            found.add((base / name).relative_to(source).as_posix())
    if found != set(manifest):
        raise StageError("H03 source path inventory mismatch")
    for relative, expected in manifest.items():
        path = source / relative
        info = path.lstat()
        kind = expected["kind"]
        if kind == "file":
            if not stat.S_ISREG(info.st_mode):
                raise StageError(f"H03 path kind changed: {relative}")
            if info.st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
                raise StageError(f"H03 file hash changed: {relative}")
        elif kind == "directory":
            if not stat.S_ISDIR(info.st_mode):
                raise StageError(f"H03 path kind changed: {relative}")
        elif kind == "symlink":
            if not stat.S_ISLNK(info.st_mode) or os.readlink(path) != expected["target"]:
                raise StageError(f"H03 symlink changed: {relative}")
        else:
            raise StageError(f"unsupported H03 path kind: {relative}")
    return manifest


def stage(source: Path, inventory_path: Path, output: Path) -> dict[str, object]:
    source = _absolute(source)
    output = _absolute(output)
    if output.exists() or output.is_symlink():
        raise StageError(f"output already exists: {output}")
    if source == output or source in output.parents or output in source.parents:
        raise StageError("output overlaps immutable H03 source")
    _check_path_components(output.parent, "directory")
    if sha256(PATCH) != PATCH_SHA256:
        raise StageError("continuous patch hash mismatch")
    inventory = verify_source(source, inventory_path)
    shutil.copytree(source, output, symlinks=True)
    output.chmod(0o700)
    try:
        subprocess.run(
            ["patch", "--batch", "--forward", "-p1", "-i", os.fspath(PATCH)],
            cwd=output,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        receipt = {
            "state": "STAGED_UNBUILT",
            "source_inventory_sha256": INVENTORY_SHA256,
            "patch_sha256": PATCH_SHA256,
            "source_entries": len(inventory),
            "output": os.fspath(output),
        }
        (output / "continuous-stage-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output / "continuous-stage-receipt.json").chmod(0o600)
    except Exception:
        shutil.rmtree(output)
        raise
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="immutable H03 source directory")
    parser.add_argument("--inventory", type=Path, required=True, help="pinned H03 source inventory JSON")
    parser.add_argument("--output", type=Path, required=True, help="new, nonexistent destination directory")
    args = parser.parse_args()
    try:
        receipt = stage(args.source, args.inventory, args.output)
    except (OSError, StageError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"stage refused: {exc}") from exc
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
