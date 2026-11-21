#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy an admitted frozen runtime into a built app; outer signing remains required.

No build, signing, execution, registration or hardware access is performed.
Inputs are retained. Existing destination runtime paths are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
NOTICES_ROOT = HERE.parents[1] / 'third_party' / 'frozen-runtime'
NOTICES_MANIFEST_SHA256 = '29b970b594e4dc4098a4021ffb3292b7f44de2cf0f87c1492d7b3df2e2130290'
NOTICES_DESTINATION = 'Resources/RuntimeNotices'
NOTICES_MANIFEST = 'manifest.json'


def _dependencies():
    path = HERE / 'prepare_bundled_operational_candidate.py'
    module = ModuleType('frozen_assembly_dependencies')
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(path.read_bytes(), str(path), 'exec', dont_inherit=True), module.__dict__)
    common = module._load_source('managed_bundled_operational_entrypoint', module._READER_PATH)
    frozen = module._load_source('assembly_frozen_consumer', HERE / 'managed_frozen_operational_entrypoint.py')
    normalizer = module._load_source('assembly_fd_helpers', module._NORMALIZER_PATH)
    return module, common, frozen, normalizer


def _read_notices(root: Path, expected_upstream: dict[str, str], deadline: float,
                  common, normalizer) -> tuple[dict[str, bytes], bytes, int, str]:
    """Read and validate the pinned notice set completely before destination writes."""
    total_limit, file_limit = 2 * 1048576, 256 * 1024
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('notice_source')
    root_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    notice_fd = None
    try:
        notice_fd = normalizer._open_dir_at(root_fd, root.parts[1:], 'notice_source')
        names = os.listdir(notice_fd)
        manifest_raw, _identity = normalizer._read_regular_at(
            notice_fd, NOTICES_MANIFEST, deadline, file_limit)
        if hashlib.sha256(manifest_raw).hexdigest() != NOTICES_MANIFEST_SHA256:
            raise ValueError('notice_manifest_pin')
        manifest = common._json(manifest_raw)
        required = {'components', 'files', 'observed_helper', 'profile',
                    'redistribution_review', 'runtime_upstream', 'schema_version'}
        if set(manifest) != required or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
            raise ValueError('notice_manifest_shape')
        if manifest['profile'] != 'ups-monitor-frozen-notices-v1' or manifest['runtime_upstream'] != expected_upstream:
            raise ValueError('notice_upstream')
        if type(manifest['components']) is not dict or type(manifest['observed_helper']) is not dict \
                or manifest['redistribution_review'] != 'NOT_PERFORMED':
            raise ValueError('notice_manifest_contract')
        historical_helper_sha256 = manifest['observed_helper'].get('sha256')
        if not common._hash(historical_helper_sha256):
            raise ValueError('notice_observed_helper_hash')
        files = manifest['files']
        if type(files) is not dict or not 1 <= len(files) <= 64 or NOTICES_MANIFEST in files:
            raise ValueError('notice_files_shape')
        expected_names = {NOTICES_MANIFEST}
        buffers: dict[str, bytes] = {NOTICES_DESTINATION + '/' + NOTICES_MANIFEST: manifest_raw}
        total = len(manifest_raw)
        for name, spec in sorted(files.items()):
            if common._path(name) != (name,) or name in ('.', '..'):
                raise ValueError('notice_path')
            if type(spec) is not dict or set(spec) != {'bytes', 'component', 'scope', 'sha256', 'source_member'}:
                raise ValueError('notice_file_shape')
            if any(type(spec[key]) is not str or not spec[key]
                   for key in ('component', 'scope', 'source_member')):
                raise ValueError('notice_file_shape')
            size, digest = spec['bytes'], spec['sha256']
            if type(size) is not int or not 0 <= size <= file_limit:
                raise ValueError('notice_file_size')
            if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('notice_file_hash')
            raw, _identity = normalizer._read_regular_at(notice_fd, name, deadline, file_limit)
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('notice_file_pin')
            total += len(raw)
            if total > total_limit:
                raise ValueError('notice_total_limit')
            expected_names.add(name)
            buffers[NOTICES_DESTINATION + '/' + name] = raw
        if set(names) != expected_names:
            raise ValueError('notice_source_members')
        # The descriptor reader rejects links and hardlinks for every listed file;
        # stat the manifest too, and ensure there are no non-regular members.
        for name in names:
            info = os.stat(name, dir_fd=notice_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('notice_source_type')
        return buffers, manifest_raw, total, historical_helper_sha256
    finally:
        if notice_fd is not None:
            os.close(notice_fd)
        os.close(root_fd)


def assemble_runtime(source: Path, destination: Path, manifest_sha256: str) -> dict[str, Any]:
    """Copy only the validated runtime closure into a distinct canonical Contents.

    The caller must build the app using the corresponding compiled Swift pin,
    then sign and verify the outer app after assembly. This function cannot
    establish that a particular app binary contains that pin.
    """
    prep, common, frozen, normalizer = _dependencies()
    source, destination = Path(source), Path(destination)
    prep._canonical_directory(source, 'Contents')
    prep._canonical_directory(destination, 'Contents')
    prep._need(source != destination and source not in destination.parents
               and destination not in source.parents, 'overlapping_inputs')
    binding = frozen._validate_bundle(source, manifest_sha256, check_process=False)
    deadline = time.monotonic() + 120
    inputs, outputs = common._Files(source), None
    try:
        outputs = common._Files(destination)
        manifest_raw = inputs.read(frozen.MANIFEST_PATH, 32768)
        inventory_raw = inputs.read(frozen.INVENTORY_PATH, 16 * 1048576)
        prep._need(hashlib.sha256(manifest_raw).hexdigest() == manifest_sha256, 'manifest_changed')
        manifest = common._json(manifest_raw)
        closure = manifest['closure']
        prep._need(hashlib.sha256(inventory_raw).hexdigest() == closure['sha256'], 'inventory_changed')
        entries = common._json(inventory_raw)['entries']
        notices, notices_manifest_raw, notices_total, historical_helper_sha256 = _read_notices(
            NOTICES_ROOT, manifest['upstream'], deadline, common, normalizer)
        verified_helper_sha256 = manifest['python']['sha256']
        prep._need(common._hash(verified_helper_sha256), 'helper_hash')
        # Collision checks precede the first write. Required app directories
        # must be genuine directories; a pre-existing Helpers directory is OK.
        for name in ('MacOS', 'Resources'):
            fd = outputs.descriptor(name, directory=True); os.close(fd)
        helpers_present = False
        try:
            os.stat('Helpers', dir_fd=outputs.fd, follow_symlinks=False)
            helpers_present = True
            fd = outputs.descriptor('Helpers', directory=True); os.close(fd)
        except FileNotFoundError:
            pass
        for name in (frozen.HELPER_ROOT, common.BACKEND_ROOT, common.NATIVE_PATH,
                     NOTICES_DESTINATION):
            if name.startswith('Helpers/') and not helpers_present: continue
            parent, leaf = normalizer._open_parent_at(outputs.fd, name, 'destination_parent')
            try:
                try: os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError: pass
                else: raise prep.CandidateError('destination_exists')
            finally: os.close(parent)
        inputs.named_root(); outputs.named_root()
        if not helpers_present:
            os.mkdir('Helpers', mode=0o755, dir_fd=outputs.fd)
            fd = outputs.descriptor('Helpers', directory=True)
            try: os.fchmod(fd, 0o755)
            finally: os.close(fd)
        rows = dict(entries)
        rows[NOTICES_DESTINATION] = {'type': 'directory', 'mode': '0755'}
        for name, raw in notices.items():
            rows[name] = {'type': 'file', 'mode': '0644', 'bytes': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest()}
        normalizer._create_dest_dirs(outputs.fd, rows, deadline)
        for name, raw in ((frozen.MANIFEST_PATH, manifest_raw), (frozen.INVENTORY_PATH, inventory_raw)):
            rows[name] = {'type': 'file', 'mode': '0644', 'bytes': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest()}
        for name, row in sorted(rows.items()):
            prep._need(time.monotonic() < deadline, 'deadline')
            if row['type'] == 'directory': continue
            if row['type'] == 'symlink':
                target, identity = normalizer._readlink_at(inputs.fd, name)
                prep._need(target == row['target'], 'source_changed')
                normalizer._copy_symlink(inputs.fd, outputs.fd, destination, name,
                    dict(row, source_mode=row['mode']), identity)
                continue
            raw = notices.get(name)
            if raw is None:
                raw = inputs.read(name, 128 * 1048576)
            prep._need(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'source_changed')
            parent, leaf = normalizer._open_parent_at(outputs.fd, name, 'destination_parent')
            fd = None
            try:
                fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
                normalizer._write_all(fd, raw, deadline)
                os.fchmod(fd, int(row['mode'], 8)); os.fsync(fd)
            finally:
                if fd is not None: os.close(fd)
                os.close(parent)
        inputs.named_root(); outputs.named_root()
        prep._need(frozen._validate_bundle(source, manifest_sha256, check_process=False) == binding,
                   'source_changed')
        frozen._validate_bundle(destination, manifest_sha256, check_process=False)
        for name, raw in notices.items():
            copied = outputs.read(name, 256 * 1024)
            prep._need(copied == raw, 'notice_copy_changed')
            parent, leaf = normalizer._open_parent_at(outputs.fd, name, 'destination_changed')
            try:
                info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                prep._need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                           and f'{stat.S_IMODE(info.st_mode):04o}' == '0644',
                           'notice_copy_mode')
            finally:
                os.close(parent)
        notice_dir = outputs.descriptor(NOTICES_DESTINATION, directory=True)
        try:
            info = os.fstat(notice_dir)
            expected_notice_names = {name.rsplit('/', 1)[1] for name in notices}
            prep._need(stat.S_IMODE(info.st_mode) == 0o755
                       and set(os.listdir(notice_dir)) == expected_notice_names,
                       'notice_directory_changed')
        finally:
            os.close(notice_dir)
        return {'schema': 1, 'state': 'ASSEMBLED_OUTER_REQUIRES_SIGNING_NOT_EXECUTED',
                'manifest_sha256': manifest_sha256, 'inventory_sha256': hashlib.sha256(inventory_raw).hexdigest(),
                'runtime_entries': len(entries), 'source_unchanged': True,
                'notices_manifest_sha256': hashlib.sha256(notices_manifest_raw).hexdigest(),
                'notice_files': len(notices), 'notice_bytes': notices_total,
                'historical_helper_sha256': historical_helper_sha256,
                'verified_helper_sha256': verified_helper_sha256,
                'helper_comparison': ('EXACT_EXECUTABLE_MATCH'
                                      if historical_helper_sha256 == verified_helper_sha256
                                      else 'DIFFERENT_EXECUTABLE_REVIEW_REQUIRED'),
                'notice_verification': 'COPY_VERIFIED', 'redistribution_review': 'NOT_PERFORMED',
                'signature_verification': 'NOT_RUN', 'compiled_app_pin_check': 'CALLER_REQUIRED',
                'runtime_execution': 'NOT_RUN'}
    finally:
        inputs.close()
        if outputs is not None: outputs.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-contents', type=Path, required=True)
    parser.add_argument('--app-contents', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = assemble_runtime(args.runtime_contents, args.app_contents, args.manifest_sha256)
    except (OSError, ValueError) as error:
        # Closed failure category, without paths, file content or exception text.
        print(json.dumps({'state': 'REJECTED', 'error_type': type(error).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__': raise SystemExit(main())
