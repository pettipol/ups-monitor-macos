#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the documented pairing gates with inert receipts and a fake validator."""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch


class PackageRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.checkout = self.root / 'checkout'
        backend = self.checkout / 'backend/nut'
        backend.mkdir(parents=True)
        # This module is only a data-fixture validator. The real validator has
        # its own full-map tests; these tests isolate the published recipe.
        self.identity = {'profile': 'first-io-v1', 'source_receipt_sha256': '1' * 64}
        self.native_map = {'drivers/fake.c': '2' * 64}
        self.runtime_map = {f'fixture_{n}.py': f'{n:064x}' for n in range(9)}
        values = {'identity': self.identity, 'native_map': self.native_map,
                  'runtime_map': self.runtime_map}
        (backend / 'fixture.json').write_text(json.dumps(values))
        (backend / 'first_io_source_stage.py').write_text(
            'import json\nfrom pathlib import Path\nfrom types import SimpleNamespace\n'
            'def validate_source_stage(stage_root, backend_root):\n'
            '    return SimpleNamespace(**json.loads((backend_root / "fixture.json").read_text()))\n')
        self.stage = self.root / 'source-stage'
        self.stage.mkdir()
        self.native = self.root / 'native'
        self.native.mkdir()
        self.candidate = self.root / 'candidate'
        self.manifest_path = self.candidate / 'stage/Contents/Resources/ManagedOperationalRuntime/frozen-runtime-bundle.json'
        self.manifest_path.parent.mkdir(parents=True)
        self.signed_pin = '3' * 64
        self.built = {
            'schema': 1, 'state': 'COMPILED_STATIC_AUDIT_ONLY',
            'reader_execution': 'NOT_RUN',
            'product': {'name': 'PRODUCT', 'mode': '0600', 'architecture': 'arm64',
                        'signature': 'ABSENT', 'bytes': 123, 'sha256': '4' * 64},
            'hidapi': {'tag': 'hidapi-0.16.0', 'commit': '750c87abb03282a237297052b84522e6bb3c0616'},
            'nut': {'revision': '73c4502191d025e35122463986a80c676e734b04'},
            'first_io_source_stage': copy.deepcopy(self.identity),
            'source_checkpoints': {'post_first_io': copy.deepcopy(self.native_map)},
        }
        self.manifest = {'backend': {'module_sha256': copy.deepcopy(self.runtime_map)},
                         'native': {'sha256': self.signed_pin}}
        self.staged = {'state': 'STAGED_FROZEN_NOT_EXECUTED',
                       'first_io_source_stage': copy.deepcopy(self.identity),
                       'module_sha256': copy.deepcopy(self.runtime_map),
                       'native_sha256': self.signed_pin}
        guide = Path(__file__).resolve().parents[2] / 'docs/REAL_PREVIEW_PACKAGE.md'
        blocks = re.findall(r"<<'PYTHON'\n(.*?)\n\s*PYTHON\n", guide.read_text(), re.S)
        self.scripts = {}
        for marker in ('first_io_package_gate', 'first_io_pairing_gate'):
            matches = [b for b in blocks if marker in b]
            self.assertEqual(len(matches), 1, f'one executable gate for {marker}')
            self.scripts[marker] = compile(textwrap.dedent(matches[0]), str(guide), 'exec')

    def write_controls(self) -> tuple[str, str]:
        native_raw = (json.dumps(self.built, sort_keys=True) + '\n').encode()
        manifest_raw = (json.dumps(self.manifest, sort_keys=True) + '\n').encode()
        (self.native / 'BUILD_RECEIPT.json').write_bytes(native_raw)
        self.manifest_path.write_bytes(manifest_raw)
        native_pin = hashlib.sha256(native_raw).hexdigest()
        manifest_pin = hashlib.sha256(manifest_raw).hexdigest()
        self.staged.setdefault('manifest_sha256', manifest_pin)
        (self.candidate / 'receipt.json').write_text(json.dumps(self.staged))
        return native_pin, manifest_pin

    def execute(self, marker: str, args: list[str]) -> str:
        output = io.StringIO()
        with patch.object(sys, 'argv', ['recipe', *map(str, args)]), redirect_stdout(output):
            exec(self.scripts[marker], {'__name__': '__main__'})
        return output.getvalue().strip()

    def native_gate(self, profile='first-io-v1', pin=None) -> str:
        recorded, _ = self.write_controls()
        return self.execute('first_io_package_gate', [self.native, recorded if pin is None else pin,
                            profile, self.stage, self.checkout])

    def pairing_gate(self, pin=None) -> str:
        recorded, manifest = self.write_controls()
        return self.execute('first_io_pairing_gate', [self.checkout, self.stage, self.native,
                            recorded if pin is None else pin, self.candidate, self.signed_pin, manifest])

    def test_native_and_pairing_positive(self) -> None:
        self.assertEqual(self.native_gate(), '4' * 64)
        self.assertEqual(self.pairing_gate(), 'FIRST_IO_PAIRING_PASS')

    def test_plain_profile_rejects_first_io_even_null_marker(self) -> None:
        for marker in (copy.deepcopy(self.identity), None):
            with self.subTest(marker=marker):
                self.built['first_io_source_stage'] = marker
                with self.assertRaisesRegex(SystemExit, 'Wrong native profile'):
                    self.native_gate('hidapi-0.16')

    def test_plain_profile_remains_admitted_without_marker(self) -> None:
        del self.built['first_io_source_stage']
        del self.built['source_checkpoints']['post_first_io']
        self.assertEqual(self.native_gate('hidapi-0.16'), '4' * 64)

    def test_plain_profile_rejects_postmap_without_identity_marker(self) -> None:
        del self.built['first_io_source_stage']
        with self.assertRaisesRegex(SystemExit, 'Wrong native profile'):
            self.native_gate('hidapi-0.16')

    def test_native_gate_rejects_wrong_stage_and_postmap(self) -> None:
        for key in ('first_io_source_stage', 'source_checkpoints'):
            with self.subTest(key=key):
                before = copy.deepcopy(self.built)
                self.built[key] = {}
                with self.assertRaisesRegex(SystemExit, 'does not match'):
                    self.native_gate()
                self.built = before

    def test_pairing_rejects_cross_profile_or_changed_source_identity(self) -> None:
        for receipt in (self.built, self.staged):
            with self.subTest(receipt='native' if receipt is self.built else 'runtime'):
                before = receipt['first_io_source_stage']
                receipt['first_io_source_stage'] = {'profile': 'other'}
                with self.assertRaisesRegex(SystemExit, 'pairing mismatch'):
                    self.pairing_gate()
                receipt['first_io_source_stage'] = before

    def test_pairing_rejects_runtime_map_native_pin_and_manifest_pin(self) -> None:
        for key, changed in (('module_sha256', {}), ('native_sha256', '5' * 64),
                             ('manifest_sha256', '6' * 64)):
            with self.subTest(key=key):
                before = copy.deepcopy(self.staged)
                self.staged[key] = changed
                with self.assertRaisesRegex(SystemExit, 'pairing mismatch'):
                    self.pairing_gate()
                self.staged = before

    def test_actual_manifest_modules_and_producer_are_compared(self) -> None:
        for key in ('backend', 'native'):
            with self.subTest(key=key):
                before = copy.deepcopy(self.manifest)
                self.manifest[key] = {}
                self.staged.pop('manifest_sha256', None)
                with self.assertRaisesRegex(SystemExit, 'pairing mismatch'):
                    self.pairing_gate()
                self.manifest = before
                self.staged.pop('manifest_sha256', None)

    def test_recorded_native_receipt_digest_required(self) -> None:
        for gate in (self.native_gate, self.pairing_gate):
            for digest in ('', '0' * 64):
                with self.subTest(gate=gate.__name__, digest=digest):
                    with self.assertRaises(SystemExit):
                        gate(pin=digest)


if __name__ == '__main__':
    unittest.main()
