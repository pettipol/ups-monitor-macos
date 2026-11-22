#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Frozen admission bootstrap; operational modules load only after validation."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
from typing import Any
import uuid

import managed_bundled_operational_entrypoint as common

PROFILE = 'apc-smc1500i-operational-frozen-v1'
HELPER_ROOT = 'Helpers/UPSOperationalHelper.app'
HELPER_PATH = HELPER_ROOT + '/Contents/MacOS/UPSOperationalHelper'
MEIPASS = HELPER_ROOT + '/Contents/Frameworks'
MANIFEST_PATH = common.BACKEND_ROOT + '/frozen-runtime-bundle.json'
INVENTORY_PATH = common.BACKEND_ROOT + '/frozen-runtime-tree.json'
MODULES = common.MODULES - {'managed_bundled_operational_entrypoint.py'}


def _validate_bundle(contents: Path, expected_manifest_sha256: str, *,
                     check_process: bool = True) -> common.Binding:
    common._need(common._hash(expected_manifest_sha256), 'manifest_pin')
    files = None
    try:
        files = common._Files(contents)
        raw = files.read(MANIFEST_PATH, 32768)
        common._need(common._sha(raw) == expected_manifest_sha256, 'manifest_pin')
        manifest = common._json(raw)
        common._keys(manifest, {'schema_version', 'profile', 'architecture', 'minimum_macos',
                                'python', 'backend', 'native', 'closure', 'upstream'})
        common._need(type(manifest['schema_version']) is int and manifest['schema_version'] == 1
                     and manifest['profile'] == PROFILE and manifest['architecture'] == 'arm64'
                     and manifest['minimum_macos'] == '27.0', 'manifest_profile')
        python, backend, native, closure, upstream = (manifest[k] for k in
            ('python', 'backend', 'native', 'closure', 'upstream'))
        common._keys(python, {'root', 'executable', 'sha256'})
        common._keys(backend, {'root', 'module_sha256'})
        common._keys(native, {'path', 'name', 'sha256', 'bytes'})
        common._keys(closure, {'path', 'sha256', 'entries'})
        common._keys(upstream, {'archive_sha256', 'metadata_sha256'})
        pins = backend['module_sha256']
        common._need(python['root'] == HELPER_ROOT and python['executable'] == HELPER_PATH
                     and common._hash(python['sha256']) and backend['root'] == common.BACKEND_ROOT
                     and type(pins) is dict and set(pins) == MODULES
                     and all(common._hash(pin) for pin in pins.values())
                     and native['path'] == common.NATIVE_PATH and native['name'] == common.NATIVE_NAME
                     and common._hash(native['sha256']) and common._integer(native['bytes'], 2097152)
                     and native['bytes'] > 0 and closure['path'] == INVENTORY_PATH
                     and common._hash(closure['sha256']) and common._integer(closure['entries'], 20000)
                     and closure['entries'] > 0 and all(common._hash(v) for v in upstream.values()), 'manifest_binding')
        inventory_raw = files.read(INVENTORY_PATH, 16 * 1048576)
        common._need(common._sha(inventory_raw) == closure['sha256'], 'inventory_pin')
        inventory = common._json(inventory_raw)
        common._keys(inventory, {'schema_version', 'entries'})
        common._need(type(inventory['schema_version']) is int and inventory['schema_version'] == 1, 'closure_shape')
        entries = inventory['entries']
        common._closure(files, entries, closure['entries'], roots=(HELPER_ROOT, common.BACKEND_ROOT),
                        controls=(MANIFEST_PATH, INVENTORY_PATH), parents=('Helpers', 'Resources', 'MacOS'),
                        same_root_links=True)
        def pinned(name: str, pin: str, *, size: int | None = None, executable: bool = False) -> None:
            row = entries.get(name, {})
            common._need(row.get('type') == 'file' and row.get('sha256') == pin
                         and (not executable or row.get('mode') == '0755' and row.get('bytes', 0) > 0)
                         and (size is None or row.get('bytes') == size), 'role_pin')
        pinned(HELPER_PATH, python['sha256'], executable=True)
        pinned(common.NATIVE_PATH, native['sha256'], size=native['bytes'], executable=True)
        for name, pin in pins.items(): pinned(common.BACKEND_ROOT + '/' + name, pin)
        if check_process:
            flags = sys.flags
            common._need(common._host_admitted() and getattr(sys, 'frozen', False) is True
                         and Path(sys.executable).resolve(strict=True) == contents / HELPER_PATH
                         and Path(getattr(sys, '_MEIPASS', '')).resolve(strict=True) == contents / MEIPASS
                         and flags.isolated == 1 and flags.no_site == 1 and flags.no_user_site == 1
                         and flags.ignore_environment == 1 and sys.dont_write_bytecode
                         and flags.optimize == 0 and flags.hash_randomization == 0, 'interpreter_identity')
        common._need(files.read(MANIFEST_PATH, 32768) == raw
                     and files.read(INVENTORY_PATH, 16 * 1048576) == inventory_raw, 'controls_changed')
        files.named_root()
        return common.Binding(contents, contents / HELPER_PATH, contents / common.BACKEND_ROOT,
                              contents / common.NATIVE_PATH, native['sha256'], dict(pins), expected_manifest_sha256)
    except (OSError, KeyError, TypeError) as error:
        raise common.BundleError('runtime_file') from error
    finally:
        if files is not None: files.close()


def main() -> int:
    owner: list[Any] = []
    launch_id = 'invalid-launch'
    bootstrap = common._BootstrapStop()
    try:
        for signum in (signal.SIGINT, signal.SIGTERM): signal.signal(signum, bootstrap.request)
        common._need(len(sys.argv) == 7 and sys.argv[1] == '--workspace' and sys.argv[3] == '--launch-id'
                     and sys.argv[5] == '--runtime-manifest-sha256', 'arguments')
        workspace, launch_id, manifest_hash = sys.argv[2], sys.argv[4], sys.argv[6]
        common._need(workspace.startswith('/') and '\0' not in workspace and '..' not in Path(workspace).parts
                     and str(uuid.UUID(launch_id)) == launch_id and common._hash(manifest_hash), 'arguments')
        executable = Path(sys.executable).resolve(strict=True)
        contents = executable.parents[4]
        binding = _validate_bundle(contents, manifest_hash)
        legacy, adapter = common._load_backend(binding, owner, validator=_validate_bundle, modules=MODULES)
        bootstrap.handoff(legacy)
        common._need(not legacy.STOP_REQUESTED, 'stopped_before_session')
        profile = adapter.FixedOperationalProfile(legacy.fixed_argv(binding.native), binding.native_sha256)
        common._need(not legacy.STOP_REQUESTED, 'stopped_before_session')
    except BaseException:
        try: common._emit_rejection(launch_id)
        except BaseException: pass
        if owner and not owner[0]._quiet_workers(): owner[0].retain()
        return 2
    return legacy.serve(adapter, profile, Path(workspace), launch_id)


if __name__ == '__main__':
    raise SystemExit(main())
