# SPDX-License-Identifier: MIT
"""Synthetic safety tests for the pinned NUT source extractor."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("extract_hidapi_nut.py")
SPEC = importlib.util.spec_from_file_location("extract_hidapi_nut", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


NOTICE = """/* upstream NUT source notice
 * This program is free software; you can redistribute it under the GNU General Public License.
 * either version 2 of the License, or (at your option) any later version.
 */"""
SYNTHETIC_DRIVER = NOTICE + """
#define MLINK_STOP_BYTE 0xF7
#define MLINK_INIT_BYTE 0xFD
#define MLINK_NEXT_BYTE 0xFE
static const char *const hidapi_forbidden_options[] = {
 "vendorid", NULL
};
static void microlink_hidapi_finish(void) { return; }
static void microlink_hidapi_finish(void) { return; }
"""


class ExtractHidapiNutTests(unittest.TestCase):
    def _inputs(self, root: Path, driver: bytes = b"synthetic driver\n") -> dict[str, str]:
        values = {
            "configure.ac": b"configure\n",
            "drivers/Makefile.am": b"makefile\n",
            "drivers/apcmicrolink.c": driver,
            "drivers/main.c": b"main\n",
            "drivers/apcmicrolink-usb.h": b"usb header\n",
            "drivers/apcmicrolink.h": b"driver header\n",
            "drivers/nut-guarded-policy.h": b"policy header\n",
        }
        for relative, data in values.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {relative: hashlib.sha256(data).hexdigest() for relative, data in values.items()}

    def test_ambiguous_function_marker_rejected(self):
        with self.assertRaisesRegex(extractor.ExtractError, "missing or ambiguous"):
            extractor.generate(SYNTHETIC_DRIVER)

    def test_descriptor_if_else_extraction_uses_next_function_boundary(self):
        source = """static int microlink_send_descriptor_write(const char *path, const unsigned char *payload,
 size_t payload_len);
