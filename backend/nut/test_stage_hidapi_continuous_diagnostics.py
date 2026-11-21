"""Synthetic-only ownership and child-completion tests; no process launched."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class Status(str, Enum):
    EXITED = "exited"
    UNREAPED = "unreaped"


class Trigger(str, Enum):
    COMPLETED = "completed"


@dataclass
class Result:
    status: Status
    returncode: int | None
    trigger: Trigger = Trigger.COMPLETED


class BaseRefusal(Exception):
    pass


class SyntheticStage(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-diag-stage-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "new-output"
        self.apc_hash_calls = 0
        self.patch_calls = 0

    def digest(self, path: Path) -> str:
        if path == candidate.DIAGNOSTIC_PATCH:
            return candidate.DIAGNOSTIC_PATCH_SHA256
        if path.name == "apcmicrolink.c":
            self.apc_hash_calls += 1
            if self.apc_hash_calls <= 2:
                return candidate.BASE_APC_SHA256
            return "1" * 64
        return "2" * 64

    def base(self, source: Path, inventory: Path, output: Path) -> dict[str, str]:
        output.mkdir(mode=0o700)
        (output / "drivers").mkdir(mode=0o700)
        (output / "drivers/apcmicrolink.c").write_text("SYNTHETIC_ONLY\n")
        return {"state": "STAGED_UNBUILT", "source_inventory_sha256": "3" * 64,
                "patch_sha256": "4" * 64}

    def run_case(self, behavior, *, base=None, digest=None):
        fake_supervisor = SimpleNamespace(RunStatus=Status, run_bounded=behavior)
        fake_base = SimpleNamespace(stage=base or self.base, StageError=BaseRefusal)
        with patch.object(candidate, "_resolved_tmpdir", return_value=self.root), \
             patch.object(candidate, "sha256", side_effect=digest or self.digest), \
             patch.object(candidate, "_load_base_stager", return_value=fake_base), \
             patch.object(candidate, "_load_supervisor", return_value=fake_supervisor):
            return candidate.stage(self.root / "unused-source", self.root / "unused-inventory", self.output, compile_opt_in=True)

    def test_completed_success_retains_staged_source(self) -> None:
        result = self.run_case(lambda *a, **kw: Result(Status.EXITED, 0))
        self.assertEqual(result["state"], "STAGED_UNBUILT")
        self.assertTrue(self.output.is_dir())

    def test_completed_failure_removes_only_owned_output(self) -> None:
        with self.assertRaises(candidate.StageError) as caught:
            self.run_case(lambda *a, **kw: Result(Status.EXITED, 1))
        self.assertFalse(self.output.exists())
        self.assertIsNone(caught.exception.retained_output)

    def test_unreaped_result_preserves_output(self) -> None:
        with self.assertRaises(candidate.StageError) as caught:
            self.run_case(lambda *a, **kw: Result(Status.UNREAPED, None))
        self.assertTrue(self.output.is_dir())
        self.assertEqual(caught.exception.retained_output, self.output)

    def test_uncertain_exceptions_preserve_output(self) -> None:
        for message in ("CHILD_UNREAPED", "SPAWN_FAILED"):
            def fail(*args, **kwargs):
                raise RuntimeError(message)
            with self.subTest(message=message), self.assertRaises(candidate.StageError) as caught:
                self.run_case(fail)
            self.assertTrue(self.output.is_dir())
            self.assertEqual(caught.exception.retained_output, self.output)
            self.assertNotIn(str(self.output), str(caught.exception))
            # Remove only this synthetic case after its assertions; no child was launched.
            import shutil
            shutil.rmtree(self.output)
            self.apc_hash_calls = 0

    def test_pre_child_hash_failure_can_remove_owned_output(self) -> None:
        def bad_apc(path):
            return "0" * 64 if path.name == "apcmicrolink.c" else self.digest(path)
        def forbidden(*args, **kwargs):
            self.fail("no process may be launched before hash validation")
        with self.assertRaises(candidate.StageError):
            self.run_case(forbidden, digest=bad_apc)
        self.assertFalse(self.output.exists())

    def test_base_refusal_never_removes_foreign_output(self) -> None:
        def refuse(source, inventory, output):
            output.mkdir(mode=0o700)
            (output / "foreign-marker").write_text("SYNTHETIC_FOREIGN\n")
            raise BaseRefusal("synthetic refusal")
        with self.assertRaises(candidate.StageError):
            self.run_case(lambda *a, **kw: self.fail("unexpected child"), base=refuse)
        self.assertTrue((self.output / "foreign-marker").is_file())

    def test_replaced_output_identity_never_removed(self) -> None:
        def replace(*args, **kwargs):
            self.output.rename(self.root / "original-owned-output")
            self.output.mkdir(mode=0o700)
            (self.output / "foreign-marker").write_text("SYNTHETIC_FOREIGN\n")
            return Result(Status.EXITED, 1)
        with self.assertRaises(candidate.StageError) as caught:
            self.run_case(replace)
        self.assertTrue((self.output / "foreign-marker").is_file())
        self.assertTrue((self.root / "original-owned-output").is_dir())
        self.assertEqual(caught.exception.retained_output, self.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stager-sha256", required=True)
    args = parser.parse_args()
    path = Path(__file__).resolve().with_name("stage_hidapi_continuous_diagnostics.py")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == args.stager_sha256
    spec = importlib.util.spec_from_file_location("synthetic_stage_candidate", path)
    candidate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = candidate
    spec.loader.exec_module(candidate)
    sys.argv = [sys.argv[0]]
    unittest.main()
