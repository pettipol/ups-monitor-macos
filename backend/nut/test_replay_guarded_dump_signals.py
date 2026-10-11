# SPDX-License-Identifier: MIT
"""Synthetic contracts for signal replay; no driver or C executable is run."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import replay_guarded_dump_signals as runner


class SourceFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.checkout = self.root / "source"
        self.source = self.checkout / runner.MAIN_SOURCE
        self.source.parent.mkdir(parents=True)
        self.content = b"synthetic main source\n"
        self.source.write_bytes(self.content)
        self.digest = hashlib.sha256(self.content).hexdigest()

    def read(self, head: str = runner.PIN) -> bytes:
        with patch.object(runner, "git_output", return_value=head):
            return runner.read_pinned_main(self.checkout, self.digest)

    def test_exact_source_is_accepted_and_wrong_head_is_rejected(self) -> None:
        self.assertEqual(self.read(), self.content)
        with self.assertRaisesRegex(runner.ValidationError, "HEAD|revision"):
            self.read("0" * 40)

    def test_missing_symlink_and_changed_source_are_rejected(self) -> None:
        self.source.unlink()
        with self.assertRaisesRegex(runner.ValidationError, "missing"):
            self.read()
        target = self.root / "target"
        target.write_bytes(self.content)
        self.source.symlink_to(target)
        with self.assertRaisesRegex(runner.ValidationError, "symlink"):
            self.read()
        self.source.unlink()
        self.source.write_bytes(self.content + b"changed")
        with self.assertRaisesRegex(runner.ValidationError, "SHA-256"):
            self.read()

    def test_baseline_must_skip_regular_signal_setup_in_dump_branch(self) -> None:
        baseline = (
            b"if (do_forceshutdown || dump_data) {\n"
            b"    no_signal_setup();\n} else {\n    setup_signals();\n}\n"
            b"# endif\t/* !WIN32 */\n"
        )
        runner.validate_baseline_source(baseline)
        for altered in (
            baseline.replace(b"setup_signals();", b"no_signal_setup();"),
            baseline.replace(b"no_signal_setup();", b"setup_signals();"),
            baseline + b"guarded_dump_signal",
        ):
            with self.subTest(altered=altered), self.assertRaises(runner.ValidationError):
                runner.validate_baseline_source(altered)


class ReplayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.counter = 0

    def scratch(self) -> Path:
        self.counter += 1
        return self.root / f"run-{self.counter}"

    def test_extract_is_nonexecuting_and_existing_evidence_is_preserved(self) -> None:
        scratch = self.scratch()
        unit = "/* synthetic helper */\n"
        with patch.object(runner.subprocess, "run") as run, redirect_stdout(StringIO()):
            self.assertEqual(runner.run_harness(unit, scratch, "extract", (self.source,)), 0)
        run.assert_not_called()
        generated = scratch / "guarded_dump_signal_generated.c"
        self.assertEqual(generated.read_text(), unit)
        with self.assertRaisesRegex(runner.ValidationError, "new"):
            runner.run_harness("changed", scratch, "extract", (self.source,))
        self.assertEqual(generated.read_text(), unit)

    def test_scratch_cannot_enter_source_product_or_symlink_parent(self) -> None:
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        targets = (
            self.source / "scratch",
            Path(runner.__file__).resolve().parents[2] / "forbidden-test-output",
            link / "scratch",
        )
        for target in targets:
            with self.subTest(path=target), self.assertRaises(runner.ValidationError):
                runner.run_harness("fixture", target, "extract", (self.source,))
            self.assertFalse(target.exists())

    def invoke(self, mode: str, code: int, stdout: str, stderr: str = "") -> list:
        responses = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, stdout="U _exit\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="/usr/lib/libSystem.B.dylib\n", stderr=""),
            subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr),
        ]
        with (
            patch.object(runner.subprocess, "run", side_effect=responses) as run,
            redirect_stdout(StringIO()),
        ):
            runner.run_harness("fixture", self.scratch(), mode, (self.source,))
        return run.call_args_list

    def test_red_and_green_outputs_are_exact_and_harness_is_bounded(self) -> None:
        red = "\n".join(runner.EXPECTED_RED) + "\n"
        green = "all guarded dump signal validation checks passed\n"
        for mode, code, output in (("red", 1, red), ("green", 0, green)):
            with self.subTest(mode=mode):
                calls = self.invoke(mode, code, output)
                self.assertEqual(len(calls), 4)
                self.assertEqual(calls[-1].kwargs["timeout"], 15)
                with self.assertRaises(runner.ValidationError):
                    self.invoke(mode, code, output + "unexpected\n")
                with self.assertRaises(runner.ValidationError):
                    self.invoke(mode, code + 1, output)

    def test_unexpected_usb_linkage_prevents_execution(self) -> None:
        for nm, otool in (
            ("U _libusb_open", "libSystem"),
            ("U _exit", "/somewhere/libnut.dylib"),
        ):
            responses = [
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0, stdout=nm),
                subprocess.CompletedProcess([], 0, stdout=otool),
            ]
            with (
                self.subTest(nm=nm, otool=otool),
                patch.object(runner.subprocess, "run", side_effect=responses) as run,
                redirect_stdout(StringIO()),
                self.assertRaisesRegex(runner.ValidationError, "references USB or NUT"),
            ):
                runner.run_harness("fixture", self.scratch(), "green", (self.source,))
            self.assertEqual(run.call_count, 3)

    def test_failed_inspection_prevents_execution(self) -> None:
        responses = [
            subprocess.CompletedProcess([], 0),
            subprocess.CalledProcessError(1, ["nm"]),
        ]
        with (
            patch.object(runner.subprocess, "run", side_effect=responses) as run,
            redirect_stdout(StringIO()),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            runner.run_harness("fixture", self.scratch(), "green", (self.source,))
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
