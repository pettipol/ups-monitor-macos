#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic filesystem tests for the pinned HIDAPI candidate stager."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name("stage_hidapi_candidate.py")
SPEC = importlib.util.spec_from_file_location("stage_hidapi_candidate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
stage = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = stage
SPEC.loader.exec_module(stage)


class StageCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="stage-hidapi-test-", dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.product = self.root / "product"
        self.hidapi = self.root / "hidapi"
        self.output_parent = self.root / "out"
        self.product.mkdir()
        self.hidapi.mkdir()
        self.output_parent.mkdir()
        self.specs: list[stage.StageInput] = []
        for index, (name, _) in enumerate(stage.PRODUCT_INPUTS):
            self._add(self.product, name, f"drivers/{name}", "product", index)
        offset = len(self.specs)
        for index, (source, destination, _) in enumerate(stage.HIDAPI_INPUTS, start=offset):
            self._add(self.hidapi, source, f"drivers/hidapi-candidate/{destination}",
                      "hidapi-0.15.0", index)
        offset = len(self.specs)
        for index, (name, _) in enumerate(stage.LICENSE_INPUTS, start=offset):
            self._add(self.hidapi, name, f"drivers/hidapi-candidate/licenses/{name}",
                      "hidapi-0.15.0", index)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _add(self, root: Path, relative: str, destination: str, group: str, index: int) -> None:
        data = f"synthetic fixture {index}: {relative}\n".encode("utf-8")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.specs.append(stage.StageInput(root, relative, destination, digest, group))

    def _stage(self, output: Path, specs=None, protected=None):
        return stage.stage_from_specs(
            self.specs if specs is None else specs,
            output,
            protected_roots=(self.product, self.hidapi) if protected is None else protected,
        )

    def test_success_stages_fourteen_pinned_files_and_manifest(self) -> None:
        output = self.output_parent / "bundle"
        manifest = self._stage(output)
        self.assertEqual(len(manifest["files"]), 14)
        self.assertEqual(manifest["state"], "STAGED_NOT_BUILT_NOT_RUN")
        self.assertEqual(manifest["hidapi_version"], "0.15.0")
        parsed = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(parsed, manifest)
        self.assertEqual(len(list(output.rglob("*.*"))), 15)
        for entry in manifest["files"]:
            self.assertFalse(Path(entry["source"]).is_absolute())
            self.assertFalse(Path(entry["destination"]).is_absolute())
            target = output / entry["destination"]
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), entry["sha256"])

    def test_drift_is_rejected_before_output_creation(self) -> None:
        spec = self.specs[0]
        (spec.source_root / spec.source_relative).write_bytes(b"changed\n")
        output = self.output_parent / "bundle"
        with self.assertRaises(stage.StageError):
            self._stage(output)
        self.assertFalse(output.exists())

    def test_missing_input_is_rejected_before_output_creation(self) -> None:
        spec = self.specs[-1]
        (spec.source_root / spec.source_relative).unlink()
        output = self.output_parent / "bundle"
        with self.assertRaises(stage.StageError):
            self._stage(output)
        self.assertFalse(output.exists())

    def test_symlink_input_file_is_rejected_before_output_creation(self) -> None:
        spec = self.specs[0]
        source = spec.source_root / spec.source_relative
        target = self.root / "outside-source"
        target.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(target)
        output = self.output_parent / "bundle"
        with self.assertRaises(stage.StageError):
            self._stage(output)
        self.assertFalse(output.exists())

    def test_symlink_input_root_and_output_parent_are_rejected(self) -> None:
        input_alias = self.root / "hidapi-link"
        input_alias.symlink_to(self.hidapi, target_is_directory=True)
        changed = [
            replace(spec, source_root=input_alias) if spec.source_root == self.hidapi else spec
            for spec in self.specs
        ]
        output = self.output_parent / "input-parent-case"
        with self.assertRaises(stage.StageError):
            self._stage(output, changed)
        self.assertFalse(output.exists())

        alias_parent = self.root / "output-link"
        alias_parent.symlink_to(self.output_parent, target_is_directory=True)
        output = alias_parent / "bundle"
        with self.assertRaises(stage.StageError):
            self._stage(output)
        self.assertFalse((self.output_parent / "bundle").exists())

    def test_existing_directory_and_non_directory_output_are_rejected(self) -> None:
        existing = self.output_parent / "existing"
        existing.mkdir()
        with self.assertRaises(stage.StageError):
            self._stage(existing)
        file_output = self.output_parent / "not-a-directory"
        file_output.write_text("fixture", encoding="utf-8")
        with self.assertRaises(stage.StageError):
            self._stage(file_output)

    def test_output_overlap_and_missing_parent_are_rejected(self) -> None:
        nested = self.product / "bundle"
        with self.assertRaises(stage.StageError):
            self._stage(nested)
        self.assertFalse(nested.exists())
        missing_parent = self.root / "missing" / "bundle"
        with self.assertRaises(stage.StageError):
            self._stage(missing_parent)
        self.assertFalse(missing_parent.parent.exists())

    def test_public_api_rejects_sibling_output_inside_product_root(self) -> None:
        docs = stage.PRODUCT_ROOT / "docs"
        self.assertTrue(docs.is_dir())
        output = docs / ".synthetic-hidapi-stage-refusal"
        with mock.patch.object(stage, "_validate_and_read", return_value=()):
            with self.assertRaisesRegex(stage.StageError, "overlaps a product"):
                stage.stage_candidate(self.hidapi, output)
        self.assertFalse(os.path.lexists(output))


if __name__ == "__main__":
    unittest.main()
