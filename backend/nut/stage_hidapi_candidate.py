#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage pinned source inputs for offline review; never build or execute them."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Sequence

HIDAPI_VERSION = "0.15.0"
STATE = "STAGED_NOT_BUILT_NOT_RUN"
PRODUCT_DIR = Path(os.path.abspath(Path(__file__).parent))
PRODUCT_ROOT = PRODUCT_DIR.parents[1]


@dataclass(frozen=True)
class StageInput:
    source_root: Path
    source_relative: str
    destination_relative: str
    sha256: str
    source_group: str


@dataclass(frozen=True)
class StagedBytes:
    spec: StageInput
    data: bytes


class StageError(ValueError):
    """Input or output failed a closed staging validation."""


PRODUCT_INPUTS = (
    ("apcmicrolink-hidapi-shared.c", "a87a7d001b992b7b1cfd1afd96d4432cb5a5d9bfe40550c1877ebd646ba83a21"),
    ("apcmicrolink-hidapi-session.h", "50104ad0660fbd3c77fa185b0d8e00269f59775a1e123d3b548cb6c86f77d5ae"),
    ("apcmicrolink-hidapi-shared-host.h", "606caa96cef85055c68c3b0d7c999e57e24efeb7bac16427dc8836bfd0631dcd"),
    ("apcmicrolink-hidapi-native.c", "3a1205741d62e02871d96c4e3091674b8131e8d3d95e58b156f2f95e9de1d2a5"),
    ("apcmicrolink-hidapi-native.h", "648531900d7d2413a59dd36c04e3cd05a3c466ec52062b2e17437cd5b2064ada"),
    ("apcmicrolink-hid-descriptor-checked.c", "7db55b980569f8385196d10c30a966b0e78f1f9266c624f05a3c2459d13ebc85"),
    ("apcmicrolink-hid-descriptor-checked.h", "65c24b24313ba78c8293ede0485839c496165779f4d87cedde5e882a9f266b52"),
)

HIDAPI_INPUTS = (
    ("mac/hid.c", "hid.c", "0770e9b42138f9a42e91c8ddb4ddbd0696ebaf6f6535c969b7b36b8caa90ae80"),
    ("hidapi/hidapi.h", "hidapi.h", "c9cef28c53a13a9403e54d5a8a099d51afff119ab04094df89356df0833a822e"),
    ("mac/hidapi_darwin.h", "hidapi_darwin.h", "48854f6f6b612a90291c3de83a5755c2ed8642da173151a41377090821c39187"),
)

