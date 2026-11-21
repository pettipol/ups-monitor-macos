#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare managed-runtime controls from an already signed Contents staging tree.

This writes only the allowlisted backend, the two public control files, and a
derived Swift pin. It does not build, sign, execute, install, or change the
canonical release pin.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any

_HERE = Path(__file__).resolve().parent
_NORMALIZER_PATH = _HERE / 'normalize_bundled_python.py'
_READER_PATH = _HERE / 'managed_bundled_operational_entrypoint.py'
_INPUTS_PATH = _HERE / 'bundled_python_runtime_inputs.json'
_INPUTS_SHA256 = '5e40eb5fd670fab8fdacc7a2cfd3a3eef8dec60cc36648bda091ca2499da8914'
_MAX_FILE = 128 * 1024 * 1024
_MAX_TOTAL = 1024 * 1024 * 1024
_MAX_MODULE = 2 * 1024 * 1024
_MAX_CONTROL = 16 * 1024 * 1024
_MAX_SECONDS = 120


class CandidateError(ValueError):
    """Closed error code; messages do not contain input paths or file bytes."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _need(condition: Any, code: str) -> None:
    if not condition:
        raise CandidateError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_source(name: str, path: Path) -> ModuleType:
    """Load a sibling source file without importing stale bytecode under -B."""
    try:
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 2 * 1024 * 1024,
              'source_module')
        raw = path.read_bytes()
        _need(len(raw) == info.st_size, 'source_module')
        code = compile(raw, str(path), 'exec', dont_inherit=True)
        module = ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(code, module.__dict__)
        return module
    except CandidateError:
        raise
    except (OSError, SyntaxError, ValueError) as error:
        raise CandidateError('source_module') from error


def _read_regular(path: Path, maximum: int, code: str) -> tuple[bytes, tuple[int, ...]]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and not before.st_mode & 0o7000
                  and 0 < before.st_size <= maximum, code)
            raw = stream.read(before.st_size + 1)
            after = os.fstat(stream.fileno())
            _need(len(raw) == before.st_size and _identity(before) == _identity(after), code)
        named = path.lstat()
        _need(_identity(named) == _identity(before), code)
        return raw, _identity(before)
    except CandidateError:
        raise
    except OSError as error:
        raise CandidateError(code) from error


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _write_new(path: Path, raw: bytes, mode: int) -> None:
    fd = None
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0), mode)
        os.fchmod(fd, mode)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            _need(count > 0, 'write_failed')
            view = view[count:]
        os.fsync(fd)
    except CandidateError:
        raise
    except OSError as error:
        raise CandidateError('write_failed') from error
    finally:
        if fd is not None:
            os.close(fd)


def _write_new_at(directory_fd: int, name: str, raw: bytes, mode: int) -> None:
    fd = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
                     mode, dir_fd=directory_fd)
        os.fchmod(fd, mode)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            _need(count > 0, 'write_failed')
            view = view[count:]
        os.fsync(fd)
    except CandidateError:
        raise
    except OSError as error:
        raise CandidateError('write_failed') from error
    finally:
        if fd is not None:
            os.close(fd)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')


def _canonical_directory(path: Path, name: str) -> None:
    try:
        _need(path.is_absolute() and path.name == name and path.resolve(strict=True) == path
              and stat.S_ISDIR(path.lstat().st_mode), 'contents_path')
    except (OSError, RuntimeError) as error:
        if isinstance(error, CandidateError):
            raise
        raise CandidateError('contents_path') from error


def _read_runtime(runtime_root: Path, normalizer: ModuleType, deadline: float
                  ) -> tuple[dict[str, dict], dict[str, tuple], tuple]:
    try:
        root_fd = normalizer._open_directory(runtime_root, code='runtime_path')
    except Exception as error:
        raise CandidateError('runtime_path') from error
    try:
        _need(not (runtime_root / 'runtime-tree.json').exists(), 'runtime_control_present')
        root_identity = normalizer._identity(os.fstat(root_fd))
        observed, identities = normalizer._scan_tree(runtime_root, root_fd, deadline, exclude_control=False)
        _need(bool(observed) and len(observed) <= 20000, 'runtime_inventory')
        total = sum(row.get('bytes', 0) for row in observed.values())
        _need(total <= _MAX_TOTAL, 'total_limit')
        for row in observed.values():
            if row['type'] == 'file':
                _need(0 <= row['bytes'] <= _MAX_FILE, 'file_limit')
        resolved = normalizer._resolve_links(observed, deadline)
        result: dict[str, dict] = {}
        for relative, row in observed.items():
            if row['type'] == 'symlink':
                _need(row['mode'] == '0777', 'runtime_link_mode')
                result[relative] = {**row, 'resolved_target': resolved[relative]}
            else:
                result[relative] = dict(row)
        return result, identities, root_identity
    except CandidateError:
        raise
    except Exception as error:
        code = getattr(error, 'code', 'runtime_inventory')
        raise CandidateError(code if type(code) is str else 'runtime_inventory') from error
    finally:
        os.close(root_fd)


def _scan_runtime(runtime_root: Path, normalizer: ModuleType, deadline: float
                  ) -> tuple[dict[str, dict], dict[str, tuple], tuple]:
    return _read_runtime(runtime_root, normalizer, deadline)


def _read_helper(root: Path, normalizer: ModuleType, common: ModuleType, deadline: float,
                 *, allow_input_link_mode: bool = False
                 ) -> tuple[dict[str, dict], dict[str, tuple], tuple]:
    """Scan a signed helper without applying the PBS install/licenses grammar.

    Reuse the fd readers and consumer link resolver; never follow directory links.
    The subsequent full consumer pass enforces the same inventory on disk.
    """
    _canonical_directory(root, 'UPSOperationalHelper.app')
    root_fd = normalizer._open_directory(root, code='helper_root')
    entries: dict[str, dict] = {}
    identities: dict[str, tuple] = {}
    aliases: set[str] = set()
    total = 0
    root_identity = normalizer._identity(os.fstat(root_fd))

    def walk(fd: int, prefix: str) -> None:
        nonlocal total
        _need(time.monotonic() < deadline, 'deadline')
        before = normalizer._identity(os.fstat(fd))
        names = []
        with os.scandir(fd) as iterator:
            for item in iterator:
                names.append(item.name)
                _need(len(entries) + len(names) <= 20000, 'entry_limit')
        if not prefix: _need(names == ['Contents'], 'helper_layout')
        for leaf in sorted(names):
            _need(time.monotonic() < deadline, 'deadline')
            name = prefix + '/' + leaf if prefix else leaf
            common._path(name)
            _need(name.lower() not in aliases, 'name_alias'); aliases.add(name.lower())
            info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
            identity = normalizer._identity(info)
            mode = f'{stat.S_IMODE(info.st_mode):04o}'
            if stat.S_ISDIR(info.st_mode):
                _need(mode == '0755', 'helper_mode')
                entries[name] = {'type': 'directory', 'mode': mode}
                child = normalizer._open_dir_at(fd, (leaf,), 'helper_changed')
                try:
                    _need(normalizer._identity(os.fstat(child)) == identity, 'helper_changed')
                    walk(child, name)
                finally: os.close(child)
            elif stat.S_ISREG(info.st_mode):
                _need(mode in ('0644', '0755') and info.st_nlink == 1, 'helper_mode')
                _need(0 <= info.st_size <= _MAX_FILE, 'file_limit')
                total += info.st_size; _need(total <= _MAX_TOTAL, 'total_limit')
                raw, observed = normalizer._read_regular_at(root_fd, name, deadline, _MAX_FILE)
                _need(observed == identity, 'helper_changed')
                entries[name] = {'type': 'file', 'mode': mode, 'bytes': len(raw), 'sha256': _sha(raw)}
            elif stat.S_ISLNK(info.st_mode):
                _need(mode in (('0755', '0777') if allow_input_link_mode else ('0777',))
                      and info.st_nlink == 1, 'helper_mode')
                target, observed = normalizer._readlink_at(root_fd, name)
                _need(observed == identity, 'helper_changed')
                entries[name] = {'type': 'symlink', 'mode': mode, 'target': target}
            else: raise CandidateError('helper_type')
            _need(normalizer._identity(os.stat(leaf, dir_fd=fd, follow_symlinks=False)) == identity, 'helper_changed')
            identities[name] = identity
        _need(normalizer._identity(os.fstat(fd)) == before, 'helper_changed')
    try:
        walk(root_fd, '')
        _need(entries.get('Contents', {}).get('type') == 'directory', 'helper_layout')
        for name, row in entries.items():
            if row['type'] == 'symlink':
                target = common._resolve(name, row['target'], entries, parents=())
                _need(target.startswith('Contents/'), 'helper_link_scope')
                row['resolved_target'] = target
        _need(normalizer._identity(root.lstat()) == root_identity, 'helper_changed')
        return entries, identities, root_identity
    except (OSError, ValueError) as error:
        if isinstance(error, CandidateError): raise
        raise CandidateError('helper_inventory') from error
    finally: os.close(root_fd)


def _prepare(contents: Path, swift_output: Path, expected_native_sha256: str,
             *, backend_source: Path | None = None, frozen: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + _MAX_SECONDS
    normalizer = _load_source('candidate_normalizer', _NORMALIZER_PATH)
    consumer = _load_source('managed_bundled_operational_entrypoint' if frozen else 'candidate_consumer', _READER_PATH)
    common = consumer
    validator = consumer._validate_bundle
    if frozen:
        bootstrap = _load_source('candidate_frozen_consumer', _HERE / 'managed_frozen_operational_entrypoint.py')
        validator = bootstrap._validate_bundle
        # Explicit second profile; the original layout and default stay fixed.
        consumer = SimpleNamespace(PROFILE=bootstrap.PROFILE, PYTHON_ROOT=bootstrap.HELPER_ROOT,
            PYTHON_PATH=bootstrap.HELPER_PATH, BACKEND_ROOT=consumer.BACKEND_ROOT,
            NATIVE_PATH=consumer.NATIVE_PATH, NATIVE_NAME=consumer.NATIVE_NAME,
            MODULES=bootstrap.MODULES, MANIFEST_PATH=bootstrap.MANIFEST_PATH,
            INVENTORY_PATH=bootstrap.INVENTORY_PATH, _hash=consumer._hash)
    _canonical_directory(contents, 'Contents')
    _need(type(expected_native_sha256) is str and consumer._hash(expected_native_sha256), 'native_identity')
    _need(swift_output.is_absolute() and not swift_output.exists() and not swift_output.is_symlink(), 'pin_exists')
    _need(swift_output.parent.is_dir() and swift_output.parent.resolve(strict=True) == swift_output.parent,
          'pin_parent')
    swift_resolved = swift_output.parent.resolve(strict=True) / swift_output.name
    contents_resolved = contents.resolve(strict=True)
    _need(swift_resolved != contents_resolved and contents_resolved not in swift_resolved.parents,
          'pin_scope')
    modules_root = (backend_source or _HERE).resolve(strict=True)
    checkout_root = _HERE.parents[1].resolve(strict=True)
    _need(all(swift_resolved != source and source not in swift_resolved.parents
              for source in (modules_root, _HERE.resolve(strict=True), checkout_root)), 'pin_source_overlap')
    for parent in (contents / name for name in (('Resources', 'MacOS', 'Helpers') if frozen else ('Resources', 'MacOS'))):
        try:
            _need(stat.S_ISDIR(parent.lstat().st_mode), 'contents_layout')
        except OSError as error:
            raise CandidateError('contents_layout') from error

    backend_dir = contents / consumer.BACKEND_ROOT
    _need(not backend_dir.exists() and not backend_dir.is_symlink(), 'backend_exists')
    _need(not (contents / consumer.MANIFEST_PATH).exists() and not (contents / consumer.INVENTORY_PATH).exists(),
          'control_exists')
    runtime_root = contents / consumer.PYTHON_ROOT
    native_path = contents / consumer.NATIVE_PATH
    def scan_runtime():
        return (_read_helper(runtime_root, normalizer, common, deadline) if frozen
                else _read_runtime(runtime_root, normalizer, deadline))
    runtime_entries, runtime_identities, runtime_root_identity = scan_runtime()
    native_raw, native_identity = _read_regular(native_path, 2 * 1024 * 1024, 'native_identity')
    native_hash = _sha(native_raw)
    _need(native_hash == expected_native_sha256 and stat.S_IMODE(native_path.lstat().st_mode) == 0o755,
          'native_identity')

    module_raw: dict[str, bytes] = {}
    module_identities: dict[str, tuple] = {}
    for name in sorted(consumer.MODULES):
        raw, identity = _read_regular(modules_root / name, _MAX_MODULE, 'module_source')
        module_raw[name], module_identities[name] = raw, identity

    entries: dict[str, dict[str, Any]] = {
        consumer.PYTHON_ROOT: {'type': 'directory', 'mode': '0755'},
        consumer.BACKEND_ROOT: {'type': 'directory', 'mode': '0755'},
    }
    for relative, row in runtime_entries.items():
        name = consumer.PYTHON_ROOT + '/' + relative
        item = {key: value for key, value in row.items()}
        if row['type'] == 'symlink':
            item['resolved_target'] = consumer.PYTHON_ROOT + '/' + row['resolved_target']
        entries[name] = item
    _need(consumer.PYTHON_PATH in entries and entries[consumer.PYTHON_PATH].get('type') == 'file'
          and entries[consumer.PYTHON_PATH].get('mode') == '0755', 'python_executable')
    module_hashes: dict[str, str] = {}
    for name, raw in module_raw.items():
        digest = _sha(raw)
        module_hashes[name] = digest
        entries[consumer.BACKEND_ROOT + '/' + name] = {
            'type': 'file', 'mode': '0644', 'bytes': len(raw), 'sha256': digest}
    entries[consumer.NATIVE_PATH] = {
        'type': 'file', 'mode': '0755', 'bytes': len(native_raw), 'sha256': native_hash}
    _need(len(entries) <= 20000 and sum(row.get('bytes', 0) for row in entries.values()) <= _MAX_TOTAL,
          'closure_limit')

    inventory_raw = _json_bytes({'schema_version': 1, 'entries': entries})
    _need(len(inventory_raw) <= _MAX_CONTROL, 'inventory_limit')
    inventory_hash = _sha(inventory_raw)
    inputs_raw, _ = _read_regular(_INPUTS_PATH, 65536, 'upstream_inputs')
    _need(_sha(inputs_raw) == _INPUTS_SHA256, 'upstream_inputs')
    try:
        upstream_inputs = json.loads(inputs_raw)
        archive_hash = upstream_inputs['archive']['sha256']
        metadata_hash = upstream_inputs['metadata']['sha256']
        _need(consumer._hash(archive_hash) and consumer._hash(metadata_hash), 'upstream_inputs')
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateError('upstream_inputs') from error
    manifest = {
        'schema_version': 1, 'profile': consumer.PROFILE, 'architecture': 'arm64',
        'minimum_macos': '27.0',
        'python': {'root': consumer.PYTHON_ROOT, 'executable': consumer.PYTHON_PATH,
                   'sha256': entries[consumer.PYTHON_PATH]['sha256']},
        'backend': {'root': consumer.BACKEND_ROOT, 'module_sha256': module_hashes},
        'native': {'path': consumer.NATIVE_PATH, 'name': consumer.NATIVE_NAME,
                   'sha256': native_hash, 'bytes': len(native_raw)},
        'closure': {'path': consumer.INVENTORY_PATH, 'sha256': inventory_hash, 'entries': len(entries)},
        'upstream': {'archive_sha256': archive_hash, 'metadata_sha256': metadata_hash},
    }
    if not frozen:
        manifest['backend']['entrypoint'] = consumer.ENTRY_PATH
    manifest_raw = _json_bytes(manifest)
    _need(len(manifest_raw) <= 32768, 'manifest_limit')
    manifest_hash = _sha(manifest_raw)
    pin_type = 'FrozenOperationalReleasePins' if frozen else 'BundledOperationalReleasePins'
    swift_raw = ('// Generated candidate pin; canonical release pin remains nil.\n'
                 f'enum {pin_type} {{\n'
                 f'    static let manifestSHA256: String? = "{manifest_hash}"\n'
                 '}\n').encode('ascii')

    # Recheck all inputs before the first write, then write exclusively.
    entries_after, identities_after, runtime_root_after = (scan_runtime() if frozen
        else _scan_runtime(runtime_root, normalizer, deadline))
    _need(entries_after == runtime_entries and identities_after == runtime_identities
          and runtime_root_after == runtime_root_identity, 'runtime_changed')
    current_native, current_native_id = _read_regular(native_path, 2 * 1024 * 1024, 'native_changed')
    _need(current_native_id == native_identity and _sha(current_native) == native_hash, 'native_changed')
    for name, expected in module_raw.items():
        current, identity = _read_regular(modules_root / name, _MAX_MODULE, 'module_changed')
        _need(current == expected and identity == module_identities[name], 'module_changed')
    contents_fd = backend_parent_fd = backend_fd = None
    try:
        contents_fd = normalizer._open_directory(contents, code='contents_path')
        backend_parts = consumer.BACKEND_ROOT.split('/')
        _need(len(backend_parts) >= 2 and all(backend_parts), 'backend_layout')
        backend_parent_fd = normalizer._open_dir_at(
            contents_fd, tuple(backend_parts[:-1]), code='backend_layout')
        backend_leaf = backend_parts[-1]
        os.mkdir(backend_leaf, mode=0o755, dir_fd=backend_parent_fd)
        backend_fd = os.open(backend_leaf, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                             getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
                             dir_fd=backend_parent_fd)
        os.fchmod(backend_fd, 0o755)
        backend_info = os.fstat(backend_fd)
        _need(stat.S_ISDIR(backend_info.st_mode) and stat.S_IMODE(backend_info.st_mode) == 0o755,
              'backend_mode')
        backend_named = os.stat(backend_leaf, dir_fd=backend_parent_fd, follow_symlinks=False)
        _need(normalizer._identity(backend_info) == normalizer._identity(backend_named), 'backend_changed')
        for name in sorted(module_raw):
            _write_new_at(backend_fd, name, module_raw[name], 0o644)
        _write_new(contents / consumer.INVENTORY_PATH, inventory_raw, 0o644)
        _write_new(contents / consumer.MANIFEST_PATH, manifest_raw, 0o644)
        _write_new(swift_output, swift_raw, 0o644)
    except CandidateError:
        raise
    except FileExistsError as error:
        raise CandidateError('destination_exists') from error
    except OSError as error:
        raise CandidateError('write_failed') from error
    except Exception as error:
        code = getattr(error, 'code', 'backend_layout')
        raise CandidateError(code if type(code) is str else 'backend_layout') from error
    finally:
        for directory_fd in (backend_fd, backend_parent_fd, contents_fd):
            if directory_fd is not None:
                os.close(directory_fd)

    try:
        validator(contents, manifest_hash, check_process=False)
    except Exception as error:
        code = getattr(error, 'code', 'consumer_rejected')
        raise CandidateError(code if type(code) is str else 'consumer_rejected') from error
    _need(_sha((contents / consumer.INVENTORY_PATH).read_bytes()) == inventory_hash
          and _sha((contents / consumer.MANIFEST_PATH).read_bytes()) == manifest_hash
          and _sha(swift_output.read_bytes()) == _sha(swift_raw), 'output_changed')
    return {
        'schema': 1, 'state': ('FROZEN_OPERATIONAL_CANDIDATE_PREPARED_NOT_RELEASED' if frozen
                              else 'BUNDLED_OPERATIONAL_CANDIDATE_PREPARED_NOT_RELEASED'),
        'manifest_sha256': manifest_hash, 'inventory_sha256': inventory_hash,
        'native_sha256': native_hash, 'module_sha256': module_hashes,
        'entries': len(entries), 'swift_pin': str(swift_output.name),
        'runtime_and_native_unchanged': True, 'backend_sources_unchanged': True,
        'runtime_execution': 'NOT_RUN',
        'signature_verification': 'NOT_RUN', 'adoption': 'NOT_ADOPTED',
        'elapsed_seconds': round(time.monotonic() - started, 3),
    }


def prepare_candidate(contents: Path, swift_output: Path, expected_native_sha256: str,
                      *, frozen: bool = False) -> dict[str, Any]:
    """Add backend/control files to a new Contents staging tree and emit a Swift pin."""
    return _prepare(Path(contents), Path(swift_output), expected_native_sha256, frozen=frozen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contents', type=Path, required=True,
                        help='new staging Contents with normalized runtime and signed native file')
    parser.add_argument('--swift-output', type=Path, required=True,
                        help='new Swift pin file in a derived source destination')
    parser.add_argument('--native-sha256', required=True,
                        help='expected SHA-256 identity supplied by the maintainer')
    parser.add_argument('--frozen', action='store_true',
                        help='select the distinct frozen-helper profile; helper must already be signed')
    args = parser.parse_args(argv)
    try:
        result = prepare_candidate(args.contents, args.swift_output, args.native_sha256, frozen=args.frozen)
    except CandidateError as error:
        print(json.dumps({'state': 'REJECTED', 'code': error.code}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
