"""Synthetic contracts for copy-only PBS runtime staging; no Python payload runs."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from compression import zstd

_STAGE_PATH = Path(__file__).resolve().with_name("stage_bundled_python_runtime.py")
_STAGE_SPEC = importlib.util.spec_from_file_location("stage_bundled_python_runtime", _STAGE_PATH)
if _STAGE_SPEC is None or _STAGE_SPEC.loader is None:
    raise ImportError("cannot_load_sibling_stage_module")
stage = importlib.util.module_from_spec(_STAGE_SPEC)
sys.modules[_STAGE_SPEC.name] = stage
exec(compile(_STAGE_PATH.read_bytes(), str(_STAGE_PATH), "exec", dont_inherit=True), stage.__dict__)


class BundledPythonStageTests(unittest.TestCase):
    def setUp(self):
        self.inputs_path = Path(stage.__file__).with_name("bundled_python_runtime_inputs.json")
        self.base_inputs = json.loads(self.inputs_path.read_text(encoding="utf-8"))

    @staticmethod
    def metadata():
        return {
            "python_version": "3.15.2",
            "target_triple": "aarch64-apple-darwin",
            "python_exe": "install/bin/python3.15",
            "apple_sdk_deployment_target": "11.0",
            "license_path": "licenses/LICENSE.fixture.txt",
            "licenses": ["MIT"],
            "build_info": {
                "extensions": {
                    "fixture_extension": [{
                        "license_paths": ["licenses/LICENSE.extension-fixture.txt"],
                        "licenses": ["BSD-2-Clause"],
                    }],
                },
            },
        }

    @staticmethod
    def records(metadata, *, additions=(), marker=None):
        marker = "SHOULD_NEVER_APPEAR" if marker is None else marker
        sentinel = ("#!/bin/sh\nprintf sentinel > '" + str(marker) + "'\n").encode()
        records = [
            ("python/install/bin/python3.15", "file", sentinel, 0o755),
            ("python/install/lib/libpython3.15.dylib", "file", b"inert dylib fixture", 0o755),
            ("python/install/lib/python3.15/os.py", "file", b"inert stdlib fixture", 0o644),
            ("python/install/lib/python3.15/large-fixture.py", "file", b"x" * 2048, 0o644),
            ("python/install/bin/python3", "symlink", "python3.15", 0o777),
            ("python/install/bin/python3-current", "symlink", "python3", 0o777),
            ("python/licenses/LICENSE.fixture.txt", "file", b"fixture license", 0o644),
            ("python/licenses/LICENSE.extension-fixture.txt", "file", b"extension fixture license", 0o644),
            ("python/PYTHON.json", "file", json.dumps(metadata, sort_keys=True).encode(), 0o644),
            ("python/build/should-not-be-staged.o", "file", b"build-only bytes", 0o644),
        ]
        records.extend(additions)
        return records

    @staticmethod
    def write_archive(path: Path, records):
        raw_tar = io.BytesIO()
        with tarfile.open(fileobj=raw_tar, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, kind, value, mode in records:
                item = tarfile.TarInfo(name)
                item.mode = mode
                if kind == "file":
                    item.type = tarfile.REGTYPE
                    item.size = len(value)
                    archive.addfile(item, io.BytesIO(value))
                elif kind == "symlink":
                    item.type = tarfile.SYMTYPE
                    item.linkname = value
                    archive.addfile(item)
                elif kind == "hardlink":
                    item.type = tarfile.LNKTYPE
                    item.linkname = value
                    archive.addfile(item)
                elif kind == "fifo":
                    item.type = tarfile.FIFOTYPE
                    archive.addfile(item)
                else:
                    raise AssertionError("unknown synthetic member kind")
        with zstd.ZstdFile(path, "wb") as compressed:
            compressed.write(raw_tar.getvalue())

    def fixture(self, root, *, metadata=None, additions=(), input_changes=None):
        root = Path(root).resolve(strict=True)
        metadata = self.metadata() if metadata is None else metadata
        archive = root / "fixture.tar.zst"
        destination = root / "new-runtime"
        marker = root / "SENTINEL_EXECUTED"
        self.write_archive(archive, self.records(metadata, additions=additions, marker=marker))
        inputs = copy.deepcopy(self.base_inputs)
        raw = archive.read_bytes()
        meta_bytes = json.dumps(metadata, sort_keys=True).encode()
        inputs["archive"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        inputs["metadata"].update(sha256=hashlib.sha256(meta_bytes).hexdigest(), bytes=len(meta_bytes))
        if input_changes:
            input_changes(inputs)
        return archive, destination, inputs, meta_bytes

    def stage_fixture(self, archive, destination, inputs):
        return stage._stage_with_inputs(archive, destination, inputs)

    def assert_rejected_before_destination(self, archive, destination, inputs, code):
        with self.assertRaises(stage.StageError) as caught:
            self.stage_fixture(archive, destination, inputs)
        self.assertEqual(caught.exception.code, code)
        self.assertFalse(destination.exists(), code)

    def test_stages_only_selected_tree_with_hashes_relative_paths_and_safe_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, destination, inputs, _metadata = self.fixture(root)
            result = self.stage_fixture(archive, destination, inputs)

            self.assertEqual(result["state"], "STAGED_PYTHON_NOT_EXECUTED_NOT_ADOPTED")
            self.assertEqual(result["inventory_name"], "runtime-tree.json")
            self.assertEqual(result["closure_macho"], "NOT_RUN")
            self.assertEqual(result["runtime_execution"], "NOT_RUN")
            self.assertEqual(result["adoption"], "NOT_ADOPTED")
            self.assertEqual(result["archive_sha256"], inputs["archive"]["sha256"])
            self.assertEqual(result["metadata_sha256"], inputs["metadata"]["sha256"])

            manifest_path = destination / result["inventory_name"]
            manifest_bytes = manifest_path.read_bytes()
            self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), result["inventory_sha256"])
            self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
            manifest = json.loads(manifest_bytes)
            self.assertEqual(manifest["state"], result["state"])
            self.assertEqual(manifest["profile"], inputs["profile"])
            self.assertEqual(manifest["expected_metadata"], inputs["expected"])
            entries = manifest["entries"]

            expected_files = {
                "install/bin/python3.15",
                "install/lib/libpython3.15.dylib",
                "install/lib/python3.15/os.py",
                "licenses/LICENSE.fixture.txt",
                "licenses/LICENSE.extension-fixture.txt",
                "PYTHON.json",
            }
            self.assertTrue(expected_files.issubset(entries))
            self.assertNotIn("build/should-not-be-staged.o", entries)
            self.assertEqual((destination / "install/bin/python3.15").read_bytes().startswith(b"#!/bin/sh"), True)
            self.assertFalse((root / "SENTINEL_EXECUTED").exists())
            self.assertEqual(stat.S_IMODE((destination / "install/bin/python3.15").stat().st_mode), 0o755)
            self.assertEqual(entries["install/bin/python3.15"]["sha256"],
                             hashlib.sha256((destination / "install/bin/python3.15").read_bytes()).hexdigest())
            self.assertEqual(entries["install/bin/python3"]["type"], "symlink")
            self.assertEqual(entries["install/bin/python3-current"]["resolved_target"],
                             "install/bin/python3.15")
            self.assertTrue((destination / "install/bin/python3-current").is_symlink())
            self.assertEqual((destination / "install/bin/python3-current").resolve(),
                             destination / "install/bin/python3.15")
            self.assertTrue((destination / "install/bin").is_dir())
            self.assertTrue((destination / "licenses").is_dir())
            self.assertFalse((destination / "build").exists())
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(result["file_count"], sum(row["type"] == "file" for row in entries.values()))
            self.assertEqual(result["symlink_count"], sum(row["type"] == "symlink" for row in entries.values()))
            self.assertEqual(result["directory_count"], sum(row["type"] == "directory" for row in entries.values()))
            self.assertEqual(result["selected_bytes"], sum(row.get("bytes", 0) for row in entries.values()))
            self.assertEqual(manifest["licenses"]["legal_or_redistribution_review"], "NOT_RUN")

    def test_bad_archive_hash_and_size_reject_before_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, destination, inputs, _ = self.fixture(root)
            bad = copy.deepcopy(inputs)
            bad["archive"]["sha256"] = "0" * 64
            self.assert_rejected_before_destination(archive, destination, bad, "archive_pin")
            bad = copy.deepcopy(inputs)
            bad["archive"]["bytes"] += 1
            self.assert_rejected_before_destination(archive, destination, bad, "archive_size")

    def test_metadata_hash_contract_and_license_closure_reject_before_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, destination, inputs, _ = self.fixture(root)
            bad_pin = copy.deepcopy(inputs)
            bad_pin["metadata"]["sha256"] = "0" * 64
            self.assert_rejected_before_destination(archive, destination, bad_pin, "metadata_pin")

            for field, value in (("python_version", "3.15.9"),
                                 ("target_triple", "x86_64-apple-darwin"),
                                 ("python_exe", "install/bin/python"),
                                 ("apple_sdk_deployment_target", "14.0")):
                with self.subTest(field=field), tempfile.TemporaryDirectory() as case:
                    case_root = Path(case).resolve()
                    metadata = self.metadata()
                    metadata[field] = value
                    a, d, i, _ = self.fixture(case_root, metadata=metadata)
                    self.assert_rejected_before_destination(a, d, i, "metadata_contract")

            metadata = self.metadata()
            metadata["license_path"] = "licenses/MISSING.txt"
            a, d, i, _ = self.fixture(root, metadata=metadata)
            self.assert_rejected_before_destination(a, d, i, "missing_license")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            metadata = self.metadata()
            metadata["build_info"]["extensions"]["fixture_extension"][0]["license_paths"] = [
                "licenses/MISSING-DEPENDENCY.txt"
            ]
            a, d, i, _ = self.fixture(root, metadata=metadata)
            self.assert_rejected_before_destination(a, d, i, "missing_license")

    def test_input_schema_is_closed_and_cli_has_no_inputs_override(self):
        self.assertEqual(tuple(inspect.signature(stage.stage).parameters), ("archive", "destination"))
        self.assertEqual(stage.INPUTS_NAME, "bundled_python_runtime_inputs.json")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, destination, _inputs, _ = self.fixture(root)
            malformed = copy.deepcopy(self.base_inputs)
            malformed["unreviewed_override"] = True
            with self.assertRaises(stage.StageError) as caught:
                self.stage_fixture(archive, destination, malformed)
            self.assertEqual(caught.exception.code, "invalid_inputs")
            self.assertFalse(destination.exists())
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:
                    stage.main(["--archive", str(archive), "--destination", str(destination),
                                "--inputs", str(root / "replacement.json")])
            self.assertEqual(caught.exception.code, 2)
            self.assertFalse(destination.exists())

    def test_unsafe_paths_duplicate_names_and_parent_conflicts_reject(self):
        cases = [
            (("../outside", "file", b"x", 0o644), "unsafe_path"),
            (("/python/install/absolute", "file", b"x", 0o644), "unsafe_path"),
            (("python\\install\\backslash", "file", b"x", 0o644), "unsafe_path"),
            (("python/install/./dot", "file", b"x", 0o644), "unsafe_path"),
            (("other/outside-prefix", "file", b"x", 0o644), "unsafe_path"),
        ]
        for record, code in cases:
            with self.subTest(path=record[0]), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                a, d, i, _ = self.fixture(root, additions=(record,))
                self.assert_rejected_before_destination(a, d, i, code)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            dup = ("python/install/repeated", "file", b"second", 0o644)
            a, d, i, _ = self.fixture(root, additions=(dup, dup))
            self.assert_rejected_before_destination(a, d, i, "duplicate_member")

        for additions in (
            (("python/install/conflict", "file", b"file", 0o644),
             ("python/install/conflict/child", "file", b"child", 0o644)),
            (("python/install/alias", "symlink", "bin", 0o777),
             ("python/install/alias/child", "file", b"child", 0o644)),
        ):
            with self.subTest(parent=additions[0][0]), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                a, d, i, _ = self.fixture(root, additions=additions)
                self.assert_rejected_before_destination(a, d, i, "member_parent_conflict")

    def test_unicode_casefold_alias_and_unsupported_tar_members_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            additions = (("python/install/Caf\u00e9", "file", b"one", 0o644),
                         ("python/install/Cafe\u0301", "file", b"two", 0o644))
            archive, dest, inputs, _ = self.fixture(root, additions=additions)
            self.assert_rejected_before_destination(archive, dest, inputs, "duplicate_member")

        for record in (("python/install/hard", "hardlink", "python/install/bin/python3.15", 0o644),
                       ("python/install/pipe", "fifo", b"", 0o644)):
            with self.subTest(kind=record[1]), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                archive, dest, inputs, _ = self.fixture(root, additions=(record,))
                self.assert_rejected_before_destination(archive, dest, inputs, "unsupported_member")

    def test_symlink_escape_absolute_backslash_missing_and_cycle_reject(self):
        bad_targets = (("../../outside", "unsafe_symlink"), ("/outside", "unsafe_symlink"),
                       ("..\\outside", "unsafe_symlink"), ("missing", "missing_target"))
        for target, code in bad_targets:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                additions = (("python/install/bin/bad-link", "symlink", target, 0o777),)
                archive, dest, inputs, _ = self.fixture(root, additions=additions)
                self.assert_rejected_before_destination(archive, dest, inputs, code)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            additions = (("python/install/a", "symlink", "b", 0o777),
                         ("python/install/b", "symlink", "a", 0o777))
            archive, dest, inputs, _ = self.fixture(root, additions=additions)
            self.assert_rejected_before_destination(archive, dest, inputs, "symlink_cycle")

    def test_member_total_selected_file_and_deadline_limits_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, dest, inputs, metadata_bytes = self.fixture(root)
            cases = (
                ("members", 2, "member_limit"),
                ("total_bytes", len(metadata_bytes) + 1, "total_limit"),
                ("selected_bytes", len(metadata_bytes) + 1, "selected_limit"),
                ("file_bytes", len(metadata_bytes) + 1, "file_limit"),
            )
            for key, limit, code in cases:
                with self.subTest(limit=key):
                    case = copy.deepcopy(inputs)
                    case["limits"][key] = limit
                    self.assert_rejected_before_destination(archive, dest, case, code)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, dest, inputs, _ = self.fixture(root)
            inputs["limits"]["seconds"] = 1
            with mock.patch.object(stage.time, "monotonic", side_effect=(0.0, 2.0)):
                self.assert_rejected_before_destination(archive, dest, inputs, "deadline")

    def test_metadata_path_nul_rejected_by_the_bounded_path_gate(self):
        with self.assertRaises(stage.StageError) as caught:
            stage._canonical("python/install/name\x00suffix")
        self.assertEqual(caught.exception.code, "unsafe_path")

    def test_existing_destination_and_non_private_parent_are_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, destination, inputs, _ = self.fixture(root)
            destination.mkdir(mode=0o700)
            marker = destination / "keep.txt"
            marker.write_text("existing owner data", encoding="utf-8")
            with self.assertRaises(stage.StageError) as caught:
                self.stage_fixture(archive, destination, inputs)
            self.assertEqual(caught.exception.code, "destination_exists")
            self.assertEqual(marker.read_text(encoding="utf-8"), "existing owner data")

            non_private_parent = root / "non-private-parent"
            non_private_parent.mkdir(mode=0o700)
            os.chmod(non_private_parent, 0o777)
            self.assertTrue(stat.S_IMODE(non_private_parent.stat().st_mode) & 0o022)
            outside = non_private_parent / "never-create-this-runtime"
            with self.assertRaises(stage.StageError) as caught:
                self.stage_fixture(archive, outside, inputs)
            self.assertEqual(caught.exception.code, "destination_rejected")
            self.assertFalse(outside.exists())

            alias_parent = root / "aliased-parent"
            alias_parent.symlink_to(root, target_is_directory=True)
            aliased_destination = alias_parent / "aliased-runtime"
            with self.assertRaises(stage.StageError) as caught:
                self.stage_fixture(archive, aliased_destination, inputs)
            self.assertEqual(caught.exception.code, "destination_rejected")
            self.assertFalse(aliased_destination.exists())

    def test_destination_outside_allowed_roots_rejects_before_open(self):
        outside = Path("/") / "ups-monitor-never-create-runtime"
        root_owner = outside.parent.stat().st_uid
        with tempfile.TemporaryDirectory() as folder:
            fixture_root = Path(folder).resolve()
            with mock.patch.dict(stage.os.environ, {"TMPDIR": str(fixture_root)}), \
                 mock.patch.object(stage.os, "getuid", return_value=root_owner), \
                 mock.patch.object(stage.os, "open", side_effect=AssertionError("unexpected_open")) as open_sentinel:
                with self.assertRaises(stage.StageError) as caught:
                    stage._destination(outside)
                self.assertEqual(caught.exception.code, "destination_rejected")
                open_sentinel.assert_not_called()

    def test_failed_write_leaves_partial_evidence_and_does_not_run_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, destination, inputs, _ = self.fixture(root)
            real_write = os.write
            calls = 0

            def fail_after_one(fd, data):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_write(fd, data)
                raise OSError("synthetic write interruption")

            with mock.patch.object(stage.os, "write", side_effect=fail_after_one):
                with self.assertRaises(stage.StageError) as caught:
                    self.stage_fixture(archive, destination, inputs)
            self.assertEqual(caught.exception.code, "io_error")
            self.assertTrue(destination.is_dir())
            self.assertTrue(any(path.is_file() for path in destination.rglob("*")))
            self.assertFalse((destination / "runtime-tree.json").exists())
            self.assertFalse((root / "SENTINEL_EXECUTED").exists())


if __name__ == "__main__":
    unittest.main()
