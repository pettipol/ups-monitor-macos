#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Restore the locked native recipe from the source delivery as data."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile


ROOT = "UPS-Monitor-E96-Native-Source"
RECIPE = "recipe/"
RECIPE_MANIFEST = "RECIPE_MANIFEST.json"
PROJECT_PREFIX = "ups-monitor-source/"
MIB = 1024 ** 2
MAX_ARCHIVE = 128 * MIB
LOCALE_LINKS = {
    "effective-reader-source/scripts/python/app/locale/" + suffix: target
    for language, region in (("fr", "fr_FR"), ("it", "it_IT"), ("ru", "ru_RU"))
    for suffix, target in ((f"{language}/{region}.UTF-8.po", f"{language}.po"), (f"{region}.UTF-8", language))
}


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def path_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    need(path.parts and not path.is_absolute() and ".." not in path.parts and path.as_posix() == name and
         not any(ord(char) < 32 or ord(char) == 127 or char == "\\" for char in name), "unsafe archive path")
    return path


def unique_values(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    need(len(result) == len(pairs), "duplicate manifest key")
    return result


def archive_index(archive: tarfile.TarFile, root: str,
                  allowed_links: dict[str, str]) -> dict[str, tarfile.TarInfo]:
    rows = {}
    prefix = root + "/"
    size = 0
    for member in archive:
        path_name(member.name)
        need(len(rows) < 4096 and (member.name == root or member.name.startswith(prefix)),
             "unexpected archive root or entry count")
        name = member.name.removeprefix(prefix) if member.name != root else "."
        need(name not in rows and not member.sparse and 0 <= member.size <= 32 * MIB,
             "duplicate member, sparse member or oversized entry")
        need((member.isdir() and member.size == 0) or (name != "." and (member.isreg() or
             (member.issym() and member.size == 0 and allowed_links.get(name) == member.linkname))),
             "unsupported tar member or symlink")
        size += member.size
        need(size <= MAX_ARCHIVE, "archive payload size")
        rows[name] = member
    need("." in rows and {name for name, row in rows.items() if row.issym()} == set(allowed_links),
         "archive root or locale link inventory")
    for name, member in rows.items():
        path = PurePosixPath(name)
        need(all(parent.as_posix() not in rows or rows[parent.as_posix()].isdir() for parent in path.parents),
             "non-directory archive ancestor")
        if member.issym():
            target = rows.get((path.parent / member.linkname).as_posix())
            need(target is not None and not target.issym(), "locale link target missing")
    return rows


def member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo, cap: int) -> bytes:
    need(member.isreg() and 0 <= member.size <= cap, "unexpected member size or kind")
    with archive.extractfile(member) as file:
        raw = file.read(cap + 1)
    need(len(raw) == member.size, "archive member length")
    return raw


def original_file(raw: bytes, row: dict) -> bytes:
    need(sha(raw) == row["delivered_sha256"] and len(raw) == row["delivered_size"],
         "delivered recipe bytes differ")
    insertion = row["insertion"]
    if insertion is not None:
        offset = insertion["offset_bytes"]
        block = insertion["text_utf8"].encode()
        need(type(offset) is int and 0 <= offset <= len(raw) and 0 < len(block) <= 8192 and
             raw[offset:offset + len(block)] == block, "notice differs")
        raw = raw[:offset] + raw[offset + len(block):]
    need(sha(raw) == row["original_sha256"] and len(raw) == row["original_size"], "restored recipe bytes differ")
    return raw


def project_bytes(files: dict[str, tuple[bytes, int]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:", format=tarfile.USTAR_FORMAT) as archive:
        for name, (raw, mode) in sorted(files.items()):
            member = tarfile.TarInfo(PROJECT_PREFIX + name)
            member.mode = mode
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def restore(archive_path: Path, expected_sha: str, output: Path) -> dict:
    archive_path, output = archive_path.absolute(), output.absolute()
    need(archive_path.resolve(strict=True) == archive_path and output.parent.resolve(strict=True) == output.parent and
         output.parent.is_dir() and not os.path.lexists(output), "use a regular archive and a new output directory")
    need(re.fullmatch(r"[a-f0-9]{64}", expected_sha) is not None, "expected a lowercase SHA-256 digest")
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as file:
        info = os.fstat(file.fileno())
        need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_ARCHIVE, "archive size or type")
        raw = file.read(MAX_ARCHIVE + 1)
    need(len(raw) == info.st_size and sha(raw) == expected_sha, "outer archive SHA-256 differs")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        rows = archive_index(archive, ROOT, LOCALE_LINKS)
        manifest = json.loads(member_bytes(archive, rows[RECIPE_MANIFEST], MIB), object_pairs_hook=unique_values)
        inputs = manifest["files"]
        need(manifest["schema"] == 1 and len(inputs) == 60 and
             sum(row["insertion"] is not None for row in inputs.values()) == 30 and
             {name.removeprefix(RECIPE) for name, member in rows.items() if name.startswith(RECIPE) and member.isreg()} ==
             inputs.keys(), "recipe member closure")
        files = {}
        for name, row in inputs.items():
            path_name(name)
            member = rows[RECIPE + name]
            need(type(row["mode"]) is int and member.mode == row["mode"] and row["mode"] in (0o644, 0o755),
                 "recipe mode differs")
            files[name] = (original_file(member_bytes(archive, member, MIB), row), row["mode"])
    project = project_bytes(files)
    need(len(project) <= 8 * MIB and sha(project) == manifest["restored_project_tar_sha256"],
         "expected project tar digest differs")
    output.mkdir(mode=0o700)
    try:
        for name, (contents, mode) in files.items():
            path = output / RECIPE / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as file:
                file.write(contents)
                os.fchmod(file.fileno(), mode)
        with (output / "project.tar").open("xb") as file:
            file.write(project)
            os.fchmod(file.fileno(), 0o600)
    except (OSError, ValueError):
        shutil.rmtree(output)
        raise
    return {"state": "RECIPE_RESTORED_AS_DATA", "recipe_files": len(files),
            "project_tar": "project.tar", "project_tar_sha256": sha(project)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = restore(args.archive, args.sha256, args.output_dir)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, tarfile.TarError) as error:
        print(f"Restore refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
