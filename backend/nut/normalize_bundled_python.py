#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy a verified E34 Python payload into a new app Contents tree, without executing it."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import time
from typing import Any
import unicodedata
import ctypes
import sys

STATE = "PRESIGN_NORMALIZED_NOT_EXECUTED"
PROFILE = "pbs-cpython-3.15.2-aarch64-20261026"
MAX_MEMBERS = 20_000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 120
BLOCK_BYTES = 1024 * 1024
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca",
}


class NormalizeError(ValueError):
    """Closed error code without source contents or local paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise NormalizeError(code)


def _tick(deadline: float) -> None:
    _need(time.monotonic() < deadline, "deadline")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_hash(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _json_object(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _need(key not in result, "tree_json")
            result[key] = value
        return result

    try:
        result = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(NormalizeError("tree_json")),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise NormalizeError("tree_json") from error
    _need(type(result) is dict, "tree_json")
    return result


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink)


def _mode(text: Any) -> int:
    _need(type(text) is str and len(text) == 4 and all(char in "01234567" for char in text), "tree_schema")
    value = int(text, 8)
    _need(value <= 0o777 and f"{value:04o}" == text, "tree_schema")
    return value


def _canonical_name(name: Any) -> str:
    _need(type(name) is str and bool(name) and "\0" not in name and "\\" not in name
          and len(name.encode("utf-8")) <= 4096, "unsafe_path")
    _need(name.isascii(), "unsafe_path")
    path = PurePosixPath(name)
    _need(not path.is_absolute() and ".." not in path.parts and path.as_posix() == name
          and name not in ("", "."), "unsafe_path")
    _need(name in ("install", "licenses", "PYTHON.json", "runtime-tree.json")
          or name.startswith(("install/", "licenses/")), "unsafe_path")
    return name


def _target_path(parent: str, target: str, rest: tuple[str, ...] = ()) -> str:
    _need(type(target) is str and bool(target) and not target.startswith("/")
          and "\\" not in target and "\0" not in target
          and len(target.encode("utf-8")) <= 4096, "unsafe_symlink")
    parts = list(PurePosixPath(parent).parts)
    for component in (*target.split("/"), *rest):
        if component in ("", "."):
            continue
        if component == "..":
            _need(len(parts) > 1, "unsafe_symlink")
            parts.pop()
        else:
            parts.append(component)
    _need(bool(parts) and parts[0] == "install", "unsafe_symlink")
    return "/".join(parts)


def _resolve_links(entries: dict[str, dict[str, Any]], deadline: float) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for name, row in entries.items():
        _tick(deadline)
        if row["type"] != "symlink":
            continue
        _need(name.startswith("install/"), "unsafe_symlink")
        current = _target_path(PurePosixPath(name).parent.as_posix(), row["target"])
        seen = {name}
        while True:
            _tick(deadline)
            changed = False
            parts = PurePosixPath(current).parts
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                candidate = entries.get(prefix)
                _need(candidate is not None, "missing_target")
                if candidate["type"] == "symlink":
                    _need(prefix not in seen, "symlink_cycle")
                    seen.add(prefix)
                    current = _target_path(PurePosixPath(prefix).parent.as_posix(),
                                           candidate["target"], parts[index:])
                    changed = True
                    break
                _need(index == len(parts) or candidate["type"] == "directory", "missing_target")
            if not changed:
                break
        resolved[name] = current
    return resolved


def _validate_manifest(manifest: dict[str, Any], deadline: float) -> dict[str, dict[str, Any]]:
    expected_fields = {
        "schema", "state", "profile", "archive_sha256", "metadata_sha256",
        "expected_metadata", "provenance", "licenses", "entries",
        "closure_macho", "runtime_execution", "adoption",
    }
    _need(set(manifest) == expected_fields, "tree_schema")
    _need(type(manifest["schema"]) is int and manifest["schema"] == 1
          and manifest["state"] == "STAGED_PYTHON_NOT_EXECUTED_NOT_ADOPTED"
          and manifest["profile"] == PROFILE
          and manifest["closure_macho"] == "NOT_RUN"
          and manifest["runtime_execution"] == "NOT_RUN"
          and manifest["adoption"] == "NOT_ADOPTED", "tree_schema")
    _need(_valid_hash(manifest["archive_sha256"])
          and _valid_hash(manifest["metadata_sha256"]), "tree_schema")

    expected = manifest["expected_metadata"]
    _need(type(expected) is dict and set(expected) == {
        "python_version", "target_triple", "python_exe", "apple_sdk_deployment_target"
    }, "tree_schema")
    _need(expected == {
        "python_version": "3.15.2",
        "target_triple": "aarch64-apple-darwin",
        "python_exe": "install/bin/python3.15",
        "apple_sdk_deployment_target": "11.0",
    }, "tree_schema")

    provenance = manifest["provenance"]
    _need(type(provenance) is dict and set(provenance) == {
        "provider", "release", "upstream_commit", "url"
    } and all(type(value) is str and value and "\0" not in value for value in provenance.values()),
        "tree_schema")
    licenses = manifest["licenses"]
    _need(type(licenses) is dict and set(licenses) == {
        "paths", "declarations", "legal_or_redistribution_review"
    } and licenses["legal_or_redistribution_review"] == "NOT_RUN"
        and type(licenses["paths"]) is list and type(licenses["declarations"]) is list,
        "tree_schema")

    raw_entries = manifest["entries"]
    _need(type(raw_entries) is dict and 0 < len(raw_entries) <= MAX_MEMBERS, "member_limit")
    entries: dict[str, dict[str, Any]] = {}
    aliases: set[str] = set()
    total_bytes = 0
    for name, original in raw_entries.items():
        _tick(deadline)
        canonical = _canonical_name(name)
        _need(canonical != "runtime-tree.json", "unsafe_path")
        alias = unicodedata.normalize("NFD", canonical).casefold()
        _need(alias not in aliases, "duplicate_member")
        aliases.add(alias)
        _need(type(original) is dict and type(original.get("type")) is str, "tree_schema")
        kind = original["type"]
        mode = _mode(original.get("mode"))
        if kind == "directory":
            _need(set(original) == {"type", "mode"} and mode == 0o700, "tree_schema")
            row = {"type": kind, "mode": original["mode"]}
        elif kind == "file":
            _need(set(original) == {"type", "mode", "bytes", "sha256"}
                  and type(original["bytes"]) is int and 0 <= original["bytes"] <= MAX_FILE_BYTES
                  and _valid_hash(original["sha256"]), "file_limit")
            total_bytes += original["bytes"]
            _need(total_bytes <= MAX_TOTAL_BYTES, "total_limit")
            row = {"type": kind, "mode": original["mode"], "bytes": original["bytes"],
                   "sha256": original["sha256"]}
        elif kind == "symlink":
            _need(set(original) == {"type", "mode", "target", "resolved_target", "source_mode"}
                  and _mode(original["source_mode"]) <= 0o777
                  and type(original["target"]) is str and type(original["resolved_target"]) is str,
                  "tree_schema")
            row = {"type": kind, "mode": original["mode"], "target": original["target"],
                   "resolved_target": original["resolved_target"], "source_mode": original["source_mode"]}
        else:
            raise NormalizeError("tree_schema")
        entries[canonical] = row

    _need("PYTHON.json" in entries and entries["PYTHON.json"]["type"] == "file"
          and expected["python_exe"] in entries and entries[expected["python_exe"]]["type"] == "file",
          "tree_schema")
    for name in entries:
        for parent in PurePosixPath(name).parents:
            parent_name = parent.as_posix()
            if parent_name != ".":
                _need(parent_name in entries and entries[parent_name]["type"] == "directory",
                      "parent_conflict")
    resolved = _resolve_links(entries, deadline)
    for name, target in resolved.items():
        _need(entries[name]["resolved_target"] == target, "unsafe_symlink")
    for license_path in licenses["paths"]:
        canonical = _canonical_name(license_path)
        _need(canonical.startswith("licenses/") and entries.get(canonical, {}).get("type") == "file",
              "missing_license")
    return entries


def _open_directory(path: Path, *, code: str) -> int:
    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise NormalizeError(code) from error
    info = os.fstat(fd)
    _need(stat.S_ISDIR(info.st_mode), code)
    return fd


def _open_dir_at(root_fd: int, components: tuple[str, ...], code: str) -> int:
    current = os.dup(root_fd)
    try:
        for component in components:
            following = os.open(component, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                                 dir_fd=current)
            os.close(current)
            current = following
        return current
    except OSError as error:
        os.close(current)
        raise NormalizeError(code) from error


def _open_parent_at(root_fd: int, relative: str, code: str) -> tuple[int, str]:
    parts = PurePosixPath(relative).parts
    _need(bool(parts), "unsafe_path")
    return _open_dir_at(root_fd, tuple(parts[:-1]), code), parts[-1]


def _read_regular_at(root_fd: int, relative: str, deadline: float,
                     maximum: int = MAX_FILE_BYTES) -> tuple[bytes, tuple[int, ...]]:
    parent_fd, leaf = _open_parent_at(root_fd, relative, "source_changed")
    fd = None
    try:
        fd = os.open(leaf, os.O_RDONLY | _NOFOLLOW | _CLOEXEC | getattr(os, "O_NONBLOCK", 0),
                     dir_fd=parent_fd)
        before = os.fstat(fd)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and 0 <= before.st_size <= maximum, "source_changed")
        identity = _identity(before)
        chunks: list[bytes] = []
        count = 0
        while True:
            _tick(deadline)
            block = os.read(fd, min(BLOCK_BYTES, max(maximum - count + 1, 1)))
            if not block:
                break
            count += len(block)
            _need(count <= maximum, "file_limit")
            chunks.append(block)
        after = os.fstat(fd)
        _need(_identity(after) == identity and count == before.st_size, "source_changed")
        return b"".join(chunks), identity
    except OSError as error:
        raise NormalizeError("io_error") from error
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def _readlink_at(root_fd: int, relative: str) -> tuple[str, tuple[int, ...]]:
    parent_fd, leaf = _open_parent_at(root_fd, relative, "source_changed")
    try:
        before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        _need(stat.S_ISLNK(before.st_mode), "source_changed")
        target = os.readlink(leaf, dir_fd=parent_fd)
        after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        _need(_identity(before) == _identity(after), "source_changed")
        return target, _identity(before)
    except OSError as error:
        raise NormalizeError("io_error") from error
    finally:
        os.close(parent_fd)


MAX_XATTR_NAME_BYTES = 65_536
_XATTR_NOFOLLOW = 0x0001


def _decode_xattr_names(blob: bytes) -> list[str]:
    _need(not blob or blob.endswith(b"\0"), "xattr_read")
    try:
        names = [part.decode("utf-8", "strict") for part in blob.split(b"\0") if part]
    except UnicodeError as error:
        raise NormalizeError("xattr_read") from error
    _need(len(names) == len(set(names)), "xattr_read")
    return sorted(names)


def _xattr_names(path: Path) -> list[str]:
    _need(sys.platform == "darwin", "xattr_unavailable")
    try:
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        listxattr = library.listxattr
        listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        listxattr.restype = ctypes.c_ssize_t
        raw_path = os.fsencode(path)
        required = listxattr(raw_path, None, 0, _XATTR_NOFOLLOW)
        _need(required >= 0, "xattr_read")
        _need(required <= MAX_XATTR_NAME_BYTES, "xattr_limit")
        buffer = ctypes.create_string_buffer(max(required, 1))
        actual = listxattr(raw_path, buffer, required, _XATTR_NOFOLLOW)
        _need(0 <= actual <= required, "xattr_read")
        return _decode_xattr_names(buffer.raw[:actual])
    except NormalizeError:
        raise
    except OSError as error:
        raise NormalizeError("xattr_read") from error
    except (AttributeError, OSError, TypeError) as error:
        raise NormalizeError("xattr_unavailable") from error


def _check_source_xattrs(source: Path, entry_names: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for relative in [".", "runtime-tree.json", *entry_names]:
        path = source if relative == "." else source / relative
        names = _xattr_names(path)
        result[relative] = names
        _need("com.apple.quarantine" not in names, "source_quarantine")
    return result


def _scan_tree(root: Path, root_fd: int, deadline: float, *,
               exclude_control: bool = True) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[int, ...]]]:
    entries: dict[str, dict[str, Any]] = {}
    identities: dict[str, tuple[int, ...]] = {}

    def walk(directory_fd: int, prefix: str) -> None:
        _tick(deadline)
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as error:
            raise NormalizeError("io_error") from error
        for leaf in names:
            _tick(deadline)
            relative = f"{prefix}/{leaf}" if prefix else leaf
            _canonical_name(relative)
            try:
                info = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise NormalizeError("source_changed") from error
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                _need(not info.st_mode & 0o7000, "source_special")
                if relative != "runtime-tree.json" or not exclude_control:
                    entries[relative] = {"type": "directory", "mode": f"{mode:04o}"}
                    identities[relative] = _identity(info)
                child_fd = os.open(leaf, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                                   dir_fd=directory_fd)
                try:
                    walk(child_fd, relative)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(info.st_mode):
                _need(not info.st_mode & 0o7000 and info.st_nlink == 1, "source_special")
                if relative == "runtime-tree.json" and exclude_control:
                    continue
                raw, identity = _read_regular_at(root_fd, relative, deadline)
                entries[relative] = {"type": "file", "mode": f"{mode:04o}",
                                     "bytes": len(raw), "sha256": _sha256(raw)}
                identities[relative] = identity
            elif stat.S_ISLNK(info.st_mode):
                _need(not info.st_mode & 0o7000, "source_special")
                target, identity = _readlink_at(root_fd, relative)
                if relative != "runtime-tree.json" or not exclude_control:
                    entries[relative] = {"type": "symlink", "mode": f"{mode:04o}", "target": target}
                    identities[relative] = identity
            else:
                raise NormalizeError("source_special")

    walk(root_fd, "")
    if exclude_control:
        entries.pop("runtime-tree.json", None)
        identities.pop("runtime-tree.json", None)
    return entries, identities


def _source_inventory_matches(observed: dict[str, dict[str, Any]],
                              expected: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    enriched = dict(observed)
    for name, row in expected.items():
        if row["type"] == "symlink" and name in enriched:
            enriched[name] = {
                "type": "symlink", "mode": enriched[name]["mode"],
                "target": enriched[name]["target"],
                "resolved_target": row["resolved_target"],
                "source_mode": row["source_mode"],
            }
    return enriched


def _read_tree_control(source_fd: int, deadline: float) -> tuple[bytes, tuple[int, ...]]:
    raw, identity = _read_regular_at(source_fd, "runtime-tree.json", deadline, MAX_TREE_BYTES)
    _need(identity[5] & 0o777 == 0o600, "tree_control")
    return raw, identity


def _validate_source(source_payload: Path, expected_tree_sha256: str, deadline: float):
    _need(type(expected_tree_sha256) is str and _valid_hash(expected_tree_sha256), "tree_pin")
    _need(source_payload.is_absolute() and source_payload.resolve(strict=True) == source_payload
          and not source_payload.is_symlink(), "source_path")
    source_fd = _open_directory(source_payload, code="source_path")
    root_info = os.fstat(source_fd)
    _need(not stat.S_IMODE(root_info.st_mode) & 0o022, "source_path")
    try:
        control, control_identity = _read_tree_control(source_fd, deadline)
        _need(_sha256(control) == expected_tree_sha256, "tree_pin")
        manifest = _json_object(control)
        entries = _validate_manifest(manifest, deadline)
        observed, identities = _scan_tree(source_payload, source_fd, deadline)
        _need(_source_inventory_matches(observed, entries) == entries, "source_inventory")
        source_xattrs = _check_source_xattrs(source_payload, sorted(entries))
        metadata_raw, _metadata_identity = _read_regular_at(
            source_fd, "PYTHON.json", deadline, MAX_FILE_BYTES)
        _need(_sha256(metadata_raw) == manifest["metadata_sha256"], "metadata_pin")
        metadata = _json_object(metadata_raw)
        _need(all(metadata.get(key) == value for key, value in manifest["expected_metadata"].items()),
              "metadata_contract")
        declared_paths = {metadata.get("license_path")}
        build_info = metadata.get("build_info", {})
        _need(type(build_info) is dict and type(build_info.get("extensions", {})) is dict,
              "metadata_contract")
        for variants in build_info.get("extensions", {}).values():
            _need(type(variants) is list, "metadata_contract")
            for variant in variants:
                _need(type(variant) is dict, "metadata_contract")
                if "license_paths" in variant:
                    paths = variant["license_paths"]
                    _need(type(paths) is list and all(type(path) is str for path in paths),
                          "metadata_contract")
                    declared_paths.update(paths)
        _need(None not in declared_paths and declared_paths.issubset(set(manifest["licenses"]["paths"])),
              "missing_license")
        return source_fd, root_info, control, control_identity, manifest, entries, identities, source_xattrs
    except BaseException:
        os.close(source_fd)
        raise


def _is_below_private_temp(path: Path) -> bool:
    roots: list[Path] = [Path("/private/tmp")]
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        if temp_root not in roots:
            roots.append(temp_root)
    except OSError:
        pass
    for root in roots:
        try:
            canonical_root = root.resolve(strict=True)
            if path == canonical_root or canonical_root not in path.parents:
                continue
            relative = path.relative_to(canonical_root)
            if not relative.parts:
                continue
            private_anchor = canonical_root / relative.parts[0]
            info = private_anchor.lstat()
            if (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o022):
                return True
        except OSError:
            continue
    return False


def _validate_destination(contents: Path) -> tuple[int, int, bool]:
    _need(contents.is_absolute() and contents.resolve(strict=True) == contents
          and not contents.is_symlink(), "destination_path")
    info = contents.lstat()
    _need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
          and not stat.S_IMODE(info.st_mode) & 0o022, "destination_path")
    _need(_is_below_private_temp(contents), "destination_path")
    contents_fd = _open_directory(contents, code="destination_path")
    resources_created = False
    try:
        try:
            resource_info = os.stat("Resources", dir_fd=contents_fd, follow_symlinks=False)
        except FileNotFoundError:
            os.mkdir("Resources", mode=0o755, dir_fd=contents_fd)
            resource_fd = os.open("Resources", os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                                 dir_fd=contents_fd)
            try:
                os.fchmod(resource_fd, 0o755)
            finally:
                os.close(resource_fd)
            resource_info = os.stat("Resources", dir_fd=contents_fd, follow_symlinks=False)
            resources_created = True
        _need(stat.S_ISDIR(resource_info.st_mode) and not stat.S_ISLNK(resource_info.st_mode)
              and resource_info.st_uid == os.getuid()
              and not stat.S_IMODE(resource_info.st_mode) & 0o022, "destination_resources")
        resources_fd = os.open("Resources", os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                               dir_fd=contents_fd)
        try:
            try:
                os.stat("PythonRuntime", dir_fd=resources_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise NormalizeError("destination_exists")
            return contents_fd, resources_fd, resources_created
        except BaseException:
            os.close(resources_fd)
            raise
    except BaseException:
        os.close(contents_fd)
        raise


def _write_all(fd: int, data: bytes, deadline: float) -> None:
    view = memoryview(data)
    while view:
        _tick(deadline)
        written = os.write(fd, view)
        _need(written > 0, "io_error")
        view = view[written:]


def _copy_regular(source_fd: int, destination_fd: int, relative: str,
                  expected: dict[str, Any], expected_identity: tuple[int, ...],
                  deadline: float) -> dict[str, Any]:
    source_parent, leaf = _open_parent_at(source_fd, relative, "source_changed")
    source_file = None
    target_parent = target_file = None
    try:
        source_file = os.open(leaf, os.O_RDONLY | _NOFOLLOW | _CLOEXEC | getattr(os, "O_NONBLOCK", 0),
                              dir_fd=source_parent)
        before = os.fstat(source_file)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and _identity(before) == expected_identity
              and before.st_size == expected["bytes"]
              and _identity(before)[5] & 0o777 == int(expected["mode"], 8), "source_changed")
        identity = _identity(before)
        target_parent = _open_dir_at(destination_fd, tuple(PurePosixPath(relative).parts[:-1]),
                                     "destination_changed")
        target_file = os.open(PurePosixPath(relative).parts[-1],
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                              0o600, dir_fd=target_parent)
        digest = hashlib.sha256()
        count = 0
        prefix = b""
        while True:
            _tick(deadline)
            block = os.read(source_file, BLOCK_BYTES)
            if not block:
                break
            if len(prefix) < 4:
                prefix = (prefix + block)[:4]
            digest.update(block)
            count += len(block)
            _write_all(target_file, block, deadline)
        after = os.fstat(source_file)
        _need(_identity(after) == identity and count == expected["bytes"]
              and digest.hexdigest() == expected["sha256"], "source_changed")
        is_macho = prefix in _MACHO_MAGICS
        normalized_mode = 0o755 if is_macho else 0o644
        os.fchmod(target_file, normalized_mode)
        os.fsync(target_file)
        target_info = os.fstat(target_file)
        _need(stat.S_ISREG(target_info.st_mode) and target_info.st_nlink == 1
              and target_info.st_size == count
              and stat.S_IMODE(target_info.st_mode) == normalized_mode, "destination_changed")
        return {"type": "file", "mode": f"{normalized_mode:04o}",
                "bytes": count, "sha256": digest.hexdigest()}
    except NormalizeError:
        raise
    except OSError as error:
        raise NormalizeError("io_error") from error
    finally:
        if target_file is not None:
            os.close(target_file)
        if target_parent is not None:
            os.close(target_parent)
        if source_file is not None:
            os.close(source_file)
        os.close(source_parent)


def _copy_symlink(source_fd: int, destination_fd: int, destination_path: Path, relative: str,
                  expected: dict[str, Any], expected_identity: tuple[int, ...]) -> dict[str, Any]:
    source_target, source_identity = _readlink_at(source_fd, relative)
    _need(source_target == expected["target"] and source_identity == expected_identity,
          "source_changed")
    target_parent = _open_dir_at(destination_fd, tuple(PurePosixPath(relative).parts[:-1]),
                                 "destination_changed")
    try:
        os.symlink(source_target, PurePosixPath(relative).parts[-1], dir_fd=target_parent)
        lchmod = getattr(os, "lchmod", None)
        _need(lchmod is not None, "symlink_mode")
        lchmod(destination_path / relative, 0o777)
        info = os.stat(PurePosixPath(relative).parts[-1], dir_fd=target_parent, follow_symlinks=False)
        _need(stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o777,
              "destination_changed")
        actual_target = os.readlink(PurePosixPath(relative).parts[-1], dir_fd=target_parent)
        _need(actual_target == expected["target"], "destination_changed")
        return {"type": "symlink", "mode": "0777", "target": actual_target,
                "resolved_target": expected["resolved_target"],
                "source_mode": expected["source_mode"]}
    except NormalizeError:
        raise
    except OSError as error:
        raise NormalizeError("io_error") from error
    finally:
        os.close(target_parent)


def _create_dest_dirs(destination_fd: int, entries: dict[str, dict[str, Any]], deadline: float) -> None:
    directories = sorted((name for name, row in entries.items() if row["type"] == "directory"),
                         key=lambda name: (len(PurePosixPath(name).parts), name))
    for relative in directories:
        _tick(deadline)
        parent_fd, leaf = _open_parent_at(destination_fd, relative, "destination_changed")
        child_fd = None
        try:
            os.mkdir(leaf, mode=0o755, dir_fd=parent_fd)
            child_fd = os.open(leaf, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                               dir_fd=parent_fd)
            os.fchmod(child_fd, 0o755)
            info = os.fstat(child_fd)
            _need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755,
                  "destination_changed")
        except OSError as error:
            raise NormalizeError("io_error") from error
        finally:
            if child_fd is not None:
                os.close(child_fd)
            os.close(parent_fd)


def _scan_output(destination_path: Path, destination_fd: int, entries: dict[str, dict[str, Any]],
                 deadline: float) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    observed, _identities = _scan_tree(destination_path, destination_fd, deadline,
                                       exclude_control=False)
    _need(set(observed) == set(entries), "destination_changed")
    actual: dict[str, dict[str, Any]] = {}
    for relative, expected in entries.items():
        row = observed[relative]
        if expected["type"] == "symlink":
            row = {"type": "symlink", "mode": row["mode"], "target": row["target"],
                   "resolved_target": expected["resolved_target"],
                   "source_mode": expected["source_mode"]}
        actual[relative] = row
    attrs: dict[str, list[str]] = {}
    for relative, expected in sorted(entries.items()):
        _tick(deadline)
        _need(actual[relative] == expected, "destination_changed")
        attrs[relative] = _xattr_names(destination_path / relative)
    root_attrs = _xattr_names(destination_path)
    attrs["."] = root_attrs
    _need(all(all(name == "com.apple.provenance" for name in names)
              for names in attrs.values()), "destination_xattr")
    return actual, attrs


def _verify_source_unchanged(source_payload: Path, expected_tree_sha256: str,
                             original_entries: dict[str, dict[str, Any]],
                             original_identities: dict[str, tuple[int, ...]],
                             original_root_identity: tuple[int, ...], deadline: float) -> None:
    source_fd = _open_directory(source_payload, code="source_changed")
    try:
        control, _identity_control = _read_tree_control(source_fd, deadline)
        _need(_sha256(control) == expected_tree_sha256, "source_changed")
        current_manifest = _json_object(control)
        current_entries = _validate_manifest(current_manifest, deadline)
        observed, identities = _scan_tree(source_payload, source_fd, deadline)
        observed = _source_inventory_matches(observed, current_entries)
        root_identity = _identity(os.fstat(source_fd))
        _need(current_entries == original_entries and observed == original_entries
              and identities == original_identities and root_identity == original_root_identity,
              "source_changed")
        _check_source_xattrs(source_payload, sorted(original_entries))
    finally:
        os.close(source_fd)


def copy_normalized_python(source_payload: Path, source_tree_sha256: str,
                           destination_contents: Path) -> dict[str, Any]:
    """Copy E34 payload entries into a new Contents/Resources/PythonRuntime tree.

    The control inventory is validated and excluded from the copy. No payload is
    imported, executed, downloaded, signed, or adopted. Partial destination data
    is deliberately retained if a write or verification fails.
    """
    started = time.monotonic()
    deadline = started + MAX_SECONDS
    source_fd = contents_fd = resources_fd = runtime_fd = None
    try:
        source_fd, source_root_info, control, control_identity, manifest, source_entries, identities, source_xattrs = \
            _validate_source(Path(source_payload), source_tree_sha256, deadline)
        _tick(deadline)
        contents_fd, resources_fd, resources_created = _validate_destination(Path(destination_contents))
        os.mkdir("PythonRuntime", mode=0o755, dir_fd=resources_fd)
        runtime_fd = os.open("PythonRuntime", os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                             dir_fd=resources_fd)
        os.fchmod(runtime_fd, 0o755)
        root_info = os.fstat(runtime_fd)
        _need(stat.S_IMODE(root_info.st_mode) == 0o755 and root_info.st_uid == os.getuid(),
              "destination_changed")

        _create_dest_dirs(runtime_fd, source_entries, deadline)
        normalized_entries: dict[str, dict[str, Any]] = {}
        for relative, expected in sorted(source_entries.items()):
            _tick(deadline)
            if expected["type"] == "directory":
                normalized_entries[relative] = {"type": "directory", "mode": "0755"}
            elif expected["type"] == "file":
                normalized_entries[relative] = _copy_regular(
                    source_fd, runtime_fd, relative, expected, identities[relative], deadline)
            else:
                # E34 links are created after all regular files and directories.
                continue
        for relative, expected in sorted(source_entries.items()):
            if expected["type"] == "symlink":
                _tick(deadline)
                normalized_entries[relative] = _copy_symlink(
                    source_fd, runtime_fd, Path(destination_contents) / "Resources" / "PythonRuntime",
                    relative, expected, identities[relative])

        _need(set(normalized_entries) == set(source_entries), "destination_changed")
        actual, destination_xattrs = _scan_output(
            Path(destination_contents) / "Resources" / "PythonRuntime",
            runtime_fd, normalized_entries, deadline)
        _need(actual == normalized_entries, "destination_changed")
        _verify_source_unchanged(Path(source_payload), source_tree_sha256, source_entries,
                                 identities, _identity(source_root_info), deadline)
        control_after, identity_after = _read_tree_control(source_fd, deadline)
        _need(_sha256(control_after) == source_tree_sha256 and identity_after == control_identity,
              "source_changed")

        result = {
            "schema": 1,
            "state": STATE,
            "profile": manifest["profile"],
            "source_tree_sha256": source_tree_sha256,
            "source_archive_sha256": manifest["archive_sha256"],
            "source_metadata_sha256": manifest["metadata_sha256"],
            "expected_metadata": manifest["expected_metadata"],
            "provenance": manifest["provenance"],
            "licenses": manifest["licenses"],
            "destination_relative": "Resources/PythonRuntime",
            "source_entries": source_entries,
            "inventory": normalized_entries,
            "file_count": sum(row["type"] == "file" for row in normalized_entries.values()),
            "directory_count": sum(row["type"] == "directory" for row in normalized_entries.values()) + 1,
            "symlink_count": sum(row["type"] == "symlink" for row in normalized_entries.values()),
            "selected_bytes": sum(row.get("bytes", 0) for row in normalized_entries.values()),
            "source_unchanged": True,
            "xattr_api_available": True,
            "destination_xattr_names": destination_xattrs,
            "xattr_values_read": False,
            "payload_execution": "NOT_RUN",
            "signature": "NOT_RUN",
            "adoption": "NOT_ADOPTED",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        return result
    except NormalizeError:
        raise
    except OSError as error:
        raise NormalizeError("io_error") from error
    finally:
        for fd in (runtime_fd, resources_fd, contents_fd, source_fd):
            if fd is not None:
                os.close(fd)
