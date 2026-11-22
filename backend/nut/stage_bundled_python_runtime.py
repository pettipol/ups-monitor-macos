#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage one admitted PBS Python distribution without executing its code."""
from __future__ import annotations

import argparse
from compression import zstd
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import time
from typing import Any, BinaryIO, Iterator
import unicodedata

INPUTS_NAME = 'bundled_python_runtime_inputs.json'
INPUTS_SHA256 = '5e40eb5fd670fab8fdacc7a2cfd3a3eef8dec60cc36648bda091ca2499da8914'
STATE = 'STAGED_PYTHON_NOT_EXECUTED_NOT_ADOPTED'
BLOCK = 1024 * 1024


class StageError(ValueError):
    """Closed failure code, without captured content or private paths."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _need(value: bool, code: str) -> None:
    if not value:
        raise StageError(code)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(raw: bytes, code: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            _need(key not in out, code)
            out[key] = value
        return out
    try:
        result = json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(StageError(code)))
        _need(type(result) is dict, code)
        return result
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise StageError(code) from error


def _valid_hash(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _validate_inputs(inputs: dict[str, Any]) -> None:
    try:
        _need(set(inputs) == {'schema', 'profile', 'archive', 'metadata', 'expected', 'limits', 'provenance'}
              and type(inputs['schema']) is int and inputs['schema'] == 1
              and type(inputs['profile']) is str and bool(inputs['profile']), 'invalid_inputs')
        for key in ('archive', 'metadata'):
            row = inputs[key]
            _need(set(row) == ({'sha256', 'bytes'} if key == 'archive' else {'sha256', 'bytes', 'path'})
                  and _valid_hash(row['sha256']) and type(row['bytes']) is int and row['bytes'] > 0,
                  'invalid_inputs')
        _need(inputs['metadata']['path'] == 'python/PYTHON.json', 'invalid_inputs')
        expected = inputs['expected']
        _need(set(expected) == {'python_version', 'target_triple', 'python_exe', 'apple_sdk_deployment_target'}
              and all(type(value) is str and value and '\0' not in value for value in expected.values()),
              'invalid_inputs')
        limits = inputs['limits']
        _need(set(limits) == {'seconds', 'members', 'total_bytes', 'selected_bytes', 'file_bytes'}
              and all(type(v) is int and v > 0 for v in limits.values())
              and limits['seconds'] <= 120 and limits['members'] <= 20000
              and limits['total_bytes'] <= 4 * 1024**3 and limits['selected_bytes'] <= 1024**3
              and limits['file_bytes'] <= 128 * 1024**2
              and inputs['metadata']['bytes'] <= min(limits['file_bytes'], 4 * BLOCK), 'invalid_inputs')
        provenance = inputs['provenance']
        _need(set(provenance) == {'provider', 'release', 'upstream_commit', 'url'}
              and all(type(v) is str and v and '\0' not in v for v in provenance.values()), 'invalid_inputs')
    except (KeyError, TypeError, AttributeError) as error:
        raise StageError('invalid_inputs') from error


def _public_inputs() -> dict[str, Any]:
    path = Path(__file__).with_name(INPUTS_NAME)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 65536, 'invalid_inputs')
        raw = stream.read(before.st_size + 1)
        _need(len(raw) == before.st_size and _identity(before) == _identity(os.fstat(stream.fileno())),
              'invalid_inputs')
    _need(_hash(raw) == INPUTS_SHA256, 'invalid_inputs')
    inputs = _json(raw, 'invalid_inputs')
    _validate_inputs(inputs)
    return inputs


def _canonical(name: str, *, directory: bool = False) -> str:
    _need(type(name) is str and bool(name) and '\0' not in name and '\\' not in name
          and len(name.encode('utf-8')) <= 4096, 'unsafe_path')
    normalized = name[:-1] if directory and name.endswith('/') else name
    path = PurePosixPath(normalized)
    _need(not path.is_absolute() and '..' not in path.parts and path.as_posix() == normalized
          and normalized not in ('', '.'), 'unsafe_path')
    return normalized


def _selected(name: str) -> str | None:
    if name == 'python/PYTHON.json':
        return 'PYTHON.json'
    if name in ('python/install', 'python/licenses') or name.startswith(('python/install/', 'python/licenses/')):
        return name[len('python/'):]
    return None


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def _check_archive_identity(raw: BinaryIO, path: Path, identity: tuple[int, ...]) -> None:
    _need(_identity(os.fstat(raw.fileno())) == identity
          and _identity(os.stat(path, follow_symlinks=False)) == identity, 'source_changed')


@dataclass(frozen=True)
class _Member:
    name: str
    kind: str
    size: int
    mode: int
    target: str = ''


class _BoundedReader:
    def __init__(self, stream: BinaryIO, maximum: int, tick: Any):
        self.stream, self.maximum, self.tick, self.count = stream, maximum, tick, 0

    def read(self, size: int = -1) -> bytes:
        self.tick()
        _need(size >= 0, 'total_limit')
        data = self.stream.read(size)
        self.count += len(data)
        _need(self.count <= self.maximum, 'total_limit')
        return data


@contextmanager
def _archive(raw: BinaryIO, limits: dict[str, int], tick: Any) -> Iterator[tarfile.TarFile]:
    raw.seek(0)
    # Include a bounded allowance for tar headers/padding, not arbitrary trailing data.
    stream_cap = limits['total_bytes'] + limits['members'] * 4096 + 2 * BLOCK
    with zstd.ZstdFile(raw, 'rb') as decompressed:
        reader = _BoundedReader(decompressed, stream_cap, tick)
        with tarfile.open(fileobj=reader, mode='r|') as archive:
            yield archive


def _member(member: tarfile.TarInfo) -> _Member:
    kind = ('file' if member.type in (tarfile.REGTYPE, tarfile.AREGTYPE)
            else 'directory' if member.type == tarfile.DIRTYPE
            else 'symlink' if member.type == tarfile.SYMTYPE else None)
    _need(kind is not None and not member.issparse() and member.mode & ~0o777 == 0, 'unsupported_member')
    name = _canonical(member.name, directory=kind == 'directory')
    _need(name == 'python' or name.startswith('python/'), 'unsafe_path')
    _need(member.size >= 0 and (kind == 'file' or member.size == 0), 'unsupported_member')
    return _Member(name, kind, member.size, member.mode, member.linkname if kind == 'symlink' else '')


def _payload(stream: BinaryIO, tick: Any, *, keep: bool = False) -> tuple[str, bytes]:
    digest, chunks = hashlib.sha256(), []
    while block := stream.read(BLOCK):
        tick()
        digest.update(block)
        if keep:
            chunks.append(block)
    return digest.hexdigest(), b''.join(chunks)


def _scan(raw: BinaryIO, inputs: dict[str, Any], tick: Any) -> tuple[dict[str, _Member], dict[str, dict], bytes]:
    members: dict[str, _Member] = {}
    selected: dict[str, dict] = {}
    aliases: set[str] = set()
    metadata = b''
    total = chosen = 0
    limits = inputs['limits']
    with _archive(raw, limits, tick) as archive:
        for entry in archive:
            tick()
            _need(len(members) < limits['members'], 'member_limit')
            item = _member(entry)
            alias = unicodedata.normalize('NFD', item.name).casefold()
            _need(item.name not in members and alias not in aliases, 'duplicate_member')
            members[item.name] = item
            aliases.add(alias)
            _need(item.size <= limits['file_bytes'], 'file_limit')
            total += item.size
            _need(total <= limits['total_bytes'], 'total_limit')
            target = _selected(item.name)
            if target is None:
                continue
            chosen += item.size
            _need(chosen <= limits['selected_bytes'], 'selected_limit')
            row: dict[str, Any] = {'type': item.kind, 'mode': f'{item.mode:04o}'}
            if item.kind == 'file':
                stream = archive.extractfile(entry)
                _need(stream is not None, 'source_changed')
                is_metadata = item.name == inputs['metadata']['path']
                if is_metadata:
                    _need(item.size == inputs['metadata']['bytes'], 'metadata_pin')
                with stream:
                    pin, data = _payload(stream, tick, keep=is_metadata)
                row.update(sha256=pin, bytes=item.size)
                if is_metadata:
                    _need(pin == inputs['metadata']['sha256'], 'metadata_pin')
                    metadata = data
            elif item.kind == 'symlink':
                row['target'] = item.target
            selected[target] = row
    _need(bool(metadata), 'metadata_pin')
    all_spellings: dict[str, str] = {}
    for name in members:
        for path in (PurePosixPath(name), *PurePosixPath(name).parents):
            spelling = path.as_posix()
            if spelling == '.':
                continue
            alias = unicodedata.normalize('NFD', spelling).casefold()
            _need(all_spellings.setdefault(alias, spelling) == spelling, 'duplicate_member')
        for parent in PurePosixPath(name).parents:
            if parent.as_posix() in members:
                _need(members[parent.as_posix()].kind == 'directory', 'member_parent_conflict')
    return members, selected, metadata


def _link_path(parent: str, target: str, rest: tuple[str, ...] = ()) -> str:
    _need(bool(target) and not target.startswith('/') and '\\' not in target and '\0' not in target
          and len(target.encode('utf-8')) <= 4096, 'unsafe_symlink')
    parts = list(PurePosixPath(parent).parts) if parent != '.' else []
    for part in (*target.split('/'), *rest):
        if part in ('', '.'):
            continue
        if part == '..':
            _need(len(parts) > 1, 'unsafe_symlink')
            parts.pop()
        else:
            parts.append(part)
    _need(bool(parts) and parts[0] == 'install', 'unsafe_symlink')
    return '/'.join(parts)


def _complete_tree(selected: dict[str, dict], tick: Any) -> None:
    for name in list(selected):
        tick()
        for parent in PurePosixPath(name).parents:
            key = parent.as_posix()
            if key != '.':
                _need(key not in selected or selected[key]['type'] == 'directory', 'member_parent_conflict')
                selected.setdefault(key, {'type': 'directory', 'mode': '0700'})
    for row in selected.values():
        if row['type'] == 'directory':
            row['mode'] = '0700'
    for name, row in selected.items():
        tick()
        if row['type'] != 'symlink':
            continue
        _need(name.startswith('install/'), 'unsafe_symlink')
        current = _link_path(PurePosixPath(name).parent.as_posix(), row['target'])
        seen = {name}
        while True:
            tick()
            changed = False
            parts = PurePosixPath(current).parts
            for index in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:index])
                candidate = selected.get(prefix)
                _need(candidate is not None, 'missing_target')
                if candidate['type'] == 'symlink':
                    _need(prefix not in seen, 'symlink_cycle')
                    seen.add(prefix)
                    current = _link_path(PurePosixPath(prefix).parent.as_posix(), candidate['target'], parts[index:])
                    changed = True
                    break
                _need(index == len(parts) or candidate['type'] == 'directory', 'missing_target')
            if not changed:
                break
        row['resolved_target'] = current


def _metadata_contract(raw: bytes, inputs: dict[str, Any], selected: dict[str, dict]) -> dict[str, Any]:
    metadata = _json(raw, 'metadata_contract')
    _need(all(metadata.get(key) == value for key, value in inputs['expected'].items()), 'metadata_contract')
    executable = _canonical(metadata['python_exe'])
    row = selected.get(executable, {})
    _need(executable.startswith('install/') and row.get('type') == 'file'
          and int(row['mode'], 8) & 0o100 != 0, 'metadata_contract')
    license_paths = metadata.get('license_path')
    licenses = metadata.get('licenses')
    _need(type(license_paths) is str and type(licenses) is list
          and bool(licenses) and all(type(v) is str and bool(v) for v in licenses), 'metadata_contract')
    paths = {license_paths}
    declarations: list[dict[str, Any]] = [{'component': 'python', 'licenses': licenses, 'license_paths': [license_paths]}]
    build = metadata.get('build_info', {})
    _need(type(build) is dict and type(build.get('extensions', {})) is dict, 'metadata_contract')
    for name, variants in build.get('extensions', {}).items():
        _need(type(variants) is list, 'metadata_contract')
        for index, variant in enumerate(variants):
            _need(type(variant) is dict, 'metadata_contract')
            if 'license_paths' not in variant:
                continue
            values = variant['license_paths']
            _need(type(values) is list and all(type(v) is str for v in values), 'metadata_contract')
            paths.update(values)
            declarations.append({'component': name, 'variant': index, 'license_paths': values,
                                 'licenses': variant.get('licenses', []),
                                 'license_public_domain': variant.get('license_public_domain', False)})
    for path in paths:
        name = _canonical(path)
        _need(name.startswith('licenses/') and selected.get(name, {}).get('type') == 'file', 'missing_license')
    return {'paths': sorted(paths), 'declarations': declarations,
            'legal_or_redistribution_review': 'NOT_RUN'}


def _destination(path: Path) -> tuple[Path, int]:
    _need(path.is_absolute() and '..' not in path.parts and path.name not in ('', '.', '..'), 'destination_rejected')
    parent = path.parent
    _need(parent.resolve(strict=True) == parent, 'destination_rejected')
    roots = (Path('/private/tmp'), Path(os.environ.get('TMPDIR', '/private/tmp')).resolve(strict=True))
    _need(any(path != root and root in path.parents for root in roots), 'destination_rejected')
    info = parent.stat()
    _need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
          and not stat.S_IMODE(info.st_mode) & 0o022, 'destination_rejected')
    if path.exists() or path.is_symlink():
        raise StageError('destination_exists')
    return parent, os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _parent_fd(root: int, name: str) -> tuple[int, str]:
    parts = PurePosixPath(name).parts
    current = os.dup(root)
    try:
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = following
        return current, parts[-1]
    except BaseException:
        os.close(current)
        raise


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        wrote = os.write(fd, view)
        _need(wrote > 0, 'io_error')
        view = view[wrote:]


def _create_payload(raw: BinaryIO, root: int, inputs: dict[str, Any], members: dict[str, _Member],
                    selected: dict[str, dict], tick: Any) -> None:
    directories = sorted((name for name, row in selected.items() if row['type'] == 'directory'),
                         key=lambda name: (len(PurePosixPath(name).parts), name))
    for name in directories:
        tick()
        parent, leaf = _parent_fd(root, name)
        try:
            os.mkdir(leaf, mode=0o700, dir_fd=parent)
        finally:
            os.close(parent)
    seen = set()
    with _archive(raw, inputs['limits'], tick) as archive:
        for entry in archive:
            tick()
            item = _member(entry)
            _need(item.name not in seen and members.get(item.name) == item, 'source_changed')
            seen.add(item.name)
            name = _selected(item.name)
            if name is None or item.kind != 'file':
                continue
            parent, leaf = _parent_fd(root, name)
            target = None
            try:
                target = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=parent)
                source = archive.extractfile(entry)
                _need(source is not None, 'source_changed')
                digest, count = hashlib.sha256(), 0
                with source:
                    while block := source.read(BLOCK):
                        tick()
                        _write_all(target, block)
                        digest.update(block)
                        count += len(block)
                _need(count == selected[name]['bytes'] and digest.hexdigest() == selected[name]['sha256'], 'source_changed')
                os.fchmod(target, item.mode)
            finally:
                if target is not None:
                    os.close(target)
                os.close(parent)
    _need(seen == set(members), 'source_changed')
    for name, row in sorted(selected.items()):
        if row['type'] == 'symlink':
            tick()
            parent, leaf = _parent_fd(root, name)
            try:
                os.symlink(row['target'], leaf, dir_fd=parent)
                info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                _need(stat.S_ISLNK(info.st_mode), 'source_changed')
                row['source_mode'], row['mode'] = row['mode'], f'{stat.S_IMODE(info.st_mode):04o}'
            finally:
                os.close(parent)


def _verify_payload(root: Path, selected: dict[str, dict], tick: Any) -> None:
    found: set[str] = set()
    for parent, directories, leaves in os.walk(root, followlinks=False):
        for leaf in directories + leaves:
            tick()
            path = Path(parent) / leaf
            name = path.relative_to(root).as_posix()
            found.add(name)
            _need(name in selected, 'source_changed')
            row, info = selected[name], path.lstat()
            if row['type'] == 'directory':
                _need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700, 'source_changed')
            elif row['type'] == 'symlink':
                _need(stat.S_ISLNK(info.st_mode) and os.readlink(path) == row['target']
                      and f'{stat.S_IMODE(info.st_mode):04o}' == row['mode'], 'source_changed')
                _need(path.resolve(strict=True) == root / row['resolved_target'], 'unsafe_symlink')
            else:
                _need(stat.S_ISREG(info.st_mode) and info.st_size == row['bytes']
                      and f'{stat.S_IMODE(info.st_mode):04o}' == row['mode'], 'source_changed')
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(fd, 'rb') as stream:
                    digest, _data = _payload(stream, tick)
                _need(digest == row['sha256'], 'source_changed')
    _need(found == set(selected), 'source_changed')


def _stage_with_inputs(archive: Path, destination: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    """Private synthetic-fixture seam; the CLI never accepts replacement inputs."""
    parent_fd = root_fd = None
    try:
        _validate_inputs(inputs)
        deadline = time.monotonic() + inputs['limits']['seconds']
        def tick() -> None:
            _need(time.monotonic() < deadline, 'deadline')
        _need(archive.is_absolute() and archive.resolve(strict=True) == archive, 'unsafe_path')
        parent, parent_fd = _destination(destination)
        source_fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(source_fd, 'rb') as raw:
            info = os.fstat(raw.fileno())
            _need(stat.S_ISREG(info.st_mode), 'archive_size')
            _need(info.st_size == inputs['archive']['bytes'], 'archive_size')
            identity = _identity(info)
            pin, _data = _payload(raw, tick)
            _need(pin == inputs['archive']['sha256'], 'archive_pin')
            members, selected, metadata = _scan(raw, inputs, tick)
            _complete_tree(selected, tick)
            licenses = _metadata_contract(metadata, inputs, selected)
            _check_archive_identity(raw, archive, identity)
            raw.seek(0)
            _need(_payload(raw, tick)[0] == inputs['archive']['sha256'], 'source_changed')
            # No destination has been created before all archive/metadata/link admission gates.
            tick()
            try:
                os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError as error:
                raise StageError('destination_exists') from error
            root_fd = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=parent_fd)
            created = os.fstat(root_fd)
            _need((created.st_dev, created.st_ino) ==
                  (destination.stat().st_dev, destination.stat().st_ino), 'destination_rejected')
            _create_payload(raw, root_fd, inputs, members, selected, tick)
            _verify_payload(destination, selected, tick)
            _check_archive_identity(raw, archive, identity)
            _need(parent.resolve(strict=True) == parent and destination.resolve(strict=True) == destination
                  and (os.stat(destination, follow_symlinks=False).st_dev,
                       os.stat(destination, follow_symlinks=False).st_ino) ==
                      (created.st_dev, created.st_ino), 'destination_rejected')
            inventory = {'schema': 1, 'state': STATE, 'profile': inputs['profile'],
                'archive_sha256': inputs['archive']['sha256'], 'metadata_sha256': inputs['metadata']['sha256'],
                'expected_metadata': inputs['expected'], 'provenance': inputs['provenance'],
                'licenses': licenses, 'entries': dict(sorted(selected.items())),
                'closure_macho': 'NOT_RUN', 'runtime_execution': 'NOT_RUN', 'adoption': 'NOT_ADOPTED'}
            encoded = (json.dumps(inventory, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
            _need(len(encoded) <= 16 * BLOCK and len(encoded) + sum(
                row.get('bytes', 0) for row in selected.values()) <= inputs['limits']['selected_bytes'], 'selected_limit')
            manifest_fd = os.open('runtime-tree.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                  | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
            try:
                _write_all(manifest_fd, encoded)
                os.fsync(manifest_fd)
            finally:
                os.close(manifest_fd)
            control = {'type': 'file', 'mode': '0600', 'bytes': len(encoded), 'sha256': _hash(encoded)}
            _verify_payload(destination, {**selected, 'runtime-tree.json': control}, tick)
            _check_archive_identity(raw, archive, identity)
            named = os.stat(destination, follow_symlinks=False)
            _need(parent.resolve(strict=True) == parent and not destination.is_symlink()
                  and (named.st_dev, named.st_ino) == (created.st_dev, created.st_ino), 'destination_rejected')
            tick()
            return {'schema': 1, 'state': STATE, 'profile': inputs['profile'],
                    'archive_sha256': inputs['archive']['sha256'], 'metadata_sha256': inputs['metadata']['sha256'],
                    'python_version': inputs['expected']['python_version'],
                    'target_triple': inputs['expected']['target_triple'], 'python_exe': inputs['expected']['python_exe'],
                    'declared_minimum_macos': inputs['expected']['apple_sdk_deployment_target'],
                    'file_count': sum(row['type'] == 'file' for row in selected.values()),
                    'symlink_count': sum(row['type'] == 'symlink' for row in selected.values()),
                    'directory_count': sum(row['type'] == 'directory' for row in selected.values()),
                    'selected_bytes': sum(row.get('bytes', 0) for row in selected.values()),
                    'inventory_name': 'runtime-tree.json', 'inventory_sha256': _hash(encoded),
                    'closure_macho': 'NOT_RUN', 'runtime_execution': 'NOT_RUN', 'adoption': 'NOT_ADOPTED'}
    except StageError:
        raise
    except (OSError, EOFError, tarfile.TarError, zstd.ZstdError, UnicodeError) as error:
        raise StageError('io_error') from error
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def stage(archive: Path, destination: Path) -> dict[str, Any]:
    """Stage only the immutable public admission adjacent to this script."""
    return _stage_with_inputs(archive, destination, _public_inputs())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = stage(args.archive, args.destination)
    except (StageError, OSError) as error:
        print(json.dumps({'state': 'REJECTED_NOT_ADOPTED', 'error': getattr(error, 'code', 'io_error')}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
