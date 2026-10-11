# SPDX-License-Identifier: MIT
"""Synthetic safety tests for the extract-only owner-retention exporter."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("extract_usb_owner_retention.py")
SPEC = importlib.util.spec_from_file_location("usb_owner_extract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


class ExporterSafetyTests(unittest.TestCase):
    def synthetic_source(self, root: Path) -> None:
        drivers = root / "drivers"
        drivers.mkdir(parents=True)
        for relative in extractor.PINNED_HASHES:
            (root / relative).write_text("synthetic mismatch\n", encoding="utf-8")

    def test_pin_mismatch_fails_before_scratch_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "candidate"
            source.mkdir()
            self.synthetic_source(source)
            scratch = base / "new-output"
            with self.assertRaisesRegex(extractor.ReplayError, "SHA-256 mismatch"):
                extractor.extract(source, scratch)
            self.assertFalse(scratch.exists())

    def test_source_repository_and_symlink_fences(self) -> None:
        product = MODULE_PATH.resolve().parents[2]
        with self.assertRaises(extractor.ReplayError):
            extractor.read_source(product)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "real-source"
            target.mkdir()
            self.synthetic_source(target)
            linked_root = base / "source-link"
            linked_root.symlink_to(target, target_is_directory=True)
            with self.assertRaises(extractor.ReplayError):
                extractor.read_source(linked_root)

            linked_drivers_root = base / "drivers-link-source"
            linked_drivers_root.mkdir()
            (linked_drivers_root / "drivers").symlink_to(
                target / "drivers", target_is_directory=True
            )
            with self.assertRaisesRegex(extractor.ReplayError, "drivers directory"):
                extractor.read_source(linked_drivers_root)

            file_root = base / "file-link-source"
            file_root.mkdir()
            drivers = file_root / "drivers"
            drivers.mkdir()
            victim = base / "victim.c"
            victim.write_text("synthetic", encoding="utf-8")
            (drivers / "apcmicrolink-usb.c").symlink_to(victim)
            with self.assertRaisesRegex(extractor.ReplayError, "symlinked"):
                extractor.read_source(file_root)

    def test_scratch_rejects_overlap_existing_and_dangling_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            with self.assertRaisesRegex(extractor.ReplayError, "overlaps"):
                extractor.validate_scratch(source / "nested", source)
            existing = base / "existing"
            existing.mkdir()
            with self.assertRaises(extractor.ReplayError):
                extractor.validate_scratch(existing, source)
            dangling = base / "dangling"
            dangling.symlink_to(base / "missing", target_is_directory=True)
            with self.assertRaises(extractor.ReplayError):
                extractor.validate_scratch(dangling, source)

            product = MODULE_PATH.resolve().parents[2]
            product_scratch = product / "backend" / "nut" / ".owner-retention-test-scratch"
            self.assertFalse(product_scratch.exists())
            with self.assertRaisesRegex(extractor.ReplayError, "overlaps"):
                extractor.validate_scratch(product_scratch, source)

    def test_headers_and_exact_function_body_are_preserved(self) -> None:
        usb_header = "/* USB copyright and GPL terms */\n"
        backend_header = "/* Backend copyright and GPL terms */\n"
        usb = usb_header + '#include "config.h"\nint usb(void) { return 1; }\n'
        backend = backend_header + '#include "config.h"\nint backend(void) { return 2; }\n'
        header = extractor.compose_headers(usb, backend)
        self.assertTrue(header.startswith("/* SPDX-License-Identifier: GPL-2.0-or-later */\n"))
        self.assertIn(usb_header.rstrip(), header)
        self.assertIn(backend_header.rstrip(), header)
        self.assertLess(header.index(usb_header.rstrip()), header.index(backend_header.rstrip()))

        body = 'int exact(void) { const char *s = "}"; /* { */ return s[0]; }'
        self.assertEqual(extractor.exact_function("prefix\n" + body + "\nsuffix", "int exact(void)"), body)

    def test_extract_writes_self_contained_fixture_and_real_manifest(self) -> None:
        fixture = MODULE_PATH.with_name(extractor.FIXTURE).read_bytes()
        self.assertIn(b"SPDX-License-Identifier: GPL-2.0-or-later", fixture[:160])
        self.assertIn(b'#include "usb_owner_retention_generated.c"', fixture)
        module_text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("subprocess", module_text)
        self.assertNotIn('"cc"', module_text)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "candidate"
            (source / "drivers").mkdir(parents=True)
            source_bytes = {
                relative: (
                    b"/* USB header */\n#include \"config.h\"\n"
                    if relative == extractor.USB_FILE else
                    b"/* backend header */\n#include \"config.h\"\n"
                    if relative == extractor.BACKEND_FILE else
                    ("synthetic " + relative + "\n").encode("utf-8")
                )
                for relative in extractor.PINNED_HASHES
            }
            for relative, data in source_bytes.items():
                (source / relative).write_bytes(data)
            hashes = {
                relative: hashlib.sha256(data).hexdigest()
                for relative, data in source_bytes.items()
            }
            synthetic_fixture = b"/* SPDX-License-Identifier: GPL-2.0-or-later */\nfixture\n"
            fixture_hash = hashlib.sha256(synthetic_fixture).hexdigest()
            generated = "/* synthetic generated C */\nint replay_fixture;\n"
            scratch = base / "output"

            with (
                patch.object(extractor, "PINNED_HASHES", hashes),
                patch.object(extractor, "generate", return_value=(generated, ["int replay_fixture;"])),
                patch.object(extractor, "validate_fixture", return_value=(synthetic_fixture, fixture_hash)),
            ):
                output = extractor.extract(source, scratch)

            generated_bytes = (output / extractor.GENERATED).read_bytes()
            copied_fixture = (output / extractor.FIXTURE).read_bytes()
            manifest_bytes = (output / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            self.assertEqual(copied_fixture, synthetic_fixture)
            self.assertEqual(manifest["fixture_sha256"], hashlib.sha256(copied_fixture).hexdigest())
            self.assertEqual(manifest["generated_sha256"], hashlib.sha256(generated_bytes).hexdigest())
            self.assertEqual(manifest["status"], "EXTRACTED_NOT_RUN")
            self.assertEqual(manifest["integration_cases_expected_not_run"], list(extractor.SCENARIOS))
            self.assertEqual(set(path.name for path in output.iterdir()), {
                extractor.GENERATED, extractor.FIXTURE, "manifest.json",
            })
            self.assertNotIn(str(base), manifest_bytes.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
