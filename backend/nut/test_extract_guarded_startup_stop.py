# SPDX-License-Identifier: MIT
"""Synthetic contract tests for the pinned guarded startup-stop extractor."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("extract_guarded_startup_stop.py")
SPEC = importlib.util.spec_from_file_location("guarded_startup_stop_extract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


MAIN_SOURCE = '''/* upstream main notice */
static volatile sig_atomic_t guarded_dump_signal = 0;
static void guarded_dump_signal_handler(int sig) { guarded_dump_signal = sig; }
int nut_guarded_dump_signal_requested(void) { return guarded_dump_signal != 0; }
static int setup_guarded_dump_signals(void) { return 0; }
static void exit_if_guarded_dump_signal_requested(void) {}
void startup_calls(void) {
  if (setup_guarded_dump_signals() != 0) return;
  exit_if_guarded_dump_signal_requested();
  upsdrv_callbacks.upsdrv_initups();
  exit_if_guarded_dump_signal_requested();
  upsdrv_callbacks.upsdrv_initinfo();
}
'''

HEADER_SOURCE = '''#ifndef NUT_MAIN_H_SEEN
#ifndef WIN32
/* Read-only checkpoint for cooperative guarded startup cancellation. */
int nut_guarded_dump_signal_requested(void);
#endif /* !WIN32 */
#endif
'''

DRIVER_SOURCE = '''/* upstream driver notice */
static int microlink_guarded_stop_requested(void) {
  return guarded_monitor && nut_guarded_dump_signal_requested();
}
static int microlink_send_write(unsigned char id, unsigned char offset,
  unsigned char len, const unsigned char *data) {
  if (microlink_guarded_stop_requested()) return 0;
  return 1;
}
static int microlink_send_simple_raw(unsigned char byte) { return 1; }
static int microlink_send_simple(unsigned char byte) {
  if (microlink_guarded_stop_requested()) return 0;
  return microlink_send_simple_raw(byte);
}
static int microlink_prime_poll(void) { return microlink_send_simple(0xFE); }
static int microlink_receive_once(void) { return 1; }
static int microlink_start_session_impl(unsigned int max_attempts) {
  if (microlink_guarded_stop_requested()) return 0;
  if (!microlink_send_simple(MLINK_STOP_BYTE)) return 0;
  if (microlink_guarded_stop_requested()) return 0;
  if (!microlink_send_simple(MLINK_INIT_BYTE)) return 0;
  if (microlink_guarded_stop_requested()) return 0;
  if (microlink_receive_once()) return microlink_prime_poll();
  return 0;
}
void upsdrv_initups(void) {
  int open_result;
  open_result = microlink_usb_open();
  if (guarded_monitor && open_result != 1) {
    microlink_usb_close();
    fatalx(EXIT_FAILURE, "guarded open failed");
  }
}
void upsdrv_cleanup(void) { microlink_send_simple_raw(MLINK_STOP_BYTE); }
'''

USB_SOURCE = '''void microlink_usb_close(void) {
#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)
  if (!microlink_usb_async_stop()) { return; }
#endif
  if (udev) { comm_driver->close_dev(udev); udev = NULL; }
}
'''


def fake_source_tree(root: Path) -> dict[str, bytes]:
    drivers = root / "drivers"
    drivers.mkdir(parents=True)
    contents = {
        extractor.MAIN: MAIN_SOURCE.encode(),
        extractor.HEADER: HEADER_SOURCE.encode(),
        extractor.DRIVER: DRIVER_SOURCE.encode(),
        extractor.USB: USB_SOURCE.encode(),
    }
    for relative, data in contents.items():
        (root / relative).write_bytes(data)
    return contents


class GuardedStartupStopExtractorTests(unittest.TestCase):
    def _run_mocked_fixture(self, base: Path, stage: str) -> tuple[int, Path, list[list[str]]]:
        work = base / stage
        work.mkdir()
        source = work / "source"
        contents = fake_source_tree(source)
        hashes = {key: hashlib.sha256(value).hexdigest()
                  for key, value in contents.items()}
        scratch = work / "scratch"
        commands: list[list[str]] = []

        def fake_tool(command: list[str], timeout: int, capture: bool = False,
                      check: bool = True) -> int | str:
            commands.append(command)
            if stage == "compile" and len(commands) == 1:
                raise extractor.ReplayError("synthetic compile failure")
            if stage == "linkage" and len(commands) == 2:
                raise extractor.ReplayError("synthetic linkage inspection failure")
            return "stub-only symbols"

        child = subprocess.CompletedProcess(
            ["synthetic-fixture"], 1 if stage == "runtime" else 0,
            stdout="unexpected\n" if stage == "runtime" else
                   "all guarded startup/stop synthetic checks passed\n",
            stderr="",
        )
        with (
            patch.multiple(
                extractor,
                MAIN_SHA256=hashes[extractor.MAIN],
                HEADER_SHA256=hashes[extractor.HEADER],
                DRIVER_SHA256=hashes[extractor.DRIVER],
                USB_SHA256=hashes[extractor.USB],
            ),
            patch.object(extractor, "source_unit", return_value="/* synthetic generated */\n"),
            patch.object(extractor, "subprocess_run", side_effect=fake_tool),
            patch.object(extractor.subprocess, "run", return_value=child) as child_run,
        ):
            if stage == "success":
                result = extractor.run(source, scratch, "green", None)
                self.assertEqual(result, 0)
                compile_command = commands[0]
                self.assertEqual(compile_command[compile_command.index("-I") + 2],
                                 str(scratch / extractor.FIXTURE))
                self.assertEqual(child_run.call_args.args[0], [str(scratch / "test_guarded_startup_stop")])
            else:
                with self.assertRaises(extractor.ReplayError):
                    extractor.run(source, scratch, "green", None)
        return (0 if stage == "success" else 2), scratch, commands

    def test_exact_source_pin_rejects_mismatch_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            contents = fake_source_tree(source)
            fake_hashes = {key: hashlib.sha256(value).hexdigest()
                           for key, value in contents.items()}
            with patch.multiple(
                extractor,
                MAIN_SHA256=fake_hashes[extractor.MAIN],
                HEADER_SHA256=fake_hashes[extractor.HEADER],
                DRIVER_SHA256=fake_hashes[extractor.DRIVER],
                USB_SHA256=fake_hashes[extractor.USB],
            ):
                self.assertEqual(extractor.read_source(source),
                                 (MAIN_SOURCE, HEADER_SOURCE, DRIVER_SOURCE, USB_SOURCE))
                (source / extractor.MAIN).write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(extractor.ReplayError, "SHA-256 mismatch"):
                    extractor.read_source(source)

            linked = base / "source-link"
            linked.symlink_to(source, target_is_directory=True)
            with self.assertRaisesRegex(extractor.ReplayError, "symlink"):
                extractor.read_source(linked)

            (source / extractor.MAIN).unlink()
            (source / extractor.MAIN).write_bytes(contents[extractor.MAIN])
            linked_file = base / "main.c"
            linked_file.write_bytes(contents[extractor.MAIN])
            (source / extractor.MAIN).unlink()
            (source / extractor.MAIN).symlink_to(linked_file)
            with patch.multiple(
                extractor,
                MAIN_SHA256=fake_hashes[extractor.MAIN],
                HEADER_SHA256=fake_hashes[extractor.HEADER],
                DRIVER_SHA256=fake_hashes[extractor.DRIVER],
                USB_SHA256=fake_hashes[extractor.USB],
            ):
                with self.assertRaisesRegex(extractor.ReplayError, "symlinked"):
                    extractor.read_source(source)

            drivers_target = base / "real-drivers"
            drivers_target.mkdir()
            drivers_link_root = base / "drivers-link-root"
            drivers_link_root.mkdir()
            (drivers_link_root / "drivers").symlink_to(
                drivers_target, target_is_directory=True
            )
            with self.assertRaisesRegex(extractor.ReplayError, "drivers directory"):
                extractor.read_source(drivers_link_root)

    def test_candidate_contract_mutations_are_rejected(self) -> None:
        header = HEADER_SOURCE
        extractor.validate_candidate(MAIN_SOURCE, header, DRIVER_SOURCE, USB_SOURCE)
        disabled_guard = DRIVER_SOURCE.replace(
            "return guarded_monitor && nut_guarded_dump_signal_requested();",
            "return 0;",
        )
        with self.assertRaisesRegex(extractor.ReplayError, "signal query"):
            extractor.validate_candidate(MAIN_SOURCE, header, disabled_guard, USB_SOURCE)

        ignored_open = DRIVER_SOURCE.replace(
            "open_result = microlink_usb_open();", "microlink_usb_open();"
        )
        with self.assertRaisesRegex(extractor.ReplayError, "checked after open"):
            extractor.validate_candidate(MAIN_SOURCE, header, ignored_open, USB_SOURCE)

    def test_extract_outputs_notice_body_manifest_and_disclaimer_without_compiling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            contents = fake_source_tree(source)
            hashes = {key: hashlib.sha256(value).hexdigest()
                      for key, value in contents.items()}
            scratch = base / "fresh-output"
            with (
                patch.multiple(
                    extractor,
                    MAIN_SHA256=hashes[extractor.MAIN],
                    HEADER_SHA256=hashes[extractor.HEADER],
                    DRIVER_SHA256=hashes[extractor.DRIVER],
                    USB_SHA256=hashes[extractor.USB],
                ),
                patch.object(extractor, "subprocess_run",
                             side_effect=AssertionError("extract mode must not compile")),
            ):
                self.assertEqual(extractor.run(source, scratch, "extract", None), 0)

            generated = (scratch / extractor.GENERATED).read_text(encoding="utf-8")
            fixture = (scratch / extractor.FIXTURE).read_bytes()
            manifest_bytes = (scratch / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            self.assertTrue(generated.startswith(
                "/* SPDX-License-Identifier: GPL-2.0-or-later */\n\n/* upstream main notice */"
            ))
            self.assertIn("/* upstream driver notice */", generated)
            self.assertIn("if (microlink_guarded_stop_requested()) return 0;", generated)
            self.assertEqual(hashlib.sha256(generated.encode()).hexdigest(),
                             manifest["generated_sha256"])
            self.assertEqual(hashlib.sha256(fixture).hexdigest(), manifest["fixture_sha256"])
            self.assertEqual(manifest["status"], "EXTRACTED_NOT_RUN")
            self.assertTrue(any("main() and the NUT process were not executed" in item
                                for item in manifest["limitations"]))
            self.assertNotIn(str(base), manifest_bytes.decode())
            self.assertEqual(set(path.name for path in scratch.iterdir()), {
                extractor.GENERATED, extractor.FIXTURE, "manifest.json",
            })

    def test_runner_status_stays_not_run_until_exact_fixture_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            for stage in ("compile", "linkage", "runtime"):
                with self.subTest(stage=stage):
                    _, scratch, commands = self._run_mocked_fixture(base, stage)
                    manifest = json.loads((scratch / "manifest.json").read_text())
                    self.assertEqual(manifest["status"], "EXTRACTED_NOT_RUN")
                    if stage != "compile":
                        self.assertTrue(commands)

            _, scratch, commands = self._run_mocked_fixture(base, "success")
            manifest = json.loads((scratch / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "GREEN_SYNTHETIC")
            self.assertEqual(Path(commands[0][commands[0].index("-I") + 2]), scratch / extractor.FIXTURE)

    def test_red_status_is_written_only_after_exact_baseline_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "candidate"
            baseline = base / "baseline"
            candidate_contents = fake_source_tree(source)
            baseline_contents = fake_source_tree(baseline)
            candidate_hashes = {key: hashlib.sha256(value).hexdigest()
                                for key, value in candidate_contents.items()}
            baseline_hashes = {key: hashlib.sha256(value).hexdigest()
                               for key, value in baseline_contents.items()}
            expected_red = (
                "FAIL main-thread signal during startup STOP permitted INIT or retry\n"
                "FAIL worker-thread signal during startup STOP permitted INIT or retry\n"
                "FAIL signal after INIT permitted receive or NEXT\n"
                "FAIL guarded pending open reached initinfo or released retained ownership\n"
                "FAIL guarded failed open did not close an unowned USB handle before fatal\n"
                "5 synthetic startup/stop check(s) failed\n"
            )
            scratch = base / "red-scratch"
            with (
                patch.multiple(
                    extractor,
                    MAIN_SHA256=candidate_hashes[extractor.MAIN],
                    HEADER_SHA256=candidate_hashes[extractor.HEADER],
                    DRIVER_SHA256=candidate_hashes[extractor.DRIVER],
                    USB_SHA256=candidate_hashes[extractor.USB],
                    BASELINE_MAIN_SHA256=baseline_hashes[extractor.MAIN],
                    BASELINE_HEADER_SHA256=baseline_hashes[extractor.HEADER],
                    BASELINE_DRIVER_SHA256=baseline_hashes[extractor.DRIVER],
                    BASELINE_USB_SHA256=baseline_hashes[extractor.USB],
                ),
                patch.object(extractor, "source_unit", return_value="/* synthetic generated */\n"),
                patch.object(extractor, "subprocess_run", return_value="stub-only symbols"),
                patch.object(
                    extractor.subprocess, "run",
                    return_value=subprocess.CompletedProcess(
                        ["synthetic-fixture"], 1, stdout="", stderr=expected_red,
                    ),
                ),
            ):
                self.assertEqual(extractor.run(source, scratch, "red", baseline), 0)
            manifest = json.loads((scratch / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "RED_REPRODUCED")

    def test_scratch_rejects_product_overlap_existing_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            fake_source_tree(source)
            with self.assertRaisesRegex(extractor.ReplayError, "overlaps"):
                extractor.validate_scratch(
                    Path(__file__).resolve().parents[2] / "backend" / "nut" / "private",
                    source, None,
                )
            existing = base / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(extractor.ReplayError, "new"):
                extractor.validate_scratch(existing, source, None)
            linked = base / "linked"
            linked.symlink_to(base / "missing", target_is_directory=True)
            with self.assertRaisesRegex(extractor.ReplayError, "new"):
                extractor.validate_scratch(linked, source, None)


if __name__ == "__main__":
    unittest.main()