static int microlink_send_descriptor_write(const char *path, const unsigned char *payload,
 size_t payload_len)
{
#if A
 if (payload_len) {
#else
 if (!payload_len) {
#endif
  return 1;
 }
 return 0;
}
static int microlink_send_descriptor_mask_value(const char *path, uint64_t mask)
{ return 0; }
"""
        extracted = extractor._descriptor_write(source)
        self.assertTrue(extracted.endswith("}"))
        self.assertIn("#if A", extracted)
        self.assertIn("#else", extracted)
        self.assertNotIn("microlink_send_descriptor_mask_value", extracted)

    def test_gpl_notice_kept_verbatim(self):
        source = NOTICE + "\nint x;\n"
        self.assertEqual(extractor.extract_notice(source), NOTICE)

    def test_missing_source_rejected_before_output(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp) / "missing-source"
            root.mkdir(mode=0o700)
            output = Path(tmp) / "result"
            with self.assertRaisesRegex(extractor.ExtractError, "missing or symlinked"):
                extractor.stage_candidate(root, output)
            self.assertFalse(os.path.lexists(output))

    def test_drift_rejected_before_output(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp) / "source"
            root.mkdir(mode=0o700)
            pins = self._inputs(root)
            (root / "drivers/apcmicrolink.c").write_bytes(b"changed after pin\n")
            output = Path(tmp) / "result"
            with patch.object(extractor, "PINNED_INPUTS", pins):
                with self.assertRaisesRegex(extractor.ExtractError, "SHA-256 mismatch"):
                    extractor.stage_candidate(root, output)
            self.assertFalse(os.path.lexists(output))

    def test_output_existing_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp) / "source"
            root.mkdir(mode=0o700)
            output = Path(tmp) / "result"
            output.mkdir(mode=0o700)
            sentinel = output / "sentinel"
            sentinel.write_text("keep", encoding="ascii")
            with patch.object(extractor, "_read_pinned_sources", return_value={
                extractor.DRIVER: NOTICE.encode("utf-8")
            }), patch.object(extractor, "generate", return_value="generated\n"):
                with self.assertRaisesRegex(extractor.ExtractError, "already exists"):
                    extractor.stage_candidate(root, output)
            self.assertEqual(sentinel.read_text(encoding="ascii"), "keep")

    def test_output_overlapping_product_rejected_before_mkdir(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp) / "source"
            root.mkdir(mode=0o700)
            target = extractor.Path(__file__).resolve().parents[2] / "docs" / ".extractor-synthetic-reject"
            with patch.object(extractor, "_read_pinned_sources", return_value={
                extractor.DRIVER: NOTICE.encode("utf-8")
            }), patch.object(extractor, "generate", return_value="generated\n"):
                with self.assertRaisesRegex(extractor.ExtractError, "overlaps product"):
                    extractor.stage_candidate(root, target)
            self.assertFalse(os.path.lexists(target))

    def test_case_alias_checkout_rejected_on_case_insensitive_volume(self):
        product = Path(__file__).resolve().parents[2]
        alias = Path(str(product).swapcase())
        if not alias.exists() or not os.path.samefile(product, alias):
            self.skipTest("checkout volume does not resolve a case-variant alias")
        target = alias / "docs" / ".extractor-case-alias-reject"
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            source = Path(tmp) / "source"
            source.mkdir(mode=0o700)
            with patch.object(extractor, "_read_pinned_sources", return_value={
                extractor.DRIVER: NOTICE.encode("utf-8")
            }), patch.object(extractor, "generate", return_value="generated\n"):
                with self.assertRaisesRegex(extractor.ExtractError, "overlaps product"):
                    extractor.stage_candidate(source, target)
        self.assertFalse(os.path.lexists(target))

    def test_case_alias_product_cannot_be_nut_source_on_case_insensitive_volume(self):
        product = Path(__file__).resolve().parents[2]
        alias = Path(str(product).swapcase())
        if not alias.exists() or not os.path.samefile(product, alias):
            self.skipTest("checkout volume does not resolve a case-variant alias")
        with self.assertRaisesRegex(extractor.ExtractError, "outside the product repository"):
            extractor._read_pinned_sources(alias, extractor.PINNED_INPUTS)

    def test_case_alias_source_root_rejected_on_case_insensitive_volume(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp)
            source = root / "MiXeD" / "SoUrCe"
            source.mkdir(parents=True, mode=0o700)
            alias_root = Path(str(root).swapcase())
            if not alias_root.exists() or not os.path.samefile(root, alias_root):
                self.skipTest("temporary volume does not resolve a case-variant alias")
            alias_source = alias_root / "mixed" / "source"
            target = alias_source / "nested-output"
            with patch.object(extractor, "_read_pinned_sources", return_value={
                extractor.DRIVER: NOTICE.encode("utf-8")
            }), patch.object(extractor, "generate", return_value="generated\n"):
                with self.assertRaisesRegex(extractor.ExtractError, "overlaps product repository or pinned input"):
                    extractor.stage_candidate(alias_source, target)
            self.assertFalse(os.path.lexists(target))

    def test_case_alias_parent_chain_allows_external_new_output(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp)
            source = root / "input" / "nut"
            source.mkdir(parents=True, mode=0o700)
            parent = root / "External" / "Nested" / "Parent"
            parent.mkdir(parents=True, mode=0o700)
            alias_parent = Path(str(parent).swapcase())
            if not alias_parent.exists() or not os.path.samefile(parent, alias_parent):
                self.skipTest("temporary volume does not resolve a case-variant parent alias")
            output = alias_parent / "new-bundle"
            with patch.object(extractor, "_read_pinned_sources", return_value={
                extractor.DRIVER: NOTICE.encode("utf-8")
            }), patch.object(extractor, "generate", return_value="generated\n"):
                extractor.stage_candidate(source, output)
            self.assertTrue((output / extractor.GENERATED).is_file())
            self.assertTrue((output / extractor.MANIFEST).is_file())

    def test_symlink_output_component_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir(mode=0o700)
            real_parent = root / "real-parent"
            real_parent.mkdir(mode=0o700)
            alias_parent = root / "alias-parent"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            target = alias_parent / "new-output"
            with patch.object(extractor, "_read_pinned_sources", return_value={
                extractor.DRIVER: NOTICE.encode("utf-8")
            }), patch.object(extractor, "generate", return_value="generated\n"):
                with self.assertRaisesRegex(extractor.ExtractError, "contains a symlink"):
                    extractor.stage_candidate(source, target)
            self.assertFalse(os.path.lexists(real_parent / "new-output"))

    def test_cli_has_no_pin_override_argument(self):
        with self.assertRaises(SystemExit) as raised:
            extractor.main(["--nut-source", "/tmp/source", "--output-dir", "/tmp/output",
                            "--pins", "/tmp/pins.json"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
