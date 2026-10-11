# SPDX-License-Identifier: MIT
"""Unit tests for the pinned USB write-completion replay fences."""

from __future__ import annotations

import hashlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import replay_usb_write_completion as runner


RED_LINES = (
    "FAIL zero-byte short write rejected",
    "FAIL one-byte short write rejected",
    "FAIL 63-byte short write rejected",
    "FAIL unexpected oversized completion rejected",
    "4 validation check(s) failed",
)
GREEN_LINE = "all USB write completion checks passed\n"
SYNTHETIC_UNIT = "/* usb header */\nstatic inline int wrapper(void) {}\nint send(void) {}\n"


class SourceFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.contents = {
            runner.SOURCE: b"synthetic USB source\n",
            runner.USB_COMMON: b"synthetic common header\n",
        }
        for relative, content in self.contents.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.hashes = {
            path: hashlib.sha256(content).hexdigest()
            for path, content in self.contents.items()
        }

    def read(self, head: str = runner.PIN) -> dict[Path, bytes]:
        with (
            patch.object(runner, "USB_COMMON_SHA256", self.hashes[runner.USB_COMMON]),
            patch.object(runner, "git_output", return_value=head),
        ):
            return runner.read_sources(self.root, self.hashes[runner.SOURCE], "fixture")

    def test_source_reader_accepts_exact_pinned_hashes(self) -> None:
        self.assertEqual(self.read(), self.contents)

    def test_source_reader_rejects_wrong_head(self) -> None:
        with self.assertRaisesRegex(runner.ReplayError, "HEAD"):
            self.read("0" * 40)

    def test_source_reader_rejects_missing_symlink_and_hash_mismatch(self) -> None:
        for relative in runner.SOURCE, runner.USB_COMMON:
            target = self.root / relative
            original = target.read_bytes()
            with self.subTest(path=relative, error="missing"):
                target.unlink()
                with self.assertRaisesRegex(runner.ReplayError, "missing or is a symlink"):
                    self.read()
                target.write_bytes(original)

            with self.subTest(path=relative, error="symlink"):
                target.unlink()
                link_target = self.root / "other-target"
                link_target.write_bytes(original)
                target.symlink_to(link_target)
                with self.assertRaisesRegex(runner.ReplayError, "missing or is a symlink"):
                    self.read()
                target.unlink()
                target.write_bytes(original)

            with self.subTest(path=relative, error="hash"):
                target.write_bytes(original + b"changed")
                with self.assertRaisesRegex(runner.ReplayError, "SHA-256"):
                    self.read()
                target.write_bytes(original)


class ExtractionTests(unittest.TestCase):
    def test_extract_preserves_both_file_headers_and_exact_wrapper(self) -> None:
        usb = (
            b"/* USB source header */\n"
            b"int microlink_usb_send_bytes(const unsigned char *buf, size_t len) { return 1; }\n"
            b"\n/* Extract a little-endian, LSB-first-packed bit field */\n"
        )
        common = (
            b"/* usb-common header */\n"
            b" static inline  int usb_interrupt_write(usb_dev_handle *dev, int ep,\n"
            b"                const usb_ctrl_charbuf bytes, int size, int timeout)\n"
            b" {\n int ret;\n ret = libusb_interrupt_transfer(dev, 0, 0, 0, size, &size, 0);\n"
            b" return (ret == LIBUSB_SUCCESS)?size:ret;\n }\n"
            b"\n static inline  int usb_bulk_read(\n"
        )
        unit = runner.extract_unit({runner.SOURCE: usb, runner.USB_COMMON: common})
        self.assertTrue(unit.startswith("/* USB source header */\n\n/* usb-common header */"))
        self.assertEqual(unit.count("static inline  int usb_interrupt_write("), 1)
        self.assertIn("ret = libusb_interrupt_transfer(dev, 0, 0, 0, size, &size, 0)", unit)
        self.assertEqual(unit.count("int microlink_usb_send_bytes("), 1)

    def test_extract_rejects_missing_header_or_marker(self) -> None:
        for usb, common in (
            (b"source", b"/* header */\n"),
            (b"/* header */\n", b"/* header */\n"),
        ):
            with self.subTest(usb=usb, common=common), self.assertRaises(runner.ReplayError):
                runner.extract_unit({runner.SOURCE: usb, runner.USB_COMMON: common})


class RunnerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.test_source = self.root / "test.c"
        self.test_source.write_text("synthetic\n", encoding="utf-8")
        self.invocation_count = 0

    def test_extract_never_compiles_or_executes_and_refuses_overwrite(self) -> None:
        scratch = self.root / "scratch"
        scratch.mkdir()
        with (
            patch.object(runner.subprocess, "run") as run,
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            runner.run_harness(SYNTHETIC_UNIT, scratch, self.test_source, "extract")
        run.assert_not_called()
        generated = scratch / "extract" / "usb_write_completion_generated.c"
        self.assertEqual(generated.read_text(encoding="utf-8"), SYNTHETIC_UNIT)
        with self.assertRaises(FileExistsError):
            runner.run_harness(SYNTHETIC_UNIT, scratch, self.test_source, "extract")

    def invoke(self, mode: str, runtime_code: int, stdout: str, nm_output: str = "") -> list[object]:
        calls: list[object] = []
        self.invocation_count += 1
        responses = (
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, stdout=nm_output, stderr=""),
            subprocess.CompletedProcess([], runtime_code, stdout=stdout, stderr=""),
        )

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return responses[len(calls) - 1]

        with (
            patch.object(runner.subprocess, "run", side_effect=fake_run),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            runner.run_harness(
                SYNTHETIC_UNIT,
                self.root / f"{mode}-{self.invocation_count}",
                self.test_source,
                mode,
            )
        return calls

    def test_red_and_green_require_exact_output_and_have_bounded_processes(self) -> None:
        red = "\n".join(RED_LINES) + "\n"
        red_calls = self.invoke("red", 1, red)
        green_calls = self.invoke("green", 0, GREEN_LINE)
        self.assertEqual(len(red_calls), 3)
        self.assertEqual(len(green_calls), 3)
        self.assertTrue(all(call[1]["timeout"] == 30 for call in red_calls + green_calls))
        for mode, code, output in (
            ("red", 1, red + "ERROR unrelated\n"),
            ("green", 0, GREEN_LINE + "unexpected\n"),
        ):
            with self.subTest(mode=mode), self.assertRaises(runner.ReplayError):
                self.invoke(mode, code, output)

    def test_unresolved_usb_symbol_blocks_execution(self) -> None:
        calls: list[object] = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            if len(calls) == 1:
                return subprocess.CompletedProcess(command, 0)
            return subprocess.CompletedProcess(command, 0, stdout="U _libusb_interrupt_transfer\n", stderr="")

        with (
            patch.object(runner.subprocess, "run", side_effect=fake_run),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            with self.assertRaisesRegex(runner.ReplayError, "unresolved USB symbol"):
                runner.run_harness(SYNTHETIC_UNIT, self.root / "blocked", self.test_source, "green")
        self.assertEqual(len(calls), 2)

    def test_failed_nm_blocks_execution(self) -> None:
        calls: list[object] = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            if len(calls) == 1:
                return subprocess.CompletedProcess(command, 0)
            raise subprocess.CalledProcessError(1, command, stderr="nm failed")

        with (
            patch.object(runner.subprocess, "run", side_effect=fake_run),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.run_harness(SYNTHETIC_UNIT, self.root / "nm-failed", self.test_source, "green")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
