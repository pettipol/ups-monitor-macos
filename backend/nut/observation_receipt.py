"""Serialize metadata-only receipts for bounded synthetic or supervised runs."""

from __future__ import annotations

import json
import math
import re

from process_deadline import BoundedRunResult, CapturedRunMetadata, RunStatus, RunTrigger


class ObservationReceiptError(ValueError):
    """A fixed safe receipt error without caller-controlled details."""

    def __init__(self) -> None:
        super().__init__("invalid observation receipt")


_DIGEST = re.compile(r"[0-9a-fA-F]{64}\Z", re.ASCII)
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_MAXIMUM_RECEIPT_OUTPUT_BYTES = 1_048_576


def encode_observation_receipt(result: BoundedRunResult) -> bytes:
    """Return compact UTF-8 JSON with validated run metadata and no raw output."""
    try:
        if not isinstance(result, BoundedRunResult):
            raise ValueError
        observation = result.observation
        if not isinstance(observation, CapturedRunMetadata):
            raise ValueError
        if not isinstance(result.status, RunStatus) or not isinstance(result.trigger, RunTrigger):
            raise ValueError
        if result.returncode is not None and (
            type(result.returncode) is not int or not _INT64_MIN <= result.returncode <= _INT64_MAX
        ):
            raise ValueError
        for count in (result.stdout_bytes, result.stderr_bytes):
            if type(count) is not int or count < 0:
                raise ValueError
        cap = observation.maximum_output_bytes
        if type(cap) is not int or not 1 <= cap <= _MAXIMUM_RECEIPT_OUTPUT_BYTES:
            raise ValueError
        if result.stdout_bytes + result.stderr_bytes > cap:
            raise ValueError
        digests = (
            observation.executable_sha256,
            observation.stdout_sha256,
            observation.stderr_sha256,
        )
        if any(not isinstance(value, str) or _DIGEST.fullmatch(value) is None for value in digests):
            raise ValueError
        started_value = observation.started_at_unix_seconds
        finished_value = observation.finished_at_unix_seconds
        _validate_timestamp(started_value)
        _validate_timestamp(finished_value)
        if finished_value < started_value:
            raise ValueError
        started = float(started_value)
        finished = float(finished_value)
        payload = {
            "schema_version": 1,
            "status": result.status.value,
            "trigger": result.trigger.value,
            "returncode": result.returncode,
            "stdout_bytes": result.stdout_bytes,
            "stderr_bytes": result.stderr_bytes,
            "maximum_output_bytes": cap,
            "executable_sha256": observation.executable_sha256.lower(),
            "stdout_sha256": observation.stdout_sha256.lower(),
            "stderr_sha256": observation.stderr_sha256.lower(),
            "started_at_unix_seconds": started,
            "finished_at_unix_seconds": finished,
            "data_qualified": False,
            "error": None,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except ObservationReceiptError:
        raise
    except Exception:
        raise ObservationReceiptError() from None


def _validate_timestamp(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    if not math.isfinite(value):
        raise ValueError
