"""Inert runtime assembly contracts; no payload is executed or signed."""
from pathlib import Path
import hashlib
import json
import os
import stat
import unittest
from unittest.mock import patch

# Reuse the existing isolated source loader and inert closure fixture.
import importlib.util
import sys
path = Path(__file__).with_name('test_managed_frozen_operational_entrypoint.py')
spec = importlib.util.spec_from_file_location('assembly_fixture', path)
fixture_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture_module
exec(compile(path.read_bytes(), str(path), 'exec'), fixture_module.__dict__)
assembly = fixture_module.load_source('assembly_under_test', 'assemble_frozen_operational_runtime.py')


class AssemblyTests(unittest.TestCase):
    NOTICE_UPSTREAM = {
        'archive_sha256': '17a41099bba8c18c45c527580014e75dc7a77300f619d7f5cdfecc57aca06f39',
        'metadata_sha256': '6256d1667b03c2f582c7ba0b4c058f59acd02c8b1819ceca3ce904349e13e1bc',
    }

    def setUp(self):
        self.f = fixture_module.Fixture(); self.addCleanup(self.f.temp.cleanup)
        self.f.manifest['upstream'] = dict(self.NOTICE_UPSTREAM); self.f.save()
        self.destination = self.f.root.parent.parent / 'Built App.app/Contents'
        for name in ('MacOS', 'Resources'):
            (self.destination / name).mkdir(mode=0o755, parents=True)
        self.sentinel = self.destination / 'MacOS/app'
        self.sentinel.write_bytes(b'inert existing app'); self.sentinel.chmod(0o755)
        self.notices_root = self.f.root.parent / 'notice-source'
        self._write_notices(self.notices_root)

    @staticmethod
    def _notice_manifest(upstream, files, historical_helper_sha256):
        return fixture_module.encode({
            'components': {},
            'files': files,
            'observed_helper': {
                'runtime_hooks': {'synthetic_hook': 'observed-in-fixture'},
                'sha256': historical_helper_sha256,
            },
            'profile': 'ups-monitor-frozen-notices-v1',
            'redistribution_review': 'NOT_PERFORMED',
            'runtime_upstream': upstream,
            'schema_version': 1,
        })

    def _write_notices(self, root, upstream=None, historical_helper_sha256=None):
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        files, payloads = {}, {}
        for index in range(24):
            name = 'README.md' if index == 0 else f'notice-{index:02d}.txt'
            raw = f'inert notice fixture {index}\n'.encode()
            payloads[name] = raw
            files[name] = {'bytes': len(raw), 'component': 'synthetic', 'scope': 'fixture',
                           'sha256': fixture_module.sha(raw), 'source_member': f'fixture/{name}'}
        for name, raw in payloads.items(): (root / name).write_bytes(raw)
        manifest_raw = self._notice_manifest(
            upstream or self.NOTICE_UPSTREAM, files,
            historical_helper_sha256 or self.f.manifest['python']['sha256'])
        (root / 'manifest.json').write_bytes(manifest_raw)
        return payloads, manifest_raw

    def _assemble_with_notices(self, source=None):
        raw = (source or self.notices_root / 'manifest.json').read_bytes()
        with patch.object(assembly, 'NOTICES_ROOT', source or self.notices_root), \
             patch.object(assembly, 'NOTICES_MANIFEST_SHA256', fixture_module.sha(raw)):
            return assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)

    def _assert_no_assembly_writes(self, *, notices_exist=False):
        self.assertEqual(self.sentinel.read_bytes(), b'inert existing app')
        self.assertFalse((self.destination / 'Helpers').exists())
        self.assertFalse((self.destination / fixture_module.common.BACKEND_ROOT).exists())
        self.assertFalse((self.destination / fixture_module.common.NATIVE_PATH).exists())
        self.assertFalse((self.destination / fixture_module.entry.MANIFEST_PATH).exists())
        self.assertFalse((self.destination / fixture_module.entry.INVENTORY_PATH).exists())
        if not notices_exist:
            self.assertFalse((self.destination / 'Resources/RuntimeNotices').exists())

    def test_copy_controls_modes_links_and_preserve_existing_app(self):
        f = self.f
        link = fixture_module.entry.HELPER_ROOT + '/Contents/Frameworks/alias'
        os.symlink('inert.dat', f.root / link)
        os.lchmod(f.root / link, 0o777)
        f.entries[link] = {'type': 'symlink', 'mode': '0777', 'target': 'inert.dat',
                          'resolved_target': fixture_module.entry.MEIPASS + '/inert.dat'}
        f.save()
        result = self._assemble_with_notices()
        self.assertEqual(result['state'], 'ASSEMBLED_OUTER_REQUIRES_SIGNING_NOT_EXECUTED')
        self.assertEqual(result['notice_files'], 25)
        self.assertEqual(result['notice_verification'], 'COPY_VERIFIED')
        self.assertEqual(result['redistribution_review'], 'NOT_PERFORMED')
        self.assertEqual(result['historical_helper_sha256'], self.f.manifest['python']['sha256'])
        self.assertEqual(result['verified_helper_sha256'], self.f.manifest['python']['sha256'])
        self.assertEqual(result['helper_comparison'], 'EXACT_EXECUTABLE_MATCH')
        self.assertEqual(result['notices_manifest_sha256'], fixture_module.sha((self.notices_root / 'manifest.json').read_bytes()))
        self.assertEqual(self.sentinel.read_bytes(), b'inert existing app')
        for name in (fixture_module.entry.MANIFEST_PATH, fixture_module.entry.INVENTORY_PATH):
            self.assertEqual((f.root / name).read_bytes(), (self.destination / name).read_bytes())
        fixture_module.entry._validate_bundle(self.destination, f.pin, check_process=False)
        f.validate()
        for path in self.notices_root.iterdir():
            copied = self.destination / 'Resources/RuntimeNotices' / path.name
            self.assertEqual(path.read_bytes(), copied.read_bytes())
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o644)
        self.assertEqual(result['notice_bytes'], sum(path.stat().st_size for path in self.notices_root.iterdir()))

    def test_canonical_notice_assets_copy_exactly_without_running_helper(self):
        source = assembly.HERE.parents[1] / 'third_party' / 'frozen-runtime'
        manifest_raw = (source / 'manifest.json').read_bytes()
        manifest = json.loads(manifest_raw)
        payloads = {name: (source / name).read_bytes() for name in manifest['files']}
        with patch.object(assembly, 'NOTICES_ROOT', source):
            result = assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        target = self.destination / 'Resources/RuntimeNotices'
        expected_names = set(payloads) | {'manifest.json'}
        self.assertEqual(set(os.listdir(target)), expected_names)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
        self.assertEqual(result['notice_files'], 25)
        self.assertEqual(result['notice_bytes'], len(manifest_raw) + sum(map(len, payloads.values())))
        self.assertEqual(result['notice_verification'], 'COPY_VERIFIED')
        self.assertEqual(result['redistribution_review'], 'NOT_PERFORMED')
        self.assertEqual(result['helper_comparison'], 'DIFFERENT_EXECUTABLE_REVIEW_REQUIRED')
        self.assertEqual(result['notices_manifest_sha256'], fixture_module.sha(manifest_raw))
        self.assertEqual((target / 'manifest.json').read_bytes(), manifest_raw)
        for name, raw in payloads.items():
            copied = target / name
            self.assertEqual(copied.read_bytes(), raw)
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o644)

    def test_missing_notice_rejected_before_any_assembly_write(self):
        (self.notices_root / 'notice-23.txt').unlink()
        with self.assertRaises((ValueError, OSError)): self._assemble_with_notices()
        self._assert_no_assembly_writes()

    def test_tampered_notice_rejected_before_any_assembly_write(self):
        (self.notices_root / 'notice-23.txt').write_bytes(b'tampered inert notice')
        with self.assertRaises((ValueError, OSError)): self._assemble_with_notices()
        self._assert_no_assembly_writes()

    def test_wrong_notice_upstream_rejected_before_any_assembly_write(self):
        other = dict(self.NOTICE_UPSTREAM); other['archive_sha256'] = 'f' * 64
        self._write_notices(self.notices_root, other)
        with self.assertRaises((ValueError, OSError)): self._assemble_with_notices()
        self._assert_no_assembly_writes()

    def test_different_historical_helper_is_reported_without_rejecting_build(self):
        historical = 'f' * 64
        self._write_notices(self.notices_root, historical_helper_sha256=historical)
        result = self._assemble_with_notices()
        self.assertEqual(result['historical_helper_sha256'], historical)
        self.assertEqual(result['verified_helper_sha256'], self.f.manifest['python']['sha256'])
        self.assertEqual(result['helper_comparison'], 'DIFFERENT_EXECUTABLE_REVIEW_REQUIRED')
        self.assertEqual(result['notice_verification'], 'COPY_VERIFIED')
        self.assertEqual(result['redistribution_review'], 'NOT_PERFORMED')

    def test_missing_historical_helper_hash_rejected_before_any_assembly_write(self):
        manifest_path = self.notices_root / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        del manifest['observed_helper']['sha256']
        manifest_path.write_bytes(fixture_module.encode(manifest))
        with self.assertRaises((ValueError, OSError)): self._assemble_with_notices()
        self._assert_no_assembly_writes()

    def test_malformed_historical_helper_hash_rejected_before_any_assembly_write(self):
        manifest_path = self.notices_root / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        manifest['observed_helper']['sha256'] = 'A' * 64
        manifest_path.write_bytes(fixture_module.encode(manifest))
        with self.assertRaises((ValueError, OSError)): self._assemble_with_notices()
        self._assert_no_assembly_writes()

    def test_bad_notice_manifest_pin_rejected_before_any_assembly_write(self):
        with patch.object(assembly, 'NOTICES_ROOT', self.notices_root), \
             patch.object(assembly, 'NOTICES_MANIFEST_SHA256', '0' * 64):
            with self.assertRaises((ValueError, OSError)):
                assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        self._assert_no_assembly_writes()

    def test_preexisting_notice_destination_rejected_without_overwrite(self):
        target = self.destination / 'Resources/RuntimeNotices'
        target.mkdir(); marker = target / 'keep'; marker.write_bytes(b'preserve')
        with self.assertRaises((ValueError, OSError)): self._assemble_with_notices()
        self._assert_no_assembly_writes(notices_exist=True)
        self.assertEqual(marker.read_bytes(), b'preserve')

    def test_extra_notice_added_during_copy_is_rejected(self):
        original_dependencies = assembly._dependencies
        prep, common, frozen, normalizer = original_dependencies()
        original_write = normalizer._write_all
        injected = False

        def write_then_inject(fd, raw, deadline):
            nonlocal injected
            if not injected:
                injected = True
                extra = self.destination / 'Resources/RuntimeNotices/unexpected.txt'
                extra.write_bytes(b'inert unexpected file')
            return original_write(fd, raw, deadline)

        normalizer._write_all = write_then_inject
        assembly._dependencies = lambda: (prep, common, frozen, normalizer)
        try:
            with patch.object(assembly, 'NOTICES_ROOT', self.notices_root), \
                 patch.object(assembly, 'NOTICES_MANIFEST_SHA256',
                              fixture_module.sha((self.notices_root / 'manifest.json').read_bytes())):
                with self.assertRaises(ValueError):
                    assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        finally:
            normalizer._write_all = original_write
            assembly._dependencies = original_dependencies
        self.assertTrue(injected)
        self.assertEqual(self.sentinel.read_bytes(), b'inert existing app')
        self.assertTrue((self.destination / 'Resources/RuntimeNotices/unexpected.txt').is_file())

    def test_existing_runtime_rejected_without_overwrite(self):
        target = self.destination / fixture_module.common.NATIVE_PATH
        target.write_bytes(b'keep this')
        with self.assertRaises(ValueError): assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        self.assertEqual(target.read_bytes(), b'keep this')
        self.assertFalse((self.destination / 'Helpers').exists())

    def test_bad_source_rejected_before_destination_changes(self):
        (self.f.root / fixture_module.entry.HELPER_PATH).write_bytes(b'changed')
        with self.assertRaises(ValueError): assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        self.assertFalse((self.destination / 'Helpers').exists())
        self.assertEqual(self.sentinel.read_bytes(), b'inert existing app')

    def test_inventory_changed_after_consumer_validation_rejected_before_write(self):
        original_dependencies = assembly._dependencies
        prep, common, frozen, normalizer = original_dependencies()
        original_validate = frozen._validate_bundle
        validations = 0

        def validate_then_change_inventory(source, pin, *, check_process=False):
            nonlocal validations
            binding = original_validate(source, pin, check_process=check_process)
            validations += 1
            if validations == 1:
                raw = fixture_module.encode({'schema_version': 1, 'entries': {}})
                (self.f.root / fixture_module.entry.INVENTORY_PATH).write_bytes(raw)
            return binding

        frozen._validate_bundle = validate_then_change_inventory
        assembly._dependencies = lambda: (prep, common, frozen, normalizer)
        try:
            with self.assertRaises(ValueError):
                assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        finally:
            frozen._validate_bundle = original_validate
            assembly._dependencies = original_dependencies

        self.assertEqual(validations, 1, 'The changed inventory must be rejected before the second consumer validation')
        self.assertEqual(self.sentinel.read_bytes(), b'inert existing app')
        self.assertFalse((self.destination / 'Helpers').exists())
        self.assertFalse((self.destination / fixture_module.common.BACKEND_ROOT).exists())
        self.assertFalse((self.destination / fixture_module.common.NATIVE_PATH).exists())
        self.assertFalse((self.destination / fixture_module.entry.MANIFEST_PATH).exists())
        self.assertFalse((self.destination / fixture_module.entry.INVENTORY_PATH).exists())

    def test_wrong_pin_and_same_source_destination_are_rejected(self):
        for target, pin in ((self.destination, '0' * 64), (self.f.root, self.f.pin)):
            with self.assertRaises(ValueError): assembly.assemble_runtime(self.f.root, target, pin)
        self.assertFalse((self.destination / 'Helpers').exists())

    def test_helpers_symlink_is_rejected_before_copy(self):
        os.symlink(self.f.root / 'Helpers', self.destination / 'Helpers')
        with self.assertRaises((ValueError, OSError)):
            assembly.assemble_runtime(self.f.root, self.destination, self.f.pin)
        self.assertFalse((self.destination / fixture_module.common.BACKEND_ROOT).exists())


if __name__ == '__main__': unittest.main()
