from __future__ import annotations

import importlib.util
from pathlib import Path
import signal
from threading import Event
import unittest

CLI = Path(__file__).with_name("prepare_production_source.py")
SPEC = importlib.util.spec_from_file_location("e63_source_cli_test", CLI)
assert SPEC is not None and SPEC.loader is not None
SOURCE_CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_CLI)


class CancelBridgeTests(unittest.TestCase):
    def test_signal_during_child_sets_event_and_rejects_success(self):
        class Helper:
            def run_bounded(self, *, cancel_event):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return "success"

        helper = Helper()
        child = Event()
        with self.assertRaisesRegex(ValueError, "cancelled"):
            with SOURCE_CLI.cancellation_bridge(helper):
                with self.assertRaisesRegex(ValueError, "cancelled"):
                    helper.run_bounded(cancel_event=child)
        self.assertTrue(child.is_set())

    def test_signal_between_commands_prevents_next_child(self):
        calls = []

        class Helper:
            def run_bounded(self, *, cancel_event):
                calls.append(cancel_event)
                return "ok"

        helper = Helper()
        with self.assertRaisesRegex(ValueError, "cancelled"):
            with SOURCE_CLI.cancellation_bridge(helper):
                helper.run_bounded(cancel_event=Event())
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                with self.assertRaisesRegex(ValueError, "cancelled"):
                    helper.run_bounded(cancel_event=Event())
        self.assertEqual(len(calls), 1)

    def test_helper_and_signal_handlers_restore_after_exception(self):
        class Helper:
            def run_bounded(self, **_kwargs):
                raise RuntimeError("synthetic failure")

        helper = Helper()
        original = Helper.run_bounded
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with SOURCE_CLI.cancellation_bridge(helper):
                helper.run_bounded(cancel_event=Event())
        self.assertIs(helper.run_bounded.__func__, original)
        self.assertEqual({sig: signal.getsignal(sig) for sig in before}, before)

    def test_signal_at_end_of_body_fails_and_restores_handlers(self):
        class Helper:
            def run_bounded(self, **_kwargs):
                return "unused"

        helper = Helper()
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with self.assertRaisesRegex(ValueError, "cancelled"):
            with SOURCE_CLI.cancellation_bridge(helper) as _campaign:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        self.assertEqual({sig: signal.getsignal(sig) for sig in before}, before)


if __name__ == "__main__":
    unittest.main()
