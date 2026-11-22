#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Filesystem-only contracts for staging a frozen helper; payloads stay inert."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
UTILITY_PATH = HERE / 'stage_frozen_operational_runtime.py'
_spec = importlib.util.spec_from_file_location('frozen_stage_under_test', UTILITY_PATH)
if _spec is None:
    raise RuntimeError('stage utility spec unavailable')
stage = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = stage
exec(compile(UTILITY_PATH.read_bytes(), str(UTILITY_PATH), 'exec', dont_inherit=True), stage.__dict__)

prepare, common, normalizer, frozen = stage._dependencies()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class StageFrozenOperationalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='frozen-stage-')
        self.root = Path(self.temp.name).resolve()
        self.helper = self.root / 'UPSOperationalHelper.app'
        self.contents = self.helper / 'Contents'
        for rel in ('MacOS', 'Frameworks', 'Resources'):
            path = self.contents / rel
            path.mkdir(parents=True, mode=0o755, exist_ok=True)
            path.chmod(0o755)
        self.sentinel = self.root / 'helper-was-executed'
        inert = (b'#!/bin/sh\n# inert test payload\n' +
                 f'touch {self.sentinel}\n'.encode('utf-8'))
        self.write_helper('Contents/MacOS/UPSOperationalHelper', inert, 0o755)
        self.write_helper('Contents/Frameworks/libpython3.15.dylib', b'inert libpython bytes', 0o755)
        self.write_helper('Contents/Resources/base_library.zip', b'inert standard library archive', 0o644)
        self.link('Contents/Frameworks/base_library.zip', '../Resources/base_library.zip', 0o755)
        self.link('Contents/Resources/libpython3.15.dylib', '../Frameworks/libpython3.15.dylib', 0o755)
        self.native = self.root / common.NATIVE_NAME
        self.native.write_bytes(b'inert native producer; never executed')
        self.native.chmod(0o755)
        self.native_bytes = self.native.read_bytes()
        self.native_hash = sha(self.native_bytes)

    def tearDown(self):
        self.temp.cleanup()

    def write_helper(self, relative, raw, mode):
        path = self.helper / relative
        path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        for parent in [path.parent, *path.parent.parents]:
            if parent == self.helper.parent:
                break
            if parent.is_dir():
                parent.chmod(0o755)
        path.write_bytes(raw)
        path.chmod(mode)
        return path

    def link(self, relative, target, mode):
        path = self.helper / relative
        path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        path.symlink_to(target)
        os.lchmod(path, mode)
        return path

    def run_stage(self, leaf='candidate'):
        output = self.root / leaf
        result = stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        return output, result

    def test_helper_reader_requires_0777_by_default_and_accepts_input_0755(self):
        deadline = time.monotonic() + 30
        with self.assertRaises(prepare.CandidateError):
            prepare._read_helper(self.helper, normalizer, common, deadline)
        rows, _identities, _root = prepare._read_helper(
            self.helper, normalizer, common, deadline, allow_input_link_mode=True)
        self.assertEqual({rows[name]['mode'] for name in stage.ALLOWED_LINKS}, {'0755'})

    def test_stages_candidate_without_executing_helper_and_normalizes_only_two_links(self):
        for mask in (0o077, 0o022):
            with self.subTest(umask=oct(mask)):
                output = self.root / f'candidate-{mask:03o}'
                previous = os.umask(mask)
                try:
                    result = stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
                finally:
                    os.umask(previous)
                self.assertEqual(result['state'], 'STAGED_FROZEN_NOT_EXECUTED')
                self.assertEqual(result['signature_verification'], 'NOT_RUN')
                self.assertEqual(result['runtime_execution'], 'NOT_RUN')
                self.assertEqual(result['compiled_pin'], 'CALLER_REQUIRED')
                self.assertEqual(result['normalized_links'], sorted(stage.ALLOWED_LINKS))
                self.assertEqual(result['backend_modules'], len(frozen.MODULES))
                self.assertEqual(stat.S_IMODE((output / 'stage/Contents').stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((output / 'stage/Contents/Helpers/UPSOperationalHelper.app').stat().st_mode), 0o755)
                for rel, (target, _resolved) in stage.ALLOWED_LINKS.items():
                    copied = output / 'stage/Contents/Helpers/UPSOperationalHelper.app' / rel
                    self.assertTrue(copied.is_symlink())
                    self.assertEqual(os.readlink(copied), target)
                    self.assertEqual(stat.S_IMODE(copied.lstat().st_mode), 0o777)
                self.assertFalse(self.sentinel.exists())
                self.assertEqual(self.native.read_bytes(), self.native_bytes)
                self.assertEqual(json.loads((output / 'receipt.json').read_text())['state'],
                                 'STAGED_FROZEN_NOT_EXECUTED')

    def test_wrong_native_pin_rejects_before_output_creation(self):
        output = self.root / 'wrong-pin-output'
        with self.assertRaises(stage.FrozenStageError) as raised:
            stage.stage_frozen_runtime(self.helper, self.native, '0' * 64, output)
        self.assertEqual(raised.exception.code, 'native_identity')
        self.assertFalse(output.exists())

    def test_first_io_output_overlap_rejects_before_helper_scan(self):
        source_stage = self.root / 'synthetic-source-stage'
        source_stage.mkdir(mode=0o700)
        selected = type('Selected', (), {'runtime_root': source_stage / 'runtime',
            'runtime_map': {}, 'identity': {'profile': 'first-io-v1'}})()
        validator = type('Validator', (), {'validate_source_stage': staticmethod(
            lambda _path, _backend: selected)})()
        original_loader = prepare._load_source

        def loader(name, path):
            if name == 'first_io_source_stage_validator':
                return validator
            return original_loader(name, path)

        with mock.patch.object(stage, '_dependencies', return_value=(prepare, common, normalizer, frozen)), \
             mock.patch.object(prepare, '_load_source', side_effect=loader), \
             mock.patch.object(stage, '_scan_helper', side_effect=AssertionError('helper scan must not run')):
            with self.assertRaises(stage.FrozenStageError) as raised:
                stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, source_stage,
                                           first_io_source_stage=source_stage)
        self.assertEqual(raised.exception.code, 'overlapping_inputs')

    def _first_io_fixture(self, output_name, mutation=None):
        source_stage = self.root / f'{output_name}-source-stage'
        source_stage.mkdir(mode=0o700)
        runtime_root = source_stage / 'runtime'
        runtime_root.mkdir(mode=0o700)
        module_map = {}
        for name in sorted(frozen.MODULES):
            raw = (stage.HERE / name).read_bytes()
            if name == 'cleanup_diagnostics.py':
                raw += b'\n# Distinct synthetic source-stage bytes; never executed.\n'
            target = runtime_root / name
            target.write_bytes(raw); target.chmod(0o600)
            module_map[name] = sha(raw)
        identity = {'profile': 'first-io-v1', 'source_receipt_sha256': 'a' * 64}
        selected = type('Selected', (), {'runtime_root': runtime_root,
            'runtime_map': module_map, 'identity': identity})()
        def admit(_path, _backend):
            if mutation == 'before-snapshot':
                with (runtime_root / 'cleanup_diagnostics.py').open('ab') as stream:
                    stream.write(b'# Changed after admission.\n')
            return selected

        validator = type('Validator', (), {'validate_source_stage': staticmethod(admit)})()
        original_loader = prepare._load_source

        def loader(name, path):
            if name == 'first_io_source_stage_validator':
                return validator
            return original_loader(name, path)

        output = self.root / output_name
        original_prepare = prepare.prepare_candidate

        def prepare_candidate(contents, swift_pin, expected_native_sha256, **kwargs):
            result = original_prepare(contents, swift_pin, expected_native_sha256, **kwargs)
            if mutation == 'result-map':
                result['module_sha256'] = {'unexpected.py': '0' * 64}
            elif mutation == 'manifest-map':
                manifest_path = contents / frozen.MANIFEST_PATH
                manifest = json.loads(manifest_path.read_bytes())
                manifest['backend']['module_sha256'] = {'unexpected.py': '0' * 64}
                manifest_path.write_text(json.dumps(manifest))
            return result

        with mock.patch.object(stage, '_dependencies', return_value=(prepare, common, normalizer, frozen)), \
             mock.patch.object(prepare, '_load_source', side_effect=loader), \
             mock.patch.object(prepare, 'prepare_candidate', side_effect=prepare_candidate):
            if mutation:
                with self.assertRaises(stage.FrozenStageError):
                    stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output,
                                               first_io_source_stage=source_stage)
                if mutation == 'before-snapshot':
                    self.assertFalse(output.exists(), 'changed admitted modules must fail before output creation')
                    return
                receipt = json.loads((output / 'receipt.json').read_bytes())
                self.assertEqual(receipt['state'], 'STAGING_FAILED_PARTIAL_PRESERVED')
                self.assertNotIn('first_io_source_stage', receipt)
                return
            receipt = stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output,
                                                 first_io_source_stage=source_stage)
        self.assertEqual(receipt['state'], 'STAGED_FROZEN_NOT_EXECUTED')
        self.assertEqual(receipt['first_io_source_stage'], identity)
        manifest = json.loads((output / 'stage/Contents' / frozen.MANIFEST_PATH).read_bytes())
        self.assertEqual(manifest['backend']['module_sha256'], module_map)
        self.assertEqual(receipt['module_sha256'], module_map)
        self.assertEqual(len(module_map), 9)
        self.assertNotEqual(module_map['cleanup_diagnostics.py'], sha((stage.HERE / 'cleanup_diagnostics.py').read_bytes()))

    def test_first_io_frozen_staging_binds_identity_and_exact_manifest_map(self):
        self._first_io_fixture('first-io-positive')

    def test_first_io_result_or_manifest_map_mismatch_cannot_get_success_receipt(self):
        self._first_io_fixture('first-io-result-mismatch', 'result-map')
        self._first_io_fixture('first-io-manifest-mismatch', 'manifest-map')

    def test_first_io_changed_admitted_modules_fail_before_any_output(self):
        self._first_io_fixture('first-io-snapshot-mismatch', 'before-snapshot')

    def test_existing_output_and_sentinel_are_preserved(self):
        output = self.root / 'existing-output'
        output.mkdir(mode=0o700)
        sentinel = output / 'keep.bin'
        sentinel.write_bytes(b'preserve')
        sentinel.chmod(0o600)
        with self.assertRaises(stage.FrozenStageError) as raised:
            stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertEqual(raised.exception.code, 'output_exists')
        self.assertEqual(sentinel.read_bytes(), b'preserve')
        self.assertEqual(set(p.name for p in output.iterdir()), {'keep.bin'})

    def test_escaping_known_link_rejects_before_output_creation(self):
        path = self.helper / 'Contents/Frameworks/base_library.zip'
        path.unlink()
        self.link('Contents/Frameworks/base_library.zip', '../../../../tmp/escape', 0o755)
        output = self.root / 'bad-link-output'
        with self.assertRaises(stage.FrozenStageError):
            stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertFalse(output.exists())

    def test_unexpected_symlink_rejects_before_output_creation(self):
        self.link('Contents/Resources/extra-link', 'base_library.zip', 0o755)
        output = self.root / 'extra-link-output'
        with self.assertRaises(stage.FrozenStageError):
            stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertFalse(output.exists())

    def test_special_helper_member_rejects_before_output_creation(self):
        os.mkfifo(self.contents / 'Resources/fifo')
        output = self.root / 'special-output'
        with self.assertRaises(stage.FrozenStageError):
            stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertFalse(output.exists())

    def test_hardlinked_helper_file_rejects_before_output_creation(self):
        source = self.contents / 'Resources/base_library.zip'
        os.link(source, self.contents / 'Resources/duplicate.zip')
        output = self.root / 'hardlink-output'
        with self.assertRaises(stage.FrozenStageError):
            stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertFalse(output.exists())

    def test_source_change_during_copy_preserves_partial_failure_receipt(self):
        output = self.root / 'changed-source-output'
        original_copy = stage._copy_helper

        def mutate_then_copy(source_fd, destination_fd, destination, rows, identities, fd_helpers, deadline):
            helper_executable = self.contents / 'MacOS/UPSOperationalHelper'
            helper_executable.write_bytes(b'changed after inventory')
            helper_executable.chmod(0o755)
            return original_copy(source_fd, destination_fd, destination, rows, identities, fd_helpers, deadline)

        with mock.patch.object(stage, '_copy_helper', side_effect=mutate_then_copy):
            with self.assertRaises(stage.FrozenStageError):
                stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        receipt = json.loads((output / 'receipt.json').read_text())
        self.assertEqual(receipt['state'], 'STAGING_FAILED_PARTIAL_PRESERVED')
        self.assertEqual(receipt['runtime_execution'], 'NOT_RUN')
        self.assertFalse(self.sentinel.exists())

    def test_same_length_destination_mutation_after_copy_is_rejected_before_finalizer(self):
        output = self.root / 'mutated-copy-output'
        original_copy = stage._copy_helper
        relative = 'Helpers/UPSOperationalHelper.app/Contents/MacOS/UPSOperationalHelper'

        def copy_then_mutate(source_fd, destination_fd, destination, rows, identities, fd_helpers, deadline):
            result = original_copy(source_fd, destination_fd, destination, rows, identities, fd_helpers, deadline)
            copied = destination / relative
            raw = copied.read_bytes()
            copied.write_bytes((b'X' if raw[:1] != b'X' else b'Y') + raw[1:])
            copied.chmod(0o755)
            return result

        with mock.patch.object(stage, '_copy_helper', side_effect=copy_then_mutate):
            with self.assertRaises(stage.FrozenStageError) as raised:
                stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertEqual(raised.exception.code, 'helper_copy_changed')
        receipt = json.loads((output / 'receipt.json').read_text())
        self.assertEqual(receipt['state'], 'STAGING_FAILED_PARTIAL_PRESERVED')
        self.assertFalse(self.sentinel.exists())

    def test_same_length_mutation_after_finalizer_is_rejected(self):
        output = self.root / 'mutated-final-output'
        original_prepare = prepare.prepare_candidate
        relative = 'Helpers/UPSOperationalHelper.app/Contents/MacOS/UPSOperationalHelper'

        def prepare_then_mutate(contents, swift_pin, expected_native_sha256, *, frozen=False):
            result = original_prepare(contents, swift_pin, expected_native_sha256, frozen=frozen)
            copied = contents / relative
            raw = copied.read_bytes()
            copied.write_bytes((b'X' if raw[:1] != b'X' else b'Y') + raw[1:])
            copied.chmod(0o755)
            return result

        with mock.patch.object(stage, '_dependencies', return_value=(prepare, common, normalizer, frozen)), \
             mock.patch.object(prepare, 'prepare_candidate', side_effect=prepare_then_mutate):
            with self.assertRaises(stage.FrozenStageError) as raised:
                stage.stage_frozen_runtime(self.helper, self.native, self.native_hash, output)
        self.assertEqual(raised.exception.code, 'helper_copy_changed')
        receipt = json.loads((output / 'receipt.json').read_text())
        self.assertEqual(receipt['state'], 'STAGING_FAILED_PARTIAL_PRESERVED')
        self.assertFalse(self.sentinel.exists())


if __name__ == '__main__':
    unittest.main()
