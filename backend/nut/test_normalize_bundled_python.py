"""Synthetic contracts for the E34-to-app resource normalizer."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import sys


_SOURCE = Path(__file__).resolve().with_name("normalize_bundled_python.py")
_SPEC = importlib.util.spec_from_file_location("normalize_bundled_python", _SOURCE)
assert _SPEC is not None and _SPEC.loader is not None
normalizer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = normalizer
exec(compile(_SOURCE.read_bytes(), str(_SOURCE), "exec", dont_inherit=True), normalizer.__dict__)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class NormalizerContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="e36-normalizer-")
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        (self.source / "install/bin").mkdir(parents=True)
        (self.source / "install/lib").mkdir(parents=True)
        (self.source / "licenses").mkdir()
        for directory in (self.source / "install", self.source / "install/bin",
                          self.source / "install/lib", self.source / "licenses"):
            os.chmod(directory, 0o700)
        self.payload = {
            "install/bin/python3.15": b"\xcf\xfa\xed\xfe" + b"synthetic executable",
            "install/lib/libpython3.15.dylib": b"\xcf\xfa\xed\xfe" + b"synthetic library",
            "licenses/LICENSE.txt": b"MIT fixture license\n",
            "licenses/DEPENDENCY.txt": b"dependency license fixture\n",
            "PYTHON.json": json.dumps({
                "python_version": "3.15.2",
                "target_triple": "aarch64-apple-darwin",
                "python_exe": "install/bin/python3.15",
                "apple_sdk_deployment_target": "11.0",
                "license_path": "licenses/LICENSE.txt",
                "licenses": ["MIT"],
                "build_info": {"extensions": {"_fixture": [{
                    "license_paths": ["licenses/DEPENDENCY.txt"]
                }]}},
            }, sort_keys=True, separators=(",", ":")).encode(),
        }
        self.entries = {
            "install": {"type": "directory", "mode": "0700"},
            "install/bin": {"type": "directory", "mode": "0700"},
            "install/lib": {"type": "directory", "mode": "0700"},
            "licenses": {"type": "directory", "mode": "0700"},
        }
        for name, data in self.payload.items():
            self.entries[name] = {"type": "file", "mode": "0644", "bytes": len(data), "sha256": digest(data)}
        self.entries["install/bin/python"] = {
            "type": "symlink", "mode": "0755", "target": "python3.15",
            "resolved_target": "install/bin/python3.15", "source_mode": "0775",
        }
        (self.source / "install/bin/python3.15").write_bytes(self.payload["install/bin/python3.15"])
        (self.source / "install/lib/libpython3.15.dylib").write_bytes(self.payload["install/lib/libpython3.15.dylib"])
        (self.source / "licenses/LICENSE.txt").write_bytes(self.payload["licenses/LICENSE.txt"])
        (self.source / "licenses/DEPENDENCY.txt").write_bytes(self.payload["licenses/DEPENDENCY.txt"])
        (self.source / "PYTHON.json").write_bytes(self.payload["PYTHON.json"])
        os.chmod(self.source / "install/bin/python3.15", 0o644)
        os.chmod(self.source / "install/lib/libpython3.15.dylib", 0o644)
        os.chmod(self.source / "licenses/LICENSE.txt", 0o644)
        os.chmod(self.source / "licenses/DEPENDENCY.txt", 0o644)
        os.chmod(self.source / "PYTHON.json", 0o644)
        os.symlink("python3.15", self.source / "install/bin/python")
        os.lchmod(self.source / "install/bin/python", 0o755)
        self.manifest = {
            "schema": 1,
            "state": "STAGED_PYTHON_NOT_EXECUTED_NOT_ADOPTED",
            "profile": normalizer.PROFILE,
            "archive_sha256": "1" * 64,
            "metadata_sha256": digest(self.payload["PYTHON.json"]),
            "expected_metadata": {
                "python_version": "3.15.2", "target_triple": "aarch64-apple-darwin",
                "python_exe": "install/bin/python3.15", "apple_sdk_deployment_target": "11.0",
            },
            "provenance": {
                "provider": "synthetic", "release": "fixture", "upstream_commit": "a" * 40,
                "url": "https://example.invalid/fixture",
            },
            "licenses": {"paths": ["licenses/LICENSE.txt", "licenses/DEPENDENCY.txt"],
                          "declarations": ["MIT", "dependency fixture"],
                          "legal_or_redistribution_review": "NOT_RUN"},
            "entries": copy.deepcopy(self.entries),
            "closure_macho": "NOT_RUN", "runtime_execution": "NOT_RUN", "adoption": "NOT_ADOPTED",
        }
        self.control = json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode()
        (self.source / "runtime-tree.json").write_bytes(self.control)
        os.chmod(self.source / "runtime-tree.json", 0o600)
        self.contents = self.root / "app/Contents"
        self.contents.mkdir(parents=True, mode=0o700)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, contents: Path | None = None) -> dict:
        return normalizer.copy_normalized_python(
            self.source, digest(self.control), contents or self.contents
        )

    def expect_error(self, code: str, contents: Path | None = None) -> None:
        with self.assertRaises(normalizer.NormalizeError) as caught:
            self.call(contents)
        self.assertEqual(caught.exception.code, code)

    def test_normalizes_complete_tree_and_preserves_source(self) -> None:
        before = {name: (self.source / name).read_bytes() for name in (*self.payload, "runtime-tree.json")}
        result = self.call()
        runtime = self.contents / "Resources/PythonRuntime"
        self.assertEqual(result["state"], "PRESIGN_NORMALIZED_NOT_EXECUTED")
        self.assertEqual(result["source_tree_sha256"], digest(self.control))
        self.assertEqual(result["file_count"], 5)
        self.assertEqual(result["symlink_count"], 1)
        self.assertNotIn("runtime-tree.json", result["inventory"])
        self.assertEqual(result["inventory"]["install/bin/python3.15"]["mode"], "0755")
        self.assertEqual(result["inventory"]["licenses/LICENSE.txt"]["mode"], "0644")
        self.assertEqual(os.readlink(runtime / "install/bin/python"), "python3.15")
        self.assertEqual((runtime / "install/bin/python").lstat().st_mode & 0o777, 0o777)
        self.assertEqual((self.source / "install/bin/python").lstat().st_mode & 0o777, 0o755)
        self.assertEqual({name: (self.source / name).read_bytes() for name in before}, before)
        self.assertEqual(stat_mode(runtime), 0o755)

    def test_wrong_control_pin_rejected_before_destination(self) -> None:
        with self.assertRaises(normalizer.NormalizeError) as caught:
            normalizer.copy_normalized_python(self.source, "0" * 64, self.contents)
        self.assertEqual(caught.exception.code, "tree_pin")
        self.assertFalse((self.contents / "Resources").exists())

    def test_unlisted_file_rejected_before_destination(self) -> None:
        (self.source / "install/lib/extra.so").write_bytes(b"extra")
        self.expect_error("source_inventory")
        self.assertFalse((self.contents / "Resources").exists())

    def test_missing_extension_license_dependency_is_rejected(self) -> None:
        self.manifest["licenses"]["paths"].remove("licenses/DEPENDENCY.txt")
        self.rewrite_manifest()
        self.expect_error("missing_license")
        self.assertFalse((self.contents / "Resources").exists())

    def test_extension_variants_dict_is_rejected(self) -> None:
        metadata = json.loads(self.payload["PYTHON.json"])
        metadata["build_info"]["extensions"]["_fixture"] = {
            "license_paths": ["licenses/DEPENDENCY.txt"]
        }
        self.rewrite_metadata(metadata)
        self.expect_error("metadata_contract")
        self.assertFalse((self.contents / "Resources").exists())

    def test_second_extension_variant_missing_license_is_rejected(self) -> None:
        metadata = json.loads(self.payload["PYTHON.json"])
        metadata["build_info"]["extensions"]["_fixture"].append({
            "license_paths": ["licenses/SECOND_VARIANT_MISSING.txt"]
        })
        self.rewrite_metadata(metadata)
        self.expect_error("missing_license")
        self.assertFalse((self.contents / "Resources").exists())

    def test_escaping_symlink_rejected_before_destination(self) -> None:
        (self.source / "install/bin/python").unlink()
        os.symlink("../../outside", self.source / "install/bin/python")
        self.entries["install/bin/python"]["target"] = "../../outside"
        self.entries["install/bin/python"]["resolved_target"] = "outside"
        self.rewrite_manifest()
        self.expect_error("unsafe_symlink")
        self.assertFalse((self.contents / "Resources").exists())

    def test_existing_destination_is_never_overwritten(self) -> None:
        resources = self.contents / "Resources"
        resources.mkdir()
        existing = resources / "PythonRuntime"
        existing.mkdir()
        marker = existing / "keep"
        marker.write_bytes(b"keep")
        self.expect_error("destination_exists")
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_source_quarantine_is_rejected_before_copy(self) -> None:
        with mock.patch.object(normalizer, "_xattr_names", return_value=["com.apple.quarantine"]):
            self.expect_error("source_quarantine")
        self.assertFalse((self.contents / "Resources").exists())

    def test_unavailable_xattr_api_fails_closed(self) -> None:
        with mock.patch.object(normalizer, "_xattr_names", side_effect=normalizer.NormalizeError("xattr_unavailable")):
            self.expect_error("xattr_unavailable")
        self.assertFalse((self.contents / "Resources").exists())

    def test_darwin_xattr_name_buffer_parser(self) -> None:
        self.assertEqual(normalizer._decode_xattr_names(b"com.apple.provenance\0user.fixture\0"),
                         ["com.apple.provenance", "user.fixture"])
        with self.assertRaises(normalizer.NormalizeError):
            normalizer._decode_xattr_names(b"unterminated")

    def test_failed_write_keeps_partial_evidence(self) -> None:
        real_write = os.write
        calls = 0

        def fail_after_first(fd: int, data: bytes) -> int:
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise OSError("synthetic write failure")
            return real_write(fd, data[:4])

        with mock.patch.object(normalizer.os, "write", side_effect=fail_after_first):
            with self.assertRaises(normalizer.NormalizeError) as caught:
                self.call()
        self.assertEqual(caught.exception.code, "io_error")
        runtime = self.contents / "Resources/PythonRuntime"
        partial = runtime / "PYTHON.json"
        self.assertTrue(partial.exists())
        self.assertEqual(partial.read_bytes(), self.payload["PYTHON.json"][:4])

    def test_source_change_during_copy_is_detected_and_retained(self) -> None:
        original_copy = normalizer._copy_regular
        changed = False

        def mutate_after_copy(*args, **kwargs):
            nonlocal changed
            result = original_copy(*args, **kwargs)
            if not changed:
                (self.source / "licenses/LICENSE.txt").write_bytes(b"mutated")
                changed = True
            return result

        with mock.patch.object(normalizer, "_copy_regular", side_effect=mutate_after_copy):
            with self.assertRaises(normalizer.NormalizeError) as caught:
                self.call()
        self.assertEqual(caught.exception.code, "source_changed")
        self.assertTrue((self.contents / "Resources/PythonRuntime").exists())

    def test_manifest_member_limit_rejected_before_destination(self) -> None:
        with mock.patch.object(normalizer, "MAX_MEMBERS", 1):
            self.expect_error("member_limit")
        self.assertFalse((self.contents / "Resources").exists())

    def rewrite_metadata(self, metadata: dict) -> None:
        raw = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        self.payload["PYTHON.json"] = raw
        (self.source / "PYTHON.json").write_bytes(raw)
        self.entries["PYTHON.json"]["bytes"] = len(raw)
        self.entries["PYTHON.json"]["sha256"] = digest(raw)
        self.manifest["metadata_sha256"] = digest(raw)
        self.rewrite_manifest()

    def rewrite_manifest(self) -> None:
        self.manifest["entries"] = copy.deepcopy(self.entries)
        self.control = json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode()
        (self.source / "runtime-tree.json").write_bytes(self.control)
        os.chmod(self.source / "runtime-tree.json", 0o600)


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
