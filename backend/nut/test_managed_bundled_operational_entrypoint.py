"""Synthetic bundle files and fake lifecycle only; no acquired Python or producer runs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

PATH = Path(__file__).with_name('managed_bundled_operational_entrypoint.py')
SPEC = importlib.util.spec_from_file_location('bundled_entrypoint_under_test', PATH)
assert SPEC and SPEC.loader
entry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = entry
exec(compile(PATH.read_bytes(), str(PATH), 'exec'), entry.__dict__)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


class Fixture:
    def __init__(self, *, code=False):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / '移動 App with spaces.app' / 'Contents'
        self.root.mkdir(parents=True, mode=0o755)
        self.entries = {}
        self.modules = {}
        self.file(entry.PYTHON_PATH, b'inert python; never executed', 0o755)
        self.file(entry.NATIVE_PATH, b'inert native; never executed', 0o755)
        self.file(entry.PYTHON_ROOT + '/install/lib/python3.15/os.py', b'# inert stdlib\n')
        for name in entry.MODULES:
            content = ('# synthetic ' + name + '\n').encode()
            if code and name == 'managed_operational_entrypoint.py':
                content = b"STOP_REQUESTED=False\ndef request_stop(s,f):\n global STOP_REQUESTED\n STOP_REQUESTED=True\ndef _quiet_workers(): return True\ndef retain(): raise AssertionError('unexpected retain')\ndef fixed_argv(native): return (str(native),'fixed')\ndef serve(*args): return 17\n"
            if code and name == 'app_controlled_operational.py':
                content = b'class FixedOperationalProfile:\n def __init__(self,argv,pin): self.argv,self.pin=argv,pin\n'
            self.file(entry.BACKEND_ROOT + '/' + name, content)
            self.modules[name] = sha(content)
        self.manifest = {'schema_version': 1, 'profile': entry.PROFILE, 'architecture': 'arm64',
            'minimum_macos': '27.0',
            'python': {'root': entry.PYTHON_ROOT, 'executable': entry.PYTHON_PATH,
                       'sha256': self.entries[entry.PYTHON_PATH]['sha256']},
            'backend': {'root': entry.BACKEND_ROOT, 'entrypoint': entry.ENTRY_PATH, 'module_sha256': self.modules},
            'native': {'path': entry.NATIVE_PATH, 'name': entry.NATIVE_NAME,
                       'sha256': self.entries[entry.NATIVE_PATH]['sha256'],
                       'bytes': self.entries[entry.NATIVE_PATH]['bytes']},
            'closure': {'path': entry.INVENTORY_PATH, 'sha256': '', 'entries': 0},
            'upstream': {'archive_sha256': 'a' * 64, 'metadata_sha256': 'b' * 64}}
        self.save()

    def close(self): self.temp.cleanup()

    def parents(self, name):
        parts = name.split('/')
        for count in range(1, len(parts)):
            relative = '/'.join(parts[:count])
            path = self.root / relative
            path.mkdir(exist_ok=True)
            path.chmod(0o755)
            if relative.startswith((entry.PYTHON_ROOT, entry.BACKEND_ROOT)):
                self.entries[relative] = {'type': 'directory', 'mode': '0755'}

    def file(self, name, content, mode=0o644):
        self.parents(name)
        path = self.root / name
        path.write_bytes(content)
        path.chmod(mode)
        self.entries[name] = {'type': 'file', 'mode': f'{mode:04o}', 'bytes': len(content), 'sha256': sha(content)}

    def link(self, name, target, resolved):
        self.parents(name)
        path = self.root / name
        os.symlink(target, path)
        os.lchmod(path, 0o777)
        self.entries[name] = {'type': 'symlink', 'mode': '0777', 'target': target, 'resolved_target': resolved}

    def save(self):
        inventory = encoded({'schema_version': 1, 'entries': self.entries})
        (self.root / entry.INVENTORY_PATH).write_bytes(inventory)
        (self.root / entry.INVENTORY_PATH).chmod(0o644)
        self.manifest['closure'].update(sha256=sha(inventory), entries=len(self.entries))
        raw = encoded(self.manifest)
        (self.root / entry.MANIFEST_PATH).write_bytes(raw)
        (self.root / entry.MANIFEST_PATH).chmod(0o644)
        self.pin = sha(raw)

    def validate(self, *, process=False):
        return entry._validate_bundle(self.root, self.pin, check_process=process)


class BundleAdmissionTests(unittest.TestCase):
    def fixture(self, **options):
        fixture = Fixture(**options)
        self.addCleanup(fixture.close)
        return fixture

    def test_valid_full_closure_and_unicode_outer_app_need_no_process(self):
        fixture = self.fixture()
        with patch.object(entry, '_load_backend', side_effect=AssertionError('no imports')):
            binding = fixture.validate()
        self.assertEqual(binding.python, fixture.root / entry.PYTHON_PATH)
        self.assertEqual(binding.native, fixture.root / entry.NATIVE_PATH)
        self.assertEqual(set(binding.module_sha256), entry.MODULES)

    def test_wrong_trusted_root_is_rejected_before_inventory_or_backend(self):
        fixture = self.fixture()
        with self.assertRaisesRegex(entry.BundleError, 'manifest_pin'):
            entry._validate_bundle(fixture.root, '0' * 64, check_process=False)

    def test_schema_boolean_float_duplicate_and_extra_fields_fail_closed(self):
        for fault in ('boolean', 'float', 'duplicate', 'extra', 'legacy'):
            fixture = self.fixture()
            manifest = fixture.manifest
            if fault == 'boolean': manifest['schema_version'] = True
            elif fault == 'float': manifest['schema_version'] = 1.0
            elif fault == 'extra': manifest['python_path'] = '/unadmitted/python'
            elif fault == 'legacy': manifest['schema_version'] = 2
            fixture.save()
            if fault == 'duplicate':
                path = fixture.root / entry.MANIFEST_PATH
                raw = path.read_bytes().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
                path.write_bytes(raw)
                fixture.pin = sha(raw)
            with self.subTest(fault=fault), self.assertRaises(entry.BundleError): fixture.validate()

    def test_missing_changed_extra_and_writable_payload_are_rejected(self):
        for fault in ('missing', 'changed', 'extra', 'mode'):
            fixture = self.fixture()
            path = fixture.root / entry.BACKEND_ROOT / 'process_deadline.py'
            if fault == 'missing': path.unlink()
            elif fault == 'changed': path.write_bytes(b'changed')
            elif fault == 'extra': (path.parent / 'unadmitted.py').write_bytes(b'extra')
            else: path.chmod(0o664)
            with self.subTest(fault=fault), self.assertRaises(entry.BundleError): fixture.validate()

    def test_fixed_paths_module_set_and_native_identity_are_not_ui_overrides(self):
        for fault in ('python', 'native', 'module', 'count'):
            fixture = self.fixture()
            if fault == 'python': fixture.manifest['python']['executable'] = '/tmp/python'
            elif fault == 'native': fixture.manifest['native']['path'] = 'MacOS/other'
            elif fault == 'module': fixture.manifest['backend']['module_sha256']['extra.py'] = 'a' * 64
            fixture.save()
            if fault == 'count':
                fixture.manifest['closure']['entries'] = True
                raw = encoded(fixture.manifest)
                (fixture.root / entry.MANIFEST_PATH).write_bytes(raw)
                fixture.pin = sha(raw)
            with self.subTest(fault=fault), self.assertRaises(entry.BundleError): fixture.validate()

    def test_declared_relative_symlink_is_accepted(self):
        fixture = self.fixture()
        fixture.link(entry.PYTHON_ROOT + '/install/bin/python3', 'python3.15', entry.PYTHON_PATH)
        fixture.save()
        fixture.validate()

    def test_external_missing_and_cyclic_links_are_rejected(self):
        for fault in ('external', 'missing', 'cycle'):
            fixture = self.fixture()
            name = entry.PYTHON_ROOT + '/install/bin/alias'
            if fault == 'cycle':
                fixture.link(name, 'other', entry.PYTHON_PATH)
                fixture.link(name.rsplit('/', 1)[0] + '/other', 'alias', entry.PYTHON_PATH)
            else:
                fixture.link(name, '/outside' if fault == 'external' else 'missing', entry.PYTHON_PATH)
            fixture.save()
            with self.subTest(fault=fault), self.assertRaises(entry.BundleError): fixture.validate()

    def test_case_alias_unicode_and_parent_symlink_fail_closed(self):
        for fault in ('case', 'unicode', 'parent'):
            fixture = self.fixture()
            if fault == 'parent':
                directory = fixture.root / entry.PYTHON_ROOT / 'install/bin'
                destination = directory.with_name('other-bin')
                directory.rename(destination)
                os.symlink('other-bin', directory)
            else:
                name = entry.PYTHON_PATH.upper() if fault == 'case' else entry.PYTHON_ROOT + '/caf\u00e9.py'
                fixture.entries[name] = dict(fixture.entries[entry.PYTHON_PATH])
                fixture.save()
            with self.subTest(fault=fault), self.assertRaises(entry.BundleError): fixture.validate()

    def test_runtime_process_identity_and_isolation_remain_mandatory(self):
        fixture = self.fixture()
        with patch.object(entry, '_host_admitted', return_value=True):
            with self.assertRaisesRegex(entry.BundleError, 'interpreter_identity'): fixture.validate(process=True)
            flags = SimpleNamespace(isolated=False, no_site=True, optimize=0)
            with patch.object(entry.sys, 'executable', str(fixture.root / entry.PYTHON_PATH)), \
                    patch.object(entry.sys, 'flags', flags), patch.object(entry.sys, 'dont_write_bytecode', True):
                with self.assertRaisesRegex(entry.BundleError, 'interpreter_identity'): fixture.validate(process=True)

    def test_raw_backend_loader_uses_verified_buffers_after_closure(self):
        fixture = self.fixture(code=True)
        binding = fixture.validate()
        saved = {name[:-3]: sys.modules.pop(name[:-3]) for name in entry.MODULES if name[:-3] in sys.modules}
        self.addCleanup(lambda: ([(sys.modules.pop(name[:-3], None)) for name in entry.MODULES], sys.modules.update(saved)))
        flags = SimpleNamespace(isolated=True, no_site=True, optimize=0)
        with patch.object(entry, '_host_admitted', return_value=True), \
                patch.object(entry.sys, 'executable', str(binding.python)), patch.object(entry.sys, 'flags', flags), \
                patch.object(entry.sys, 'dont_write_bytecode', True):
            owner = []
            legacy, adapter = entry._load_backend(binding, owner)
        self.assertIs(owner[0], legacy)
        self.assertTrue(hasattr(adapter, 'FixedOperationalProfile'))
        self.assertFalse(legacy.STOP_REQUESTED)

    def test_preloaded_backend_is_rejected_before_any_module_exec(self):
        fixture = self.fixture()
        binding = fixture.validate()
        with patch.dict(sys.modules, {'process_deadline': SimpleNamespace()}):
            with self.assertRaisesRegex(entry.BundleError, 'preloaded_backend'):
                entry._load_backend(binding, [])

    def test_regular_hardlink_alias_is_not_an_admitted_symlink(self):
        fixture = self.fixture()
        path = fixture.root / entry.PYTHON_PATH
        alias = fixture.root.parent / 'outside-hardlink'
        os.link(path, alias)
        with self.assertRaises(entry.BundleError): fixture.validate()


class BootstrapLifecycleTests(unittest.TestCase):
    def test_latch_hands_off_to_the_legacy_stop_state_once(self):
        legacy = SimpleNamespace(STOP_REQUESTED=False)
        def request(_signal, _frame): legacy.STOP_REQUESTED = True
        legacy.request_stop = request
        latch = entry._BootstrapStop()
        latch.request(signal.SIGINT, None)
        with patch.object(entry.signal, 'signal'): latch.handoff(legacy)
        self.assertTrue(legacy.STOP_REQUESTED)
        self.assertFalse(latch.pending)
        self.assertIs(latch.delegate, legacy)
        latch.request(signal.SIGTERM, None)
        self.assertTrue(legacy.STOP_REQUESTED)

    def test_main_reuses_legacy_serve_and_stop_during_admission_never_starts_producer(self):
        for phase in ('normal', 'before', 'validation', 'loading', 'transfer', 'profile'):
            handlers = {}
            legacy = SimpleNamespace(STOP_REQUESTED=False, serve=Mock(return_value=17),
                fixed_argv=Mock(return_value=('fixed-native', 'fixed-args')),
                _quiet_workers=lambda: True, retain=Mock())
            def request(_signal, _frame): legacy.STOP_REQUESTED = True
            legacy.request_stop = request
            binding = SimpleNamespace(native=Path('/synthetic/native'), native_sha256='a' * 64)
            def register(signum, callback):
                old = handlers.get(signum)
                handlers[signum] = callback
                if phase == 'before' and signum == signal.SIGINT and old is None: callback(signum, None)
                if phase == 'transfer' and callback is legacy.request_stop and old is not None: old(signum, None)
            def validate(_pin):
                if phase == 'validation': handlers[signal.SIGTERM](signal.SIGTERM, None)
                return binding
            def profile(*_args):
                if phase == 'profile': legacy.request_stop(signal.SIGTERM, None)
                return 'admitted-profile'
            adapter = SimpleNamespace(FixedOperationalProfile=Mock(side_effect=profile))
            def load(_binding, owner):
                owner.append(legacy)
                if phase == 'loading': handlers[signal.SIGINT](signal.SIGINT, None)
                return legacy, adapter
            arguments = ['entry', '--workspace', '/synthetic/workspace', '--launch-id',
                         str(uuid.uuid4()), '--runtime-manifest-sha256', 'b' * 64]
            with self.subTest(phase=phase), patch.object(entry.sys, 'argv', arguments), \
                    patch.object(entry.signal, 'signal', side_effect=register), \
                    patch.object(entry, 'validate_runtime', side_effect=validate) as admission, \
                    patch.object(entry, '_load_backend', side_effect=load), patch.object(entry, '_emit_rejection'):
                result = entry.main()
            admission.assert_called_once_with('b' * 64)
            if phase == 'normal':
                self.assertEqual(result, 17)
                legacy.serve.assert_called_once_with(adapter, 'admitted-profile', Path('/synthetic/workspace'), arguments[4])
                adapter.FixedOperationalProfile.assert_called_once_with(('fixed-native', 'fixed-args'), 'a' * 64)
            else:
                self.assertEqual(result, 2)
                self.assertTrue(legacy.STOP_REQUESTED)
                legacy.serve.assert_not_called()
            legacy.retain.assert_not_called()

    def test_invalid_root_or_extra_cli_argument_imports_no_backend_and_has_no_fallback(self):
        base = ['entry', '--workspace', '/synthetic/workspace', '--launch-id', str(uuid.uuid4()),
                '--runtime-manifest-sha256', 'b' * 64]
        for argv in (base, base + ['--native', '/other']):
            with patch.object(entry.sys, 'argv', argv), patch.object(entry.signal, 'signal'), \
                    patch.object(entry, 'validate_runtime', side_effect=entry.BundleError('manifest_pin')), \
                    patch.object(entry, '_load_backend') as loader, patch.object(entry, '_emit_rejection'):
                self.assertEqual(entry.main(), 2)
            loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
