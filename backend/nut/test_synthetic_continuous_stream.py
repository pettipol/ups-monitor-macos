from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from continuous_protocol import End, Sample, StreamValidator, parse_line
from synthetic_continuous_stream import DURATION_MS, _stdout_writer, main, produce_stream


class VirtualTime:
    def __init__(self, *, jumps: list[int] | None = None) -> None:
        self.now = 0
        self.jumps = iter(jumps) if jumps is not None else None

    def clock(self) -> int:
        if self.jumps is not None:
            self.now = next(self.jumps)
        return self.now

    def wait(self, seconds: float) -> None:
        if self.jumps is None:
            self.now += int(seconds * 1000)


class SyntheticContinuousStreamTests(unittest.TestCase):
    def collect(self, clock: VirtualTime) -> list[bytes]:
        lines: list[bytes] = []
        produce_stream(lines.append, clock.clock, clock.wait)
        return lines

    def test_emits_24_samples_then_duration_complete_end(self) -> None:
        clock = VirtualTime()
        lines = self.collect(clock)
        records = [parse_line(line) for line in lines]
        samples = [record for record in records if isinstance(record, Sample)]
        self.assertEqual(len(samples), 24)
        self.assertIsInstance(records[-1], End)
        self.assertEqual(records[-1].reason, "duration_complete")
        self.assertGreaterEqual(records[-1].elapsed_ms, DURATION_MS)

        validator = StreamValidator(1_000_000, 0)
        for record in records:
            validator.accept(record, now_wall_ms=1_000_000 + record.elapsed_ms,
                             now_monotonic_ms=record.elapsed_ms)
        self.assertEqual(len(validator.samples), 24)
        self.assertIsNotNone(validator.end)

    def test_timestamps_advance_even_when_values_are_constant(self) -> None:
        records = [parse_line(line) for line in self.collect(VirtualTime())]
        samples = [record for record in records if isinstance(record, Sample)]
        self.assertEqual(len({sample.fields["battery.charge"].value for sample in samples}), 1)
        self.assertTrue(all(a.elapsed_ms < b.elapsed_ms for a, b in zip(samples, samples[1:])))
        self.assertTrue(all(sample.fields["battery.charge"].observed_ms == sample.elapsed_ms
                            for sample in samples))

    def test_backward_clock_fails(self) -> None:
        clock = VirtualTime(jumps=[0, 0, 5_000, 4_000])
        lines: list[bytes] = []
        with self.assertRaisesRegex(ValueError, "clock_discontinuity"):
            produce_stream(lines.append, clock.clock, clock.wait)

    def test_missed_slots_are_accounted_without_retroactive_samples(self) -> None:
        clock = VirtualTime(jumps=[0, 0, 16_000, 120_000])
        lines: list[bytes] = []
        produce_stream(lines.append, clock.clock, clock.wait)
        samples = [parse_line(line) for line in lines if json.loads(line)["type"] == "sample"]
        self.assertEqual([(sample.slot, sample.sequence, sample.missed_slots)
                          for sample in samples], [(0, 1, 0), (3, 2, 2)])

    def test_stdout_error_terminates_without_retrying_output(self) -> None:
        clock = VirtualTime()
        calls = 0

        def broken_writer(_: bytes) -> None:
            nonlocal calls
            calls += 1
            raise OSError("private output detail")

        with self.assertRaises(OSError):
            produce_stream(broken_writer, clock.clock, clock.wait)
        self.assertEqual(calls, 1)

    def test_stdout_writer_completes_short_writes(self) -> None:
        data = b"synthetic\n"
        chunks: list[bytes] = []

        def short_write(fd: int, buffer: object) -> int:
            self.assertEqual(fd, 1)
            chunk = bytes(buffer)
            size = min(3, len(chunk))
            chunks.append(chunk[:size])
            return size

        with patch("synthetic_continuous_stream.os.write", side_effect=short_write) as write:
            _stdout_writer(data)
        self.assertEqual(b"".join(chunks), data)
        self.assertGreater(write.call_count, 1)

    def test_stdout_writer_rejects_zero_write(self) -> None:
        with patch("synthetic_continuous_stream.os.write", return_value=0):
            with self.assertRaises(OSError):
                _stdout_writer(b"record\n")

    def test_stdout_writer_propagates_os_error(self) -> None:
        with patch("synthetic_continuous_stream.os.write", side_effect=OSError("private detail")):
            with self.assertRaises(OSError):
                _stdout_writer(b"record\n")

    def test_main_rejects_extra_arguments_before_starting_producer(self) -> None:
        with patch("synthetic_continuous_stream.sys.argv",
                   ["synthetic_continuous_stream.py", "--duration-seconds", "10"]), \
             patch("synthetic_continuous_stream.sys.stderr") as stderr, \
             patch("synthetic_continuous_stream.produce_stream") as producer:
            result = main()
        self.assertNotEqual(result, 0)
        producer.assert_not_called()
        stderr.write.assert_called_once_with("synthetic_stream_error\n")

    def test_main_returns_error_if_stderr_also_fails(self) -> None:
        class BrokenStderr:
            def write(self, _: str) -> None:
                raise OSError("private stderr detail")

            def flush(self) -> None:
                raise AssertionError("flush must not run after a failed write")

        with patch("synthetic_continuous_stream.sys.argv", ["synthetic_continuous_stream.py"]), \
             patch("synthetic_continuous_stream.sys.stderr", BrokenStderr()), \
             patch("synthetic_continuous_stream.produce_stream", side_effect=OSError("private stdout detail")) as producer:
            self.assertEqual(main(), 1)
        producer.assert_called_once()

    def test_cutoff_can_finish_without_any_sample(self) -> None:
        clock = VirtualTime(jumps=[0, 120_000])
        lines: list[bytes] = []
        produce_stream(lines.append, clock.clock, clock.wait)
        records = [parse_line(line) for line in lines]
        self.assertEqual(len(records), 1)
        self.assertIsInstance(records[0], End)
        self.assertEqual(records[0].elapsed_ms, DURATION_MS)

    def test_no_sample_is_emitted_at_or_after_cutoff(self) -> None:
        clock = VirtualTime(jumps=[0, 0, 120_000])
        lines: list[bytes] = []
        produce_stream(lines.append, clock.clock, clock.wait)
        records = [parse_line(line) for line in lines]
        samples = [record for record in records if isinstance(record, Sample)]
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].elapsed_ms, 0)
        self.assertIsInstance(records[-1], End)
        self.assertEqual(records[-1].elapsed_ms, DURATION_MS)
        self.assertTrue(all(sample.elapsed_ms < DURATION_MS for sample in samples))


if __name__ == "__main__":
    unittest.main()
