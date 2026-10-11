# SPDX-License-Identifier: MIT
"""Synthetic contract tests for the pinned USB lifecycle replay runner."""

from __future__ import annotations

import hashlib
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_usb_async_state as async_replay  # noqa: E402
import replay_usb_guard_deadline as deadline_replay  # noqa: E402
import replay_usb_lifecycle_observation as replay  # noqa: E402


PUMP = "static void *microlink_usb_async_pump(void *arg)"
CALLBACK = "static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer)"
START = "static int microlink_usb_async_start(void)"
STOP = "static void microlink_usb_async_stop(void)"
CLOSE = "void microlink_usb_close(void)"


def synthetic_source() -> str:
    return """/* GPL header */
static int usb_device_gone = 0;
#define MLINK_USB_ASYNC_QUEUE_LEN 8U
static int async_state = 0;
static int microlink_usb_guard_remaining_ms_locked(unsigned int *remaining_ms)
{ *remaining_ms = 1; return 1; }
#else
static int async_fallback_state = 0;
#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */
static int microlink_usb_device_gone_get(void) { return usb_device_gone; }
static void microlink_usb_device_gone_set(int gone) { usb_device_gone = gone; }
static void *microlink_usb_async_pump(void *arg)
{ if (arg) { async_state++; } return NULL; }
static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer)
{ if (transfer) { async_state++; } }
static int microlink_usb_async_start(void) { async_state++; return 1; }
static void microlink_usb_async_stop(void) { async_state++; }
void microlink_usb_close(void) { microlink_usb_async_stop(); }
"""


