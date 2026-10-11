# SPDX-License-Identifier: MIT
"""Offline contract tests for the bounded async-state replay runner."""

from __future__ import annotations

import sys
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_usb_async_state as replay  # noqa: E402


class ReplayRunnerTests(unittest.TestCase):
    def test_source_head_hash_and_symlink_fences(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent).resolve()
            source = root / replay.SOURCE
            source.parent.mkdir()
            content = b"synthetic source\n"
            source.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            with patch.object(replay, "git_output", return_value=replay.PIN):
                self.assertEqual(replay.read_pinned_source(root, digest), content)
                with self.assertRaisesRegex(replay.ValidationError, "SHA-256"):
                    replay.read_pinned_source(root, "0" * 64)
                source.unlink()
                source.symlink_to(root / "missing")
                with self.assertRaisesRegex(replay.ValidationError, "symlink"):
                    replay.read_pinned_source(root, digest)
            with patch.object(replay, "git_output", return_value="0" * 40):
                with self.assertRaisesRegex(replay.ValidationError, "HEAD"):
                    replay.read_pinned_source(root, digest)

    def test_state_extraction_omits_only_unused_start_stop_prototypes(self) -> None:
        state = (
            "#define MLINK_USB_ASYNC_QUEUE_LEN 8U\n"
            "static int async_pump_stop = 0;\n"
            "static int microlink_usb_async_start(void);\n"
            "static void microlink_usb_async_stop(void);\n"
            "#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */"
        )
        extracted = replay.extract_state_declarations(state)
        self.assertIn("static int async_pump_stop = 0;", extracted)
        self.assertTrue(extracted.endswith("#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */"))
        self.assertNotIn("microlink_usb_async_start", extracted)
        self.assertNotIn("microlink_usb_async_stop", extracted)
        with self.assertRaisesRegex(replay.ValidationError, "prototype"):
            replay.extract_state_declarations(state.replace("static int microlink_usb_async_start(void);", ""))

    def test_each_of_six_helpers_requires_its_own_lock(self) -> None:
        operations = (
            ("static int microlink_usb_async_xfer_active_get(void)", "active = async_xfer_active;"),
            ("static void microlink_usb_async_xfer_active_set(int active)", "async_xfer_active = active;"),
            ("static int microlink_usb_async_pump_stop_get(void)", "stop = async_pump_stop;"),
            ("static void microlink_usb_async_pump_stop_set(int stop)", "async_pump_stop = stop;"),
            ("static int microlink_usb_device_gone_get(void)", "gone = usb_device_gone;"),
            ("static void microlink_usb_device_gone_set(int gone)", "usb_device_gone = gone;"),
        )
        helpers = [signature + " { pthread_mutex_lock(&async_lock); " + operation
                   + " pthread_mutex_unlock(&async_lock); }" for signature, operation in operations]
        replay.validate_helper_locks("\n".join(helpers))
        for index in range(6):
            for token in ("pthread_mutex_lock(&async_lock);", "pthread_mutex_unlock(&async_lock);"):
                mutant = list(helpers)
                mutant[index] = mutant[index].replace(token, "/* removed */")
                with self.subTest(helper=index, token=token), self.assertRaises(replay.ValidationError):
                    replay.validate_helper_locks("\n".join(mutant))

    def test_extract_is_nonexecuting_and_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            scratch = Path(parent).resolve() / "new"
            with patch.object(replay.subprocess, "run") as run:
                replay.run_replay("synthetic unit", scratch, "extract", ())
            run.assert_not_called()
            generated = scratch / "usb_async_state_generated.c"
            self.assertEqual(generated.read_text(), "synthetic unit")
            with self.assertRaises(replay.ValidationError):
                replay.run_replay("replacement", scratch, "extract", ())
            self.assertEqual(generated.read_text(), "synthetic unit")

    def test_product_repository_output_is_rejected_before_execution(self) -> None:
        output = Path(replay.__file__).resolve().parents[2] / "forbidden-async-replay-output"
        with patch.object(replay.subprocess, "run") as run, self.assertRaisesRegex(replay.ValidationError, "overlaps"):
            replay.run_replay("synthetic unit", output, "extract", ())
        run.assert_not_called()
        self.assertFalse(output.exists())

    def test_inspection_failure_or_usb_linkage_prevents_execution(self) -> None:
        for stage in ("nm", "otool", "linkage"):
            with tempfile.TemporaryDirectory() as parent:
                responses = [subprocess.CompletedProcess([], 0, "", "")]
                if stage == "nm":
                    responses.append(subprocess.CalledProcessError(1, ["nm"]))
                else:
                    responses.append(subprocess.CompletedProcess([], 0, "U _malloc\n", ""))
                    responses.append(subprocess.CalledProcessError(1, ["otool"]) if stage == "otool"
                                     else subprocess.CompletedProcess([], 0, "binary:\n libusb.dylib\n", ""))
                with patch.object(replay.subprocess, "run", side_effect=responses) as run:
                    with self.subTest(stage=stage), self.assertRaises(replay.ValidationError):
                        replay.run_replay("unit", Path(parent).resolve() / "new", "green", ())
                    self.assertEqual(run.call_count, len(responses))

    def test_three_separate_green_cases_use_reviewed_tsan_options(self) -> None:
        cases = (
            ("pump", "async pump shared-state check passed\n"),
            ("device", "device-gone callback shared-state check passed\n"),
            ("active", "active callback shared-state check passed\n"),
        )
        responses = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "U _malloc\n", ""),
            subprocess.CompletedProcess([], 0, "binary:\n libSystem.B.dylib\n", ""),
            *(subprocess.CompletedProcess([], 0, output, "") for _, output in cases),
        ]
        with tempfile.TemporaryDirectory() as parent:
            scratch = Path(parent).resolve() / "new"
            with patch.object(replay.subprocess, "run", side_effect=responses) as run:
                self.assertEqual(replay.run_replay("unit", scratch, "green", ()), 0)
            calls = run.call_args_list
            self.assertEqual(len(calls), 6)
            self.assertNotIn("-Wno-unused-variable", calls[0].args[0])
            self.assertIn("-DEXPECT_CANDIDATE=1", calls[0].args[0])
            for call, (case, _) in zip(calls[3:], cases):
                self.assertEqual(call.args[0][-1], case)
                self.assertEqual(call.kwargs["timeout"], 15)
                self.assertEqual(call.kwargs["env"]["TSAN_OPTIONS"], replay.TSAN_OPTIONS)
                self.assertEqual((scratch / f"{case}.returncode.txt").read_text(), "0\n")

    def test_function_body_ignores_braces_in_comments_and_literals(self) -> None:
        source = 'int sample(void) { const char *s = "}"; /* { */ return 0; }'
        self.assertEqual(replay.function_body(source, "int sample(void)"),
                         '{ const char *s = "}"; /* { */ return 0; }')

    def test_function_body_skips_prototype_but_rejects_duplicate_definitions(self) -> None:
        source = "int sample(void); int sample(void) { return 0; }"
        self.assertEqual(replay.function_body(source, "int sample(void)"), "{ return 0; }")
        duplicate = "int sample(void) { return 0; } int sample(void) { return 1; }"
        with self.assertRaisesRegex(replay.ValidationError, "definition marker"):
            replay.function_body(duplicate, "int sample(void)")

    def test_code_only_ignores_comment_mentions(self) -> None:
        self.assertNotIn("async_pump_stop", replay.code_only("/* async_pump_stop */ return 0;"))
        self.assertIn("async_pump_stop", replay.code_only("async_pump_stop = 1;"))

    def test_red_requires_exact_race_class_not_any_crash(self) -> None:
        evidence = "ThreadSanitizer: data race in microlink_usb_async_pump from writer_thread"
        self.assertTrue(replay.red_output_is_expected(66, "", evidence, "microlink_usb_async_pump", "writer_thread"))
        self.assertFalse(replay.red_output_is_expected(66, "", "segmentation fault", "microlink_usb_async_pump", "writer_thread"))
        self.assertFalse(replay.red_output_is_expected(66, "", evidence, "other_function", "writer_thread"))
        self.assertFalse(replay.red_output_is_expected(66, "", evidence, "microlink_usb_async_pump", "other_thread"))
        self.assertFalse(replay.red_output_is_expected(66, "", evidence, "microlink_usb_async_pump", "writer_thread", "async_pump_stop"))
        self.assertTrue(replay.red_output_is_expected(66, "", evidence + "\nLocation is global 'async_pump_stop'",
                                                    "microlink_usb_async_pump", "writer_thread", "async_pump_stop"))

    def test_red_rejects_tsan_runtime_unavailable(self) -> None:
        evidence = "FATAL: ThreadSanitizer: unexpected memory mapping"
        self.assertFalse(replay.red_output_is_expected(66, "", evidence, "microlink_usb_async_pump", "writer_thread"))

    def test_green_requires_exact_stdout_and_empty_stderr(self) -> None:
        expected = "callback shared-state check passed\n"
        self.assertTrue(replay.green_output_is_expected(0, expected, "", expected))
        self.assertFalse(replay.green_output_is_expected(0, "", "", expected))
        self.assertFalse(replay.green_output_is_expected(0, expected, "warning\n", expected))
        self.assertFalse(replay.green_output_is_expected(1, expected, "", expected))

    def test_scratch_rejects_preexisting_path(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            existing = Path(parent) / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(replay.ValidationError, "new"):
                replay.scratch_path(existing, ())

    def test_scratch_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "target"
            target.mkdir()
            link = Path(parent) / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(replay.ValidationError, "symlink"):
                replay.scratch_path(link, ())

    def test_scratch_rejects_source_checkout_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "source"
            root.mkdir()
            root = root.resolve()
            child = root / "output"
            with self.assertRaisesRegex(replay.ValidationError, "overlaps"):
                replay.scratch_path(child, (root,))

    def test_pins_are_sha256_sized_and_distinct(self) -> None:
        self.assertEqual(len(replay.BASELINE_SHA256), 64)
        self.assertEqual(len(replay.CANDIDATE_SHA256), 64)
        self.assertNotEqual(replay.BASELINE_SHA256, replay.CANDIDATE_SHA256)


if __name__ == "__main__":
    unittest.main()
