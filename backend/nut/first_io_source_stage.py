#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Authenticate an explicitly supplied, source-only first-IO E119 stage.

This module treats staged source and runtime files as data. It never imports or
executes code from the stage.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

PROFILE_SHA256 = "a9350f0674a7f2aa26b61ad186e37d9d77204fa7ab672a65c4dadf066907c064"
NATIVE_POST_SHA256 = "1cd2f2888d56fbf8cfa00f685aa3cfd0674e2a8e80877254ce8502057a602f02"
RUNTIME_POST_SHA256 = "909313f6be3d67da67c25b890dd0029997161837f8ffa049f394a2e43196a784"
BASE_HIDAPI_SHA256 = "ac1e333cf6974791772a1272d648a2f599cbbcf368876a2b861af24f94de8411"
BASE_RUNTIME_SHA256 = "191253602725c1e71a527821d518d70ee567cd25336867aec91c7cf73c467dcd"
QUALIFICATION_PATCH_SHA256 = "75e7a32a7032f07af8f97c78520389fa011320e26780da9066c237662892b1a9"
MAX_FILE = 4 * 1024 * 1024
MAX_TREE = 128 * 1024 * 1024


class SourceStageError(ValueError):
    """Rejected source stage with a path-free reason."""


def _need(condition: Any, reason: str) -> None:
    if not condition:
        raise SourceStageError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular(info: os.stat_result, maximum: int) -> None:
    _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o7000
          and 0 <= info.st_size <= maximum, "regular_file")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _read(path: Path, maximum: int = MAX_FILE) -> bytes:
    try:
        _root(path.parent)
        info = path.lstat()
        _regular(info, maximum)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0))
        expected = _identity(info)
        with os.fdopen(fd, "rb") as stream:
            _need(_identity(os.fstat(stream.fileno())) == expected, "file_changed")
            raw = stream.read(info.st_size)
            _need(len(raw) == info.st_size and _identity(os.fstat(stream.fileno())) == expected,
                  "file_changed")
        _need(_identity(path.lstat()) == expected, "file_changed")
        return raw
    except SourceStageError:
        raise
    except OSError as error:
        raise SourceStageError("regular_file") from error


def _root(path: Path, *, private: bool = False) -> Path:
    try:
        _need(path.is_absolute() and ".." not in path.parts, "canonical_root")
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            info = current.lstat()
            _need(not stat.S_ISLNK(info.st_mode), "root_symlink")
            _need(stat.S_ISDIR(info.st_mode), "canonical_root")
        _need(path.resolve(strict=True) == path, "canonical_root")
        if private:
            info = path.lstat()
            _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                  "private_stage_root")
        return path
    except SourceStageError:
        raise
    except OSError as error:
        raise SourceStageError("canonical_root") from error


def _safe_rel(name: str) -> str:
    path = PurePosixPath(name)
    _need(type(name) is str and path.as_posix() == name and bool(path.parts) and
          not path.is_absolute() and ".." not in path.parts and
          not any(part in ("", ".") for part in path.parts), "manifest_path")
    return name


def _map_sha(rows: dict[str, str]) -> str:
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    return _sha(raw)


def _load_json(path: Path, pin: str) -> tuple[dict[str, Any], bytes]:
    raw = _read(path)
    _need(_sha(raw) == pin, "pinned_input")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SourceStageError("pinned_input_json") from error
    _need(type(value) is dict, "pinned_input_json")
    return value, raw


def _inventory(root: Path, expected: set[str], reason: str,
               *, opaque_directories: tuple[str, ...] = ()) -> dict[str, int]:
    """Enumerate only the exact expected file and directory closure."""
    files = set(expected)
    directories = {parent.as_posix() for name in files for parent in PurePosixPath(name).parents
                   if parent != PurePosixPath(".")}
    directories.update(opaque_directories)
    _need(not files & directories, reason)
    pending = [""]
    sizes: dict[str, int] = {}
    total = 0
    try:
        while pending:
            parent = pending.pop()
            with os.scandir(_root(root / parent)) as entries:
                for entry in entries:
                    name = f"{parent}/{entry.name}" if parent else entry.name
                    if name in directories:
                        _need(entry.is_dir(follow_symlinks=False), "tree_member")
                        directories.remove(name)
                        if name not in opaque_directories:
                            pending.append(name)
                        continue
                    _need(name in files, reason)
                    files.remove(name)
                    info = entry.stat(follow_symlinks=False)
                    _regular(info, MAX_FILE)
                    total += info.st_size
                    _need(total <= MAX_TREE, "tree_size")
                    sizes[name] = info.st_size
    except SourceStageError:
        raise
    except OSError as error:
        raise SourceStageError("tree_member") from error
    _need(not files and not directories, reason)
    return sizes


