#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic contracts for authenticated first-IO source-stage admission."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('first_io_source_stage_under_test', HERE / 'first_io_source_stage.py')
assert SPEC is not None and SPEC.loader is not None
stage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage
SPEC.loader.exec_module(stage)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def map_sha(rows: dict[str, str]) -> str:
    return sha((json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii'))


class FirstIOStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='first-io-stage-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.backend = self.root / 'checkout/backend/nut'
        self.profile_dir = self.backend / 'native-build/first-io-v1'
        self.profile_dir.mkdir(parents=True)
        self.runtime_dir = self.backend / 'qualification'
        self.runtime_dir.mkdir()
        self.stage_root = self.root / 'private-stage'
        self.stage_root.mkdir(mode=0o700)
        self.source = self.stage_root / 'source'
        self.runtime = self.stage_root / 'runtime'
        self.source.mkdir(mode=0o700); self.runtime.mkdir(mode=0o700)
        (self.stage_root / 'logs').mkdir(mode=0o700)

        native_names = [f'project/file-{i:03}.c' for i in range(187)] + [
            'drivers/apcmicrolink-hidapi-session.h',
            'drivers/apcmicrolink-hidapi-shared.c', 'drivers/apcmicrolink.c']
        vendor_names = ['mac/vendor-0.h', *(f'vendor-{i}.h' for i in range(1, 8))]
        runtime_names = [f'module-{i}.py' for i in range(7)] + ['cleanup_diagnostics.py', 'process_deadline.py']
        self.native_base = {name: sha(f'native-base:{name}'.encode()) for name in native_names}
        self.vendor_base = {name: sha(f'vendor:{name}'.encode()) for name in vendor_names}
        self.runtime_base = {name: sha(f'runtime-base:{name}'.encode()) for name in runtime_names}
        self.native_delta = {
            'drivers/apcmicrolink-hidapi-session.h': {'before': self.native_base['drivers/apcmicrolink-hidapi-session.h'], 'after': sha(b'native-after-session')},
            'drivers/apcmicrolink-hidapi-shared.c': {'before': self.native_base['drivers/apcmicrolink-hidapi-shared.c'], 'after': sha(b'native-after-shared')},
            'drivers/apcmicrolink.c': {'before': self.native_base['drivers/apcmicrolink.c'], 'after': sha(b'native-after-driver')},
        }
        self.runtime_delta = {
            'cleanup_diagnostics.py': {'before': self.runtime_base['cleanup_diagnostics.py'], 'after': sha(b'runtime-after-cleanup')},
            'process_deadline.py': {'before': self.runtime_base['process_deadline.py'], 'after': sha(b'runtime-after-deadline')},
        }
        native_post = dict(self.native_base); native_post.update({k: v['after'] for k, v in self.native_delta.items()})
        runtime_post = dict(self.runtime_base); runtime_post.update({k: v['after'] for k, v in self.runtime_delta.items()})
        self.native_post, self.runtime_post = native_post, runtime_post
        self.native_manifest = {
            'post_hidapi_016_sha256': self.native_base,
            'hidapi': {'files': [{'path': name, 'sha256': pin, 'bytes': len(f'vendor:{name}'.encode())}
                                for name, pin in self.vendor_base.items()]},
        }
        self.runtime_manifest = self.runtime_base
        self.write(self.backend / 'native-build/hidapi-0.16/manifest.json', self.json(self.native_manifest))
        self.write(self.runtime_dir / 'module-sha256.json', self.json(self.runtime_manifest))
        self.write(self.runtime_dir / 'smc1500i-90s.patch', b'qualification patch')
        self.profile = {
            'schema': 1,
            'status': 'SOURCE_ONLY_PROFILE', 'source_only': True,
            'qualification': {
                'base_manifest_sha256': 'NATIVE_BASE_PIN', 'native_project_file_count': 190,
                'native_base_map_sha256': map_sha(self.native_base),
                'native_postimage_map_sha256': map_sha(native_post), 'native_unchanged_project_files': 187,
                'vendor_file_count': 8, 'vendor_map_unchanged': True,
                'runtime_base_manifest_sha256': 'RUNTIME_BASE_PIN',
                'runtime_qualification_patch_sha256': 'QUAL_PATCH_PIN',
                'runtime_qualified_base_file_count': 9,
                'runtime_qualified_base_map_sha256': map_sha(self.runtime_base),
                'runtime_postimage_map_sha256': map_sha(runtime_post),
            },
            'native_delta': self.native_delta, 'runtime_delta': self.runtime_delta,
            'payloads': {name: sha(name.encode()) for name in ('native-first-io-v1.patch',
                'cleanup-diagnostics-first-io-v1.patch', 'process-deadline-first-io-v1.patch')},
        }
        for name, pin in self.profile['payloads'].items():
            self.write(self.profile_dir / name, name.encode())
        self.profile['qualification']['base_manifest_sha256'] = sha(self.json(self.native_manifest))
        self.profile['qualification']['runtime_base_manifest_sha256'] = sha(self.json(self.runtime_manifest))
        self.profile['qualification']['runtime_qualification_patch_sha256'] = sha(b'qualification patch')
        self.write(self.profile_dir / 'manifest.json', self.json(self.profile))
        for name, pin in self.native_base.items():
            self.write(self.source / name, f'native-base:{name}'.encode())
        for name, pin in self.vendor_base.items():
            self.write(self.source / 'drivers/hidapi-0.16.0' / name, f'vendor:{name}'.encode())
        for name, pin in self.runtime_base.items():
            raw = f'runtime-base:{name}'.encode()
            if name in self.runtime_delta:
                raw = b'runtime-after-' + (b'cleanup' if name == 'cleanup_diagnostics.py' else b'deadline')
            self.write(self.runtime / name, raw)
        # Use exact postimage bytes corresponding to the profile's digest pins.
        native_after_bytes = {
            'drivers/apcmicrolink-hidapi-session.h': b'native-after-session',
            'drivers/apcmicrolink-hidapi-shared.c': b'native-after-shared',
            'drivers/apcmicrolink.c': b'native-after-driver'}
        for name, raw in native_after_bytes.items(): self.write(self.source / name, raw)
        receipt = {
            'state': 'SOURCE_ONLY_PASS', 'profile_manifest_sha256': 'PROFILE_PIN',
            'native_base_manifest_sha256': 'NATIVE_BASE_PIN', 'runtime_base_manifest_sha256': 'RUNTIME_BASE_PIN',
            'qualification_patch_sha256': 'QUAL_PATCH_PIN',
            'native_base_map_sha256': map_sha(self.native_base), 'native_postimage_map_sha256': map_sha(native_post),
            'runtime_base_map_sha256': map_sha(self.runtime_base), 'runtime_postimage_map_sha256': map_sha(runtime_post),
            'native_delta': self.native_delta, 'runtime_delta': self.runtime_delta,
            'patch_sha256': self.profile['payloads'],
            'counts': {'native_project': 190, 'native_changed': 3, 'native_unchanged': 187,
                       'runtime': 9, 'runtime_changed': 2, 'runtime_unchanged': 7, 'vendor': 8, 'vendor_changed': 0},
            'phase_outcomes': {'native_patch': 'EXITED_0', 'cleanup_patch': 'EXITED_0', 'deadline_patch': 'EXITED_0',
                'complete_map_checks': 'PASS', 'vendor_unchanged': 'PASS', 'original_inputs_unchanged': 'PASS'},
            'build': 'NOT_RUN', 'signing': 'NOT_RUN', 'payload_execution': 'NOT_RUN'}
        self.receipt = receipt
        patches = mock.patch.multiple(
            stage, PROFILE_SHA256=sha(self.json(self.profile)), BASE_HIDAPI_SHA256=sha(self.json(self.native_manifest)),
            BASE_RUNTIME_SHA256=sha(self.json(self.runtime_manifest)), QUALIFICATION_PATCH_SHA256=sha(b'qualification patch'),
            NATIVE_POST_SHA256=map_sha(native_post), RUNTIME_POST_SHA256=map_sha(runtime_post))
        patches.start()
        self.addCleanup(patches.stop)
        self.receipt['profile_manifest_sha256'] = stage.PROFILE_SHA256
        self.receipt['native_base_manifest_sha256'] = stage.BASE_HIDAPI_SHA256
        self.receipt['runtime_base_manifest_sha256'] = stage.BASE_RUNTIME_SHA256
        self.receipt['qualification_patch_sha256'] = stage.QUALIFICATION_PATCH_SHA256
        self.write_receipt()

    @staticmethod
    def json(value):
        return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')

    @staticmethod
    def write(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw); path.chmod(0o600)

    def write_receipt(self):
        self.write(self.stage_root / 'SOURCE_RECEIPT.json', self.json(self.receipt))

    def validate(self):
        return stage.validate_source_stage(self.stage_root, self.backend)

    def test_authenticates_exact_maps_and_returns_path_free_identity_and_overlay(self):
        result = self.validate()
        self.assertEqual(result.native_map, self.native_post)
        self.assertEqual(result.runtime_map, self.runtime_post)
        self.assertEqual(result.vendor_map, self.vendor_base)
        self.assertEqual(result.native_overlay['drivers/apcmicrolink.c'], b'native-after-driver')
        self.assertNotIn(str(self.root), repr(result.identity))
        self.assertEqual(result.identity['profile'], 'first-io-v1')

    def test_rejects_source_vendor_runtime_inventory_receipt_and_profile_tampering(self):
        mutations = (
            self.source / 'project/file-000.c', self.source / 'drivers/hidapi-0.16.0/mac/vendor-0.h',
            self.runtime / 'module-0.py', self.stage_root / 'SOURCE_RECEIPT.json',
        )
        for path in mutations:
            with self.subTest(path=path.name):
                original = path.read_bytes(); path.write_bytes(original + b'changed')
                with self.assertRaises(stage.SourceStageError): self.validate()
                path.write_bytes(original)
        extra = self.source / 'unexpected.txt'; extra.write_bytes(b'x')
        with self.assertRaises(stage.SourceStageError): self.validate()

    def test_rejects_missing_members_symlink_escape_and_edited_profile_delta(self):
        native = self.source / 'project/file-001.c'; raw = native.read_bytes(); native.unlink()
        with self.assertRaises(stage.SourceStageError): self.validate()
        native.write_bytes(raw); native.chmod(0o600)
        link = self.runtime / 'escape.py'; link.symlink_to(self.root / 'outside')
        with self.assertRaises(stage.SourceStageError): self.validate()
        link.unlink()
        self.profile['native_delta']['drivers/apcmicrolink.c']['after'] = '0' * 64
        self.write(self.profile_dir / 'manifest.json', self.json(self.profile))
        with self.assertRaises(stage.SourceStageError): self.validate()

    def test_rejects_altered_or_missing_authenticated_profile_inputs(self):
        manifest = self.profile_dir / 'manifest.json'; raw = manifest.read_bytes()
        manifest.write_bytes(raw + b' ')
        with self.assertRaises(stage.SourceStageError): self.validate()
        manifest.write_bytes(raw)
        payload = self.profile_dir / 'native-first-io-v1.patch'; payload.unlink()
        with self.assertRaises(stage.SourceStageError): self.validate()

    def test_rejects_extra_empty_directories_before_reading_any_stage_members(self):
        for parent, reason in ((self.stage_root, 'stage_inventory'), (self.source, 'source_inventory'),
                               (self.runtime, 'runtime_inventory')):
            with self.subTest(reason=reason):
                extra = parent / 'extra-empty'
                extra.mkdir()
                try:
                    self.assert_rejected_before_stage_read(reason)
                finally:
                    extra.rmdir()

    def test_rejects_symlink_in_expected_nested_ancestor(self):
        vendor = self.source / 'drivers/hidapi-0.16.0'
        original = self.root / 'mac-original'
        (vendor / 'mac').rename(original)
        (vendor / 'mac').symlink_to(original, target_is_directory=True)
        self.assert_rejected_before_stage_read('tree_member')
        with self.assertRaisesRegex(stage.SourceStageError, 'root_symlink'):
            stage._read(vendor / 'mac/vendor-0.h')

    def test_checks_file_and_tree_size_before_reading_stage_members(self):
        target = self.source / 'project/file-000.c'
        original = target.read_bytes()
        with target.open('wb') as stream:
            stream.truncate(stage.MAX_FILE + 1)
        self.assert_rejected_before_stage_read('regular_file')
        target.write_bytes(original)
        with mock.patch.object(stage, 'MAX_TREE', 3_500):
            self.assert_rejected_before_stage_read('tree_size')

    def test_authenticated_vendor_size_checked_before_hashing_vendor(self):
        row = self.native_manifest['hidapi']['files'][0]
        original_size = row['bytes']
        native_lock = self.backend / 'native-build/hidapi-0.16/manifest.json'
        for incorrect, reason in ((original_size + 1, 'vendor_size'), (True, 'vendor_base_shape'),
                                  (0, 'vendor_base_shape'), (stage.MAX_FILE + 1, 'vendor_base_shape')):
            with self.subTest(size=incorrect):
                row['bytes'] = incorrect
                hidapi_raw = self.json(self.native_manifest)
                self.write(native_lock, hidapi_raw)
                hidapi_pin = sha(hidapi_raw)
                self.profile['qualification']['base_manifest_sha256'] = hidapi_pin
                profile_raw = self.json(self.profile)
                self.write(self.profile_dir / 'manifest.json', profile_raw)
                with mock.patch.multiple(stage, BASE_HIDAPI_SHA256=hidapi_pin, PROFILE_SHA256=sha(profile_raw)):
                    self.assert_rejected_before_stage_read(reason)

    def test_inventory_stops_iterating_at_first_unexpected_fanout_entry(self):
        real_scandir = os.scandir
        for location, reason in ((self.stage_root, 'stage_inventory'), (self.source, 'source_inventory')):
            with self.subTest(reason=reason):
                def excess_entries():
                    yield SimpleNamespace(name='unexpected-first')
                    self.fail('inventory consumed another entry after the first unexpected child')

                contents = mock.MagicMock()
                contents.__enter__.return_value = excess_entries()
                with mock.patch.object(stage.os, 'scandir',
                                       side_effect=lambda path: contents if path == location else real_scandir(path)):
                    self.assert_rejected_before_stage_read(reason)

    def assert_rejected_before_stage_read(self, reason):
        read = stage._read

        def read_checkout_only(path, *args):
            self.assertFalse(path.is_relative_to(self.stage_root), 'read a stage member before admission')
            return read(path, *args)

        with mock.patch.object(stage, '_read', side_effect=read_checkout_only):
            with self.assertRaisesRegex(stage.SourceStageError, reason):
                self.validate()


if __name__ == '__main__':
    unittest.main()
