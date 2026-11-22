# SPDX-License-Identifier: MIT
"""Pure-Python safety tests for the guarded reopen/stop source extractor."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch


MODULE_PATH = Path(__file__).with_name("extract_guarded_reopen_stop.py")
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("guarded_reopen_extract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)

EXPECTED_DRIVER_CONTROL_SHA256 = "efdad6737c377931e5130f00d9e1257091584670d149d49015d06e2854fa14a5"


class GuardedReopenExtractorTests(unittest.TestCase):
    @staticmethod
    def synthetic_generator_inputs() -> tuple[str, str]:
        async_signatures = {
            "static int async_pending_get_locked(void)",
            "static int microlink_usb_async_owner_exists(void)",
            "static int microlink_usb_async_pending(void)",
            "int microlink_usb_guard_begin(long seconds)",
            "int microlink_usb_guard_expired(void)",
        }
        async_region = [
            "#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)",
            "/* Always-outstanding async interrupt-IN listener",
        ]
        usb_parts = [
            "#define MLINK_USB_REPORT_PAYLOAD_LEN 8U\n",
            "#define MLINK_USB_WRITE_TIMEOUT_MS 50U\n",
            "#define MLINK_USB_ASYNC_QUEUE_LEN 4U\n",
        ]
        for signature in extractor.owner.USB_FUNCTIONS:
            if signature in async_signatures:
                async_region.append(signature + " { return 0; }")
            elif signature == "int microlink_usb_open(void)":
                usb_parts.append(
                    "int microlink_usb_open(void) { "
                    "if (microlink_usb_async_owner_exists()) return 0; "
                    "USBNewRegexMatcher(); "
                    "int async_ret = microlink_usb_async_start(); "
                    "if (async_ret <= 0) return 0; "
                    "if (async_ret < 0) return 0; "
                    "falling back to per-call; return 0; }"
                )
            elif signature == "int microlink_usb_reset_and_reopen(void)":
                usb_parts.append(
                    "int microlink_usb_reset_and_reopen(void) { "
                    "int async_ret = microlink_usb_async_start(); "
                    "if (async_ret <= 0) return 0; "
                    "if (async_ret < 0) return 0; "
                    "falling back to per-call; microlink_usb_async_stop(); "
                    "if (!microlink_usb_async_stop()) return 0; "
                    "comm_driver->close_dev(); return 0; }"
                )
            elif signature == "void microlink_usb_flush_io(void)":
                usb_parts.append(
                    "void microlink_usb_flush_io(void) { "
                    "if (microlink_usb_async_pending()) return; "
                    "if (microlink_usb_async_owner_exists()) return; "
                    "comm_driver->get_interrupt(); }"
                )
            elif signature == "int microlink_usb_get_char(unsigned char *ch, long d_usec)":
                continue
            else:
                usb_parts.append(signature + " { return 0; }")
        async_region.extend(("#else", "static int microlink_usb_async_owner_exists(void) { return 0; }"))
        usb_parts.append("\n".join(async_region))
        usb_parts.append(
            "/* Mirrors ser_get_char()'s contract, same as the synchronous version above: */\n"
            "int microlink_usb_get_char(unsigned char *ch, long d_usec) { "
            "if (microlink_usb_async_owner_exists()) return 0; "
            "return microlink_usb_get_char_sync(ch, d_usec); }\n"
            "#else /* !(WITH_LIBUSB_1_0 && HAVE_PTHREAD) */"
        )
        usb_parts.append(extractor.STOP_HELPER + " { return 0; }")
        usb = "\n".join(usb_parts)
        backend = "\n".join((
            "static libusb_context\t*nut_usb_ctx = NULL;",
            "static int nut_libusb_guarded_monitor(void)",
            "static void nut_libusb_cleanup_atexit(void) { return; }",
            "void nut_libusb_context_hold(void) { return; }",
            "void nut_libusb_context_release(void) { return; }",
        ))
        return usb, backend

    def synthetic_tree(self, root: Path, *, usb_suffix: str = "base") -> dict[str, bytes]:
        (root / "drivers").mkdir(parents=True)
        contents: dict[str, bytes] = {}
        for relative in extractor.SOURCE_FILES:
            if relative == extractor.owner.USB_FILE:
                data = (
                    b"/* synthetic USB notice */\n#include \"config.h\"\n"
                    + f"/* {usb_suffix} */\n".encode("ascii")
                )
            elif relative == extractor.owner.BACKEND_FILE:
                data = b"/* synthetic backend notice */\n#include \"config.h\"\n"
            else:
                data = ("synthetic source: " + relative + "\n").encode("utf-8")
            contents[relative] = data
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return contents

    @staticmethod
    def hashes(contents: dict[str, bytes]) -> dict[str, str]:
        return {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}

    def test_base7_driver_control_pin_is_current_in_both_profiles(self) -> None:
        driver = extractor.owner.DRIVER_CONTROL
        self.assertEqual(extractor.BASELINE_HASHES[driver], EXPECTED_DRIVER_CONTROL_SHA256)
        self.assertEqual(extractor.CANDIDATE_HASHES[driver], EXPECTED_DRIVER_CONTROL_SHA256)

    def test_source_rejections_happen_before_scratch_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / "base"
            self.synthetic_tree(base)
            driver = extractor.owner.DRIVER_CONTROL

            for kind in ("mismatch", "missing", "symlink"):
                with self.subTest(kind=kind):
                    candidate = root / kind
                    candidate_data = self.synthetic_tree(candidate)
                    expected_candidate = self.hashes(candidate_data)
                    if kind == "mismatch":
                        expected_candidate[driver] = "0" * 64
                        error = "SHA-256 mismatch"
                    elif kind == "missing":
                        (candidate / driver).unlink()
                        error = "missing or symlinked"
                    else:
                        victim = root / "victim.c"
                        victim.write_bytes(candidate_data[driver])
                        (candidate / driver).unlink()
                        (candidate / driver).symlink_to(victim)
                        error = "missing or symlinked"

                    scratch = root / f"output-{kind}"
                    with (
                        patch.object(extractor, "BASELINE_HASHES", self.hashes(self.synthetic_bytes(base))),
                        patch.object(extractor, "CANDIDATE_HASHES", expected_candidate),
                        self.assertRaisesRegex(extractor.ExtractError, error),
                    ):
                        extractor.extract(base, candidate, scratch)
                    self.assertFalse(scratch.exists())

    @staticmethod
    def synthetic_bytes(root: Path) -> dict[str, bytes]:
        return {
            relative: (root / relative).read_bytes()
            for relative in extractor.SOURCE_FILES
        }

    def test_extract_rejects_bad_sources_before_creating_requested_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / "base"
            candidate = root / "candidate"
            base_data = self.synthetic_tree(base)
            candidate_data = self.synthetic_tree(candidate, usb_suffix="candidate")
            bad_candidate = dict(extractor.CANDIDATE_HASHES)
            bad_candidate[extractor.owner.DRIVER_CONTROL] = "f" * 64
            scratch = root / "never-created"
            with (
                patch.object(extractor, "BASELINE_HASHES", self.hashes(base_data)),
                patch.object(extractor, "CANDIDATE_HASHES", bad_candidate),
                self.assertRaisesRegex(extractor.ExtractError, "SHA-256 mismatch"),
            ):
                extractor.extract(base, candidate, scratch)
            self.assertFalse(scratch.exists())

    def test_scratch_rejects_repository_source_overlap_and_existing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / "base"
            candidate = root / "candidate"
            base.mkdir()
            candidate.mkdir()

            with self.assertRaisesRegex(extractor.ExtractError, "overlaps"):
                extractor.validate_scratch(base / "nested", (base, candidate))
            with self.assertRaisesRegex(extractor.ExtractError, "overlaps"):
                extractor.validate_scratch(candidate / "nested", (base, candidate))
            product = Path(extractor.__file__).resolve().parents[2]
            with self.assertRaisesRegex(extractor.ExtractError, "overlaps"):
                extractor.validate_scratch(product / "backend" / "nut" / ".rf04-scratch", (base, candidate))

            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(extractor.ExtractError, "new, non-symlink"):
                extractor.validate_scratch(existing, (base, candidate))
            linked = root / "scratch-link"
            linked.symlink_to(root / "absent", target_is_directory=True)
            with self.assertRaisesRegex(extractor.ExtractError, "new, non-symlink"):
                extractor.validate_scratch(linked, (base, candidate))

    def test_extract_writes_source_bound_outputs_manifest_notices_and_interpositions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / "base"
            candidate = root / "candidate"
            base_data = self.synthetic_tree(base)
            candidate_data = self.synthetic_tree(candidate, usb_suffix="candidate")
            fixture = b"/* SPDX-License-Identifier: GPL-2.0-or-later */\nsynthetic fixture\n"
            fixture_hash = hashlib.sha256(fixture).hexdigest()
            generated_base = "/* generated base */\nint base_fixture;\n"
            generated_candidate = "/* generated candidate */\nint candidate_fixture;\n"
            output = root / "scratch"

            with (
                patch.object(extractor, "BASELINE_HASHES", self.hashes(base_data)),
                patch.object(extractor, "CANDIDATE_HASHES", self.hashes(candidate_data)),
                patch.object(extractor.owner, "validate_fixture", return_value=(fixture, fixture_hash)),
                patch.object(extractor.owner, "generate", side_effect=[
                    (generated_base, ["int base_fixture;"]),
                    (generated_candidate, ["int candidate_fixture;", extractor.STOP_HELPER]),
                ]) as generate,
            ):
                result = extractor.extract(base, candidate, output)

            self.assertEqual(result, output)
            self.assertEqual(generate.call_args_list, [
                call(
                    base_data[extractor.owner.USB_FILE].decode("utf-8"),
                    base_data[extractor.owner.BACKEND_FILE].decode("utf-8"),
                    extra_usb_functions=(),
                ),
                call(
                    candidate_data[extractor.owner.USB_FILE].decode("utf-8"),
                    candidate_data[extractor.owner.BACKEND_FILE].decode("utf-8"),
                    extra_usb_functions=(extractor.STOP_HELPER,),
                ),
            ])

            wrapper = extractor.WRAPPER
            for label, expected_generated, expected_names in (
                ("base7", generated_base, ["int base_fixture;"]),
                ("candidate8", generated_candidate, ["int candidate_fixture;", extractor.STOP_HELPER]),
            ):
                directory = output / label
                c_source = (directory / extractor.GENERATED).read_text(encoding="utf-8")
                manifest_bytes = (directory / "manifest.json").read_bytes()
                manifest = json.loads(manifest_bytes)
                self.assertEqual((directory / extractor.FIXTURE).read_bytes(), fixture)
                self.assertEqual((directory / wrapper).read_bytes(), Path(extractor.__file__).with_name(wrapper).read_bytes())
                self.assertIn("SPDX-License-Identifier: GPL-2.0-or-later", c_source)
                self.assertIn("synthetic USB notice", c_source)
                self.assertIn("synthetic backend notice", c_source)
                self.assertIn("guarded_fill_interrupt_transfer", c_source)
                self.assertIn("#define pthread_create guarded_pthread_create", c_source)
                self.assertIn(expected_generated.strip(), c_source)
                self.assertEqual(manifest["status"], "EXTRACTED_NOT_RUN")
                self.assertEqual(manifest["source_sha256"]["base"], self.hashes(base_data))
                self.assertEqual(manifest["source_sha256"]["candidate"], self.hashes(candidate_data))
                self.assertEqual(manifest["extracted_functions"][label == "candidate8" and "candidate" or "base"], expected_names)
                self.assertEqual(manifest["fixture_sha256"], fixture_hash)
                self.assertEqual(manifest["generated_sha256"]["candidate" if label == "candidate8" else "base"], hashlib.sha256(c_source.encode("utf-8")).hexdigest())
                self.assertIn("No real libusb", " ".join(manifest["limitations"]))
                self.assertNotIn(str(root), manifest_bytes.decode("utf-8"))

    def test_render_passes_no_extra_by_default_and_only_named_candidate_extra(self) -> None:
        contents = {
            extractor.owner.USB_FILE: b"/* USB */\n#include \"config.h\"\n",
            extractor.owner.BACKEND_FILE: b"/* backend */\n#include \"config.h\"\n",
        }
        with patch.object(
            extractor.owner,
            "generate",
            return_value=("int generated;", ["int generated;"]),
        ) as generate:
            base_source, base_names = extractor._render(contents, False)
            candidate_source, candidate_names = extractor._render(contents, True)

        self.assertEqual(generate.call_args_list, [
            call(contents[extractor.owner.USB_FILE].decode(), contents[extractor.owner.BACKEND_FILE].decode(), extra_usb_functions=()),
            call(contents[extractor.owner.USB_FILE].decode(), contents[extractor.owner.BACKEND_FILE].decode(), extra_usb_functions=(extractor.STOP_HELPER,)),
        ])
        self.assertEqual(base_names, ["int generated;"])
        self.assertEqual(candidate_names, ["int generated;"])
        self.assertIn("int generated;", base_source)
        self.assertIn("int generated;", candidate_source)
        self.assertEqual(
            inspect.signature(extractor.owner.generate).parameters["extra_usb_functions"].default,
            (),
        )

    def test_real_generator_keeps_default_functions_and_appends_candidate_extra(self) -> None:
        usb, backend = self.synthetic_generator_inputs()
        base_source, base_names = extractor.owner.generate(usb, backend)
        candidate_source, candidate_names = extractor.owner.generate(
            usb, backend, extra_usb_functions=(extractor.STOP_HELPER,)
        )

        self.assertEqual(
            base_names,
            list(extractor.owner.USB_FUNCTIONS) + list(extractor.owner.BACKEND_FUNCTIONS),
        )
        self.assertEqual(
            candidate_names,
            list(extractor.owner.USB_FUNCTIONS)
            + [extractor.STOP_HELPER]
            + list(extractor.owner.BACKEND_FUNCTIONS),
        )
        self.assertNotIn(extractor.STOP_HELPER, base_source)
        self.assertIn(extractor.STOP_HELPER, candidate_source)

    def test_extractor_is_process_free(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("Popen(", source)
        self.assertNotIn("os.system(", source)


if __name__ == "__main__":
    unittest.main()
