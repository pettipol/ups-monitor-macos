#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic-only tests for prepare_synthetic_source."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import prepare_synthetic_source as subject


class PrepareSyntheticSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ups-source-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(strict=True)
        self.base.chmod(0o700)
        self.admitted_temp = self.base / "admitted-temp"
        self.admitted_temp.mkdir(mode=0o700)
        self.outside_parent = self.base / "outside-parent"
        self.outside_parent.mkdir(mode=0o700)
        self.checkout = self.base / "checkout"
        self.checkout.mkdir(mode=0o700)
        self.git_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/"),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        if os.environ.get("TMPDIR"):
            self.git_env["TMPDIR"] = os.environ["TMPDIR"]
        self.environment_patch = mock.patch.dict(os.environ, self.git_env, clear=True)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        self.git("init", "-q", str(self.checkout))
        self.git("-C", str(self.checkout), "config", "user.email", "fixture@example.invalid")
        self.git("-C", str(self.checkout), "config", "user.name", "Synthetic Fixture")
        self.git("-C", str(self.checkout), "config", "commit.gpgsign", "false")
        self.git("-C", str(self.checkout), "config", "core.hooksPath", "/dev/null")
        (self.checkout / ".gitignore").write_text("build/\n", encoding="utf-8")
        (self.checkout / "Sources/UPSRuntime").mkdir(parents=True)
        (self.checkout / "Sources/UPSRuntime/FrozenOperationalReleasePins.swift").write_bytes(
            b"/// Populated only in a separately reviewed packaging copy.\n"
            b"enum FrozenOperationalReleasePins {\n"
            b"    static let manifestSHA256: String? = nil\n}\n")
        (self.checkout / "Sources/UPSRuntime/BundledOperationalReleasePins.swift").write_bytes(
            b"/// A reviewed packaging build replaces this nil only in its isolated source copy.\n"
            b"/// No manifest, environment variable or UI input can enable the public default.\n"
            b"enum BundledOperationalReleasePins {\n"
            b"    static let manifestSHA256: String? = nil\n}\n")
        (self.checkout / "UPSMonitor.xcodeproj").mkdir()
        (self.checkout / "UPSMonitor.xcodeproj/project.pbxproj").write_bytes(
            b"PRODUCT_BUNDLE_IDENTIFIER = org.openupsmonitor.mac.preview;\n" * 8)
        image_fixture = self.checkout / "docs/images/widget-source0600.png"
        image_fixture.parent.mkdir(parents=True)
        image_fixture.write_bytes(b"synthetic image fixture\n")
        os.chmod(image_fixture, 0o600)
        (self.checkout / "tracked.txt").write_text("HEAD version\n", encoding="utf-8")
        (self.checkout / "executable.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(self.checkout / "executable.sh", 0o755)
        for path in (
            self.checkout / ".gitignore",
            self.checkout / "Sources/UPSRuntime/FrozenOperationalReleasePins.swift",
            self.checkout / "Sources/UPSRuntime/BundledOperationalReleasePins.swift",
            self.checkout / "UPSMonitor.xcodeproj/project.pbxproj",
            self.checkout / "tracked.txt",
        ):
            os.chmod(path, 0o644)
        self.git("-C", str(self.checkout), "add", ".")
        self.git("-C", str(self.checkout), "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        (self.checkout / "tracked.txt").write_text("current working-tree version\n", encoding="utf-8")
        (self.checkout / "untracked.txt").write_text("current untracked fixture\n", encoding="utf-8")
        os.chmod(self.checkout / "tracked.txt", 0o644)
        os.chmod(self.checkout / "untracked.txt", 0o644)
        (self.checkout / "AGENTS.md").write_text("private local instruction\n", encoding="utf-8")
        (self.checkout / "build").mkdir()
        (self.checkout / "build/generated.txt").write_text("ignored\n", encoding="utf-8")
        self.manifest = "a" * 64
        self.pin_file = self.base / "derived-pin.swift"
        self.pin_file.write_bytes(
            b"// Generated candidate pin; canonical release pin remains nil.\n"
            b"enum FrozenOperationalReleasePins {\n"
            + f'    static let manifestSHA256: String? = "{self.manifest}"\n'.encode("ascii")
            + b"}\n")
        self.output = self.base / "candidate"
        self.identifier = "org.openupsmonitor.synthetic.e58.synthetic"

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], check=True, env=self.git_env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_prepare(self, output: Path | None = None) -> dict:
        return subject.prepare_source(self.checkout, self.pin_file, self.manifest,
                                     self.identifier, output or self.output)

    def run_prepare_with_synthetic_temp_roots(self, output: Path) -> dict:
        real_path = Path
        environment_temp = os.getenv("TMPDIR", "/tmp")

        def redirect_temp_root(*args: object, **kwargs: object) -> Path:
            if len(args) == 1 and isinstance(args[0], str) and args[0] in {
                "/private/tmp", environment_temp,
            }:
                return real_path(self.admitted_temp)
            return real_path(*args, **kwargs)

        with mock.patch.object(subject, "Path", side_effect=redirect_temp_root):
            return self.run_prepare(output)

    def test_real_preview_requires_explicit_mode_and_matching_identifier(self) -> None:
        real = "org.example.monitor.real"
        for identifier, enabled in [(real, False), (self.identifier, True)]:
            with self.subTest(identifier=identifier), self.assertRaisesRegex(subject.PrepareError, "bundle_identifier"):
                subject.prepare_source(self.checkout, self.pin_file, self.manifest, identifier,
                                       self.output, real_preview=enabled)
            self.assertFalse(self.output.exists())
        receipt = subject.prepare_source(self.checkout, self.pin_file, self.manifest, real,
                                         self.output, real_preview=True)
        self.assertEqual(receipt["bundle_identifier"], real)
        self.assertEqual(len(receipt["deltas"]), 2)
        project = "UPSMonitor.xcodeproj/project.pbxproj"
        self.assertEqual((self.output / "source" / project).read_bytes().count(real.encode()), 8)
        self.assertEqual((self.checkout / project).read_bytes().count(subject.OLD_BUNDLE), 8)

    def test_success_copies_current_tree_and_records_only_two_deltas(self) -> None:
        receipt = self.run_prepare()
        source = self.output / "source"
        self.assertEqual(receipt["status"], "SOURCE_PREPARED_NOT_BUILT")
        self.assertEqual(len(receipt["deltas"]), 2)
        self.assertEqual((source / "tracked.txt").read_text(), "current working-tree version\n")
        self.assertTrue((source / "untracked.txt").exists())
        self.assertFalse((source / "AGENTS.md").exists())
        self.assertFalse((source / "build/generated.txt").exists())
        self.assertEqual((source / "Sources/UPSRuntime/FrozenOperationalReleasePins.swift").read_bytes(),
                         self.pin_file.read_bytes())
        project = (source / "UPSMonitor.xcodeproj/project.pbxproj").read_bytes()
        self.assertEqual(project.count(self.identifier.encode("ascii")), 8)
        self.assertTrue((self.output / "receipt.json").exists())
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        self.assertEqual((source / "tracked.txt").stat().st_mode & 0o777, 0o644)
        self.assertEqual((source / "executable.sh").stat().st_mode & 0o777, 0o755)
        self.assertEqual((source / "docs/images/widget-source0600.png").read_bytes(), b"synthetic image fixture\n")
        self.assertEqual((source / "docs/images/widget-source0600.png").stat().st_mode & 0o777, 0o600)
        self.assertEqual(receipt["source_before"], receipt["source_after"])
        before = {row["path"]: row for row in receipt["source_before"]}
        destination = {row["path"]: row for row in receipt["destination"]}
        actual_deltas = {name for name in before if before[name] != destination[name]}
        self.assertEqual(actual_deltas, {
            "Sources/UPSRuntime/FrozenOperationalReleasePins.swift",
            "UPSMonitor.xcodeproj/project.pbxproj",
        })

    def test_rejects_invalid_pin_hash_identifier_and_occupied_destination(self) -> None:
        with self.subTest("bad pin"):
            self.pin_file.write_bytes(b"arbitrary Swift\n")
            with self.assertRaises(subject.PrepareError):
                self.run_prepare()
            self.pin_file.write_text("", encoding="utf-8")
            self.pin_file.write_bytes(
                b"// Generated candidate pin; canonical release pin remains nil.\n"
                b"enum FrozenOperationalReleasePins {\n"
                + f'    static let manifestSHA256: String? = "{self.manifest}"\n'.encode("ascii")
                + b"}\n")
        with self.subTest("valid-length pin mismatch"):
            wrong_hash = "b" * 64
            self.pin_file.write_bytes(
                b"// Generated candidate pin; canonical release pin remains nil.\n"
                b"enum FrozenOperationalReleasePins {\n"
                + f'    static let manifestSHA256: String? = "{wrong_hash}"\n'.encode("ascii")
                + b"}\n")
            with self.assertRaisesRegex(subject.PrepareError, "pin_format"):
                self.run_prepare()
            self.pin_file.write_bytes(
                b"// Generated candidate pin; canonical release pin remains nil.\n"
                b"enum FrozenOperationalReleasePins {\n"
                + f'    static let manifestSHA256: String? = "{self.manifest}"\n'.encode("ascii")
                + b"}\n")
        with self.subTest("appended Swift"):
            self.pin_file.write_bytes(self.pin_file.read_bytes() + b"// appended\n")
            with self.assertRaisesRegex(subject.PrepareError, "pin_format"):
                self.run_prepare()
            self.pin_file.write_bytes(self.pin_file.read_bytes().removesuffix(b"// appended\n"))
        with self.subTest("bad digest"):
            with self.assertRaises(subject.PrepareError):
                subject.prepare_source(self.checkout, self.pin_file, "A" * 64,
                                       self.identifier, self.output)
        with self.subTest("bad identifier"):
            with self.assertRaises(subject.PrepareError):
                subject.prepare_source(self.checkout, self.pin_file, self.manifest,
                                       "org.openupsmonitor.mac.preview.synthetic", self.output)
        with self.subTest("occupied destination"):
            self.output.mkdir()
            with self.assertRaises(subject.PrepareError):
                self.run_prepare()

    def test_rejects_symlink_source(self) -> None:
        (self.checkout / "linked.txt").symlink_to("tracked.txt")
        with self.assertRaises(subject.PrepareError):
            self.run_prepare()

    def test_rejects_symlink_pin_before_destination(self) -> None:
        linked_pin = self.base / "derived-pin-link.swift"
        linked_pin.symlink_to(self.pin_file.name)
        with self.assertRaisesRegex(subject.PrepareError, "pin_file"):
            subject.prepare_source(self.checkout, linked_pin, self.manifest,
                                  self.identifier, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_enabled_canonical_pin_even_with_nil_comment(self) -> None:
        path = self.checkout / "Sources/UPSRuntime/FrozenOperationalReleasePins.swift"
        path.write_text(
            "/* static let manifestSHA256: String? = nil */\n"
            "enum FrozenOperationalReleasePins {\n"
            "    static let manifestSHA256: String? = \"enabled\"\n}\n",
            encoding="utf-8")
        with self.assertRaisesRegex(subject.PrepareError, "canonical_pin"):
            self.run_prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_bad_bundle_prefix_count(self) -> None:
        path = self.checkout / "UPSMonitor.xcodeproj/project.pbxproj"
        original = path.read_bytes()
        with self.subTest("seven"):
            path.write_bytes(original.replace(subject.OLD_BUNDLE, b"org.example.synthetic", 1))
            with self.assertRaisesRegex(subject.PrepareError, "bundle_occurrences"):
                self.run_prepare()
            self.assertFalse(self.output.exists())
        with self.subTest("nine"):
            path.write_bytes(original + subject.OLD_BUNDLE)
            with self.assertRaisesRegex(subject.PrepareError, "bundle_occurrences"):
                self.run_prepare()
            self.assertFalse(self.output.exists())

    def test_rejects_other_modes_and_file_size_over_limit(self) -> None:
        for mode in (0o640, 0o666):
            with self.subTest(mode=oct(mode)):
                private = self.checkout / "private.txt"
                private.write_text("private mode\n", encoding="utf-8")
                os.chmod(private, mode)
                with self.assertRaisesRegex(subject.PrepareError, "source_mode"):
                    self.run_prepare()
                self.assertFalse(self.output.exists())
                private.unlink()
        with mock.patch.object(subject, "MAX_FILE", 4):
            with self.assertRaisesRegex(subject.PrepareError, "file_limit"):
                self.run_prepare()
        self.assertFalse(self.output.exists())

    def test_rejects_output_overlap_nonprivate_and_outside_temp(self) -> None:
        with self.subTest("overlap"):
            with self.assertRaisesRegex(subject.PrepareError, "path_overlap"):
                self.run_prepare(self.checkout / "candidate")
        world = self.base / "world"
        world.mkdir()
        world.chmod(0o777)
        with self.subTest("nonprivate parent"):
            with self.assertRaisesRegex(subject.PrepareError, "destination_parent"):
                self.run_prepare(world / "candidate")
        world.chmod(0o700)
        admitted = self.admitted_temp / "candidate"
        with self.subTest("admitted temp sibling"):
            receipt = self.run_prepare_with_synthetic_temp_roots(admitted)
            self.assertEqual(receipt["status"], "SOURCE_PREPARED_NOT_BUILT")
            self.assertTrue(admitted.is_dir())
        outside = self.outside_parent / "candidate"
        with self.subTest("outside temp"):
            with self.assertRaisesRegex(subject.PrepareError, "destination_not_temp"):
                self.run_prepare_with_synthetic_temp_roots(outside)
            self.assertFalse(outside.exists())

    def test_rechecks_source_after_copy_and_preserves_partial_candidate(self) -> None:
        original = subject._copy_file

        def change_source(root: Path, name: str, raw: bytes, mode: int) -> None:
            original(root, name, raw, mode)
            if name == "tracked.txt":
                (self.checkout / name).write_text("changed during copy\n", encoding="utf-8")

        with mock.patch.object(subject, "_copy_file", side_effect=change_source):
            with self.assertRaisesRegex(subject.PrepareError, "source_changed"):
                self.run_prepare()
        self.assertTrue((self.output / "source/tracked.txt").exists())

    def test_detects_corrupted_destination_copy(self) -> None:
        original = subject._copy_file

        def corrupt_copy(root: Path, name: str, raw: bytes, mode: int) -> None:
            original(root, name, raw, mode)
            if name == "tracked.txt":
                (root / name).write_text("corrupted copy\n", encoding="utf-8")

        with mock.patch.object(subject, "_copy_file", side_effect=corrupt_copy):
            with self.assertRaisesRegex(subject.PrepareError, "destination_corrupt"):
                self.run_prepare()

    def test_rechecks_source_name_set_after_copy(self) -> None:
        original = subject._copy_file

        def add_source_name(root: Path, name: str, raw: bytes, mode: int) -> None:
            original(root, name, raw, mode)
            if name == "tracked.txt":
                appeared = self.checkout / "appeared-after-snapshot.txt"
                appeared.write_text("late\n", encoding="utf-8")
                os.chmod(appeared, 0o644)

        with mock.patch.object(subject, "_copy_file", side_effect=add_source_name):
            with self.assertRaisesRegex(subject.PrepareError, "source_changed"):
                self.run_prepare()

    def test_detects_extra_destination_entry(self) -> None:
        original = subject._copy_file

        def add_destination_file(root: Path, name: str, raw: bytes, mode: int) -> None:
            original(root, name, raw, mode)
            if name == "tracked.txt":
                (root / "extra.txt").write_text("extra\n", encoding="utf-8")

        with mock.patch.object(subject, "_copy_file", side_effect=add_destination_file):
            with self.assertRaisesRegex(subject.PrepareError, "destination_corrupt"):
                self.run_prepare()


if __name__ == "__main__":
    unittest.main()
