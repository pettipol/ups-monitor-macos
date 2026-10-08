"""Independent, synthetic regressions for the process supervision boundary."""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

import process_deadline as runner


class ProcessBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        with open(cls.python, "rb") as executable:
            cls.digest = hashlib.file_digest(executable, "sha256").hexdigest()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="ups-watchdog-boundary-")
        self.addCleanup(self.directory.cleanup)
        self.parent = Path(self.directory.name)

    def arguments(self, code: str = "pass") -> dict:
        return dict(argv=[self.python, "-c", code], executable_sha256=self.digest,
                    output_directory=self.parent / "capture", timeout_seconds=1)

    def test_inherited_pipe_is_not_reported_as_complete_output(self) -> None:
        code = "import subprocess,sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.5)']); print('fixture')"
        try:
            result = runner.run_bounded(**self.arguments(code))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.status.value, "output_incomplete")
        finally:
            # This fixture alone creates a short-lived descendant; it exits itself.
            time.sleep(0.6)

    def test_unreaped_child_on_io_error_is_explicit(self) -> None:
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.close(stdout_write)
        os.close(stderr_write)
        fake = mock.Mock()
        fake.poll.return_value = None
        fake.stdout = os.fdopen(stdout_read, "rb")
        fake.stderr = os.fdopen(stderr_read, "rb")
        with mock.patch.object(runner.subprocess, "Popen", return_value=fake), \
             mock.patch.object(runner, "_consume_events", side_effect=OSError("synthetic private detail")), \
             mock.patch.object(runner, "_reap_with_grace", return_value=False):
            with self.assertRaises(runner.BoundedRunError) as failure:
                runner.run_bounded(**self.arguments())
        self.assertEqual(failure.exception.code.value, "child_unreaped")
        self.assertNotIn("synthetic private detail", str(failure.exception))

    def test_huge_numeric_parameter_is_rejected_without_spawning(self) -> None:
        arguments = self.arguments()
        arguments["timeout_seconds"] = 10 ** 1000
        with mock.patch.object(runner.subprocess, "Popen") as spawn:
            with self.assertRaises(runner.BoundedRunError) as failure:
                runner.run_bounded(**arguments)
            self.assertEqual(failure.exception.code, runner.RunErrorCode.INVALID_ARGUMENT)
            spawn.assert_not_called()

    def test_world_writable_parent_is_rejected_without_spawning(self) -> None:
        self.parent.chmod(0o777)
        with mock.patch.object(runner.subprocess, "Popen", side_effect=AssertionError("must not launch")) as spawn:
            with self.assertRaises(runner.BoundedRunError):
                runner.run_bounded(**self.arguments())
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
