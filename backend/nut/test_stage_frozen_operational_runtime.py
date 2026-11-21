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
