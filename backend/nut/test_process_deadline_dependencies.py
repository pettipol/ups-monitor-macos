from __future__ import annotations

from dataclasses import replace
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import MappingProxyType
from unittest import mock

import operator_session
import operator_stop
import process_deadline as runner


class DependencyPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.python = str(Path(sys.executable).resolve(strict=True))
        cls.python_sha256 = hashlib.sha256(Path(cls.python).read_bytes()).hexdigest()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="dependency-pin-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.loader_root = self.root / "opt" / "runtime"
        self.target_root = self.root / "cellar" / "runtime-1"
        self.library_relative = "lib/libsample.dylib"
        self.link_target = "../cellar/runtime-1"
        self.resolved_library = self.target_root / self.library_relative
        self.resolved_library.parent.mkdir(parents=True)
        self.resolved_library.write_bytes(b"synthetic dependency bytes\n")
        self.loader_root.parent.mkdir(parents=True)
        self.loader_root.symlink_to(self.link_target)
        self.pin = runner.DependencyPin(
            link_path=self.loader_root,
            loader_relative_path=self.library_relative,
            symlink_target=self.link_target,
            resolved_path=self.resolved_library,
            sha256=hashlib.sha256(self.resolved_library.read_bytes()).hexdigest(),
        )
        self.output_parent = self.root / "runs"
        self.output_parent.mkdir(mode=0o700)
        os.chmod(self.output_parent, 0o700)

    def run_bounded(self, output: Path, *, pins: tuple[runner.DependencyPin, ...] | None = None):
        return runner.run_bounded(
            [self.python, "-c", "pass"],
            executable_sha256=self.python_sha256,
            output_directory=output,
            timeout_seconds=3,
            termination_grace_seconds=1,
            maximum_output_bytes=4096,
            dependency_pins=(self.pin,) if pins is None else pins,
        )

    def assert_dependency_rejected_without_spawn(self, output: Path) -> None:
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                self.run_bounded(output)
        self.assertIs(raised.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
        popen.assert_not_called()

    def test_valid_pin_runs_one_synthetic_child(self) -> None:
        output = self.output_parent / "valid"
        real_popen = runner.subprocess.Popen
        child_count = [0]

        def count_child(*args, **kwargs):
            child_count[0] += 1
            return real_popen(*args, **kwargs)

        with mock.patch.object(runner.subprocess, "Popen", side_effect=count_child):
            result = self.run_bounded(output)
        self.assertEqual(child_count[0], 1)
        self.assertEqual(result.status, runner.RunStatus.EXITED)
        self.assertEqual((result.returncode, result.stdout_bytes, result.stderr_bytes), (0, 0, 0))
        self.assertEqual((output / "stdout.bin").read_bytes(), b"")
        self.assertEqual((output / "stderr.bin").read_bytes(), b"")

    def test_bad_executable_hash_rejects_before_output_or_spawn(self) -> None:
        output = self.output_parent / "bad-executable"
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                runner.run_bounded(
                    [self.python, "-c", "pass"],
                    executable_sha256="0" * 64,
                    output_directory=output,
                    timeout_seconds=3,
                    dependency_pins=(self.pin,),
                )
        self.assertIs(raised.exception.code, runner.RunErrorCode.HASH_MISMATCH)
        self.assertFalse(output.exists())
        popen.assert_not_called()

    def test_bad_dependency_hash_rejects_before_output_or_spawn(self) -> None:
        output = self.output_parent / "bad-dependency"
        bad_pin = replace(self.pin, sha256="0" * 64)
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                self.run_bounded(output, pins=(bad_pin,))
        self.assertIs(raised.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
        self.assertFalse(output.exists())
        popen.assert_not_called()

    def test_wrong_symlink_target_and_unexpected_link_type_reject(self) -> None:
        output = self.output_parent / "wrong-link"
        self.loader_root.unlink()
        self.loader_root.symlink_to("../../cellar/other-runtime")
        self.assert_dependency_rejected_without_spawn(output)
        self.loader_root.unlink()
        self.loader_root.mkdir()
        self.assert_dependency_rejected_without_spawn(output)
        self.assertFalse(output.exists())

    def test_resolved_library_symlink_is_rejected(self) -> None:
        output = self.output_parent / "resolved-symlink"
        actual_file = self.resolved_library.with_name("actual-library")
        actual_file.write_bytes(self.resolved_library.read_bytes())
        self.resolved_library.unlink()
        self.resolved_library.symlink_to(actual_file.name)
        self.assert_dependency_rejected_without_spawn(output)
        self.assertFalse(output.exists())

    def test_fifo_target_rejects_without_blocking_or_spawn(self) -> None:
        fifo_root = self.root / "cellar" / "fifo-runtime"
        fifo_library = fifo_root / self.library_relative
        fifo_library.parent.mkdir(parents=True)
        os.mkfifo(fifo_library)
        self.loader_root.unlink()
        self.link_target = "../cellar/fifo-runtime"
        self.loader_root.symlink_to(self.link_target)
        pin = replace(
            self.pin,
            symlink_target=self.link_target,
            resolved_path=fifo_library,
        )
        output = self.output_parent / "fifo"
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                self.run_bounded(output, pins=(pin,))
        self.assertIs(raised.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
        self.assertFalse(output.exists())
        popen.assert_not_called()

    def test_same_bytes_target_replacement_during_output_setup_is_rejected(self) -> None:
        output = self.output_parent / "changed-target"
        create_output = runner._create_output_files
        real_open = os.open
        target_fds: list[int] = []
        output_fds: list[int] = []

        def track_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if Path(path) == self.resolved_library:
                target_fds.append(descriptor)
            return descriptor

        def create_then_replace(*args, **kwargs):
            result = create_output(*args, **kwargs)
            output_fds.extend(result[:4])
            replacement = self.resolved_library.with_name("replacement")
            replacement.write_bytes(self.resolved_library.read_bytes())
            os.replace(replacement, self.resolved_library)
            return result

        with mock.patch.object(runner.os, "open", side_effect=track_open), \
             mock.patch.object(runner, "_create_output_files", side_effect=create_then_replace), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                self.run_bounded(output)
        self.assertIs(raised.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
        self.assertTrue((output / "stdout.bin").is_file())
        self.assertEqual((output / "stdout.bin").stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(target_fds), 2)
        for descriptor in target_fds:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        self.assertEqual(len(output_fds), 4)
        for descriptor in output_fds:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        popen.assert_not_called()

    def test_same_bytes_symlink_replacement_during_output_setup_is_rejected(self) -> None:
        output = self.output_parent / "changed-link"
        create_output = runner._create_output_files

        def create_then_replace(*args, **kwargs):
            result = create_output(*args, **kwargs)
            replacement_link = self.loader_root.with_name("replacement-link")
            replacement_link.symlink_to(self.link_target)
            os.replace(replacement_link, self.loader_root)
            return result

        with mock.patch.object(runner, "_create_output_files", side_effect=create_then_replace), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                self.run_bounded(output)
        self.assertIs(raised.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
        self.assertTrue((output / "stdout.bin").is_file())
        popen.assert_not_called()

    def test_same_bytes_executable_replacement_during_output_setup_is_rejected(self) -> None:
        output = self.output_parent / "changed-executable"
        executable = self.root / "synthetic-executable"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        create_output = runner._create_output_files

        def create_then_replace(*args, **kwargs):
            result = create_output(*args, **kwargs)
            replacement = executable.with_name("replacement-executable")
            replacement.write_bytes(executable.read_bytes())
            replacement.chmod(0o700)
            os.replace(replacement, executable)
            return result

        with mock.patch.object(runner, "_create_output_files", side_effect=create_then_replace), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                runner.run_bounded(
                    [str(executable)],
                    executable_sha256=executable_hash,
                    output_directory=output,
                    timeout_seconds=3,
                    dependency_pins=(self.pin,),
                )
        self.assertIs(raised.exception.code, runner.RunErrorCode.EXECUTABLE_REJECTED)
        self.assertTrue((output / "stdout.bin").is_file())
        popen.assert_not_called()

    def test_executable_replacement_during_second_dependency_audit_is_rejected(self) -> None:
        output = self.output_parent / "changed-executable-during-audit"
        executable = self.root / "synthetic-executable-during-audit"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        verify_dependencies = runner._verify_dependency_pins
        calls = [0]

        def verify_then_replace(pins):
            snapshot = verify_dependencies(pins)
            calls[0] += 1
            if calls[0] == 2:
                replacement = executable.with_name("replacement-during-audit")
                replacement.write_bytes(executable.read_bytes())
                replacement.chmod(0o700)
                os.replace(replacement, executable)
            return snapshot

        with mock.patch.object(runner, "_verify_dependency_pins", side_effect=verify_then_replace), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                runner.run_bounded(
                    [str(executable)],
                    executable_sha256=executable_hash,
                    output_directory=output,
                    timeout_seconds=3,
                    dependency_pins=(self.pin,),
                )
        self.assertEqual(calls[0], 2)
        self.assertIs(raised.exception.code, runner.RunErrorCode.EXECUTABLE_REJECTED)
        self.assertTrue((output / "stdout.bin").is_file())
        popen.assert_not_called()

    def test_replacement_during_hash_is_rejected_and_descriptor_is_closed(self) -> None:
        output = self.output_parent / "changed-during-hash"
        self.resolved_library.write_bytes(b"X" * (2 * 1024 * 1024 + 1))
        self.pin = replace(
            self.pin,
            sha256=hashlib.sha256(self.resolved_library.read_bytes()).hexdigest(),
        )
        target_identity = self.resolved_library.stat()
        identity = (target_identity.st_dev, target_identity.st_ino)
        real_read = os.read
        replaced = [False]
        opened_target_fds: list[int] = []

        def read_and_replace(fd: int, length: int) -> bytes:
            data = real_read(fd, length)
            info = os.fstat(fd)
            if not replaced[0] and (info.st_dev, info.st_ino) == identity:
                opened_target_fds.append(fd)
                replacement = self.resolved_library.with_name("replacement")
                replacement.write_bytes(self.resolved_library.read_bytes())
                os.replace(replacement, self.resolved_library)
                replaced[0] = True
            return data

        with mock.patch.object(runner.os, "read", side_effect=read_and_replace), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.BoundedRunError) as raised:
                self.run_bounded(output)
        self.assertTrue(replaced[0])
        self.assertIs(raised.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
        self.assertFalse(output.exists())
        self.assertEqual(len(opened_target_fds), 1)
        with self.assertRaises(OSError):
            os.fstat(opened_target_fds[0])
        popen.assert_not_called()

    def test_cancel_during_dependency_audit_prevents_output_and_spawn(self) -> None:
        output = self.output_parent / "cancel-during-audit"
        event = threading.Event()
        verify = runner._verify_dependency_pins

        def verify_then_cancel(pins):
            result = verify(pins)
            event.set()
            return result

        with mock.patch.object(runner, "_verify_dependency_pins", side_effect=verify_then_cancel), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run_bounded(
                [self.python, "-c", "pass"],
                executable_sha256=self.python_sha256,
                output_directory=output,
                timeout_seconds=3,
                dependency_pins=(self.pin,),
                cancel_event=event,
            )
        self.assertEqual((result.status, result.trigger, result.returncode), (
            runner.RunStatus.CANCELLED, runner.RunTrigger.CANCELLED, None,
        ))
        self.assertFalse(output.exists())
        popen.assert_not_called()

    def test_hash_close_failures_use_fixed_errors_and_preserve_active_error(self) -> None:
        executable = self.root / "close-test-executable"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        real_open = os.open
        real_close = os.close
        tracked_fds: set[int] = set()

        def track_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if Path(path) in (executable, self.resolved_library):
                tracked_fds.add(descriptor)
            return descriptor

        def close_then_raise(descriptor: int) -> None:
            real_close(descriptor)
            if descriptor in tracked_fds:
                tracked_fds.remove(descriptor)
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
                raise OSError(f"private close path: {self.root}")

        with mock.patch.object(runner.os, "open", side_effect=track_open), \
             mock.patch.object(runner.os, "close", side_effect=close_then_raise):
            with self.assertRaises(runner.BoundedRunError) as close_failure:
                runner._verify_executable_snapshot(str(executable), executable_hash)
            self.assertIs(close_failure.exception.code, runner.RunErrorCode.EXECUTABLE_REJECTED)
            self.assertNotIn(str(self.root), str(close_failure.exception))

            with self.assertRaises(runner.BoundedRunError) as hash_failure:
                runner._verify_executable_snapshot(str(executable), "0" * 64)
            self.assertIs(hash_failure.exception.code, runner.RunErrorCode.HASH_MISMATCH)
            self.assertNotIn(str(self.root), str(hash_failure.exception))

            with self.assertRaises(runner.BoundedRunError) as dependency_close_failure:
                runner._verify_dependency_pin(self.pin)
            self.assertIs(dependency_close_failure.exception.code, runner.RunErrorCode.DEPENDENCY_REJECTED)
            self.assertNotIn(str(self.root), str(dependency_close_failure.exception))

        output = self.output_parent / "close-failure-in-caller-except"
        with mock.patch.object(runner.os, "open", side_effect=track_open), \
             mock.patch.object(runner.os, "close", side_effect=close_then_raise), \
             mock.patch.object(runner.subprocess, "Popen") as popen:
            try:
                raise RuntimeError("ambient caller exception")
            except RuntimeError:
                with self.assertRaises(runner.BoundedRunError) as ambient_close_failure:
                    runner.run_bounded(
                        [str(executable)],
                        executable_sha256=executable_hash,
                        output_directory=output,
                        timeout_seconds=3,
                        dependency_pins=(self.pin,),
                    )
        self.assertIs(ambient_close_failure.exception.code, runner.RunErrorCode.EXECUTABLE_REJECTED)
        self.assertNotIn(str(self.root), str(ambient_close_failure.exception))
        self.assertFalse(output.exists())
        popen.assert_not_called()

    def test_cli_rejects_bad_library_hash_without_path_output_or_spawn(self) -> None:
        output_parent = self.root / "cli-runs"
        output_parent.mkdir(mode=0o700)
        os.chmod(output_parent, 0o700)
        bad_pin = replace(self.pin, sha256="0" * 64)
        profile = operator_session.OperatorProfile(
            argv=(self.python, "-c", "pass"),
            executable_sha256=self.python_sha256,
            output_parent=output_parent,
            timeout_seconds=3,
            termination_grace_seconds=1,
            maximum_output_bytes=4096,
            dependency_pins=(bad_pin,),
        )
        captured = io.StringIO()
        with mock.patch.object(operator_session, "PROFILES", MappingProxyType({"synthetic": profile})), \
             mock.patch.object(runner.subprocess, "Popen") as popen, \
             contextlib.redirect_stdout(captured):
            returncode = operator_session.main(["--profile", "synthetic", "--execute"])
        raw = captured.getvalue()
        payload = json.loads(raw)
        self.assertEqual(returncode, 1)
        self.assertEqual((payload["status"], payload["error"]), ("error", "dependency_rejected"))
        self.assertNotIn(str(self.root), raw)
        self.assertEqual(list(output_parent.iterdir()), [])
        popen.assert_not_called()

    def test_dependency_pins_are_forwarded_unchanged_through_adapter_and_profile(self) -> None:
        pins = (self.pin,)
        expected = runner.BoundedRunResult(
            runner.RunStatus.EXITED, runner.RunTrigger.COMPLETED, 0, 0, 0,
        )
        with mock.patch.object(operator_stop, "run_bounded", return_value=expected) as run:
            actual = operator_stop.run_operator_controlled(
                [self.python, "-c", "pass"],
                executable_sha256=self.python_sha256,
                output_directory=self.output_parent / "adapter",
                timeout_seconds=3,
                dependency_pins=pins,
            )
        self.assertIs(actual, expected)
        self.assertIs(run.call_args.kwargs["dependency_pins"], pins)

        profile = operator_session.OperatorProfile(
            argv=(self.python, "-c", "pass"),
            executable_sha256=self.python_sha256,
            output_parent=self.output_parent,
            timeout_seconds=3,
            termination_grace_seconds=1,
            maximum_output_bytes=4096,
            dependency_pins=pins,
        )
        with mock.patch.object(operator_session, "run_operator_controlled", return_value=expected) as run:
            payload, returncode = operator_session._run_profile(profile)
        self.assertEqual(returncode, 0)
        self.assertIsNone(payload["error"])
        self.assertIs(run.call_args.kwargs["dependency_pins"], pins)


if __name__ == "__main__":
    unittest.main()