def _hash_inventory(root: Path, sizes: dict[str, int]) -> dict[str, str]:
    rows = {}
    for name, size in sizes.items():
        raw = _read(root / name, size)
        _need(len(raw) == size, "file_changed")
        rows[name] = _sha(raw)
    return rows


@dataclass(frozen=True)
class AuthenticatedSourceStage:
    identity: dict[str, str]
    runtime_root: Path
    runtime_map: dict[str, str]
    native_base_map: dict[str, str]
    native_map: dict[str, str]
    vendor_map: dict[str, str]
    native_overlay: dict[str, bytes]


def validate_source_stage(stage_root: Path, backend_root: Path) -> AuthenticatedSourceStage:
    """Validate a private E119 stage against authenticated checkout locks."""
    stage_root = _root(Path(stage_root), private=True)
    backend_root = _root(Path(backend_root))
    profile_dir = backend_root / "native-build/first-io-v1"
    profile, profile_raw = _load_json(profile_dir / "manifest.json", PROFILE_SHA256)
    _need(profile.get("source_only") is True and profile.get("status") == "SOURCE_ONLY_PROFILE",
          "profile_scope")
    qualification = profile.get("qualification")
    _need(type(qualification) is dict, "profile_shape")
    _need(qualification.get("base_manifest_sha256") == BASE_HIDAPI_SHA256 and
          qualification.get("runtime_base_manifest_sha256") == BASE_RUNTIME_SHA256 and
          qualification.get("runtime_qualification_patch_sha256") == QUALIFICATION_PATCH_SHA256,
          "profile_binding")
    payloads = profile.get("payloads")
    _need(type(payloads) is dict and set(payloads) == {
        "native-first-io-v1.patch", "cleanup-diagnostics-first-io-v1.patch",
        "process-deadline-first-io-v1.patch"}, "profile_payload_set")
    for name, pin in payloads.items():
        _need(type(pin) is str and re.fullmatch(r"[0-9a-f]{64}", pin) is not None, "profile_payload_pin")
        _need(_sha(_read(profile_dir / _safe_rel(name))) == pin, "profile_payload")

    hidapi, _ = _load_json(backend_root / "native-build/hidapi-0.16/manifest.json", BASE_HIDAPI_SHA256)
    native_base = hidapi.get("post_hidapi_016_sha256")
    vendor_rows = hidapi.get("hidapi", {}).get("files")
    _need(type(native_base) is dict and len(native_base) == 190 and
          type(vendor_rows) is list and len(vendor_rows) == 8, "native_base_shape")
    _need(all(_safe_rel(name) == name and type(pin) is str and
              re.fullmatch(r"[0-9a-f]{64}", pin) is not None for name, pin in native_base.items()),
          "native_base_shape")
    vendor_base: dict[str, str] = {}
    vendor_sizes: dict[str, int] = {}
    for row in vendor_rows:
        _need(type(row) is dict and type(row.get("path")) is str and type(row.get("sha256")) is str
              and type(row.get("bytes")) is int and 0 < row["bytes"] <= MAX_FILE,
              "vendor_base_shape")
        path = _safe_rel(row["path"])
        _need(not path.startswith("drivers/") and path not in vendor_base and
              re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "vendor_base_shape")
        vendor_base[path] = row["sha256"]
        vendor_sizes[path] = row["bytes"]
    runtime_base, _ = _load_json(backend_root / "qualification/module-sha256.json", BASE_RUNTIME_SHA256)
    _need(len(runtime_base) == 9 and all(_safe_rel(name) == name and type(pin) is str and
          re.fullmatch(r"[0-9a-f]{64}", pin) is not None for name, pin in runtime_base.items()),
          "runtime_base_shape")
    patch_path = backend_root / "qualification/smc1500i-90s.patch"
    _need(_sha(_read(patch_path)) == QUALIFICATION_PATCH_SHA256, "qualification_patch")

    native_post = dict(native_base)
    native_delta = profile.get("native_delta")
    runtime_post = dict(runtime_base)
    runtime_delta = profile.get("runtime_delta")
    _need(type(native_delta) is dict and set(native_delta) == {
        "drivers/apcmicrolink-hidapi-session.h", "drivers/apcmicrolink-hidapi-shared.c",
        "drivers/apcmicrolink.c"}, "native_delta_shape")
    _need(type(runtime_delta) is dict and set(runtime_delta) == {
        "cleanup_diagnostics.py", "process_deadline.py"}, "runtime_delta_shape")
    native_overlay: dict[str, bytes] = {}
    for name, delta in native_delta.items():
        _safe_rel(name)
        _need(type(delta) is dict and delta.get("before") == native_base.get(name) and
              delta.get("after") != delta.get("before"), "native_preimage")
        native_post[name] = delta.get("after")
    for name, delta in runtime_delta.items():
        _need(type(delta) is dict and delta.get("before") == runtime_base.get(name) and
              delta.get("after") != delta.get("before"), "runtime_preimage")
        runtime_post[name] = delta.get("after")
    _need(sum(native_base[name] != native_post[name] for name in native_base) == 3 and
          sum(runtime_base[name] != runtime_post[name] for name in runtime_base) == 2,
          "delta_counts")
    _need(_map_sha(native_base) == qualification.get("native_base_map_sha256") and
          _map_sha(native_post) == NATIVE_POST_SHA256 and
          _map_sha(runtime_base) == qualification.get("runtime_qualified_base_map_sha256") and
          _map_sha(runtime_post) == RUNTIME_POST_SHA256, "expected_map_digest")
    _need(qualification.get("native_project_file_count") == 190 and
          qualification.get("vendor_file_count") == 8 and
          qualification.get("runtime_qualified_base_file_count") == 9, "expected_counts")

    source_root, runtime_root = stage_root / "source", stage_root / "runtime"
    vendor_prefix = "drivers/hidapi-0.16.0/"
    expected_source = set(native_base) | {vendor_prefix + name for name in vendor_base}
    _inventory(stage_root, {"SOURCE_RECEIPT.json"}, "stage_inventory",
               opaque_directories=("source", "runtime", "logs"))
    source_sizes = _inventory(source_root, expected_source, "source_inventory")
    runtime_sizes = _inventory(runtime_root, set(runtime_post), "runtime_inventory")
    _need(all(source_sizes[vendor_prefix + name] == size for name, size in vendor_sizes.items()),
          "vendor_size")
    source_rows = _hash_inventory(source_root, source_sizes)
    runtime_rows = _hash_inventory(runtime_root, runtime_sizes)
    _need({name: source_rows[name] for name in native_base} == native_post, "native_postmap")
    actual_vendor = {name: source_rows[vendor_prefix + name] for name in vendor_base}
    _need(actual_vendor == vendor_base, "vendor_map")
    _need(runtime_rows == runtime_post, "runtime_postmap")

    receipt_raw = _read(stage_root / "SOURCE_RECEIPT.json", 256 * 1024)
    try:
        receipt = json.loads(receipt_raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SourceStageError("source_receipt") from error
    expected_counts = {"native_project": 190, "native_changed": 3, "native_unchanged": 187,
                       "runtime": 9, "runtime_changed": 2, "runtime_unchanged": 7,
                       "vendor": 8, "vendor_changed": 0}
    expected_outcomes = {"native_patch": "EXITED_0", "cleanup_patch": "EXITED_0",
                         "deadline_patch": "EXITED_0", "complete_map_checks": "PASS",
                         "vendor_unchanged": "PASS", "original_inputs_unchanged": "PASS"}
    _need(type(receipt) is dict and receipt.get("state") == "SOURCE_ONLY_PASS" and
          receipt.get("profile_manifest_sha256") == PROFILE_SHA256 and
          receipt.get("native_base_manifest_sha256") == BASE_HIDAPI_SHA256 and
          receipt.get("runtime_base_manifest_sha256") == BASE_RUNTIME_SHA256 and
          receipt.get("qualification_patch_sha256") == QUALIFICATION_PATCH_SHA256 and
          receipt.get("native_base_map_sha256") == _map_sha(native_base) and
          receipt.get("native_postimage_map_sha256") == NATIVE_POST_SHA256 and
          receipt.get("runtime_base_map_sha256") == _map_sha(runtime_base) and
          receipt.get("runtime_postimage_map_sha256") == RUNTIME_POST_SHA256 and
          receipt.get("native_delta") == native_delta and
          receipt.get("runtime_delta") == runtime_delta and
          receipt.get("patch_sha256") == profile.get("payloads") and
          receipt.get("counts") == expected_counts and receipt.get("phase_outcomes") == expected_outcomes and
          receipt.get("build") == "NOT_RUN" and receipt.get("signing") == "NOT_RUN" and
          receipt.get("payload_execution") == "NOT_RUN", "source_receipt")

    for name in native_delta:
        native_overlay[name] = _read(source_root / name)
        _need(_sha(native_overlay[name]) == native_post[name], "native_overlay")
    identity = {
        "profile": "first-io-v1",
        "profile_manifest_sha256": _sha(profile_raw),
        "source_receipt_sha256": _sha(receipt_raw),
        "native_postmap_sha256": _map_sha(native_post),
        "runtime_postmap_sha256": _map_sha(runtime_post),
        "vendor_map_sha256": _map_sha(vendor_base),
        "native_base_manifest_sha256": BASE_HIDAPI_SHA256,
        "runtime_base_manifest_sha256": BASE_RUNTIME_SHA256,
        "qualification_patch_sha256": QUALIFICATION_PATCH_SHA256,
    }
    return AuthenticatedSourceStage(identity, runtime_root, runtime_post, native_base,
                                    native_post, vendor_base, native_overlay)
