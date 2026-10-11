# SPDX-License-Identifier: MIT
"""Synthetic source-fence and subprocess-contract tests for the replay runner."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import replay_hid_fallback as replay
import replay_hid_validation as runner


EXPECTED_RED = (
    "FAIL incomplete report ID-only unavailable\n"
    "FAIL failed getter leaves outputs untouched\n"
    "FAIL incomplete sibling does not refresh cache\n"
    "FAIL incomplete sibling keeps pair unavailable\n"
    "FAIL incomplete report preserves prior status cache and timestamp\n"
    "FAIL incomplete report cannot refresh prior status pair\n"
    "FAIL ID-only optional report preserves neutral missing values\n"
    "FAIL complete optional field updates independently\n"
    "FAIL partial straddling optional field preserves cache\n"
    "FAIL 32-bit partial report preserves cache\n"
    "FAIL rollback invalidates pair\n"
    "FAIL rollback clears both timestamps\n"
    "FAIL rollback leaves caller outputs untouched\n"
    "FAIL catch-up cannot resurrect old pair\n"
    "FAIL one new status report is insufficient\n"
    "FAIL publisher suppresses invalid status\n"
    "FAIL invalid fallback emits no events\n"
    "FAIL publisher suppresses status after rollback\n"
    "FAIL rollback emits no publisher events\n"
    "19 validation check(s) failed\n"
)
EXPECTED_GREEN = "all HID fallback validation checks passed\n"
SYNTHETIC_UNIT = "\n".join(
    (
        "static unsigned long hid_extract_bits(void);",
        "static void microlink_usb_try_decode_fallback(void);",
        "int microlink_usb_get_hid_fallback(void);",
        "static int microlink_publish_hid_fallback(void);",
    )
)


class CandidateFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.contents: dict[Path, bytes] = {}
        self.hashes: dict[Path, str] = {}
        for relative in runner.SOURCES:
            path = self.candidate / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = f"synthetic source {relative}\n".encode()
            path.write_bytes(data)
            self.contents[relative] = data
            self.hashes[relative] = hashlib.sha256(data).hexdigest()
        self.status = f" M {runner.UPSTREAM_USB.as_posix()}"

    def verify_candidate(self, git_values: list[str] | None = None) -> dict[Path, bytes]:
        values = git_values or [
            runner.PIN,
            runner.UPSTREAM_USB.as_posix(),
            self.status,
        ]
        with (
            patch.object(runner, "PATCHED_SHA256", self.hashes),
            patch.object(runner, "output", side_effect=values),
        ):
            return runner.read_candidate(self.candidate)

    def test_read_candidate_accepts_only_the_pinned_two_source_candidate(self) -> None:
        result = self.verify_candidate()
        self.assertEqual(result, self.contents)

    def test_read_candidate_rejects_wrong_head(self) -> None:
        with self.assertRaisesRegex(runner.ValidationError, "HEAD"):
            self.verify_candidate(["0" * 40])

    def test_read_candidate_rejects_extra_source_change(self) -> None:
        with self.assertRaisesRegex(runner.ValidationError, "modify only"):
            self.verify_candidate(
                [runner.PIN, f"{runner.UPSTREAM_USB}\n{runner.UPSTREAM_PUBLISHER}"]
            )

    def test_read_candidate_rejects_staged_and_untracked_changes(self) -> None:
        for status in (
            f"M  {runner.UPSTREAM_USB.as_posix()}",
            f" M {runner.UPSTREAM_USB.as_posix()}\n?? stray.txt",
        ):
            with self.subTest(status=status), self.assertRaisesRegex(
                runner.ValidationError, "unexpected staged or untracked"
            ):
                self.verify_candidate([runner.PIN, runner.UPSTREAM_USB.as_posix(), status])

    def test_read_candidate_rejects_missing_symlink_and_hash_change_for_each_source(self) -> None:
        for relative in runner.SOURCES:
            path = self.candidate / relative
            with self.subTest(source=relative, failure="missing"):
                original = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(runner.ValidationError, "missing or symlink"):
                    self.verify_candidate()
                path.write_bytes(original)

            with self.subTest(source=relative, failure="symlink"):
                original = path.read_bytes()
                path.unlink()
                target = self.root / f"target-{path.name}"
                target.write_bytes(original)
                path.symlink_to(target)
                with self.assertRaisesRegex(runner.ValidationError, "missing or symlink"):
                    self.verify_candidate()
                path.unlink()
                path.write_bytes(original)

            with self.subTest(source=relative, failure="hash"):
                original = path.read_bytes()
                path.write_bytes(original + b"changed\n")
                with self.assertRaisesRegex(runner.ValidationError, "SHA-256"):
                    self.verify_candidate()
                path.write_bytes(original)


class RunnerOutputFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.candidate = self.root / "candidate"
        self.source.mkdir()
        self.candidate.mkdir()
        self.scratch = self.root / "scratch"

    def run_main(self, mode: str, scratch: Path | None = None) -> tuple[int, str, str]:
        argv = [
            "replay_hid_validation.py",
            "--source-root", str(self.source),
            "--candidate-root", str(self.candidate),
            "--scratch", str(scratch or self.scratch),
            "--mode", mode,
        ]
        stdout, stderr = StringIO(), StringIO()
        with (
            patch.object(runner.sys, "argv", argv),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            patch.object(replay, "verify_source", return_value=("merged", {})),
            patch.object(runner, "read_candidate", return_value={}),
            patch.object(replay, "extract_translation_unit", return_value=SYNTHETIC_UNIT),
        ):
            code = runner.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_extract_writes_only_fenced_text_and_never_calls_compiler(self) -> None:
        with patch.object(runner.subprocess, "run") as run:
            code, output, error = self.run_main("extract")
        self.assertEqual(code, 0)
        self.assertFalse(error)
        self.assertIn("extracted fenced source", output)
        generated = self.scratch / "candidate" / "hid_fallback_validation_generated.c"
        self.assertTrue(generated.is_file())
        run.assert_not_called()

    def test_extract_rejects_existing_output_directory_without_overwrite(self) -> None:
        output_dir = self.scratch / "candidate"
        output_dir.mkdir(parents=True)
        generated = output_dir / "hid_fallback_validation_generated.c"
        generated.write_text("preserve this sentinel\n", encoding="utf-8")
        code, _, error = self.run_main("extract")
        self.assertEqual(code, 2)
        self.assertIn("File exists", error)
        self.assertEqual(generated.read_text(encoding="utf-8"), "preserve this sentinel\n")

    def test_scratch_symlink_and_each_forbidden_tree_are_rejected(self) -> None:
        destination = self.root / "elsewhere"
        destination.mkdir()
        link = self.root / "scratch-link"
        link.symlink_to(destination, target_is_directory=True)
        code, _, error = self.run_main("extract", link)
        self.assertEqual(code, 2)
        self.assertIn("must not be a symlink", error)

        forbidden_roots = (
            Path(runner.__file__).resolve().parents[2] / "synthetic-test-scratch",
            self.source / "nested-scratch",
            self.candidate / "nested-scratch",
        )
        for forbidden in forbidden_roots:
            with self.subTest(forbidden=forbidden.name):
                code, _, error = self.run_main("extract", forbidden)
                self.assertEqual(code, 2)
                self.assertIn("outside repository and source checkouts", error)


class SubprocessContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(
        self,
        mode: str,
        runtime_code: int,
        stdout: str,
        stderr: str = "",
        compile_error: Exception | None = None,
    ) -> tuple[int | None, str, str, list[object]]:
        output_dir = self.root / f"{mode}-{len(list(self.root.iterdir()))}"
        compile_result = subprocess_result(returncode=0)
        runtime_result = subprocess_result(returncode=runtime_code, stdout=stdout, stderr=stderr)
        calls: list[object] = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            if len(calls) == 1 and compile_error is not None:
                raise compile_error
            return compile_result if len(calls) == 1 else runtime_result

        captured_out, captured_err = StringIO(), StringIO()
        try:
            with (
                patch.object(runner.subprocess, "run", side_effect=fake_run),
                redirect_stdout(captured_out),
                redirect_stderr(captured_err),
            ):
                result = runner.compile_and_run(
                    SYNTHETIC_UNIT,
                    output_dir,
                    self.root / "synthetic-test.c",
                    mode,
                )
            return result, captured_out.getvalue(), captured_err.getvalue(), calls
        except Exception as error:
            return None, captured_out.getvalue(), captured_err.getvalue() + str(error), calls

    def test_red_accepts_only_exact_exit_one_and_expected_markers(self) -> None:
        result, _, _, calls = self.invoke("red", 1, EXPECTED_RED)
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)

    def test_red_rejects_success_other_errors_and_negative_signal_codes(self) -> None:
        for code, output in (
            (0, EXPECTED_RED),
            (2, EXPECTED_RED),
            (-11, EXPECTED_RED),
            (1, EXPECTED_RED.replace("FAIL rollback invalidates pair\n", "")),
            (1, EXPECTED_RED.replace("FAIL rollback invalidates pair\n", "FAIL unrelated\nFAIL rollback invalidates pair\n")),
            (1, EXPECTED_RED.replace("FAIL rollback invalidates pair\n", "", 1).replace(
                "FAIL rollback clears both timestamps\n",
                "FAIL rollback clears both timestamps\nFAIL rollback invalidates pair\n",
            )),
            (1, EXPECTED_RED.replace("FAIL incomplete report ID-only unavailable\n", "prefix FAIL incomplete report ID-only unavailable\n")),
            (1, EXPECTED_RED.replace("19 validation", "ERROR unrelated\n19 validation")),
        ):
            with self.subTest(code=code, output=output):
                result, _, error, _ = self.invoke("red", code, output)
                self.assertIsNone(result)
                self.assertIn("controlled RED checks", error)

    def test_red_rejects_ubsan_and_any_runtime_stderr(self) -> None:
        for stderr in (
            "runtime error: signed integer overflow\n",
            "unexpected runtime diagnostic\n",
        ):
            with self.subTest(stderr=stderr):
                result, _, error, _ = self.invoke("red", 1, EXPECTED_RED, stderr)
                self.assertIsNone(result)
                self.assertIn("controlled RED checks", error)

    def test_green_requires_clean_success(self) -> None:
        result, _, _, _ = self.invoke("green", 0, EXPECTED_GREEN)
        self.assertEqual(result, 0)
        for code, stdout, stderr in (
            (1, EXPECTED_GREEN, ""),
            (-11, EXPECTED_GREEN, ""),
            (0, EXPECTED_GREEN, "runtime error: invalid access\n"),
            (0, "", ""),
            (0, EXPECTED_GREEN + "unexpected extra line\n", ""),
        ):
            with self.subTest(code=code, stderr=stderr):
                result, _, error, _ = self.invoke("green", code, stdout, stderr)
                self.assertIsNone(result)
                self.assertTrue(
                    "returned" in error or "unexpected output" in error,
                    error,
                )

    def test_compiler_failure_is_not_misclassified_as_red(self) -> None:
        failure = runner.subprocess.CalledProcessError(1, ["cc"])
        result, _, error, calls = self.invoke("red", 1, EXPECTED_RED, compile_error=failure)
        self.assertIsNone(result)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("RED reproduced", error)


def subprocess_result(returncode: int, stdout: str = "", stderr: str = ""):
    return runner.subprocess.CompletedProcess([], returncode, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
