from __future__ import annotations

import ast
import threading
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import patch

import bounded_stream_dispatch as dispatch_module
from bounded_stream_dispatch import BoundedStreamDispatch, DispatchSnapshot


class BoundedStreamDispatchRetentionTests(unittest.TestCase):
    def test_snapshot_is_frozen_slotted_and_fixed_size(self) -> None:
        expected = {
            "started",
            "input_closed",
            "stop_requested",
            "eof_delivered",
            "quiesced",
            "error",
            "accepted_progress_count",
            "last_progress_monotonic",
            "queued_chunks",
        }
        self.assertEqual({field.name for field in fields(DispatchSnapshot)}, expected)
        snapshot = BoundedStreamDispatch(lambda _data: False).snapshot()
        with self.assertRaises(FrozenInstanceError):
            snapshot.queued_chunks = 99  # type: ignore[misc]
        self.assertFalse(hasattr(snapshot, "__dict__"))

    def test_component_has_fixed_capacity_queue_and_no_external_io_apis(self) -> None:
        source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(imports.intersection({"os", "subprocess", "socket", "pathlib", "urllib"}))
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(called_names.intersection({"open", "Popen", "run", "check_call", "urlopen"}))
        self.assertIn("_QUEUE_CAPACITY = 2", source)
        self.assertIn("_MAX_CHUNK_BYTES = 65_536", source)
        self.assertIn("_WORKER_POLL_SECONDS = 0.025", source)
        self.assertIn("deque()", source)

    def test_progress_counter_overflow_is_latched_without_increment(self) -> None:
        dispatcher = BoundedStreamDispatch(lambda _data: True, monotonic_clock=lambda: 1.0)
        try:
            dispatcher.start()
            with dispatcher._condition:  # Seed the checked boundary deterministically.
                dispatcher._progress_count = dispatch_module._MAX_COUNTER
            self.assertTrue(dispatcher.submit(b"one"))
            state = dispatcher.join(1.0)
            self.assertEqual(state.error, "progress_overflow")
            self.assertEqual(state.accepted_progress_count, dispatch_module._MAX_COUNTER)
        finally:
            dispatcher.request_stop()
            self.assertTrue(dispatcher.join(2.0).quiesced)

    def test_starting_thread_delayed_does_not_block_snapshot_or_zero_join(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        call_start = threading.Event()
        original_start = threading.Thread.start
        dispatcher = BoundedStreamDispatch(lambda _data: True)

        def delayed_start(thread: threading.Thread) -> None:
            entered.set()
            if not release.wait(1.0):
                raise RuntimeError("test release timed out")
            original_start(thread)

        def start_after_patch() -> None:
            if call_start.wait(1.0):
                dispatcher.start()

        starter = threading.Thread(target=start_after_patch)
        try:
            starter.start()
            with patch.object(threading.Thread, "start", delayed_start):
                call_start.set()
                self.assertTrue(entered.wait(1.0))
                state = dispatcher.join(0.0)
                self.assertFalse(state.quiesced)
                self.assertFalse(state.started)
                self.assertFalse(dispatcher.snapshot().quiesced)
                dispatcher.request_stop()
                release.set()
                starter.join(1.0)
                self.assertFalse(starter.is_alive())
                self.assertTrue(dispatcher.join(1.0).quiesced)
        finally:
            call_start.set()
            release.set()
            dispatcher.request_stop()
            starter.join(1.0)
            self.assertTrue(dispatcher.join(2.0).quiesced)
            self.assertFalse(starter.is_alive())


if __name__ == "__main__":
    unittest.main()
