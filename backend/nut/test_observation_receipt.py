from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace

from observation_receipt import ObservationReceiptError, encode_observation_receipt
from process_deadline import BoundedRunResult, CapturedRunMetadata, RunStatus, RunTrigger


class ObservationReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = CapturedRunMetadata(
            maximum_output_bytes=64,
            executable_sha256="a" * 64,
            stdout_sha256=hashlib.sha256(b"out").hexdigest(),
            stderr_sha256=hashlib.sha256(b"err").hexdigest(),
            started_at_unix_seconds=1,
            finished_at_unix_seconds=2,
        )
        self.result = BoundedRunResult(RunStatus.EXITED, RunTrigger.COMPLETED, 0, 3, 3, self.metadata)

    def test_encodes_exact_metadata_only_schema(self) -> None:
        encoded = encode_observation_receipt(self.result)
        payload = json.loads(encoded)
        self.assertEqual(len(payload), 14)
        self.assertEqual(payload["schema_version"], 1)
        self.assertFalse(payload["data_qualified"])
        self.assertIsNone(payload["error"])
        self.assertNotIn("stdout", payload)
        self.assertNotIn("stderr", payload)

    def test_rejects_missing_metadata_and_invalid_runtime_values(self) -> None:
        invalid = [
            replace(self.result, observation=None),
            replace(self.result, stdout_bytes=True),
            replace(self.result, stderr_bytes=-1),
            replace(self.result, returncode=True),
            replace(self.result, returncode=2**63),
            replace(self.result, observation=replace(self.metadata, maximum_output_bytes=0)),
            replace(self.result, observation=replace(self.metadata, maximum_output_bytes=5)),
            replace(self.result, observation=replace(self.metadata, stdout_sha256="g" * 64)),
            replace(self.result, observation=replace(self.metadata, started_at_unix_seconds=True)),
            replace(self.result, observation=replace(self.metadata, started_at_unix_seconds=float("nan"))),
            replace(self.result, observation=replace(self.metadata, finished_at_unix_seconds=0)),
        ]
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(ObservationReceiptError) as failure:
                encode_observation_receipt(result)
            self.assertEqual(str(failure.exception), "invalid observation receipt")

    def test_status_and_trigger_must_be_enums(self) -> None:
        for result in (replace(self.result, status="exited"), replace(self.result, trigger="completed")):
            with self.subTest(result=result), self.assertRaises(ObservationReceiptError):
                encode_observation_receipt(result)

    def test_rejects_oversized_cap_and_unrepresentable_timestamp(self) -> None:
        invalid = (
            replace(self.result, observation=replace(self.metadata, maximum_output_bytes=1_048_577)),
            replace(self.result, observation=replace(self.metadata, finished_at_unix_seconds=10**1000)),
            replace(
                self.result,
                observation=replace(
                    self.metadata,
                    started_at_unix_seconds=-(2**53),
                    finished_at_unix_seconds=-(2**53) - 1,
                ),
            ),
        )
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(ObservationReceiptError):
                encode_observation_receipt(result)

    def test_negative_outcome_with_valid_metadata_remains_serializable(self) -> None:
        result = replace(
            self.result,
            status=RunStatus.TIMED_OUT,
            trigger=RunTrigger.TIMEOUT,
            returncode=-15,
        )
        payload = json.loads(encode_observation_receipt(result))
        self.assertEqual(payload["status"], RunStatus.TIMED_OUT.value)
        self.assertEqual(payload["trigger"], RunTrigger.TIMEOUT.value)
        self.assertEqual(payload["returncode"], -15)


if __name__ == "__main__":
    unittest.main()
