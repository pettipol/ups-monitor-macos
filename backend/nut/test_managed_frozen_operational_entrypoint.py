"""Inert admission fixtures: no helper or native producer is executed."""
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
from unittest.mock import patch

def load_source(name, filename):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


common = load_source('managed_bundled_operational_entrypoint', 'managed_bundled_operational_entrypoint.py')
entry = load_source('managed_frozen_operational_entrypoint', 'managed_frozen_operational_entrypoint.py')


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encode(obj): return (json.dumps(obj, sort_keys=True, separators=(',', ':')) + '\n').encode()


class Fixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / '移動 App with spaces.app' / 'Contents'
        self.root.mkdir(parents=True)
        self.entries = {}
        self.file(entry.HELPER_PATH, b'inert helper', 0o755)
        self.file(entry.MEIPASS + '/inert.dat', b'inert')
        self.file(common.NATIVE_PATH, b'inert producer', 0o755)
        pins = {}
        for name in entry.MODULES:
            raw = ('# synthetic ' + name).encode()
            self.file(common.BACKEND_ROOT + '/' + name, raw)
            pins[name] = sha(raw)
        self.manifest = {'schema_version': 1, 'profile': entry.PROFILE, 'architecture': 'arm64',
            'minimum_macos': '27.0', 'python': {'root': entry.HELPER_ROOT,
                'executable': entry.HELPER_PATH, 'sha256': self.entries[entry.HELPER_PATH]['sha256']},
            'backend': {'root': common.BACKEND_ROOT, 'module_sha256': pins},
            'native': {'path': common.NATIVE_PATH, 'name': common.NATIVE_NAME,
                'sha256': self.entries[common.NATIVE_PATH]['sha256'], 'bytes': len(b'inert producer')},
            'closure': {'path': entry.INVENTORY_PATH, 'sha256': '', 'entries': 0},
            'upstream': {'archive_sha256': 'a' * 64, 'metadata_sha256': 'b' * 64}}
        self.save()

    def file(self, name, raw, mode=0o644):
        parts = name.split('/')
        for i in range(1, len(parts)):
            parent = '/'.join(parts[:i]); path = self.root / parent
            path.mkdir(exist_ok=True); path.chmod(0o755)
            if parent.startswith((entry.HELPER_ROOT, common.BACKEND_ROOT)):
                self.entries[parent] = {'type': 'directory', 'mode': '0755'}
        path = self.root / name; path.write_bytes(raw); path.chmod(mode)
        self.entries[name] = {'type': 'file', 'mode': f'{mode:04o}', 'bytes': len(raw), 'sha256': sha(raw)}

    def save(self):
        raw = encode({'schema_version': 1, 'entries': self.entries})
        (self.root / entry.INVENTORY_PATH).write_bytes(raw)
        self.manifest['closure'].update(sha256=sha(raw), entries=len(self.entries))
        raw = encode(self.manifest); (self.root / entry.MANIFEST_PATH).write_bytes(raw); self.pin = sha(raw)

    def validate(self): return entry._validate_bundle(self.root, self.pin, check_process=False)


class FrozenAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.temp.cleanup)

    def test_valid_fixture_and_nine_module_binding(self):
        binding = self.f.validate()
        self.assertEqual(binding.python, self.f.root / entry.HELPER_PATH)
        self.assertEqual(set(binding.module_sha256), entry.MODULES)
        self.assertEqual(len(entry.MODULES), 9)

    def test_pin_profile_and_payload_mutations_rejected(self):
        with self.assertRaises(common.BundleError): entry._validate_bundle(self.f.root, '0' * 64, check_process=False)
        self.f.manifest['profile'] = common.PROFILE; self.f.save()
        with self.assertRaises(common.BundleError): self.f.validate()
        self.f.manifest['profile'] = entry.PROFILE; self.f.save()
        (self.f.root / entry.HELPER_PATH).write_bytes(b'tampered')
        with self.assertRaises(common.BundleError): self.f.validate()

    def test_extra_missing_and_cross_root_link_rejected(self):
        (self.f.root / common.BACKEND_ROOT / 'extra.py').write_text('# extra')
        with self.assertRaises(common.BundleError): self.f.validate()
        (self.f.root / common.BACKEND_ROOT / 'extra.py').unlink()
        link = entry.HELPER_ROOT + '/Contents/cross'
        target = '../../../Resources/ManagedOperationalRuntime'
        os.symlink(target, self.f.root / link)
        self.f.entries[link] = {'type': 'symlink', 'mode': '0777', 'target': target,
                                'resolved_target': common.BACKEND_ROOT}
        self.f.save()
        with self.assertRaisesRegex(common.BundleError, 'cross_root_symlink'): self.f.validate()
        (self.f.root / link).unlink(); del self.f.entries[link]; self.f.save()
        (self.f.root / entry.HELPER_PATH).unlink()
        with self.assertRaises(common.BundleError): self.f.validate()

    def test_process_check_cannot_be_satisfied_by_host_python(self):
        with patch.object(common, '_host_admitted', return_value=True):
            with self.assertRaises(common.BundleError):
                entry._validate_bundle(self.f.root, self.f.pin)

    def test_process_identity_and_each_required_flag_fail_closed(self):
        values = dict(isolated=1, no_site=1, no_user_site=1, ignore_environment=1,
                      optimize=0, hash_randomization=0)
        with patch.object(common, '_host_admitted', return_value=True), \
             patch.object(sys, 'executable', str(self.f.root / entry.HELPER_PATH)), \
             patch.object(sys, '_MEIPASS', str(self.f.root / entry.MEIPASS), create=True), \
             patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'dont_write_bytecode', True):
            with patch.object(sys, 'flags', SimpleNamespace(**values)):
                entry._validate_bundle(self.f.root, self.f.pin)
            for flag, value in values.items():
                altered = dict(values); altered[flag] = 1 - value
                with self.subTest(flag=flag), patch.object(sys, 'flags', SimpleNamespace(**altered)):
                    with self.assertRaisesRegex(common.BundleError, 'interpreter_identity'):
                        entry._validate_bundle(self.f.root, self.f.pin)
            with patch.object(sys, '_MEIPASS', str(self.f.root)):
                with self.assertRaisesRegex(common.BundleError, 'interpreter_identity'):
                    entry._validate_bundle(self.f.root, self.f.pin)
            with patch.object(sys, 'executable', str(self.f.root / common.NATIVE_PATH)):
                with self.assertRaisesRegex(common.BundleError, 'interpreter_identity'):
                    entry._validate_bundle(self.f.root, self.f.pin)

    def test_preloaded_operational_module_rejected_and_stop_retained(self):
        binding = self.f.validate()
        with patch.dict(sys.modules, {'continuous_protocol': SimpleNamespace()}):
            with self.assertRaisesRegex(common.BundleError, 'preloaded_backend'):
                common._load_backend(binding, [], validator=entry._validate_bundle, modules=entry.MODULES)
        stop = common._BootstrapStop(); stop.request(signal.SIGTERM, None)
        requests = []
        delegate = SimpleNamespace(request_stop=lambda signum, frame: requests.append(signum))
        with patch.object(signal, 'signal'):
            stop.handoff(delegate)
        self.assertEqual(requests, [signal.SIGTERM])
        self.assertFalse(stop.pending)


if __name__ == '__main__': unittest.main()
