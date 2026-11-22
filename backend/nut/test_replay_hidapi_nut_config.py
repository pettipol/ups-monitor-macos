# SPDX-License-Identifier: MIT
"""Synthetic config-selection tests; no build or NUT execution."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("replay_hidapi_nut.py")
SPEC = importlib.util.spec_from_file_location("replay_hidapi_nut_config", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ConfigSelectionTests(unittest.TestCase):
    def test_repository_test_header_has_pinned_compile_defines(self):
        header = MODULE_PATH.with_name("test_hidapi_nut_config.h")
        self.assertEqual(hashlib.sha256(header.read_bytes()).hexdigest(),
                         runner.PORTABLE_CONFIG_PIN)
        text = header.read_text(encoding="utf-8")
        for line in ("#define _DARWIN_C_SOURCE 1", "#define WITH_USB 1",
                     "#define WITH_LIBUSB_1_0 1", "#define WITH_LIBUSB_0_1 0"):
            self.assertIn(line, text)

    def test_default_selects_pinned_portable_header(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            default = Path(temp) / "test_hidapi_nut_config.h"
            content = b"synthetic portable config\n"
            default.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            with patch.object(runner, "PORTABLE_CONFIG_PIN", digest):
                selected, kind, pin = runner.select_nut_config(None, default)
            self.assertEqual((selected, kind, pin), (default, "portable-test", digest))

    def test_explicit_portable_and_legacy_pins_are_accepted(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            config = Path(temp) / "config.h"
            config.write_bytes(b"synthetic selected config\n")
            digest = hashlib.sha256(config.read_bytes()).hexdigest()
            with patch.object(runner, "PORTABLE_CONFIG_PIN", digest), \
                 patch.object(runner, "LEGACY_CONFIG_PIN", "0" * 64):
                self.assertEqual(runner.select_nut_config(config, config)[1], "portable-test")
            with patch.object(runner, "PORTABLE_CONFIG_PIN", "0" * 64), \
                 patch.object(runner, "LEGACY_CONFIG_PIN", digest):
                self.assertEqual(runner.select_nut_config(config, config)[1],
                                 "legacy-private-generated")

    def test_default_missing_or_drift_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            default = Path(temp) / "test_hidapi_nut_config.h"
            with patch.object(runner, "PORTABLE_CONFIG_PIN", "1" * 64):
                with self.assertRaisesRegex(SystemExit, "pinned input mismatch"):
                    runner.select_nut_config(None, default)
                default.write_text("drift", encoding="ascii")
                with self.assertRaisesRegex(SystemExit, "pinned input mismatch"):
                    runner.select_nut_config(None, default)

    def test_explicit_unknown_hash_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            config = Path(temp) / "config.h"
            config.write_text("unknown config", encoding="ascii")
            with patch.object(runner, "PORTABLE_CONFIG_PIN", "1" * 64), \
                 patch.object(runner, "LEGACY_CONFIG_PIN", "2" * 64):
                with self.assertRaisesRegex(SystemExit, "not one of the pinned"):
                    runner.select_nut_config(config, config)


if __name__ == "__main__":
    unittest.main()