class LifecycleRunnerTests(unittest.TestCase):
    def _mock_runner_source(self, parent: Path) -> tuple[Path, Path, dict[str, bytes]]:
        parent = parent.resolve()
        source = parent / "source"
        source.mkdir()
        scratch = parent / "scratch"
        contents = {name: b"synthetic pinned bytes" for name in replay.SOURCE_FILES}
        contents["drivers/apcmicrolink-usb.c"] = synthetic_source().encode("utf-8")
        return source, scratch, contents

    def test_source_head_and_hash_pins_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            for relative in replay.SOURCE_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic wrong source")

            wrong_head = subprocess.CompletedProcess([], 0, "0" * 40 + "\n", "")
            with patch.object(deadline_replay, "run_checked", return_value=wrong_head):
                with self.assertRaisesRegex(replay.ReplayError, "HEAD"):
                    replay.read_candidate(root)

            correct_head = subprocess.CompletedProcess([], 0, deadline_replay.BASE_HEAD + "\n", "")
            with patch.object(deadline_replay, "run_checked", return_value=correct_head):
                with self.assertRaisesRegex(replay.ReplayError, "source pin"):
                    replay.read_candidate(root)

            with patch.object(deadline_replay, "run_checked",
                              side_effect=subprocess.TimeoutExpired(["git"], 5)):
                with self.assertRaisesRegex(replay.ReplayError, "timed out"):
                    replay.read_candidate(root)

    def test_source_root_and_external_scratch_fences(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent).resolve()
            source = root / "candidate"
            source.mkdir()
            with self.assertRaisesRegex(replay.ReplayError, "source root"):
                replay.read_candidate(root / "absent")
            with self.assertRaisesRegex(replay.ReplayError, "external"):
                replay.read_candidate(Path(replay.__file__).resolve().parents[2])
            link = root / "candidate-link"
            link.symlink_to(source, target_is_directory=True)
            with self.assertRaisesRegex(replay.ReplayError, "real directory"):
                replay.read_candidate(link)
            with self.assertRaisesRegex(async_replay.ValidationError, "overlaps"):
                async_replay.scratch_path(source / "scratch", (source,))
            scratch_link = root / "scratch-link"
            scratch_link.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(async_replay.ValidationError, "symlink"):
                async_replay.scratch_path(scratch_link, ())

            repository = Path(replay.__file__).resolve().parents[2]
            with self.assertRaisesRegex(async_replay.ValidationError, "overlaps"):
                async_replay.scratch_path(repository / "forbidden-lifecycle-scratch", (repository,))

    def test_generated_functions_preserve_exact_source_bodies(self) -> None:
        source = synthetic_source()
        generated = replay.generate(source)
        self.assertTrue(generated.startswith("/* GPL header */"))
        self.assertIn("#define MLINK_USB_REPORT_TOTAL_LEN 64U", generated)
        feature_open = generated.index("#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)")
        region_start = generated.index("#define MLINK_USB_ASYNC_QUEUE_LEN")
        self.assertLess(feature_open, region_start)
        self.assertIn("#else\nstatic int async_fallback_state", generated[region_start:])
        feature_close = generated.index("#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */", region_start)
        device_helper = generated.index("static int microlink_usb_device_gone_get(void)")
        self.assertLess(feature_close, device_helper)
        for signature in (
            "static int microlink_usb_device_gone_get(void)",
            "static void microlink_usb_device_gone_set(int gone)",
            PUMP, CALLBACK, START, STOP, CLOSE,
        ):
            self.assertEqual(
                async_replay.function_body(generated, signature),
                async_replay.function_body(source, signature),
                signature,
            )

    def test_generated_function_extraction_rejects_missing_or_ambiguous_body(self) -> None:
        source = synthetic_source().replace(PUMP, "static void *missing_pump(void *arg)")
        with self.assertRaises(replay.ReplayError):
            replay.generate(source)

        duplicate = synthetic_source() + "\n" + START + " { return 1; }\n"
        with self.assertRaises(replay.ReplayError):
            replay.generate(duplicate)

    def test_binary_symbol_inspection_rejects_hardware_and_driver_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            binary = root / "fixture"
            binary.write_bytes(b"synthetic")
            for symbols, libraries in (
                ("U _libusb_submit_transfer\n", "fixture:\n libSystem.B.dylib\n"),
                ("U _malloc\n", "fixture:\n /System/Library/Frameworks/IOKit.framework/IOKit\n"),
                ("U _upsdrv_initups\n", "fixture:\n libSystem.B.dylib\n"),
            ):
                outputs = [
                    subprocess.CompletedProcess([], 0, symbols, ""),
                    subprocess.CompletedProcess([], 0, libraries, ""),
                ]
                with patch.object(deadline_replay, "run_checked", side_effect=outputs):
                    with self.assertRaisesRegex(ValueError, "unexpectedly links"):
                        deadline_replay.inspect_binary(binary, root)

    def test_binary_symbol_inspection_records_clean_local_stub_linkage(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            binary = root / "fixture"
            binary.write_bytes(b"synthetic")
            outputs = [
                subprocess.CompletedProcess([], 0, "U _pthread_mutex_lock\n", ""),
                subprocess.CompletedProcess([], 0, "fixture:\n libSystem.B.dylib\n", ""),
            ]
            with patch.object(deadline_replay, "run_checked", side_effect=outputs):
                deadline_replay.inspect_binary(binary, root)
            self.assertIn("_pthread_mutex_lock", (root / "nm.txt").read_text())
            self.assertIn("libSystem.B.dylib", (root / "otool.txt").read_text())

    def test_eight_profile_cases_have_exact_red_and_control_contracts(self) -> None:
        self.assertEqual(len(replay.EXPECTED_CASES), 8)
        for profile in ("ordinary", "guarded"):
            for scenario in ("create-failure", "cancel-pending", "cancel-not-found"):
                case = f"{profile}-{scenario}"
                with self.subTest(case=case):
                    replay.validate_case_result(
                        case, 1, "RED pending transfer observed at close with owner cleared\n", ""
                    )
            replay.validate_case_result(
                f"{profile}-cancel-completed", 0,
                "CONTROL cancellation callback reaped before close\n", "",
            )

    def test_unexpected_case_output_or_return_code_is_not_accepted_as_red(self) -> None:
        case = "ordinary-create-failure"
        for result in (
            (0, "RED pending transfer observed at close with owner cleared\n", ""),
            (1, "different failure\n", ""),
            (1, "RED pending transfer observed at close with owner cleared\n", "crash\n"),
        ):
            with self.subTest(result=result), self.assertRaises(replay.ReplayError):
                replay.validate_case_result(case, *result)

    def test_case_timeout_is_a_harness_failure_not_a_red_observation(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            scratch = Path(parent)
            error = subprocess.TimeoutExpired(["fixture"], replay.CASE_TIMEOUT_SECONDS)
            with patch.object(deadline_replay, "run_checked", side_effect=error):
                with self.assertRaisesRegex(replay.ReplayError, "timed out"):
                    replay.run_case(scratch / "fixture", "ordinary-create-failure", scratch)
            self.assertEqual((scratch / "ordinary-create-failure.timeout").read_text(), "timeout\n")

    def test_programmatic_invalid_mode_fails_before_source_or_scratch_access(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            scratch = Path(parent) / "not-created"
            with self.assertRaisesRegex(replay.ReplayError, "invalid mode"):
                replay.run("other", Path(parent) / "missing-source", scratch)
            self.assertFalse(scratch.exists())

    def test_extract_mode_writes_scope_without_compiler_or_case_execution(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            source, scratch, contents = self._mock_runner_source(Path(parent))
            with patch.object(replay, "read_candidate", return_value=(source, contents)), \
                 patch.object(deadline_replay, "validate_candidate_callpaths"), \
                 patch.object(deadline_replay, "run_checked") as checked_run, \
                 patch.object(replay, "run_case") as case_run, \
                 redirect_stdout(StringIO()):
                self.assertEqual(replay.run("extract", source, scratch), 0)
            checked_run.assert_not_called()
            case_run.assert_not_called()
            manifest = json.loads((scratch / "manifest.json").read_text())
            self.assertEqual(manifest["result"], "extracted; compile and execution not requested")
            self.assertEqual(manifest["compiler_command"], None)
            self.assertTrue((scratch / replay.GENERATED_NAME).is_file())

    def test_compile_failure_prevents_binary_inspection_and_case_execution(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            source, scratch, contents = self._mock_runner_source(Path(parent))
            compile_failure = subprocess.CompletedProcess([], 1, "", "synthetic compiler error")
            with patch.object(replay, "read_candidate", return_value=(source, contents)), \
                 patch.object(deadline_replay, "validate_candidate_callpaths"), \
                 patch.object(deadline_replay, "run_checked", return_value=compile_failure) as checked_run, \
                 patch.object(deadline_replay, "inspect_binary") as inspect, \
                 patch.object(replay, "run_case") as case_run, \
                 redirect_stdout(StringIO()):
                with self.assertRaisesRegex(replay.ReplayError, "failed compilation"):
                    replay.run("observe", source, scratch)
            self.assertEqual(checked_run.call_count, 1)
            inspect.assert_not_called()
            case_run.assert_not_called()
            manifest = json.loads((scratch / "manifest.json").read_text())
            self.assertEqual(manifest["result"], "failed: compile contract")

    def test_binary_inspection_rejection_prevents_case_execution(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            source, scratch, contents = self._mock_runner_source(Path(parent))
            compile_ok = subprocess.CompletedProcess([], 0, "", "")
            with patch.object(replay, "read_candidate", return_value=(source, contents)), \
                 patch.object(deadline_replay, "validate_candidate_callpaths"), \
                 patch.object(deadline_replay, "run_checked", return_value=compile_ok) as checked_run, \
                 patch.object(deadline_replay, "inspect_binary", side_effect=ValueError("forbidden linkage")), \
                 patch.object(replay, "run_case") as case_run, \
                 redirect_stdout(StringIO()):
                with self.assertRaisesRegex(replay.ReplayError, "inspection rejected"):
                    replay.run("observe", source, scratch)
            self.assertEqual(checked_run.call_count, 1)
            case_run.assert_not_called()
            manifest = json.loads((scratch / "manifest.json").read_text())
            self.assertEqual(manifest["result"], "failed: binary inspection contract")

    def test_compile_timeout_is_failure_and_never_classified_as_red(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            source, scratch, contents = self._mock_runner_source(Path(parent))
            timeout = subprocess.TimeoutExpired(["cc"], replay.COMPILE_TIMEOUT_SECONDS)
            with patch.object(replay, "read_candidate", return_value=(source, contents)), \
                 patch.object(deadline_replay, "validate_candidate_callpaths"), \
                 patch.object(deadline_replay, "run_checked", side_effect=timeout) as checked_run, \
                 patch.object(deadline_replay, "inspect_binary") as inspect, \
                 patch.object(replay, "run_case") as case_run, \
                 redirect_stdout(StringIO()):
                with self.assertRaisesRegex(replay.ReplayError, "compile timed out"):
                    replay.run("observe", source, scratch)
            self.assertEqual(checked_run.call_count, 1)
            inspect.assert_not_called()
            case_run.assert_not_called()
            self.assertEqual((scratch / "compile.timeout").read_text(), "timeout\n")
            manifest = json.loads((scratch / "manifest.json").read_text())
            self.assertEqual(manifest["result"], "failed: compile timed out")

    def test_manifest_contains_only_scope_hashes_and_declared_proof_boundary(self) -> None:
        contents = {name: b"synthetic" for name in replay.SOURCE_FILES}
        compiler_command = ["cc", "-std=c99", "fixture.c"]
        manifest = replay.scope_manifest("extract", contents, b"generated",
                                         b"fixture", compiler_command)
        self.assertEqual(manifest["source_sha256"], {
            name: hashlib.sha256(data).hexdigest() for name, data in contents.items()
        })
        self.assertEqual(manifest["generated_sha256"], hashlib.sha256(b"generated").hexdigest())
        self.assertEqual(manifest["c_fixture_sha256"], hashlib.sha256(b"fixture").hexdigest())
        self.assertEqual(manifest["compiler_command"], compiler_command)
        self.assertIn("no USB/NUT/IOKit", manifest["runtime_scope"])


if __name__ == "__main__":
    unittest.main()
