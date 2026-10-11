# SPDX-License-Identifier: MIT
"""Fail-closed unit tests for the synthetic USB deadline replay runner."""

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


RUNNER = Path(__file__).with_name("replay_usb_guard_deadline.py")
SPEC = importlib.util.spec_from_file_location("replay_usb_guard_deadline", RUNNER)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


class ExtractionTests(unittest.TestCase):
    def test_extract_unique_function(self):
        src = "static void cb(int x) { if (x) { x++; } }\n"
        self.assertIn("x++", runner.extract_function(src, "cb"))

    def test_reject_missing_function(self):
        with self.assertRaises(ValueError):
            runner.extract_function("static void other(void) {}", "cb")

    def test_reject_duplicate_function(self):
        src = "static void cb(void) {}\nstatic void cb(void) {}\n"
        with self.assertRaises(ValueError):
            runner.extract_function(src, "cb")

    def test_reject_unterminated_function(self):
        with self.assertRaises(ValueError):
            runner.extract_function("static void cb(void) {", "cb")

    def test_reject_ambiguous_region(self):
        with self.assertRaises(ValueError):
            runner.extract_region("#define MLINK_USB_ASYNC_QUEUE_LEN 8\n#define MLINK_USB_ASYNC_QUEUE_LEN 8\n#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */")

    def test_hash_pins(self):
        self.assertEqual(len(runner.BASE_USB_SHA), 64)
        self.assertNotEqual(runner.BASE_USB_SHA, runner.CANDIDATE_USB_SHA)
        self.assertNotEqual(runner.BASE_HEADER_SHA, runner.CANDIDATE_HEADER_SHA)

    def callpath_fixture(self):
        cb = "static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer) { if (microlink_usb_guard_expired_locked()) return; if (microlink_usb_guard_expired_locked()) return; microlink_usb_try_decode_fallback(0, 0); async_queue_count++; microlink_usb_guard_timeout_ms_locked(&timeout_ms); libusb_submit_transfer(transfer); }"
        start = "static int microlink_usb_async_start(void) { libusb_alloc_transfer(0); microlink_usb_guard_timeout_ms_locked(&timeout_ms); libusb_fill_interrupt_transfer(timeout_ms); microlink_usb_guard_timeout_ms_locked(&timeout_ms); async_xfer->timeout = timeout_ms; libusb_submit_transfer(x); }"
        getter = "int microlink_usb_get_char(unsigned char *ch, long d_usec) { if (guarded && (expired || !async_xfer_active)) return 0; if (!guarded) return microlink_usb_get_char_sync(ch,d_usec); }"
        flush = "void microlink_usb_flush_io(void) { if (microlink_usb_guard_expired_locked() || !async_xfer_active) return; }"
        opening = "int microlink_usb_open(void) { if (!microlink_usb_async_start()) { microlink_usb_guard_invalidate(); return 0; } }"
        reopen = "int microlink_usb_reset_and_reopen(void) { microlink_usb_guard_expired(); microlink_usb_guard_expired(); comm_driver->open_dev(x); }"
        driver = "void upsdrv_initups(void) { microlink_usb_guard_begin(x); microlink_usb_open(); }\nvoid upsdrv_initinfo(void) { microlink_guard_deadline_expired(); memset(objects, 0, 0); }"
        return "\n".join((cb, start, getter, flush, opening, reopen)), driver

    def test_candidate_callpath_rejects_deadline_after_submit(self):
        usb, driver = self.callpath_fixture()
        runner.validate_candidate_callpaths(usb, driver)
        mutant = usb.replace("microlink_usb_guard_timeout_ms_locked(&timeout_ms); libusb_submit_transfer(transfer);",
                             "libusb_submit_transfer(transfer); microlink_usb_guard_timeout_ms_locked(&timeout_ms);")
        with self.assertRaises(ValueError):
            runner.validate_candidate_callpaths(mutant, driver)

    def test_callpaths_reject_renewal_premature_fatal_and_missing_refresh(self):
        usb, driver = self.callpath_fixture()
        for changed_usb, changed_driver in (
            (usb, driver + "\nmicrolink_guard_deadline_begin();"),
            (usb.replace("microlink_usb_guard_invalidate(); return 0;", "fatalx(1);"), driver),
            (usb.replace("async_xfer->timeout = timeout_ms;", ""), driver),
            (usb.replace("microlink_usb_guard_invalidate(); return 0;", "microlink_usb_guard_invalidate(); close_dev(x); return 0;"), driver),
            (usb.replace("microlink_usb_guard_invalidate();", "/* microlink_usb_guard_invalidate(); */"), driver),
        ):
            with self.subTest(usb=changed_usb, driver=changed_driver), self.assertRaises(ValueError):
                runner.validate_candidate_callpaths(changed_usb, changed_driver)

    def test_checked_file_rejects_symlink_and_wrong_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.write_text("pinned")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                runner.checked_file(root, "link", runner.sha256(target))
            with self.assertRaises(ValueError):
                runner.checked_file(root, "target", "0" * 64)

    def test_output_path_must_not_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "source"
            source.mkdir()
            output = root / "out"
            output.mkdir()
            with patch.object(runner, "run_checked") as run, self.assertRaises(runner.ValidationError):
                runner.run_replay("extract", source, output)
            run.assert_not_called()

    def test_source_and_product_overlap_prevent_writes_and_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp).resolve()
            repo = RUNNER.resolve().parents[2]
            for output in (source / "new", repo / "forbidden-deadline-replay"):
                with self.subTest(output=output), patch.object(runner, "run_checked") as run:
                    with self.assertRaises(runner.ValidationError):
                        runner.run_replay("extract", source, output)
                    run.assert_not_called()
                    self.assertFalse(output.exists())

    def test_head_and_all_three_hash_fences_prevent_compile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "source"
            (source / "drivers").mkdir(parents=True)
            relatives = ("drivers/apcmicrolink-usb.c", "drivers/apcmicrolink-usb.h", "drivers/apcmicrolink.c")
            digest = hashlib.sha256(b"fixture").hexdigest()
            for relative in relatives:
                (source / relative).write_bytes(b"fixture")
            with patch.object(runner, "run_checked", return_value=subprocess.CompletedProcess([], 0, "wrong\n", "")) as run:
                with self.assertRaisesRegex(ValueError, "HEAD"):
                    runner.run_replay("extract", source, root / "bad-head")
                self.assertEqual(run.call_count, 1)
            for index, relative in enumerate(relatives):
                (source / relative).write_bytes(b"changed")
                with patch.object(runner, "BASE_USB_SHA", digest), patch.object(runner, "BASE_HEADER_SHA", digest), patch.object(runner, "BASE_DRIVER_SHA", digest):
                    with patch.object(runner, "run_checked", return_value=subprocess.CompletedProcess([], 0, runner.BASE_HEAD, "")) as run:
                        with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "source pin"):
                            runner.run_replay("red", source, root / f"bad-hash-{index}")
                        self.assertEqual(run.call_count, 1)
                (source / relative).write_bytes(b"fixture")

    def test_binary_inspection_failure_and_usb_symbols_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            responses = (
                (subprocess.CompletedProcess([], 1, "", "error"), subprocess.CompletedProcess([], 0, "binary:\nlibSystem\n", "")),
                (subprocess.CompletedProcess([], 0, "U _usb_open\n", ""), subprocess.CompletedProcess([], 0, "binary:\nlibSystem\n", "")),
                (subprocess.CompletedProcess([], 0, "U _malloc\n", ""), subprocess.CompletedProcess([], 1, "", "error")),
            )
            for results in responses:
                with patch.object(runner, "run_checked", side_effect=results) as run, self.assertRaises(ValueError):
                    runner.inspect_binary(root / "replay", root)
                self.assertEqual(run.call_count, 2)

    def test_parser_ignores_braces_in_comments(self):
        src = "static void cb(void) { /* } */ if (1) { } }"
        self.assertTrue(runner.extract_function(src, "cb").endswith("}"))


if __name__ == "__main__":
    unittest.main()
