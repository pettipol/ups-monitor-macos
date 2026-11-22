#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage a signed PyInstaller helper and native producer into a frozen candidate.

This operation copies files and normalizes two known helper symlinks only. It
does not sign, execute, launch, install, or qualify the staged candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
MAX_SECONDS = 120
MAX_ENTRIES = 20_000
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
HELPER_NAME = 'UPSOperationalHelper.app'
ALLOWED_LINKS = {
    'Contents/Frameworks/base_library.zip': ('../Resources/base_library.zip',
                                                'Contents/Resources/base_library.zip'),
    'Contents/Resources/libpython3.15.dylib': ('../Frameworks/libpython3.15.dylib',
                                                'Contents/Frameworks/libpython3.15.dylib'),
}


class FrozenStageError(ValueError):
    """Closed error category without input paths or file contents."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _need(condition: Any, code: str) -> None:
    if not condition:
        raise FrozenStageError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_source(name: str, path: Path) -> ModuleType:
    try:
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 2 * 1024 * 1024,
              'source_module')
        raw = path.read_bytes()
        _need(len(raw) == info.st_size, 'source_module')
        module = ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
        return module
    except FrozenStageError:
        raise
    except (OSError, SyntaxError, ValueError) as error:
        raise FrozenStageError('source_module') from error


def _dependencies():
    prepare = _load_source('frozen_stage_candidate_prepare', HERE / 'prepare_bundled_operational_candidate.py')
    common = prepare._load_source('managed_bundled_operational_entrypoint', prepare._READER_PATH)
    normalizer = prepare._load_source('frozen_stage_normalizer', prepare._NORMALIZER_PATH)
    frozen = prepare._load_source('frozen_stage_consumer', HERE / 'managed_frozen_operational_entrypoint.py')
    return prepare, common, normalizer, frozen


def _canonical_input(path: Path, name: str, prepare) -> None:
    prepare._canonical_directory(path, name)
    info = path.lstat()
    _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o755, 'helper_root')


def _scan_helper(helper: Path, normalizer, common, prepare, deadline: float):
    _canonical_input(helper, HELPER_NAME, prepare)
    root_fd = normalizer._open_directory(helper, code='helper_root')
    try:
        root_info = normalizer._identity(os.fstat(root_fd))
        rows, identities, read_root_info = prepare._read_helper(
            helper, normalizer, common, deadline, allow_input_link_mode=True)
        _need(read_root_info == root_info, 'helper_changed')
        _need(0 < len(rows) <= MAX_ENTRIES, 'entry_limit')
        total = 0
        for name, row in rows.items():
            _need(time.monotonic() < deadline, 'deadline')
            kind, mode = row['type'], row['mode']
            if kind == 'directory':
                _need(mode == '0755', 'helper_mode')
            elif kind == 'file':
                _need(mode in ('0644', '0755'), 'helper_mode')
                _need(type(row.get('bytes')) is int and row['bytes'] <= MAX_FILE_BYTES, 'file_limit')
                total += row['bytes']
                _need(total <= MAX_TOTAL_BYTES, 'total_limit')
            elif kind == 'symlink':
                _need(name in ALLOWED_LINKS and mode in ('0755', '0777'), 'helper_symlink')
                _need(identities[name][6] == 1, 'helper_special')
                target, resolved = ALLOWED_LINKS[name]
                _need(row['target'] == target, 'helper_symlink')
                _need(common._resolve(name, target, rows, parents=()) == resolved, 'helper_symlink')
                row['resolved_target'] = resolved
                row['source_mode'] = mode
            else:
                raise FrozenStageError('helper_type')
        _need({name for name, row in rows.items() if row['type'] == 'symlink'} == set(ALLOWED_LINKS),
              'helper_symlink_set')
        _need(rows.get('Contents', {}).get('type') == 'directory'
              and rows.get('Contents/MacOS/UPSOperationalHelper', {}).get('type') == 'file'
              and rows['Contents/MacOS/UPSOperationalHelper'].get('mode') == '0755'
              and rows.get('Contents/Frameworks/base_library.zip', {}).get('type') == 'symlink'
              and rows.get('Contents/Resources/libpython3.15.dylib', {}).get('type') == 'symlink',
              'helper_layout')
        _need(normalizer._identity(helper.lstat()) == root_info, 'helper_changed')
        return root_fd, rows, identities, root_info, total
    except BaseException:
        os.close(root_fd)
        raise


def _mapped_helper(rows: dict[str, dict]) -> dict[str, dict]:
    mapped: dict[str, dict] = {'Helpers': {'type': 'directory', 'mode': '0755'},
                               f'Helpers/{HELPER_NAME}': {'type': 'directory', 'mode': '0755'}}
    prefix = f'Helpers/{HELPER_NAME}/'
    for name, row in rows.items():
        target_name = prefix + name
        item = dict(row)
        if item['type'] == 'symlink':
            item['mode'] = '0777'
            item.pop('source_mode', None)
        mapped[target_name] = item
    return mapped


def _copy_helper(source_fd: int, destination_fd: int, destination: Path, rows: dict[str, dict],
                 identities: dict[str, tuple], normalizer, deadline: float) -> None:
    prefix = f'Helpers/{HELPER_NAME}/'
    for name, row in sorted(rows.items()):
        _need(time.monotonic() < deadline, 'deadline')
        target_name = prefix + name
        if row['type'] == 'directory':
            continue
        source_parent, leaf = normalizer._open_parent_at(source_fd, name, 'helper_changed')
        target_parent = None
        fd = None
        try:
            if row['type'] == 'symlink':
                actual_target, actual_identity = normalizer._readlink_at(source_fd, name)
                _need(actual_identity == identities[name] and actual_target == row['target'], 'helper_changed')
                target_parent, target_leaf = normalizer._open_parent_at(destination_fd, target_name,
                                                                         'destination_parent')
                os.symlink(actual_target, target_leaf, dir_fd=target_parent)
                target_path = destination / target_name
                lchmod = getattr(os, 'lchmod', None)
                _need(lchmod is not None, 'symlink_mode')
                lchmod(target_path, 0o777)
                copied = os.stat(target_leaf, dir_fd=target_parent, follow_symlinks=False)
                _need(stat.S_ISLNK(copied.st_mode) and stat.S_IMODE(copied.st_mode) == 0o777
                      and os.readlink(target_leaf, dir_fd=target_parent) == actual_target,
                      'destination_changed')
            else:
                fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, 'O_NONBLOCK', 0),
                             dir_fd=source_parent)
                before = os.fstat(fd)
                _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                      and normalizer._identity(before) == identities[name]
                      and before.st_size == row['bytes'], 'helper_changed')
                chunks = []
                count = 0
                while True:
                    _need(time.monotonic() < deadline, 'deadline')
                    block = os.read(fd, 1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    _need(count <= MAX_FILE_BYTES, 'file_limit')
                    chunks.append(block)
                raw = b''.join(chunks)
                _need(normalizer._identity(os.fstat(fd)) == identities[name]
                      and len(raw) == row['bytes'] and _sha(raw) == row['sha256'], 'helper_changed')
                target_parent, target_leaf = normalizer._open_parent_at(destination_fd, target_name,
                                                                          'destination_parent')
                out = os.open(target_leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                              0o600, dir_fd=target_parent)
                try:
                    normalizer._write_all(out, raw, deadline)
                    os.fchmod(out, int(row['mode'], 8))
                    os.fsync(out)
                    out_info = os.fstat(out)
                    _need(stat.S_ISREG(out_info.st_mode) and out_info.st_nlink == 1
                          and out_info.st_size == len(raw)
                          and stat.S_IMODE(out_info.st_mode) == int(row['mode'], 8), 'destination_changed')
                finally:
                    os.close(out)
        except FrozenStageError:
            raise
        except (OSError, ValueError) as error:
            raise FrozenStageError('copy_failed') from error
        finally:
            if fd is not None:
                os.close(fd)
            if target_parent is not None:
                os.close(target_parent)
            os.close(source_parent)


def _verify_copied_helper(helper: Path, source_rows: dict[str, dict], prepare,
                          normalizer, common, deadline: float) -> dict[str, dict]:
    copied, _identities, _root_identity = prepare._read_helper(helper, normalizer, common, deadline)
    expected = {}
    for name, row in source_rows.items():
        item = dict(row)
        if item['type'] == 'symlink':
            item['mode'] = '0777'
            item.pop('source_mode', None)
        expected[name] = item
    _need(copied == expected, 'helper_copy_changed')
    return copied


def _read_native(path: Path, expected_sha256: str, prepare):
    _need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path,
          'native_path')
    raw, identity = prepare._read_regular(path, 2 * 1024 * 1024, 'native_identity')
    info = path.lstat()
    _need(stat.S_IMODE(info.st_mode) == 0o755 and _sha(raw) == expected_sha256, 'native_identity')
    return raw, identity


def _output_parent(path: Path, normalizer) -> None:
    _need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path
          and stat.S_ISDIR(path.lstat().st_mode), 'output_parent')
    info = path.lstat()
    _need(info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o022
          and normalizer._is_below_private_temp(path), 'output_parent')


def _check_output_root(path: Path, identity: tuple[int, int]) -> None:
    info = path.lstat()
    _need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
          and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
          and (info.st_dev, info.st_ino) == identity, 'output_root_changed')


def _no_overlap(output_root: Path, helper: Path, native: Path, prepare: ModuleType) -> None:
    protected = (helper, native, prepare._HERE, prepare._HERE.parents[1])
    for item in protected:
        _need(output_root != item and output_root not in item.parents and item not in output_root.parents,
              'overlapping_inputs')


def _write_receipt(root: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    fd = None
    try:
        fd = os.open(root / 'receipt.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError('receipt_write')
            view = view[written:]
        os.fsync(fd)
    finally:
        if fd is not None:
            os.close(fd)


def stage_frozen_runtime(helper_app: Path, native_producer: Path, native_sha256: str,
                         output_root: Path, *, first_io_source_stage: Path | None = None) -> dict[str, Any]:
    """Copy and validate a frozen helper candidate; never execute or sign inputs."""
    helper_app, native_producer, output_root = map(Path, (helper_app, native_producer, output_root))
    deadline = time.monotonic() + MAX_SECONDS
    prepare, common, normalizer, frozen = _dependencies()
    root_created = False
    helper_fd = None
    try:
        _need(type(native_sha256) is str and common._hash(native_sha256), 'native_identity')
        selected = None
        backend_source = None
        expected_modules = None
        if first_io_source_stage is not None:
            validator = prepare._load_source('first_io_source_stage_validator',
                                             HERE / 'first_io_source_stage.py')
            try:
                selected = validator.validate_source_stage(Path(first_io_source_stage), HERE)
            except Exception as error:
                raise FrozenStageError('first_io_source_stage') from error
            backend_source = selected.runtime_root
            expected_modules = selected.runtime_map
            output_candidate = Path(output_root)
            _need(output_candidate.is_absolute() and '..' not in output_candidate.parts,
                  'output_path')
            stage_root = Path(first_io_source_stage).resolve(strict=True)
            _need(output_candidate != stage_root and output_candidate not in stage_root.parents
                  and stage_root not in output_candidate.parents, 'overlapping_inputs')
        _canonical_input(helper_app, HELPER_NAME, prepare)
        helper_fd, helper_rows, helper_ids, helper_root_id, helper_bytes = _scan_helper(
            helper_app, normalizer, common, prepare, deadline)
        native_raw, native_id = _read_native(native_producer, native_sha256, prepare)
        native_name = common.NATIVE_NAME
        module_hashes = {}
        module_snapshots = {}
        for name in sorted(frozen.MODULES):
            source_root = backend_source or prepare._HERE
            raw, identity = prepare._read_regular(source_root / name, prepare._MAX_MODULE, 'module_source')
            module_hashes[name] = _sha(raw)
            module_snapshots[name] = (raw, identity)
        if expected_modules is not None:
            _need(set(expected_modules) == set(module_hashes) and module_hashes == expected_modules,
                  'stage_module_snapshot')
        inputs_raw, _inputs_identity = prepare._read_regular(prepare._INPUTS_PATH, 65536, 'upstream_inputs')
        _need(_sha(inputs_raw) == prepare._INPUTS_SHA256, 'upstream_inputs')
        _need(output_root.is_absolute() and '..' not in output_root.parts
              and not output_root.exists() and not output_root.is_symlink(), 'output_exists')
        parent = output_root.parent
        _output_parent(parent, normalizer)
        _no_overlap(output_root, helper_app, native_producer, prepare)
        _need(time.monotonic() < deadline, 'deadline')

        os.mkdir(output_root, 0o700)
        root_created = True
        os.chmod(output_root, 0o700)
        root_info = output_root.lstat()
        _need(stat.S_ISDIR(root_info.st_mode) and root_info.st_uid == os.getuid()
              and stat.S_IMODE(root_info.st_mode) == 0o700, 'output_root')
        root_identity = (root_info.st_dev, root_info.st_ino)
        stage_dir, derived_dir = output_root / 'stage', output_root / 'derived'
        os.mkdir(stage_dir, 0o700); os.mkdir(derived_dir, 0o700)
        contents = stage_dir / 'Contents'
        os.mkdir(contents, 0o755); os.chmod(contents, 0o755)
        contents_fd = normalizer._open_directory(contents, code='contents_path')
        try:
            rows: dict[str, dict] = {'MacOS': {'type': 'directory', 'mode': '0755'},
                                     'Resources': {'type': 'directory', 'mode': '0755'}}
            rows.update({f'MacOS/{native_name}': {'type': 'file', 'mode': '0755',
                'bytes': len(native_raw), 'sha256': native_sha256}})
            mapped = _mapped_helper(helper_rows)
            rows.update(mapped)
            normalizer._create_dest_dirs(contents_fd, rows, deadline)
            _copy_helper(helper_fd, contents_fd, contents, helper_rows, helper_ids,
                         normalizer, deadline)
            parent_fd, leaf = normalizer._open_parent_at(contents_fd, f'MacOS/{native_name}', 'destination_parent')
            try:
                fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent_fd)
                try:
                    normalizer._write_all(fd, native_raw, deadline); os.fchmod(fd, 0o755); os.fsync(fd)
                    info = os.fstat(fd)
                    _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                          and stat.S_IMODE(info.st_mode) == 0o755 and info.st_size == len(native_raw),
                          'native_copy')
                finally: os.close(fd)
            finally: os.close(parent_fd)
        finally:
            os.close(contents_fd)

        copied_helper_root = contents / frozen.HELPER_ROOT
        _verify_copied_helper(copied_helper_root, helper_rows, prepare, normalizer, common, deadline)
        _check_output_root(output_root, root_identity)
        helper_after = _scan_helper(helper_app, normalizer, common, prepare, deadline)
        try:
            _need(helper_after[1] == helper_rows and helper_after[2] == helper_ids
                  and helper_after[3] == helper_root_id, 'helper_changed')
        finally:
            os.close(helper_after[0])
        current_native, current_native_id = _read_native(native_producer, native_sha256, prepare)
        _need(current_native == native_raw and current_native_id == native_id, 'native_changed')
        swift_pin = output_root / 'derived' / 'FrozenOperationalReleasePins.swift'
        _need(time.monotonic() < deadline, 'deadline')
        _check_output_root(output_root, root_identity)
        if selected is None:
            result = prepare.prepare_candidate(contents, swift_pin, native_sha256, frozen=True)
        else:
            result = prepare.prepare_candidate(contents, swift_pin, native_sha256, frozen=True,
                backend_source=backend_source, expected_module_sha256=expected_modules)
            _need(type(result) is dict and result.get('module_sha256') == expected_modules == module_hashes,
                  'stage_packager_module_map')
            try:
                manifest_raw, _ = prepare._read_regular(contents / frozen.MANIFEST_PATH, 32768,
                                                         'stage_manifest_identity')
                _need(_sha(manifest_raw) == result.get('manifest_sha256'), 'stage_manifest_identity')
                manifest = json.loads(manifest_raw)
                manifest_modules = manifest['backend']['module_sha256']
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
                raise FrozenStageError('stage_manifest_module_map') from error
            _need(manifest_modules == expected_modules, 'stage_manifest_module_map')
        _need(time.monotonic() < deadline, 'deadline')
        _check_output_root(output_root, root_identity)
        _verify_copied_helper(copied_helper_root, helper_rows, prepare, normalizer, common, deadline)
        helper_after = _scan_helper(helper_app, normalizer, common, prepare, deadline)
        try:
            _need(helper_after[1] == helper_rows and helper_after[2] == helper_ids
                  and helper_after[3] == helper_root_id, 'helper_changed')
        finally:
            os.close(helper_after[0])
        current_native, current_native_id = _read_native(native_producer, native_sha256, prepare)
        _need(current_native == native_raw and current_native_id == native_id, 'native_changed')
        for name, (expected_raw, expected_identity) in module_snapshots.items():
            current, current_identity = prepare._read_regular((backend_source or prepare._HERE) / name, prepare._MAX_MODULE,
                                                               'module_changed')
            _need(current == expected_raw and current_identity == expected_identity, 'module_changed')
        _need(time.monotonic() < deadline, 'deadline')
        _check_output_root(output_root, root_identity)
        helper_hash = _sha(prepare._json_bytes({'entries': helper_rows}))
        receipt = {
            'schema': 1, 'state': 'STAGED_FROZEN_NOT_EXECUTED',
            'helper_source_inventory_sha256': helper_hash,
            'native_sha256': native_sha256,
            'manifest_sha256': result['manifest_sha256'],
            'inventory_sha256': result['inventory_sha256'],
            'swift_pin_sha256': _sha(swift_pin.read_bytes()),
            'helper_entries': len(helper_rows), 'helper_bytes': helper_bytes,
            'backend_modules': len(module_hashes), 'module_sha256': module_hashes,
            'normalized_links': sorted(ALLOWED_LINKS),
            'source_unchanged': True,
            'signature_verification': 'NOT_RUN', 'compiled_pin': 'CALLER_REQUIRED',
            'runtime_execution': 'NOT_RUN', 'adoption': 'NOT_ADOPTED',
            'elapsed_seconds': round(time.monotonic() - (deadline - MAX_SECONDS), 3),
        }
        if selected is not None:
            receipt['first_io_source_stage'] = selected.identity
            receipt['module_sha256'] = module_hashes
        _write_receipt(output_root, receipt)
        return receipt
    except BaseException as error:
        if root_created:
            code = getattr(error, 'code', 'stage_failed')
            if type(code) is not str: code = 'stage_failed'
            try:
                _write_receipt(output_root, {'schema': 1, 'state': 'STAGING_FAILED_PARTIAL_PRESERVED',
                    'code': code, 'signature_verification': 'NOT_RUN', 'compiled_pin': 'CALLER_REQUIRED',
                    'runtime_execution': 'NOT_RUN', 'adoption': 'NOT_ADOPTED'})
            except BaseException:
                pass
        if isinstance(error, FrozenStageError):
            raise
        code = getattr(error, 'code', 'stage_failed')
        raise FrozenStageError(code if type(code) is str else 'stage_failed') from error
    finally:
        if helper_fd is not None:
            os.close(helper_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper-app', type=Path, required=True)
    parser.add_argument('--native-producer', type=Path, required=True)
    parser.add_argument('--native-sha256', required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--first-io-source-stage', type=Path,
                        help='authenticate and select the E119 qualified runtime modules')
    args = parser.parse_args(argv)
    try:
        if args.first_io_source_stage is None:
            result = stage_frozen_runtime(args.helper_app, args.native_producer,
                                          args.native_sha256, args.output_root)
        else:
            result = stage_frozen_runtime(args.helper_app, args.native_producer,
                                          args.native_sha256, args.output_root,
                                          first_io_source_stage=args.first_io_source_stage)
    except (OSError, ValueError) as error:
        code = getattr(error, 'code', 'stage_failed')
        print(json.dumps({'state': 'REJECTED', 'code': code}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
