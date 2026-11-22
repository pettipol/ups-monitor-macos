from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from continuous_capture import AtomicSamplePublisher, _has_empty_extended_acl
from continuous_protocol import FIELD_KINDS
from operational_publication import AtomicOperationalPublisher


def operational_sample() -> dict[str, object]:
    values = {
        "ups.status": "OL", "battery.charge": "93.5", "battery.runtime": "1280",
        "battery.voltage": "27.4", "battery.temperature": "24.0", "ups.temperature": "24.0",
        "input.voltage": "231.2", "input.frequency": "50.0", "output.voltage": "229.8",
        "output.current": "1.10", "output.frequency": "50.0", "ups.load": "31.5",
        "experimental.ups.load.apparent": "42.0", "ups.realpower.nominal": "650",
        "ups.power.nominal": "900", "ups.realpower": "204.75", "ups.power": "378",
    }
    fields = {name: {"value": values[name], "observed_ms": 0, "kind": kind, "state": "observed"}
              for name, kind in FIELD_KINDS.items()}
    return {"protocol": "ups-monitor.continuous.v2", "schema_version": 2, "type": "sample",
            "sequence": 1, "slot": 0, "elapsed_ms": 0, "missed_slots": 0, "fields": fields}


class AtomicOperationalPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.feed = self.root / "feed"
        self.feed.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_two_publish_replaces_atomically_and_keeps_private_mode(self) -> None:
        publisher = AtomicOperationalPublisher(self.feed, "synthetic", "0123456789abcdef0123456789abcdef")
        try:
            publisher.publish(state="active", started_at_unix_ms=1, terminal_reason=None,
                              sample=operational_sample(), published_at_unix_ms=2)
            first = (self.feed / "sample.json").read_bytes()
            publisher.publish(state="failed", started_at_unix_ms=1, terminal_reason="io_error",
                              sample=None, published_at_unix_ms=3)
            envelope = json.loads((self.feed / "sample.json").read_text(encoding="ascii"))
            self.assertEqual((envelope["schema_version"], envelope["protocol"], envelope["state"]),
                             (2, "ups-monitor.continuous.v2", "failed"))
            self.assertNotEqual(first, (self.feed / "sample.json").read_bytes())
            self.assertEqual(sorted(path.name for path in self.feed.iterdir()), ["sample.json"])
            self.assertEqual((self.feed.stat().st_mode & 0o777, (self.feed / "sample.json").stat().st_mode & 0o777),
                             (0o700, 0o600))
            self.assertTrue(_has_empty_extended_acl(publisher.dir_fd))
        finally:
            publisher.close()

    def test_v1_payload_serialization_remains_byte_identical(self) -> None:
        publisher = AtomicSamplePublisher(self.feed, "synthetic", "session")
        sample = {"sequence": 1}
        expected = (json.dumps({
            "schema_version": 1, "protocol": "ups-monitor.continuous.v1", "source_id": "synthetic",
            "session_id": "session", "state": "active", "started_at_unix_ms": 1,
            "published_at_unix_ms": 2, "terminal_reason": None, "sample": sample,
        }, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
        try:
            publisher.publish(state="active", started_at_unix_ms=1, terminal_reason=None,
                              sample=sample, published_at_unix_ms=2)
            self.assertEqual((self.feed / "sample.json").read_bytes(), expected)
        finally:
            publisher.close()

    def test_terminal_states_timestamps_and_sample_validation_are_closed(self) -> None:
        publisher = AtomicOperationalPublisher(self.feed, "synthetic", "0123456789abcdef0123456789abcdef")
        try:
            for args in (
                dict(state="stopped", terminal_reason="duration_complete"),
                dict(state="stopped", terminal_reason="cancelled", started_at_unix_ms=True),
                dict(state="active", terminal_reason="cancelled"),
                dict(state="failed", terminal_reason="duration_complete"),
                dict(state="active", terminal_reason=None, sample={"type": "end"}),
            ):
                values = {"state": "active", "started_at_unix_ms": 1, "terminal_reason": None,
                          "sample": None, "published_at_unix_ms": 2}
                values.update(args)
                with self.subTest(args=args), self.assertRaises((ValueError, OSError)):
                    publisher.publish(**values)
        finally:
            publisher.close()

