"""Closed operator CLI for explicitly registered bounded local sessions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Mapping, Sequence
import uuid

from operator_stop import run_operator_controlled
from process_deadline import BoundedRunError, BoundedRunResult, DependencyPin, RunStatus


@dataclass(frozen=True, slots=True)
class OperatorProfile:
    argv: tuple[str, ...]
    executable_sha256: str
    output_parent: Path
    timeout_seconds: float
    termination_grace_seconds: float
    maximum_output_bytes: int
    dependency_pins: tuple[DependencyPin, ...] = ()

    def __post_init__(self) -> None:
        if type(self.dependency_pins) is not tuple or any(
            type(pin) is not DependencyPin for pin in self.dependency_pins
        ):
            raise ValueError("dependency pins must be an immutable tuple")

# No operational profile is approved or distributed by this module.
PROFILES: Mapping[str, OperatorProfile] = MappingProxyType({})

_JSON_FIELDS = (
    "status",
    "trigger",
    "returncode",
    "stdout_bytes",
    "stderr_bytes",
    "data_qualified",
    "error",
)


def _payload(
    status: str,
    trigger: str,
    returncode: int | None,
    stdout_bytes: int,
    stderr_bytes: int,
    error: str | None,
) -> dict[str, object]:
    return {
        "status": status,
        "trigger": trigger,
        "returncode": returncode,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "data_qualified": False,
        "error": error,
    }


def _parse_arguments(args: Sequence[str]) -> tuple[str | None, bool, str | None, bool]:
    if any(not isinstance(item, str) for item in args):
        return None, False, "invalid_arguments", False
    if len(args) == 1 and args[0] in ("-h", "--help"):
        return None, False, None, True
    if not args:
        return None, False, None, False
    if len(args) == 1 and args[0] == "--execute":
        return None, True, None, False
    if len(args) == 2 and args[0] == "--profile":
        return args[1], False, None, False
    if len(args) == 3 and args[0] == "--profile" and args[2] == "--execute":
        return args[1], True, None, False
    return None, False, "invalid_arguments", False


def _run_profile(profile: OperatorProfile) -> tuple[dict[str, object], int]:
    output_directory = profile.output_parent / f"operator-session-{uuid.uuid4().hex}"
    try:
        result = run_operator_controlled(
            profile.argv,
            executable_sha256=profile.executable_sha256,
            output_directory=output_directory,
            timeout_seconds=profile.timeout_seconds,
            termination_grace_seconds=profile.termination_grace_seconds,
            maximum_output_bytes=profile.maximum_output_bytes,
            private_nut_environment=True,
            dependency_pins=profile.dependency_pins,
        )
    except BoundedRunError as error:
        code = error.code.value
        status = "unreaped" if code == "child_unreaped" else "error"
        return _payload(status, "none", None, 0, 0, code), 1
    except KeyboardInterrupt:
        return _payload("error", "none", None, 0, 0, "interrupted"), 1
    except Exception:
        return _payload("error", "none", None, 0, 0, "internal_error"), 1

    if not isinstance(result, BoundedRunResult):
        return _payload("error", "none", None, 0, 0, "internal_error"), 1

    payload = _payload(
        result.status.value,
        result.trigger.value,
        result.returncode,
        result.stdout_bytes,
        result.stderr_bytes,
        None,
    )
    successful_exit = (
        result.status is RunStatus.EXITED
        and result.returncode == 0
        and result.trigger.value == "completed"
    )
    return payload, 0 if successful_exit else 1


def _write_response(payload: dict[str, object]) -> bool:
    if tuple(payload) != _JSON_FIELDS:
        raise RuntimeError("invalid response schema")
    try:
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=False) + "\n")
        sys.stdout.flush()
        return True
    except (BrokenPipeError, OSError, UnicodeError):
        return False


def _dispatch(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    profile_id, execute, parse_error, help_requested = _parse_arguments(args)

    if help_requested:
        payload = _payload(
            "not_run", "none", None, 0, 0,
            "usage: operator_session --profile ID [--execute]",
        )
        return 0 if _write_response(payload) else 1
    if parse_error is not None:
        _write_response(_payload("rejected", "none", None, 0, 0, parse_error))
        return 2
    if profile_id is None:
        if execute:
            _write_response(_payload("rejected", "none", None, 0, 0, "profile_required"))
            return 2
        return 0 if _write_response(_payload("not_run", "none", None, 0, 0, None)) else 1

    profile = PROFILES.get(profile_id)
    if profile is None:
        _write_response(_payload("rejected", "none", None, 0, 0, "unknown_profile"))
        return 2
    if not execute:
        return 0 if _write_response(_payload("not_run", "none", None, 0, 0, None)) else 1

    payload, exit_code = _run_profile(profile)
    return exit_code if _write_response(payload) else 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _dispatch(argv)
    except KeyboardInterrupt:
        _write_response(_payload("error", "none", None, 0, 0, "interrupted"))
        return 1
    except Exception:
        _write_response(_payload("error", "none", None, 0, 0, "internal_error"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
