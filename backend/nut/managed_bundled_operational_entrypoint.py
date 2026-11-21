#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bundle-relative operational admission; existing lifecycle, no hardware fuse added."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import sys
import threading
from types import ModuleType
from typing import Any
import uuid

PROFILE = 'apc-smc1500i-operational-bundled-v1'
# The default layout remains the PBS profile.
PYTHON_ROOT = 'Resources/PythonRuntime'
PYTHON_PATH = PYTHON_ROOT + '/install/bin/python3.15'
BACKEND_ROOT = 'Resources/ManagedOperationalRuntime'
ENTRY_PATH = BACKEND_ROOT + '/managed_bundled_operational_entrypoint.py'
NATIVE_NAME = 'apcmicrolink-hidapi-operational'
NATIVE_PATH = 'MacOS/' + NATIVE_NAME
MANIFEST_PATH = BACKEND_ROOT + '/runtime-bundle.json'
INVENTORY_PATH = BACKEND_ROOT + '/runtime-tree.json'
MODULES = frozenset({
    'managed_operational_entrypoint.py', 'managed_bundled_operational_entrypoint.py',
    'app_controlled_operational.py', 'operational_capture.py', 'operational_publication.py',
    'continuous_capture.py', 'continuous_protocol.py', 'process_deadline.py',
    'bounded_stream_dispatch.py', 'cleanup_diagnostics.py',
})
LOAD_ORDER = ('managed_operational_entrypoint', 'continuous_protocol', 'cleanup_diagnostics',
              'bounded_stream_dispatch', 'process_deadline', 'continuous_capture',
              'operational_publication', 'operational_capture', 'app_controlled_operational')


