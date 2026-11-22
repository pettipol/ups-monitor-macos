from __future__ import annotations

import errno
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import process_deadline as runner


class _ClosedPipe:
    closed = True

    def fileno(self) -> int:
        return -1

    def close(self) -> None:
        self.closed = True


class _FakeSelector:
    def __init__(self, on_select=None) -> None:
        self.on_select = on_select

    def register(self, *_args, **_kwargs) -> None:
        return None

    def select(self, _timeout: float = 0) -> list[object]:
        if self.on_select is not None:
            self.on_select()
        return [object()] if self.on_select is None else []

    def get_map(self) -> dict[object, object]:
        return {}

    def close(self) -> None:
        return None


class _FakeProcess:
    pid = 48123

    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.stdout = _ClosedPipe()
        self.stderr = _ClosedPipe()
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -signal.SIGTERM

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -signal.SIGKILL


class ProcessGroupCleanupTests(unittest.TestCase):
    def test_group_absence_requires_esrch_and_treats_permission_as_uncertain(self) -> None:
        with mock.patch.object(runner.os, "killpg", side_effect=ProcessLookupError(errno.ESRCH, "gone")):
            self.assertTrue(runner._process_group_absent(48123))
        with mock.patch.object(runner.os, "killpg", side_effect=PermissionError(errno.EPERM, "denied")):
            self.assertFalse(runner._process_group_absent(48123))
        with mock.patch.object(runner.os, "killpg", side_effect=OSError(errno.EIO, "unknown")):
            self.assertFalse(runner._process_group_absent(48123))

    def test_exited_leader_still_signals_and_waits_for_owned_group(self) -> None:
        process = _FakeProcess(returncode=0)
        group_alive = True
        signal_calls: list[int] = []
        reap_calls: list[float] = []

        def killpg(pgid: int, sig: int) -> None:
            nonlocal group_alive
            self.assertEqual(pgid, process.pid)
            if sig == 0:
                if not group_alive:
                    raise ProcessLookupError(errno.ESRCH, "group gone")
                return
            signal_calls.append(int(sig))
            if sig == signal.SIGKILL:
                group_alive = False

        def bounded_wait(_process, seconds, _selector, _streams, **kwargs) -> bool:
            reap_calls.append(seconds)
            self.assertEqual(kwargs.get("owned_pgid"), process.pid)
            return seconds == runner._KILL_REAP_SECONDS and not group_alive

        with mock.patch.object(runner.os, "killpg", side_effect=killpg), \
                mock.patch.object(runner, "_reap_with_grace", side_effect=bounded_wait):
            cleaned = runner._terminate_and_reap(process, 0.25, None, [], process.pid)

        self.assertTrue(cleaned)
        self.assertEqual(signal_calls, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(reap_calls, [0.25, runner._KILL_REAP_SECONDS])
        self.assertFalse(group_alive)
        self.assertEqual(process.terminate_calls, 0)
        self.assertEqual(process.kill_calls, 0)

    def test_uncertain_group_state_fails_after_fixed_term_and_kill_budgets(self) -> None:
        process = _FakeProcess(returncode=0)
        signals: list[int] = []
        budgets: list[float] = []

        def denied_killpg(_pgid: int, sig: int) -> None:
            if sig != 0:
                signals.append(int(sig))
            raise PermissionError(errno.EPERM, "group state unavailable")

        def bounded_wait(_process, seconds, _selector, _streams, **_kwargs) -> bool:
            budgets.append(seconds)
            return False

        with mock.patch.object(runner.os, "killpg", side_effect=denied_killpg), \
                mock.patch.object(runner, "_reap_with_grace", side_effect=bounded_wait):
            cleaned = runner._terminate_and_reap(process, 0.25, None, [], process.pid)

        self.assertFalse(cleaned)
        self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(budgets, [0.25, runner._KILL_REAP_SECONDS])

    def test_esrch_before_cleanup_does_not_signal_reused_group_id(self) -> None:
        process = _FakeProcess(returncode=0)
        calls: list[tuple[int, int]] = []

        def absent(_pgid: int, sig: int) -> None:
            calls.append((process.pid, int(sig)))
            raise ProcessLookupError(errno.ESRCH, "group absent")

        with mock.patch.object(runner.os, "killpg", side_effect=absent):
            cleaned = runner._terminate_and_reap(process, 0.25, None, [], process.pid)
        self.assertTrue(cleaned)
        self.assertEqual(calls, [(process.pid, 0)])

    def test_unowned_legacy_cleanup_uses_only_direct_child_signals(self) -> None:
        process = _FakeProcess()
        calls: list[int] = []

        def bounded_wait(_process, seconds, _selector, _streams, **_kwargs) -> bool:
            return seconds == runner._KILL_REAP_SECONDS

        with mock.patch.object(runner.os, "killpg", side_effect=AssertionError("legacy path must not signal groups")), \
                mock.patch.object(runner, "_reap_with_grace", side_effect=bounded_wait):
            cleaned = runner._terminate_and_reap(process, 0.25, None, [])
        self.assertTrue(cleaned)
        self.assertEqual((process.terminate_calls, process.kill_calls), (1, 0))

    def test_owned_signal_avoids_duplicate_delivery_and_limits_direct_fallback(self) -> None:
        scenarios = (
            ("same-group", False, False, False, False, 0, 1),
            ("escaped-group", False, False, False, False, 1, 1),
            ("group-delivery-error", True, False, False, False, 1, 0),
            ("membership-query-error", False, True, False, False, 1, 1),
            ("leader-exits-during-query", False, False, True, False, 0, 1),
            ("leader-already-exited", False, False, False, True, 0, 0),
        )
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for name, group_error, query_error, exit_in_query, leader_exited, direct, queries in scenarios:
                with self.subTest(signal=sig.name, scenario=name):
                    process = _FakeProcess(returncode=0 if leader_exited else None)
                    group_calls: list[tuple[int, int]] = []
                    queried_pids: list[int] = []

                    def killpg(pgid: int, delivered_sig: int) -> None:
                        group_calls.append((pgid, int(delivered_sig)))
                        if group_error:
                            raise OSError(errno.EIO, "synthetic group delivery failure")

                    def getpgid(pid: int) -> int:
                        self.assertEqual(pid, process.pid)
                        queried_pids.append(pid)
                        if query_error:
                            raise OSError(errno.EIO, "synthetic membership query failure")
                        if exit_in_query:
                            process.returncode = -int(sig)
                        return process.pid if name == "same-group" else process.pid + 1

                    with mock.patch.object(runner.os, "killpg", side_effect=killpg), \
                            mock.patch.object(runner.os, "getpgid", side_effect=getpgid):
                        runner._signal_child(process, sig, process.pid)

                    self.assertEqual(group_calls, [(process.pid, int(sig))])
                    self.assertEqual(queried_pids, [process.pid] * queries)
                    self.assertEqual((process.terminate_calls + process.kill_calls), direct)
                    self.assertEqual(process.terminate_calls, int(direct and sig is signal.SIGTERM))
                    self.assertEqual(process.kill_calls, int(direct and sig is signal.SIGKILL))

    def _run_mocked_campaign(self, mode: str) -> tuple[runner.BoundedRunResult, list[int], dict[str, object]]:
        process = _FakeProcess(returncode=0 if mode == "normal-exit" else None)
        group_alive = True
        signals: list[int] = []
        event = threading.Event()

        def killpg(pgid: int, sig: int) -> None:
            nonlocal group_alive
            if pgid != process.pid:
                raise AssertionError("unexpected process group target")
            if sig == 0:
                if not group_alive:
                    raise ProcessLookupError(errno.ESRCH, "group gone")
                return
            signals.append(int(sig))
            if sig == signal.SIGKILL:
                group_alive = False
                if process.returncode is None:
                    process.returncode = -signal.SIGKILL

        selector = _FakeSelector(event.set if mode == "cancel" else None)
        if mode == "cap":
            selector.select = lambda _timeout=0: [object()]

        descriptors = [os.open(os.devnull, os.O_RDONLY) for _ in range(4)]
        fake_popen_kwargs: dict[str, object] = {}

        def create_output_files(*_args, **_kwargs):
            return (*descriptors, {})

        def popen(_argv, **kwargs):
            fake_popen_kwargs.update(kwargs)
            return process

        def consume_overflow(*_args, **_kwargs):
            return mode == "cap"

        output_path = Path(tempfile.gettempdir()) / f"run-deadline-mock-{mode}"
        try:
            with mock.patch.object(runner, "_verify_executable", side_effect=lambda path, _digest: path), \
                    mock.patch.object(runner, "_create_output_files", side_effect=create_output_files), \
                    mock.patch.object(runner.subprocess, "Popen", side_effect=popen), \
                    mock.patch.object(runner.os, "set_blocking"), \
                    mock.patch.object(runner.selectors, "DefaultSelector", return_value=selector), \
                    mock.patch.object(runner.os, "killpg", side_effect=killpg), \
                    mock.patch.object(runner.os, "getpgid", return_value=process.pid), \
                    mock.patch.object(runner, "_consume_events", side_effect=consume_overflow):
                result = runner.run_bounded(
                    ["/synthetic/replay"], executable_sha256="a" * 64,
                    output_directory=output_path, timeout_seconds=0.5,
                    termination_grace_seconds=0.01, maximum_output_bytes=128,
                    cancel_event=event,
                )
            return result, signals, fake_popen_kwargs
        finally:
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def test_normal_leader_exit_with_residual_group_is_incomplete(self) -> None:
        result, signals, popen_kwargs = self._run_mocked_campaign("normal-exit")
        self.assertEqual(result.status, runner.RunStatus.OUTPUT_INCOMPLETE)
        self.assertEqual(result.trigger, runner.RunTrigger.OUTPUT_INCOMPLETE)
        self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertTrue(popen_kwargs["start_new_session"] if "start_new_session" in popen_kwargs else True)

    def test_cancel_and_output_cap_terminate_owned_groups(self) -> None:
        for mode, expected in (("cancel", runner.RunTrigger.CANCELLED),
                               ("cap", runner.RunTrigger.OUTPUT_LIMIT)):
            with self.subTest(mode=mode):
                result, signals, popen_kwargs = self._run_mocked_campaign(mode)
                self.assertEqual(result.trigger, expected)
                self.assertEqual(result.status, runner.RunStatus.CANCELLED if mode == "cancel"
                                 else runner.RunStatus.OUTPUT_LIMIT)
                self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL])
                self.assertTrue(popen_kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