LICENSE_INPUTS = (
    ("LICENSE.txt", "7d3b087c34f35d4d538e3bcddd1ff8f66e92f9ef336881999482800ddf840913"),
    ("LICENSE-orig.txt", "fb5436aa63d1b71a8dfbf74ecaf1a5b4e1ec4df7f80074d11fec99284f69ca5f"),
    ("LICENSE-bsd.txt", "30eb1bef29b46f8ba7ab8b416035dbd93cb034a45481dd97815b944284582cd2"),
    ("LICENSE-gpl3.txt", "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"),
)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _safe_relative(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or any(part in (".", "..") for part in relative.parts):
        raise StageError(f"unsafe relative path: {value}")
    return relative


def _check_components(path: Path, *, final_kind: str) -> None:
    """Require every component to exist, be non-symlink, and have the right kind."""
    path = _absolute(path)
    parts = path.parts
    current = Path(parts[0])
    for index, component in enumerate(parts[1:], start=1):
        current = current / component
        try:
            info = current.lstat()
        except OSError as exc:
            raise StageError(f"path component unavailable: {current}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise StageError(f"symlink component refused: {current}")
        is_final = index == len(parts) - 1
        if not is_final and not stat.S_ISDIR(info.st_mode):
            raise StageError(f"non-directory path component: {current}")
        if is_final:
            if final_kind == "directory" and not stat.S_ISDIR(info.st_mode):
                raise StageError(f"not a directory: {current}")
            if final_kind == "file" and not stat.S_ISREG(info.st_mode):
                raise StageError(f"not a regular file: {current}")


def _overlaps(left: Path, right: Path) -> bool:
    a = os.fspath(_absolute(left)).casefold()
    b = os.fspath(_absolute(right)).casefold()
    try:
        common = os.path.commonpath((a, b))
    except ValueError:
        return False
    return common == a or common == b


def _read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StageError(f"cannot open input without following symlinks: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StageError(f"not a regular input file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _specs(product_dir: Path, hidapi_source: Path) -> tuple[StageInput, ...]:
    product_dir = _absolute(product_dir)
    hidapi_source = _absolute(hidapi_source)
    product = tuple(
        StageInput(product_dir, name, f"drivers/{name}", digest, "product")
        for name, digest in PRODUCT_INPUTS
    )
    hidapi = tuple(
        StageInput(hidapi_source, source, f"drivers/hidapi-candidate/{destination}", digest, "hidapi-0.15.0")
        for source, destination, digest in HIDAPI_INPUTS
    )
    licenses = tuple(
        StageInput(hidapi_source, name, f"drivers/hidapi-candidate/licenses/{name}", digest, "hidapi-0.15.0")
        for name, digest in LICENSE_INPUTS
    )
    return product + hidapi + licenses


def _validate_and_read(specs: Sequence[StageInput]) -> tuple[StagedBytes, ...]:
    if len(specs) != 14:
        raise StageError("bundle input plan must contain exactly 14 files")
    staged: list[StagedBytes] = []
    destinations: set[str] = set()
    for spec in specs:
        source_rel = _safe_relative(spec.source_relative)
        dest_rel = _safe_relative(spec.destination_relative)
        dest_key = os.fspath(dest_rel).casefold()
        if dest_key in destinations:
            raise StageError(f"duplicate bundle destination: {dest_rel}")
        destinations.add(dest_key)
        root = _absolute(spec.source_root)
        _check_components(root, final_kind="directory")
        source_path = root / source_rel
        _check_components(source_path, final_kind="file")
        data = _read_regular(source_path)
        digest = hashlib.sha256(data).hexdigest()
        if digest != spec.sha256:
            raise StageError(f"SHA-256 mismatch: {spec.source_group}/{source_rel}")
        staged.append(StagedBytes(spec, data))
    return tuple(staged)


def _validate_output(output_dir: Path, protected_roots: Sequence[Path]) -> Path:
    output = _absolute(output_dir)
    if any(_overlaps(output, protected) for protected in protected_roots):
        raise StageError("output overlaps a product or HIDAPI input tree")
    if os.path.lexists(output):
        raise StageError("output already exists")
    parent = output.parent
    _check_components(parent, final_kind="directory")
    return output


def stage_from_specs(
    specs: Sequence[StageInput],
    output_dir: Path,
    *,
    protected_roots: Sequence[Path],
    hidapi_version: str = HIDAPI_VERSION,
) -> dict[str, object]:
    """Internal testable staging primitive; CLI callers cannot replace pins."""
    staged = _validate_and_read(specs)
    output = _validate_output(output_dir, protected_roots)

    output.mkdir(mode=0o700, exist_ok=False)
    (output / "drivers").mkdir(mode=0o700, exist_ok=False)
    (output / "drivers/hidapi-candidate").mkdir(mode=0o700, exist_ok=False)
    (output / "drivers/hidapi-candidate/licenses").mkdir(mode=0o700, exist_ok=False)

    manifest_files: list[dict[str, str]] = []
    for item in staged:
        destination_relative = _safe_relative(item.spec.destination_relative)
        destination = output / destination_relative
        with destination.open("xb") as stream:
            stream.write(item.data)
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual != item.spec.sha256:
            raise StageError(f"copied file hash mismatch: {destination_relative}")
        manifest_files.append({
            "source": f"{item.spec.source_group}/{_safe_relative(item.spec.source_relative).as_posix()}",
            "destination": destination_relative.as_posix(),
            "sha256": actual,
        })

    manifest: dict[str, object] = {
        "bundle_format_version": 1,
        "hidapi_version": hidapi_version,
        "state": STATE,
        "files": manifest_files,
    }
    with (output / "manifest.json").open("xb") as stream:
        stream.write((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return manifest


def stage_candidate(hidapi_source: Path, output_dir: Path) -> dict[str, object]:
    """Stage the fixed product and HIDAPI 0.15.0 input set."""
    hidapi_source = _absolute(hidapi_source)
    _check_components(hidapi_source, final_kind="directory")
    specs = _specs(PRODUCT_DIR, hidapi_source)
    return stage_from_specs(
        specs,
        output_dir,
        protected_roots=(PRODUCT_ROOT, hidapi_source),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidapi-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = stage_candidate(args.hidapi_source, args.output_dir)
    except StageError as exc:
        parser.error(str(exc))
    print(f"STAGED files={len(manifest['files'])} state={STATE}")
    print(f"manifest={_absolute(args.output_dir) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