class BundleError(ValueError):
    """Closed admission failure, without file contents or user paths."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _BootstrapStop:
    """Only admission-time signal retention; legacy owns the operational stop state."""
    def __init__(self) -> None:
        self.pending = False
        self.delegate: Any = None

    def request(self, signum: int, frame: Any) -> None:
        if self.delegate is None:
            self.pending = True
        else:
            self.delegate.request_stop(signum, frame)

    def handoff(self, legacy: Any) -> None:
        self.delegate = legacy
        if self.pending:
            legacy.request_stop(signal.SIGTERM, None)
            self.pending = False
        for signum in (signal.SIGINT, signal.SIGTERM): signal.signal(signum, legacy.request_stop)


def _need(condition: Any, code: str) -> None:
    if not condition:
        raise BundleError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: Any) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _integer(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _json(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            _need(key not in out, 'duplicate_json_key')
            out[key] = value
        return out
    def reject(_value: str) -> Any:
        raise BundleError('invalid_json_number')
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)
        _need(type(result) is dict, 'json_shape')
        # No arrays or null exist in this closed format. Keep both readers aligned.
        def shape(value: Any, depth: int = 0) -> None:
            _need(depth <= 32 and value is not None and type(value) is not list, 'json_shape')
            if type(value) is dict:
                for child in value.values(): shape(child, depth + 1)
        shape(result)
        return result
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BundleError('json_shape') from error


def _keys(value: Any, keys: set[str]) -> None:
    _need(type(value) is dict and set(value) == keys, 'manifest_shape')


def _path(value: Any) -> tuple[str, ...]:
    _need(type(value) is str and bool(value) and len(value.encode('utf-8')) <= 4096
          and all(32 <= ord(c) < 127 for c in value) and '\\' not in value, 'unsafe_path')
    parts = tuple(value.split('/'))
    _need(len(parts) <= 64 and all(part not in ('', '.', '..') for part in parts), 'unsafe_path')
    return parts


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_mtime_ns, info.st_ctime_ns)


class _Files:
    def __init__(self, contents: Path):
        _need(contents.is_absolute() and contents.name == 'Contents'
              and contents.resolve(strict=True) == contents and '..' not in contents.parts, 'bundle_root')
        self.contents = contents
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in contents.parts[1:]:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = following
            info = os.fstat(fd)
            _need(not stat.S_IMODE(info.st_mode) & 0o022, 'writable_parent')
            self.fd, self.identity = fd, (info.st_dev, info.st_ino)
        except BaseException:
            os.close(fd)
            raise

    def close(self) -> None:
        os.close(self.fd)

    def descriptor(self, name: str, *, directory: bool = False) -> int:
        parts = _path(name)
        current = os.dup(self.fd)
        try:
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                if directory or index < len(parts) - 1: flags |= os.O_DIRECTORY
                following = os.open(part, flags, dir_fd=current)
                os.close(current)
                current = following
                _need(not stat.S_IMODE(os.fstat(current).st_mode) & 0o022, 'writable_parent')
            return current
        except BaseException:
            os.close(current)
            raise

    def read(self, name: str, maximum: int) -> bytes:
        fd = self.descriptor(name)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and not before.st_mode & 0o7000
                  and 0 <= before.st_size <= maximum, 'file_type_size')
            raw = stream.read(before.st_size + 1)
            _need(len(raw) == before.st_size and _stamp(before) == _stamp(os.fstat(stream.fileno())), 'file_changed')
        named = self.descriptor(name)
        try: _need(_stamp(os.fstat(named)) == _stamp(before), 'file_changed')
        finally: os.close(named)
        return raw

    def named_root(self) -> None:
        current = _Files(self.contents)
        try: _need(current.identity == self.identity, 'bundle_root_changed')
        finally: current.close()

    def node(self, name: str, entries: dict[str, dict]) -> None:
        row = entries.get(name)
        _need(row is not None, 'extra_file')
        parts = _path(name)
        parent = self.descriptor('/'.join(parts[:-1]), directory=True) if len(parts) > 1 else os.dup(self.fd)
        try:
            info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            _need(f'{stat.S_IMODE(info.st_mode):04o}' == row['mode'], 'file_mode')
            if row['type'] == 'directory':
                _need(stat.S_ISDIR(info.st_mode), 'file_type_size')
            elif row['type'] == 'symlink':
                _need(stat.S_ISLNK(info.st_mode) and info.st_nlink == 1
                      and os.readlink(parts[-1], dir_fd=parent) == row['target'], 'symlink_target')
            else:
                _need(stat.S_ISREG(info.st_mode) and info.st_size == row['bytes'], 'file_type_size')
                _need(_sha(self.read(name, 128 * 1048576)) == row['sha256'], 'file_hash')
        finally:
            os.close(parent)

    def visit(self, fd: int, prefix: str, entries: dict[str, dict], found: set[str],
              controls: tuple[str, str] = (MANIFEST_PATH, INVENTORY_PATH)) -> None:
        self.node(prefix, entries)
        found.add(prefix)
        for name in os.listdir(fd):
            path = prefix + '/' + name
            if path in controls: continue
            self.node(path, entries)
            found.add(path)
            if entries[path]['type'] == 'directory':
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                try: self.visit(child, path, entries, found, controls)
                finally: os.close(child)


def _joined(name: str, target: str, rest: tuple[str, ...] = ()) -> str:
    _need(type(target) is str and bool(target) and not target.startswith('/') and '\\' not in target
          and len(target.encode('utf-8')) <= 4096 and all(32 <= ord(c) < 127 for c in target), 'unsafe_symlink')
    parts = list(_path(name)[:-1])
    for part in (*target.split('/'), *rest):
        if part in ('', '.'): continue
        if part == '..':
            _need(bool(parts), 'unsafe_symlink')
            parts.pop()
        else: parts.append(part)
    result = '/'.join(parts)
    _path(result)
    return result


def _resolve(name: str, target: str, entries: dict[str, dict],
             parents: tuple[str, ...] = ('Resources', 'MacOS')) -> str:
    current, seen = _joined(name, target), {name}
    while True:
        parts, changed = _path(current), False
        for length in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:length])
            if prefix in parents: continue
            row = entries.get(prefix)
            _need(row is not None, 'missing_symlink_target')
            if row['type'] == 'symlink':
                _need(prefix not in seen, 'symlink_cycle')
                seen.add(prefix)
                current, changed = _joined(prefix, row['target'], parts[length:]), True
                break
            _need(length == len(parts) or row['type'] == 'directory', 'missing_symlink_target')
        if not changed: return current


def _closure(files: _Files, entries: Any, count: int, *,
             roots: tuple[str, str] = (PYTHON_ROOT, BACKEND_ROOT),
             native_path: str = NATIVE_PATH,
             controls: tuple[str, str] = (MANIFEST_PATH, INVENTORY_PATH),
             parents: tuple[str, ...] = ('Resources', 'MacOS'),
             same_root_links: bool = False) -> None:
    _need(type(entries) is dict and len(entries) == count, 'closure_count')
    aliases, total = set(), 0
    for name, row in entries.items():
        _path(name)
        _need(name.lower() not in aliases, 'name_alias')
        aliases.add(name.lower())
        _need(name not in controls
              and (name in (*roots, native_path)
                   or name.startswith(tuple(root + '/' for root in roots))), 'closure_scope')
        _need(type(row) is dict, 'closure_shape')
        kind = row.get('type')
        if kind == 'file':
            _keys(row, {'type', 'mode', 'bytes', 'sha256'})
            _need(row['mode'] in ('0644', '0755') and _integer(row['bytes'], 128 * 1048576)
                  and _hash(row['sha256']), 'closure_shape')
            total += row['bytes']
        elif kind == 'directory':
            _keys(row, {'type', 'mode'})
            _need(row['mode'] == '0755', 'closure_shape')
        elif kind == 'symlink':
            _keys(row, {'type', 'mode', 'target', 'resolved_target'})
            _need(row['mode'] == '0777' and type(row['target']) is str
                  and type(row['resolved_target']) is str, 'closure_shape')
        else: raise BundleError('closure_shape')
    _need(total <= 1073741824 and all(entries.get(root, {}).get('type') == 'directory' for root in roots), 'closure_shape')
    for name in entries:
        parts = _path(name)
        for length in range(1, len(parts)):
            parent = '/'.join(parts[:length])
            _need(parent in parents or entries.get(parent, {}).get('type') == 'directory', 'parent_alias')
    for name, row in entries.items():
        if row['type'] == 'symlink':
            resolved = _resolve(name, row['target'], entries, parents)
            _need(resolved == row['resolved_target'], 'symlink_target')
            if same_root_links:
                _need(any(name.startswith(root + '/') and resolved.startswith(root + '/')
                          for root in roots), 'cross_root_symlink')
    found: set[str] = set()
    for prefix in roots:
        fd = files.descriptor(prefix, directory=True)
        try: files.visit(fd, prefix, entries, found, controls)
        finally: os.close(fd)
    files.node(native_path, entries)
    found.add(native_path)
    _need(found == set(entries), 'closure_files')


@dataclass(frozen=True)
class Binding:
    contents: Path
    python: Path
    backend: Path
    native: Path
    native_sha256: str
    module_sha256: dict[str, str]
    manifest_sha256: str


def _host_admitted() -> bool:
    version = platform.mac_ver()[0]
    return (platform.system() == 'Darwin' and platform.machine() == 'arm64'
            and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}', version) is not None
            and tuple(int(part) for part in version.split('.')) >= (27, 0))


def _validate_bundle(contents: Path, expected_manifest_sha256: str, *, check_process: bool = True) -> Binding:
    """Internal inert-fixture seam; production always checks its real process."""
    _need(_hash(expected_manifest_sha256), 'manifest_pin')
    files = None
    try:
        files = _Files(contents)
        raw = files.read(MANIFEST_PATH, 32768)
        _need(_sha(raw) == expected_manifest_sha256, 'manifest_pin')
        manifest = _json(raw)
        _keys(manifest, {'schema_version', 'profile', 'architecture', 'minimum_macos',
                         'python', 'backend', 'native', 'closure', 'upstream'})
        _need(type(manifest['schema_version']) is int and manifest['schema_version'] == 1
              and manifest['profile'] == PROFILE and manifest['architecture'] == 'arm64'
              and manifest['minimum_macos'] == '27.0', 'manifest_profile')
        python, backend, native, closure, upstream = (manifest[key] for key in
            ('python', 'backend', 'native', 'closure', 'upstream'))
        _keys(python, {'root', 'executable', 'sha256'})
        _keys(backend, {'root', 'entrypoint', 'module_sha256'})
        _keys(native, {'path', 'name', 'sha256', 'bytes'})
        _keys(closure, {'path', 'sha256', 'entries'})
        _keys(upstream, {'archive_sha256', 'metadata_sha256'})
        pins = backend['module_sha256']
        _need(python['root'] == PYTHON_ROOT and python['executable'] == PYTHON_PATH
              and _hash(python['sha256']) and backend['root'] == BACKEND_ROOT
              and backend['entrypoint'] == ENTRY_PATH and type(pins) is dict and set(pins) == MODULES
              and all(_hash(pin) for pin in pins.values())
              and native['path'] == NATIVE_PATH and native['name'] == NATIVE_NAME
              and _hash(native['sha256']) and _integer(native['bytes'], 2097152) and native['bytes'] > 0
              and closure['path'] == INVENTORY_PATH and _hash(closure['sha256'])
              and _integer(closure['entries'], 20000) and closure['entries'] > 0
              and all(_hash(value) for value in upstream.values()), 'manifest_binding')
        inventory_raw = files.read(INVENTORY_PATH, 16 * 1048576)
        _need(_sha(inventory_raw) == closure['sha256'], 'inventory_pin')
        inventory = _json(inventory_raw)
        _keys(inventory, {'schema_version', 'entries'})
        _need(type(inventory['schema_version']) is int and inventory['schema_version'] == 1, 'closure_shape')
        entries = inventory['entries']
        _closure(files, entries, closure['entries'])
        def pinned(name: str, pin: str, *, size: int | None = None, executable: bool = False) -> None:
            row = entries.get(name, {})
            _need(row.get('type') == 'file' and row.get('sha256') == pin
                  and (not executable or row.get('mode') == '0755' and row.get('bytes', 0) > 0)
                  and (size is None or row.get('bytes') == size), 'role_pin')
        pinned(PYTHON_PATH, python['sha256'], executable=True)
        pinned(NATIVE_PATH, native['sha256'], size=native['bytes'], executable=True)
        for name, pin in pins.items(): pinned(BACKEND_ROOT + '/' + name, pin)
        python_path = contents / PYTHON_PATH
        if check_process:
            _need(_host_admitted() and Path(sys.executable).resolve(strict=True) == python_path
                  and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
                  and not sys.flags.optimize, 'interpreter_identity')
        _need(files.read(MANIFEST_PATH, 32768) == raw
              and files.read(INVENTORY_PATH, 16 * 1048576) == inventory_raw, 'controls_changed')
        files.named_root()
        return Binding(contents, python_path, contents / BACKEND_ROOT, contents / NATIVE_PATH,
                       native['sha256'], dict(pins), expected_manifest_sha256)
    except (OSError, KeyError, TypeError) as error:
        raise BundleError('runtime_file') from error
    finally:
        if files is not None: files.close()


def validate_runtime(expected_manifest_sha256: str) -> Binding:
    directory = Path(__file__).absolute().parent
    _need(directory.name == 'ManagedOperationalRuntime' and directory.parent.name == 'Resources', 'entry_location')
    return _validate_bundle(directory.parent.parent, expected_manifest_sha256)


def _load_backend(binding: Binding, owner: list[Any], *, validator: Any = _validate_bundle,
                  modules: frozenset[str] = MODULES) -> tuple[Any, Any]:
    _need(not any(name[:-3] in sys.modules for name in modules), 'preloaded_backend')
    # Recheck the whole package, then hash each exact module buffer before exec.
    current = validator(binding.contents, binding.manifest_sha256)
    _need(current == binding, 'binding_changed')
    files = _Files(binding.contents)
    loaded: dict[str, Any] = {}
    try:
        for name in LOAD_ORDER:
            leaf = name + '.py'
            data = files.read(BACKEND_ROOT + '/' + leaf, 2097152)
            _need(_sha(data) == binding.module_sha256[leaf], 'module_changed')
            module = ModuleType(name)
            module.__file__ = str(binding.backend / leaf)
            sys.modules[name] = module
            loaded[name] = module
            exec(compile(data, module.__file__, 'exec', dont_inherit=True), module.__dict__)
            _need(_sha(files.read(BACKEND_ROOT + '/' + leaf, 2097152)) == binding.module_sha256[leaf], 'module_changed')
            if name == 'managed_operational_entrypoint': owner.append(module)
        files.named_root()
        return loaded['managed_operational_entrypoint'], loaded['app_controlled_operational']
    finally:
        files.close()


def _emit_rejection(launch_id: str) -> None:
    value = {'protocol': 'ups-monitor.managed-operational.v2', 'schema_version': 2,
        'launch_id': launch_id, 'adapter': {'capture_result': None, 'control_reason': None,
        'adapter_error': 'adapter_setup_failed', 'watcher_quiesced': threading.active_count() == 1,
        'ownership_resolved': False}}
    raw = (json.dumps(value, separators=(',', ':')) + '\n').encode('ascii')
    _need(len(raw) <= 65536, 'receipt_limit')
    view = memoryview(raw)
    while view:
        wrote = os.write(1, view)
        _need(wrote > 0, 'receipt_write')
        view = view[wrote:]


def main() -> int:
    owner: list[Any] = []
    launch_id = 'invalid-launch'
    bootstrap = _BootstrapStop()
    try:
        for signum in (signal.SIGINT, signal.SIGTERM): signal.signal(signum, bootstrap.request)
        _need(len(sys.argv) == 7 and sys.argv[1] == '--workspace' and sys.argv[3] == '--launch-id'
              and sys.argv[5] == '--runtime-manifest-sha256', 'arguments')
        workspace, launch_id, manifest_hash = sys.argv[2], sys.argv[4], sys.argv[6]
        _need(workspace.startswith('/') and '\0' not in workspace and '..' not in Path(workspace).parts
              and str(uuid.UUID(launch_id)) == launch_id and _hash(manifest_hash), 'arguments')
        binding = validate_runtime(manifest_hash)
        legacy, adapter = _load_backend(binding, owner)
        bootstrap.handoff(legacy)
        _need(not legacy.STOP_REQUESTED, 'stopped_before_session')
        profile = adapter.FixedOperationalProfile(legacy.fixed_argv(binding.native), binding.native_sha256)
        _need(not legacy.STOP_REQUESTED, 'stopped_before_session')
    except BaseException:
        try: _emit_rejection(launch_id)
        except BaseException: pass
        if owner and not owner[0]._quiet_workers(): owner[0].retain()
        return 2
    return legacy.serve(adapter, profile, Path(workspace), launch_id)


if __name__ == '__main__':
    raise SystemExit(main())
