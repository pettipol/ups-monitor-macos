#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Small filesystem-only contracts for the public candidate packager."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
UTILITY_PATH = HERE / 'prepare_bundled_operational_candidate.py'


def load_utility():
    raw = UTILITY_PATH.read_bytes()
    spec = importlib.util.spec_from_file_location('candidate_packager_under_test', UTILITY_PATH)
    if spec is None:
        raise RuntimeError('utility spec unavailable')
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    exec(compile(raw, str(UTILITY_PATH), 'exec', dont_inherit=True), module.__dict__)
    module._HERE = HERE
    module._NORMALIZER_PATH = HERE / 'normalize_bundled_python.py'
    module._READER_PATH = HERE / 'managed_bundled_operational_entrypoint.py'
    module._INPUTS_PATH = HERE / 'bundled_python_runtime_inputs.json'
    return module


PACKAGER = load_utility()
CONSUMER = PACKAGER._load_source('candidate_test_consumer', PACKAGER._READER_PATH)


class CandidatePackagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bundled-candidate-')
        self.root = Path(os.path.realpath(self.temporary.name))
        self.modules = self.root / 'checkout-modules'
        self.modules.mkdir(mode=0o700)
        for name in sorted(CONSUMER.MODULES):
            (self.modules / name).write_bytes(('fixture module: ' + name + '\n').encode())
            (self.modules / name).chmod(0o644)

    def tearDown(self):
        self.temporary.cleanup()

    def contents(self, leaf='contents'):
        root = self.root / leaf / 'Contents'
        runtime = root / CONSUMER.PYTHON_ROOT
        (runtime / 'install/bin').mkdir(mode=0o755, parents=True)
        (runtime / 'install/lib').mkdir(mode=0o755)
        (runtime / 'licenses').mkdir(mode=0o755)
        (root / 'MacOS').mkdir(mode=0o755)
        executable = runtime / 'install/bin/python3.15'
        executable.write_bytes(b'fixture interpreter bytes; never executed\n')
        executable.chmod(0o755)
        (runtime / 'install/lib/libpython.fixture.dylib').write_bytes(b'fixture runtime library\n')
        (runtime / 'install/lib/libpython.fixture.dylib').chmod(0o644)
        (runtime / 'licenses/LICENSE.fixture.txt').write_bytes(b'MIT fixture notice\n')
        (runtime / 'licenses/LICENSE.fixture.txt').chmod(0o644)
        (runtime / 'install/lib/empty.fixture').write_bytes(b'')
        (runtime / 'install/lib/empty.fixture').chmod(0o644)
        os.symlink('../lib/libpython.fixture.dylib', runtime / 'install/bin/libpython-link')
        self.set_link_mode(runtime / 'install/bin/libpython-link')
        native = root / CONSUMER.NATIVE_PATH
        native.write_bytes(b'fixture native image; signature not checked here\n')
        native.chmod(0o755)
        self.normalize_fixture_directories(root)
        return root, native

    @staticmethod
    def set_link_mode(path):
        if hasattr(os, 'lchmod'):
            os.lchmod(path, 0o777)
        else:
            os.chmod(path, 0o777, follow_symlinks=False)
        if stat.S_IMODE(os.lstat(path).st_mode) != 0o777:
            raise AssertionError('fixture link mode was not normalized')

    @staticmethod
    def normalize_fixture_directories(root):
        for current, directories, _files in os.walk(root, topdown=False, followlinks=False):
            current_path = Path(current)
            for name in directories:
                child = current_path / name
                if not child.is_symlink():
                    child.chmod(0o755)
                    if stat.S_IMODE(child.lstat().st_mode) != 0o755:
                        raise AssertionError('fixture directory mode was not normalized')
            current_path.chmod(0o755)
            if stat.S_IMODE(current_path.lstat().st_mode) != 0o755:
                raise AssertionError('fixture directory mode was not normalized')

    def prepare(self, leaf='contents', swift_name='BundledOperationalReleasePins.swift'):
        root, native = self.contents(leaf)
        pin = self.root / leaf / swift_name
        result = PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                                  backend_source=self.modules)
        return root, pin, result

    def test_valid_candidate_is_deterministic_and_consumer_accepts_three_artifacts(self):
        first, first_pin, first_result = self.prepare('one')
        second, second_pin, second_result = self.prepare('two')
        self.assertEqual(first_result['manifest_sha256'], second_result['manifest_sha256'])
        self.assertEqual(first_result['inventory_sha256'], second_result['inventory_sha256'])
        for relative in (CONSUMER.MANIFEST_PATH, CONSUMER.INVENTORY_PATH):
            self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes())
        self.assertEqual(first_pin.read_bytes(), second_pin.read_bytes())
        manifest = json.loads((first / CONSUMER.MANIFEST_PATH).read_bytes())
        inventory = json.loads((first / CONSUMER.INVENTORY_PATH).read_bytes())
        self.assertEqual(manifest['closure']['sha256'], first_result['inventory_sha256'])
        self.assertEqual(manifest['native']['sha256'], first_result['native_sha256'])
        self.assertEqual(set(manifest['backend']['module_sha256']), set(CONSUMER.MODULES))
        empty_path = CONSUMER.PYTHON_ROOT + '/install/lib/empty.fixture'
        self.assertEqual(inventory['entries'][empty_path]['bytes'], 0)
        self.assertEqual(inventory['entries'][empty_path]['sha256'], hashlib.sha256(b'').hexdigest())
        CONSUMER._validate_bundle(first, first_result['manifest_sha256'], check_process=False)

    def test_wrong_native_identity_fails_before_writing(self):
        root, native = self.contents('wrong-native')
        pin = self.root / 'wrong-native' / 'Pins.swift'
        with self.assertRaises(PACKAGER.CandidateError):
            PACKAGER._prepare(root, pin, '0' * 64, backend_source=self.modules)
        self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())
        self.assertFalse(pin.exists())

    def test_first_io_module_snapshot_mismatch_fails_before_controls_or_pin(self):
        root, native = self.contents('first-io-module-mismatch')
        expected = {name: hashlib.sha256((self.modules / name).read_bytes()).hexdigest()
                    for name in CONSUMER.MODULES}
        changed = sorted(expected)[0]
        (self.modules / changed).write_bytes(b'mutated after authenticated snapshot')
        pin = self.root / 'first-io-module-mismatch' / 'Pins.swift'
        with self.assertRaises(PACKAGER.CandidateError) as raised:
            PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                backend_source=self.modules, expected_module_sha256=expected)
        self.assertEqual(raised.exception.code, 'stage_module_snapshot')
        self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())
        self.assertFalse((root / CONSUMER.MANIFEST_PATH).exists())
        self.assertFalse((root / CONSUMER.INVENTORY_PATH).exists())
        self.assertFalse(pin.exists())

    def test_extra_module_and_mutated_module_are_rejected_by_public_consumer(self):
        root, pin, result = self.prepare('mutations')
        extra = root / CONSUMER.BACKEND_ROOT / 'unlisted.py'
        extra.write_bytes(b'extra')
        extra.chmod(0o644)
        with self.assertRaises(ValueError):
            CONSUMER._validate_bundle(root, result['manifest_sha256'], check_process=False)
        extra.unlink()
        module = root / CONSUMER.BACKEND_ROOT / sorted(CONSUMER.MODULES)[0]
        module.write_bytes(b'mutated module bytes\n')
        module.chmod(0o644)
        with self.assertRaises(ValueError):
            CONSUMER._validate_bundle(root, result['manifest_sha256'], check_process=False)

    def test_external_and_dangling_runtime_links_fail_closed(self):
        for leaf, target in (('external-link', '../../../outside'), ('dangling-link', 'missing-target')):
            with self.subTest(target=target):
                root, _ = self.contents(leaf)
                link = root / CONSUMER.PYTHON_ROOT / 'install/bin/invalid-link'
                os.symlink(target, link)
                self.set_link_mode(link)
                pin = self.root / leaf / 'Pins.swift'
                native_hash = hashlib.sha256((root / CONSUMER.NATIVE_PATH).read_bytes()).hexdigest()
                with self.assertRaises(PACKAGER.CandidateError):
                    PACKAGER._prepare(root, pin, native_hash, backend_source=self.modules)
                self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())
                self.assertFalse(pin.exists())

    def test_swift_pin_inside_contents_or_resolving_alias_is_rejected_before_writes(self):
        root, native = self.contents('pin-scope')
        runtime = root / CONSUMER.PYTHON_ROOT
        executable = runtime / 'install/bin/python3.15'
        before_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        alias = root / 'Resources/runtime-alias'
        os.symlink('PythonRuntime/install', alias)
        self.set_link_mode(alias)
        invalid_outputs = (
            runtime / 'install/Pins.swift',
            root / 'Resources/runtime-alias/Pins.swift',
        )
        for pin in invalid_outputs:
            with self.subTest(pin=pin.name):
                with self.assertRaises(PACKAGER.CandidateError):
                    PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                                      backend_source=self.modules)
                self.assertEqual(hashlib.sha256(executable.read_bytes()).hexdigest(), before_hash)
                self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())
                self.assertFalse((root / CONSUMER.INVENTORY_PATH).exists())
                self.assertFalse((root / CONSUMER.MANIFEST_PATH).exists())

    def test_swift_pin_inside_backend_source_is_rejected_before_writes(self):
        root, native = self.contents('pin-source-overlap')
        executable = root / CONSUMER.PYTHON_PATH
        before_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        pin = self.modules / 'BundledOperationalReleasePins.swift'
        with self.assertRaises(PACKAGER.CandidateError):
            PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                              backend_source=self.modules)
        self.assertEqual(hashlib.sha256(executable.read_bytes()).hexdigest(), before_hash)
        self.assertFalse(pin.exists())
        self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())
        self.assertFalse((root / CONSUMER.INVENTORY_PATH).exists())
        self.assertFalse((root / CONSUMER.MANIFEST_PATH).exists())

    def test_preexisting_backend_is_not_overwritten(self):
        root, native = self.contents('preexisting')
        backend = root / CONSUMER.BACKEND_ROOT
        backend.mkdir(mode=0o755)
        pin = self.root / 'preexisting' / 'Pins.swift'
        with self.assertRaises(PACKAGER.CandidateError):
            PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                              backend_source=self.modules)
        self.assertFalse(pin.exists())
        self.assertEqual(list(backend.iterdir()), [])

    def test_preexisting_pin_is_not_overwritten(self):
        root, native = self.contents('preexisting-pin')
        pin = self.root / 'preexisting-pin' / 'Pins.swift'
        pin.write_text('sentinel', encoding='utf-8')
        with self.assertRaises(PACKAGER.CandidateError):
            PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                              backend_source=self.modules)
        self.assertEqual(pin.read_text(encoding='utf-8'), 'sentinel')
        self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())

    def frozen_contents(self, leaf):
        root = self.root / leaf / 'Contents'
        helper = root / 'Helpers/UPSOperationalHelper.app/Contents/MacOS/UPSOperationalHelper'
        helper.parent.mkdir(mode=0o755, parents=True)
        helper.write_bytes(b'inert frozen helper; never executed\n')
        helper.chmod(0o755)
        frameworks = helper.parent.parent / 'Frameworks'
        resources = helper.parent.parent / 'Resources'
        frameworks.mkdir(mode=0o755)
        resources.mkdir(mode=0o755)
        (resources / 'base_library.zip').write_bytes(b'inert stdlib archive\n')
        (resources / 'base_library.zip').chmod(0o644)
        (resources / 'empty.fixture').write_bytes(b'')
        (resources / 'empty.fixture').chmod(0o644)
        link = frameworks / 'base_library.zip'
        os.symlink('../Resources/base_library.zip', link)
        self.set_link_mode(link)
        (root / 'Resources').mkdir(mode=0o755)
        (root / 'MacOS').mkdir(mode=0o755)
        native = root / CONSUMER.NATIVE_PATH
        native.write_bytes(b'inert native; never executed\n')
        native.chmod(0o755)
        self.normalize_fixture_directories(root)
        return root, helper, native

    def test_frozen_profile_prepares_nine_modules_and_distinct_pin(self):
        root, helper, native = self.frozen_contents('frozen')
        pin = self.root / 'FrozenOperationalReleasePins.swift'
        result = PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                                  backend_source=self.modules, frozen=True)
        self.assertEqual(result['state'], 'FROZEN_OPERATIONAL_CANDIDATE_PREPARED_NOT_RELEASED')
        self.assertEqual(len(result['module_sha256']), 9)
        self.assertNotIn('managed_bundled_operational_entrypoint.py', result['module_sha256'])
        manifest = json.loads((root / CONSUMER.BACKEND_ROOT / 'frozen-runtime-bundle.json').read_bytes())
        self.assertEqual(manifest['python']['sha256'], hashlib.sha256(helper.read_bytes()).hexdigest())
        self.assertEqual(manifest['profile'], 'apc-smc1500i-operational-frozen-v1')
        self.assertNotIn('entrypoint', manifest['backend'])
        self.assertIn('enum FrozenOperationalReleasePins', pin.read_text())
        self.assertFalse((root / CONSUMER.MANIFEST_PATH).exists())
        self.assertFalse((root / CONSUMER.BACKEND_ROOT / 'managed_bundled_operational_entrypoint.py').exists())

    def test_frozen_helper_link_cannot_escape_before_writing(self):
        root, helper, native = self.frozen_contents('frozen-link')
        link = helper.parent.parent / 'outside'
        os.symlink('../../../../Resources', link)
        self.set_link_mode(link)
        pin = self.root / 'rejected-frozen-pin.swift'
        with self.assertRaises(PACKAGER.CandidateError):
            PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                              backend_source=self.modules, frozen=True)
        self.assertFalse(pin.exists())
        self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())

    def test_backend_mode_and_public_consumers_under_restrictive_umasks(self):
        results = {}
        for mask in (0o077, 0o022):
            previous = os.umask(mask)
            try:
                bundled_root, bundled_native = self.contents(f'umask-bundled-{mask:03o}')
                bundled_pin = self.root / f'umask-bundled-{mask:03o}' / 'Pins.swift'
                bundled_result = PACKAGER._prepare(
                    bundled_root, bundled_pin, hashlib.sha256(bundled_native.read_bytes()).hexdigest(),
                    backend_source=self.modules)
                bundled_backend = bundled_root / CONSUMER.BACKEND_ROOT
                self.assertEqual(stat.S_IMODE(bundled_backend.lstat().st_mode), 0o755)
                CONSUMER._validate_bundle(
                    bundled_root, bundled_result['manifest_sha256'], check_process=False)

                frozen_root, _helper, frozen_native = self.frozen_contents(f'umask-frozen-{mask:03o}')
                frozen_pin = self.root / f'umask-frozen-{mask:03o}-Pins.swift'
                frozen_result = PACKAGER._prepare(
                    frozen_root, frozen_pin, hashlib.sha256(frozen_native.read_bytes()).hexdigest(),
                    backend_source=self.modules, frozen=True)
                frozen_backend = frozen_root / CONSUMER.BACKEND_ROOT
                self.assertEqual(stat.S_IMODE(frozen_backend.lstat().st_mode), 0o755)
                frozen_consumer = PACKAGER._load_source(
                    'candidate_test_frozen_consumer', HERE / 'managed_frozen_operational_entrypoint.py')
                frozen_consumer._validate_bundle(
                    frozen_root, frozen_result['manifest_sha256'], check_process=False)
                results[(mask, 'bundled')] = bundled_result['manifest_sha256']
                results[(mask, 'frozen')] = frozen_result['manifest_sha256']
            finally:
                os.umask(previous)
        self.assertEqual(results[(0o077, 'bundled')], results[(0o022, 'bundled')])
        self.assertEqual(results[(0o077, 'frozen')], results[(0o022, 'frozen')])

    def test_frozen_helper_link_cycle_fails_before_writing(self):
        root, helper, native = self.frozen_contents('frozen-cycle')
        for name, target in [('a', 'b'), ('b', 'a')]:
            link = helper.parent.parent / 'Frameworks' / name
            os.symlink(target, link)
            self.set_link_mode(link)
        pin = self.root / 'cyclic-frozen-pin.swift'
        with self.assertRaises(PACKAGER.CandidateError):
            PACKAGER._prepare(root, pin, hashlib.sha256(native.read_bytes()).hexdigest(),
                              backend_source=self.modules, frozen=True)
        self.assertFalse(pin.exists())
        self.assertFalse((root / CONSUMER.BACKEND_ROOT).exists())


if __name__ == '__main__':
    unittest.main()
