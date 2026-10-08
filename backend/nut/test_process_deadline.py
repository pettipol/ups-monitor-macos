from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

import process_deadline as runner


class BoundedProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        digest = hashlib.sha256()
        with open(cls.python, "rb") as executable:
            for block in iter(lambda: executable.read(1024 * 1024), b""):
                digest.update(block)
        cls.python_sha256 = digest.hexdigest()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="process-deadline-")
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)

    def output_directory(self, name: str = "run") -> Path:
        return self.parent / name

    def run_python(
        self,
        code: str,
        *,
        name: str = "run",
        timeout: float = 2,
        grace: float = 0.1,
        maximum_output_bytes: int = 16_384,
        private_nut_environment: bool = False,
    ) -> runner.BoundedRunResult:
        return runner.run_bounded(
            [self.python, "-c", code],
            executable_sha256=self.python_sha256,
            output_directory=self.output_directory(name),
            timeout_seconds=timeout,
            termination_grace_seconds=grace,
            maximum_output_bytes=maximum_output_bytes,
            private_nut_environment=private_nut_environment,
        )

    def test_success_and_nonzero_exit_capture_private_raw_output(self) -> None:
        success = self.run_python("import sys; print('fixture-out'); print('fixture-err', file=sys.stderr)")
        directory = self.output_directory()
        self.assertEqual(success.status, runner.RunStatus.EXITED)
        self.assertEqual(success.returncode, 0)
        self.assertEqual((directory / "stdout.bin").read_bytes(), b"fixture-out\n")
        self.assertEqual((directory / "stderr.bin").read_bytes(), b"fixture-err\n")
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((directory / "stdout.bin").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((directory / "stderr.bin").stat().st_mode), 0o600)

        failed = self.run_python("raise SystemExit(7)", name="nonzero")
        self.assertEqual(failed.status, runner.RunStatus.EXITED)
        self.assertEqual(failed.returncode, 7)

    def test_timeout_kills_and_reaps_child_ignoring_term(self) -> None:
        code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        started = time.monotonic()
        result = self.run_python(code, timeout=0.15, grace=0.1)
        elapsed = time.monotonic() - started
        self.assertEqual(result.status, runner.RunStatus.TIMED_OUT)
        self.assertEqual(result.trigger, runner.RunTrigger.TIMEOUT)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertLess(elapsed, 2)

    def test_flood_is_capped_across_both_streams(self) -> None:
        code = "import os\nblock=b'x'*4096\nwhile True:\n os.write(1, block)\n os.write(2, block)"
        result = self.run_python(code, maximum_output_bytes=4096)
        total = result.stdout_bytes + result.stderr_bytes
        self.assertEqual(result.status, runner.RunStatus.OUTPUT_LIMIT)
        self.assertEqual(result.trigger, runner.RunTrigger.OUTPUT_LIMIT)
        self.assertLessEqual(total, 4096)
        self.assertEqual((self.output_directory() / "stdout.bin").stat().st_size, result.stdout_bytes)
        self.assertEqual((self.output_directory() / "stderr.bin").stat().st_size, result.stderr_bytes)

    def test_hash_mismatch_and_invalid_parameters_never_spawn(self) -> None:
        output = self.output_directory()
        with mock.patch.object(runner.subprocess, "Popen", side_effect=AssertionError("spawned")) as spawn:
            with self.assertRaises(runner.BoundedRunError) as mismatch:
                runner.run_bounded(
                    [self.python, "-c", "pass"],
                    executable_sha256="0" * 64,
                    output_directory=output,
                    timeout_seconds=1,
                )
            self.assertEqual(mismatch.exception.code, runner.RunErrorCode.HASH_MISMATCH)
            self.assertNotIn(self.python, str(mismatch.exception))
            self.assertFalse(output.exists())

            with self.assertRaises(runner.BoundedRunError) as invalid:
                runner.run_bounded(
                    [self.python, "-c", "pass"],
                    executable_sha256=self.python_sha256,
                    output_directory=output,
                    timeout_seconds=float("inf"),
                )
            self.assertEqual(invalid.exception.code, runner.RunErrorCode.INVALID_ARGUMENT)
            spawn.assert_not_called()

    def test_rejects_executable_directory_existing_output_and_file_parent(self) -> None:
        with self.assertRaises(runner.BoundedRunError) as bad_executable:
            runner.run_bounded(
                [str(self.parent), "-c", "pass"],
                executable_sha256=self.python_sha256,
                output_directory=self.output_directory("bad-executable"),
                timeout_seconds=1,
            )
        self.assertEqual(bad_executable.exception.code, runner.RunErrorCode.EXECUTABLE_REJECTED)

        existing = self.output_directory("existing")
        existing.mkdir(mode=0o700)
        with self.assertRaises(runner.BoundedRunError) as existing_output:
            self.run_python("pass", name="existing")
        self.assertEqual(existing_output.exception.code, runner.RunErrorCode.OUTPUT_LOCATION_REJECTED)

        file_parent = self.parent / "not-a-directory"
        file_parent.write_text("fixture", encoding="ascii")
        with self.assertRaises(runner.BoundedRunError) as bad_parent:
            self.run_python("pass", name="not-a-directory/child")
        self.assertEqual(bad_parent.exception.code, runner.RunErrorCode.OUTPUT_CREATION_FAILED)

    def test_pipe_inherited_by_short_lived_descendant_does_not_delay_return(self) -> None:
        descendant = "import time; time.sleep(0.35)"
        code = (
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
            "print('direct-child-done')"
        )
        started = time.monotonic()
        result = self.run_python(code, timeout=1)
        elapsed = time.monotonic() - started
        self.assertEqual(result.status, runner.RunStatus.OUTPUT_INCOMPLETE)
        self.assertEqual(result.trigger, runner.RunTrigger.OUTPUT_INCOMPLETE)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.output_directory() / "stdout.bin").read_bytes(), b"direct-child-done\n")
        self.assertLess(elapsed, 2)
        time.sleep(0.4)

    def test_private_nut_environment_uses_new_paths_and_drops_parent_variables(self) -> None:
        code = (
            "import json,os; print(json.dumps({key: os.environ.get(key) for key in "
            "('NUT_STATEPATH','NUT_CONFPATH','NUT_DEBUG_LEVEL','NUT_DEBUG_SYSLOG','NUT_PARENT_ONLY')}))"
        )
        with mock.patch.dict(os.environ, {
            "NUT_STATEPATH": "/parent/state",
            "NUT_CONFPATH": "/parent/conf",
            "NUT_DEBUG_LEVEL": "9",
            "NUT_DEBUG_SYSLOG": "default",
            "NUT_PARENT_ONLY": "must-not-propagate",
        }):
            result = self.run_python(code, private_nut_environment=True)
        directory = self.output_directory()
        self.assertEqual(result.status, runner.RunStatus.EXITED)
        child_environment = json.loads((directory / "stdout.bin").read_text(encoding="ascii"))
        self.assertEqual(child_environment["NUT_STATEPATH"], str(directory / "state"))
        self.assertEqual(child_environment["NUT_CONFPATH"], str(directory / "conf"))
        self.assertEqual(child_environment["NUT_DEBUG_LEVEL"], "0")
        self.assertEqual(child_environment["NUT_DEBUG_SYSLOG"], "stderr")
        self.assertIsNone(child_environment["NUT_PARENT_ONLY"])
        self.assertEqual(stat.S_IMODE((directory / "state").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((directory / "conf").stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
