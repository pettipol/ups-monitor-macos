#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Supervisor checks called only by the source-built, audited fake NUT replay.

There is intentionally no CLI or unittest discovery entry point. The caller
must build and audit the synthetic HIDAPI executable before passing its hash.
This exercises process cancellation, not real HIDAPI shutdown or device safety.
"""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import signal
import stat
from threading import Event, Thread

from process_deadline import RunStatus, RunTrigger, run_bounded


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _cancel_after_ready(output: Path, ready: Event, cancel: Event,
                        done: Event, errors: list[str]) -> None:
    while not done.wait(0.01):
        try:
            with (output / "stdout.bin").open("rb") as stream:
                captured = stream.read(16385)
        except FileNotFoundError:
            continue
        except OSError:
            errors.append("could not read synthetic child readiness")
            cancel.set()
            return
        if len(captured) > 16384:
            errors.append("synthetic readiness output exceeded bound")
            cancel.set()
            return
        if b"READY" in captured.splitlines():
            ready.set()
            cancel.set()
            return


def run_supervisor_checks(binary: Path, output_parent: Path, *,
                          executable_sha256: str) -> dict[str, object]:
    """Run two owned fake children; require bounded, fully reaped cancellation.

    The parent directory must be new/private and owned by the caller. This
    helper does not register an operational driver profile or install handlers
    in the parent. Only process_deadline signals its directly spawned child.
    """
    summaries: dict[str, object] = {}
    for scenario in ("supervisor-cooperative", "supervisor-blocked"):
        output = output_parent / scenario
        ready, cancel, done = Event(), Event(), Event()
        errors: list[str] = []
        watcher = Thread(target=_cancel_after_ready,
                         args=(output, ready, cancel, done, errors),
                         name="fake-hid-readiness", daemon=False)
        watcher.start()
        try:
            result = run_bounded(
                [str(binary), scenario, str(output / "lifecycle.bin")],
                executable_sha256=executable_sha256,
                output_directory=output,
                timeout_seconds=15,
                termination_grace_seconds=1,
                maximum_output_bytes=16384,
                cancel_event=cancel,
            )
        finally:
            done.set()
            watcher.join(timeout=2)
        _require(not watcher.is_alive(), "readiness watcher did not stop")
        _require(not errors, "; ".join(errors))
        _require(ready.is_set(), f"{scenario}: no admitted read readiness")
        _require(result.status is RunStatus.CANCELLED,
                 f"{scenario}: child was not reaped as cancelled")
        _require(result.trigger is RunTrigger.CANCELLED,
                 f"{scenario}: cancellation was not the first trigger")
        stdout = (output / "stdout.bin").read_bytes()
        stderr = (output / "stderr.bin").read_bytes()
        _require(not stderr, f"{scenario}: unexpected diagnostic/sanitizer output")
        _require(result.stdout_bytes == len(stdout) and result.stderr_bytes == 0,
                 f"{scenario}: capture counters disagree")
        _require(stdout.splitlines().count(b"READY") == 1,
                 f"{scenario}: readiness was not captured exactly once")
        # The existing supervisor drains, but does not capture, post-TERM pipe
        # bytes. A fake-only sidecar independently records cleanup callbacks.
        descriptor = os.open(output / "lifecycle.bin", os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                     and stat.S_IMODE(info.st_mode) == 0o600,
                     f"{scenario}: lifecycle sidecar is not a private regular file")
            lifecycle = os.read(descriptor, 257)
        finally:
            os.close(descriptor)
        _require(len(lifecycle) <= 256, f"{scenario}: lifecycle sidecar exceeded bound")
        tokens = lifecycle.decode("ascii").splitlines()
        expected = (["READY", "CLOSE", "EXIT", "FINISH"]
                    if scenario == "supervisor-cooperative" else ["READY"])
        _require(tokens == expected, f"{scenario}: lifecycle markers disagree")
        expected_rc = 0 if scenario == "supervisor-cooperative" else -signal.SIGKILL
        _require(result.returncode == expected_rc,
                 f"{scenario}: unexpected child exit status")
        if scenario == "supervisor-blocked":
            _require(not any(line.startswith(b"PASS") for line in stdout.splitlines()),
                     "blocked child must not report completed assertions")
        summaries[scenario] = {
            **asdict(result),
            "markers": tokens,
            "cleanup_observed": scenario == "supervisor-cooperative",
            "device_safety_qualified": False,
        }
    return {"status": "PASS", "scenarios": summaries,
            "scope": "source-built synthetic HIDAPI only",
            "data_qualified": False, "hardware": "NOT_RUN"}
