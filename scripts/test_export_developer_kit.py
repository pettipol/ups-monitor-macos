"""Offline contract tests for export_developer_kit."""
from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
import io
import json
import sys
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import export_developer_kit as exporter

NATIVE = "backend/nut/native-build/"
PROFILE_MANIFEST = NATIVE + "hidapi-0.16/manifest.json"
PROFILE_GATE = NATIVE + "hidapi-0.16/version-gate.patch"
PROFILE_FILES = {"mac/hid.c", "mac/hidapi_darwin.h", "hidapi/hidapi.h", "src/core/hidapi_input_ring.h",
                 "LICENSE.txt", "LICENSE-bsd.txt", "LICENSE-gpl3.txt", "LICENSE-orig.txt"}
RING = "src/core/hidapi_input_ring.h"

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ExportDeveloperKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="developer-kit-test-")
        self.root = Path(self.temp.name)
        self.source_root = "reviewed-project"
        self.source = self.root / "project.tar"
        self.nut = self.root / "nut.tar"
        self.hidapi = self.root / "hidapi"
        self.hidapi_016 = self.root / "hidapi-016"
        self.pbs_name = "cpython-3.15.2+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst"
        self.pbs = self.root / self.pbs_name
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        self.hidapi.mkdir()
        self._make_inputs()
        self.output = self.root / "kit.tar"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_inputs(self) -> None:
        wheel_rows = []
        self.wheel_blobs = {}
        for name, blob in ((f"pkg{i}-1.0-py3-none-any.whl", f"wheel-{i}".encode()) for i in range(6)):
            wheel_rows.append({"filename": name, "sha256": sha(blob), "bytes": len(blob)})
            self.wheel_blobs[name] = blob
            (self.wheels / name).write_bytes(blob)

        self.pbs_blob = b"pbs-content"
        self.nut_blob = b"nut-content"
        self.hid_blobs = {name: ("hid:" + name).encode() for name in exporter.HIDAPI_PATHS}
        self.hid_license_blobs = {name: ("license:" + name).encode()
                                  for name in ("LICENSE.txt", "LICENSE-bsd.txt", "LICENSE-gpl3.txt", "LICENSE-orig.txt")}
        for rel, blob in self.hid_blobs.items():
            path = self.hidapi / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        for name, blob in self.hid_license_blobs.items():
            (self.hidapi / name).write_bytes(blob)
        self.pbs.write_bytes(self.pbs_blob)
        self.nut.write_bytes(self.nut_blob)

        runtime = {"archive": {"sha256": sha(self.pbs_blob), "bytes": len(self.pbs_blob)},
                   "provenance": {"url": "https://example.invalid/releases/" + self.pbs_name}}
        frozen = {"packages": wheel_rows}
        native = {"upstream": {"archive_sha256": sha(self.nut_blob)},
                  "hidapi": {"source_sha256": {name: sha(self.hid_blobs[name])
                                                  for name in exporter.HIDAPI_PATHS},
                            "license_sha256": {name: sha(blob)
                                               for name, blob in self.hid_license_blobs.items()}}}
        self.source_files = {
            "LICENSE": b"MIT license text\n",
            "THIRD_PARTY_NOTICES.md": b"Notices\n",
            "docs/OFFLINE_DEVELOPER_KIT.md": b"Offline instructions\n",
            "backend/nut/bundled_python_runtime_inputs.json": json.dumps(runtime).encode(),
            "backend/nut/frozen_build_inputs.json": json.dumps(frozen).encode(),
            "backend/nut/native-build/production_source_post_cal.json": json.dumps(native).encode(),
            **{"backend/nut/native-build/licenses/hidapi/" + name: blob
               for name, blob in self.hid_license_blobs.items()},
            "Package.swift": b"// Swift package input\n",
            "backend/nut/prepare_production_source.py": b"# source preparation\n",
            "backend/nut/stage_hidapi_candidate.py": b"# HIDAPI staging\n",
            "backend/nut/stage_bundled_python_runtime.py": b"# PBS staging\n",
            "backend/nut/native-build/README.md": b"Native build instructions\n",
            "docs/FROZEN_BUILD_RECIPE.md": b"Frozen build steps\n",
            "docs/SOURCE_RELEASE.md": b"Source release steps\n",
        }
        self._write_source(self.source_files)

    def _write_source(self, files: dict[str, bytes], extra: tuple[str, ...] = ()) -> None:
        with tarfile.open(self.source, "w", format=tarfile.USTAR_FORMAT) as archive:
            root_info = exporter.tar_info(self.source_root, is_directory=True)
            archive.addfile(root_info)
            directories = {"backend", "backend/nut", "backend/nut/native-build",
                           "backend/nut/native-build/licenses", "backend/nut/native-build/licenses/hidapi", "docs"}
            for name in sorted(directories):
                archive.addfile(exporter.tar_info(f"{self.source_root}/{name}", is_directory=True))
            for name, blob in [*sorted(files.items()), *((name, b"extra") for name in extra)]:
                info = exporter.tar_info(f"{self.source_root}/{name}", size=len(blob))
                archive.addfile(info, io.BytesIO(blob))

    def _profile_files(self) -> dict[str, bytes]:
        files = self.source_files.copy()
        changed = {"drivers/apcmicrolink-hidapi-native.c", "drivers/apcmicrolink-hidapi-shared.c",
                   "drivers/apcmicrolink-hidapi-shared-host.h"}
        base = {name: sha(name.encode()) for name in changed | {f"drivers/file-{i}.c" for i in range(187)}}
        cancel = {**base, **{name: sha((name + ":cancel").encode()) for name in changed}}
        after = {**cancel, "drivers/apcmicrolink-hidapi-native.c": sha(b"native-gate-016")}
        generated = {name: sha(name.encode()) for name in (
            "include/config.h", "include/nut_version.h", "drivers/.libs/libdummy_serial.a",
            "drivers/.libs/libdummy_upsdrvquery.a", "common/.libs/libcommon.a",
            "common/.libs/libcommonversion.a", "common/.libs/libparseconf.a")}
        files[NATIVE + "nut-cal-status-freshness.patch"] = b"CAL patch data\n"
        files[NATIVE + "nut-write-cancel-boundary-v2.patch"] = b"write-cancel patch data\n"
        files[PROFILE_GATE] = b"version-gate patch data\n"
        files[NATIVE + "WRITE_CANCEL_BOUNDARY.md"] = b"Write-cancel guide\n"
        files[NATIVE + "hidapi-0.16/README.md"] = b"HIDAPI 0.16 guide\n"
        cal_path = NATIVE + "production_source_post_cal.json"
        cal = json.loads(files[cal_path])
        cal["upstream"]["revision"] = "73c4502191d025e35122463986a80c676e734b04"
        cal["hidapi"]["tag"] = "hidapi-0.15.0"
        cal["cal_patch"] = {"file": "nut-cal-status-freshness.patch",
                            "sha256": sha(files[NATIVE + "nut-cal-status-freshness.patch"])}
        cal["post_cal_sha256"] = base
        cal["build"] = {"generated_input_sha256": generated}
        files[cal_path] = json.dumps(cal, sort_keys=True).encode()
        cancel_path = NATIVE + "production_source_post_write_cancel.json"
        files[cancel_path] = json.dumps({"base_manifest_sha256": sha(files[cal_path]),
            "patch_sha256": sha(files[NATIVE + "nut-write-cancel-boundary-v2.patch"]),
            "post_write_cancel_sha256": cancel}, sort_keys=True).encode()
        rows = []
        self.hid_016_blobs = {}
        for name in sorted(PROFILE_FILES):
            blob = ("hid016:" + name).encode()
            self.hid_016_blobs[name] = blob
            dest = self.hidapi_016 / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            rows.append({"path": name, "bytes": len(blob), "sha256": sha(blob)})
        files[PROFILE_MANIFEST] = json.dumps({"base_manifest_sha256": sha(files[cancel_path]),
            "gate_patch_sha256": sha(files[PROFILE_GATE]), "nut_commit": cal["upstream"]["revision"],
            "nut_git_archive_sha256": cal["upstream"]["archive_sha256"], "reused_generated_input_sha256": generated,
            "post_hidapi_016_sha256": after, "hidapi": {"tag": "hidapi-0.16.0",
                "commit": "750c87abb03282a237297052b84522e6bb3c0616", "files": rows}}, sort_keys=True).encode()
        return files

    def _args(self, output: Path | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            source=self.source, source_sha256=sha(self.source.read_bytes()), nut_archive=self.nut,
            hidapi_source=self.hidapi, pbs_archive=self.pbs, wheels=self.wheels,
            output=output or self.output)

    def _profile_args(self, output: Path | None = None) -> SimpleNamespace:
        args = self._args(output)
        args.native_profile = "hidapi-0.16"
        args.hidapi_016_source = self.hidapi_016
        return args

    def _unchanged_outputs(self) -> None:
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".kit.tar.*.tmp")), [])

    def test_exports_reproducible_ustar_with_only_locked_payload(self) -> None:
        first, second = self.root / "one.tar", self.root / "two.tar"
        first_sha = exporter.export_kit(self._args(first))
        second_sha = exporter.export_kit(self._args(second))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first_sha, second_sha)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        with tarfile.open(first, "r:") as archive:
            rows = archive.getmembers()
            names = {member.name for member in rows}
            self.assertEqual(len(rows), len(names))
            self.assertTrue(all(member.uid == member.gid == member.mtime == 0 for member in rows))
            self.assertTrue(all(member.uname == member.gname == "" for member in rows))
            self.assertTrue(all(member.isfile() or member.isdir() for member in rows))
            self.assertIn("UPS-Monitor-Developer-Inputs/README.md", names)
            self.assertIn("UPS-Monitor-Developer-Inputs/source/project.tar", names)
            self.assertIn("UPS-Monitor-Developer-Inputs/native/hidapi/hidapi/hidapi.h", names)
            self.assertIn("UPS-Monitor-Developer-Inputs/native/hidapi/mac/hidapi_darwin.h", names)
            self.assertIn("UPS-Monitor-Developer-Inputs/python/" + self.pbs_name, names)
            self.assertIn("UPS-Monitor-Developer-Inputs/SHA256SUMS", names)
            self.assertEqual(sum(member.isfile() for member in rows), 16)
            project_member = archive.getmember("UPS-Monitor-Developer-Inputs/source/project.tar")
            project_blob = archive.extractfile(project_member).read()
            with tarfile.open(fileobj=io.BytesIO(project_blob), mode="r:") as project_tar:
                license_member = project_tar.getmember(
                    f"{self.source_root}/backend/nut/native-build/licenses/hidapi/LICENSE-bsd.txt")
                self.assertEqual(project_tar.extractfile(license_member).read(),
                                 self.hid_license_blobs["LICENSE-bsd.txt"])

    def test_accepts_git_archive_shape_without_directory_headers(self) -> None:
        blob = self.source.read_bytes()
        rows = []
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as source_tar:
            for member in source_tar.getmembers():
                if member.isfile():
                    rows.append((member, source_tar.extractfile(member).read()))
        no_dirs = self.root / "git-archive.tar"
        with tarfile.open(no_dirs, "w", format=tarfile.USTAR_FORMAT) as archive:
            for member, content in rows:
                archive.addfile(member, io.BytesIO(content))
        args = self._args(self.root / "implicit-dirs.tar")
        args.source = no_dirs
        args.source_sha256 = sha(no_dirs.read_bytes())
        exporter.export_kit(args)
        with tarfile.open(args.output, "r:") as result:
            self.assertEqual(result.extractfile("UPS-Monitor-Developer-Inputs/README.md").read(),
                             b"Offline instructions\n")

    def test_rejects_regular_file_used_as_archive_parent(self) -> None:
        blob = self.source.read_bytes()
        rows = []
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as source_tar:
            for member in source_tar.getmembers():
                if member.isdir() and member.name.rstrip("/") == f"{self.source_root}/docs":
                    continue
                stream = source_tar.extractfile(member) if member.isfile() else None
                rows.append((member, stream.read() if stream else None))
        malicious = self.root / "file-parent.tar"
        with tarfile.open(malicious, "w", format=tarfile.USTAR_FORMAT) as archive:
            for member, content in rows:
                archive.addfile(member, io.BytesIO(content) if content is not None else None)
            blob = b"parent is a regular file"
            archive.addfile(exporter.tar_info(f"{self.source_root}/docs", size=len(blob)), io.BytesIO(blob))
        args = self._args()
        args.source = malicious
        args.source_sha256 = sha(malicious.read_bytes())
        with self.assertRaisesRegex(exporter.ExportError, "regular file as parent"):
            exporter.export_kit(args)
        self.assertFalse(self.output.exists())

    def test_mutated_outer_source_pin_refused_before_output(self) -> None:
        original = self._args()
        stale_pin = original.source_sha256
        self.source.write_bytes(self.source.read_bytes() + b"tamper")
        original.source_sha256 = stale_pin
        with self.assertRaisesRegex(exporter.ExportError, "source archive SHA-256 mismatch"):
            exporter.export_kit(original)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".kit.tar.*.tmp")), [])

    def test_missing_required_source_file_refused(self) -> None:
        # Rebuild a valid outer tar without the required offline guide.
        blob = self.source.read_bytes()
        rows = []
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as source_tar:
            for member in source_tar.getmembers():
                if member.name.endswith("/docs/OFFLINE_DEVELOPER_KIT.md"):
                    continue
                stream = source_tar.extractfile(member) if member.isfile() else None
                rows.append((member, stream.read() if stream else None))
        replacement = self.root / "missing.tar"
        with tarfile.open(replacement, "w", format=tarfile.USTAR_FORMAT) as archive:
            for member, content in rows:
                archive.addfile(member, io.BytesIO(content) if content is not None else None)
        args = self._args()
        args.source = replacement
        args.source_sha256 = sha(replacement.read_bytes())
        with self.assertRaisesRegex(exporter.ExportError, "source lacks required file"):
            exporter.export_kit(args)
        self.assertFalse(self.output.exists())

    def test_locked_input_mutation_rolls_back_temporary_output(self) -> None:
        files = exporter.build_file_set(self.source, sha(self.source.read_bytes()), self.nut,
                                        self.hidapi, self.pbs, self.wheels)
        wheel = self.wheels / sorted(self.wheel_blobs)[0]
        changed = wheel.read_bytes()
        wheel.write_bytes(b"X" + changed[1:])
        with self.assertRaisesRegex(exporter.ExportError, "input changed while being archived"):
            exporter.publish_tar(self.output, files)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".kit.tar.*.tmp")), [])

    def test_existing_output_is_never_overwritten(self) -> None:
        sentinel = b"keep existing output"
        self.output.write_bytes(sentinel)
        with self.assertRaisesRegex(exporter.ExportError, "output already exists"):
            exporter.export_kit(self._args())
        self.assertEqual(self.output.read_bytes(), sentinel)
        self.assertEqual(list(self.root.glob(".kit.tar.*.tmp")), [])

    def test_default_is_identical_with_or_without_explicit_profile_even_with_invalid_opt_in_lock(self) -> None:
        files = self._profile_files()
        files[PROFILE_MANIFEST] = b"not a JSON lock"
        self._write_source(files)
        implicit = self._args(self.root / "implicit.tar")
        explicit = self._args(self.root / "explicit.tar")
        explicit.native_profile = "hidapi-0.15"
        explicit.hidapi_016_source = None
        self.assertEqual(exporter.export_kit(implicit), exporter.export_kit(explicit))
        self.assertEqual(implicit.output.read_bytes(), explicit.output.read_bytes())
        with tarfile.open(implicit.output, "r:") as archive:
            self.assertEqual(sum(member.isfile() for member in archive.getmembers()), 16)
        with self.assertRaisesRegex(exporter.ExportError, "invalid JSON lock"):
            exporter.export_kit(self._profile_args())
        self._unchanged_outputs()

    def test_opt_in_adds_exactly_eight_verified_files_to_default_archive(self) -> None:
        self._write_source(self._profile_files())
        default = self._args(self.root / "default.tar")
        exporter.export_kit(default)
        first = self._profile_args()
        second = self._profile_args(self.root / "again.tar")
        self.assertEqual(exporter.export_kit(first), exporter.export_kit(second))
        self.assertEqual(first.output.read_bytes(), second.output.read_bytes())
        root = "UPS-Monitor-Developer-Inputs/"

        def payload(path: Path) -> dict[str, bytes]:
            with tarfile.open(path, "r:") as archive:
                rows = archive.getmembers()
                for member in rows:
                    self.assertEqual((member.uid, member.gid, member.mtime, member.uname, member.gname), (0, 0, 0, "", ""))
                    self.assertEqual(member.mode, 0o644 if member.isfile() else 0o755)
                return {m.name.removeprefix(root): archive.extractfile(m).read() for m in rows if m.isfile()}

        before, after = payload(default.output), payload(first.output)
        self.assertEqual((len(before), len(after)), (16, 24))
        self.assertEqual({key: value for key, value in after.items() if key.startswith("native/hidapi-0.16/")},
                         {"native/hidapi-0.16/" + name: blob for name, blob in self.hid_016_blobs.items()})
        for name, blob in before.items():
            if name != "SHA256SUMS":
                self.assertEqual(after[name], blob)
        self.assertEqual(after.pop("SHA256SUMS"), "".join(
            f"{sha(blob)}  {name}\n" for name, blob in sorted(after.items())).encode())

    def test_cli_rejects_unknown_missing_and_misused_profile_options(self) -> None:
        argv = ["export_developer_kit.py", "--source", str(self.source), "--source-sha256", sha(self.source.read_bytes()),
                "--nut-archive", str(self.nut), "--hidapi-source", str(self.hidapi), "--pbs-archive", str(self.pbs),
                "--wheels", str(self.wheels), "--output", str(self.output)]
        cases = ((["--native-profile", "hidapi-0.18"], "invalid choice"),
                 (["--native-profile", "hidapi-0.16"], "requires --hidapi-016-source"),
                 (["--hidapi-016-source", str(self.hidapi_016)], "requires --native-profile hidapi-0.16"))
        for flags, diagnostic in cases:
            with self.subTest(flags=flags), patch.object(sys, "argv", argv + flags), redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
                    exporter.main()
                self.assertEqual(error.exception.code, 2)
                self.assertIn(diagnostic, stderr.getvalue())
                self._unchanged_outputs()

    def test_api_rejects_inconsistent_profile_before_reading_inputs(self) -> None:
        for profile, vendor, diagnostic in (("hidapi-0.18", None, "unknown native profile"),
                ("hidapi-0.16", None, "requires --hidapi-016-source"),
                ("hidapi-0.15", self.hidapi_016, "requires --native-profile hidapi-0.16")):
            with self.subTest(profile=profile):
                args = self._args()
                args.source = self.root / "missing.tar"
                args.native_profile, args.hidapi_016_source = profile, vendor
                with self.assertRaisesRegex(exporter.ExportError, diagnostic):
                    exporter.export_kit(args)
                self._unchanged_outputs()

    def test_repinned_source_requires_embedded_gate_and_ignores_adjacent_copy(self) -> None:
        files = self._profile_files()
        omitted = files.copy()
        real_gate = omitted.pop(PROFILE_GATE)
        adjacent = self.root / PROFILE_GATE
        adjacent.parent.mkdir(parents=True)
        adjacent.write_bytes(real_gate)
        cases = [(omitted, "source lacks required file")]
        cases.extend(({**files, path: b"corrupt patch"}, "patch SHA-256 mismatch: " + path.removeprefix(NATIVE))
                     for path in (PROFILE_GATE, NATIVE + "nut-cal-status-freshness.patch",
                                  NATIVE + "nut-write-cancel-boundary-v2.patch"))
        for changed, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self._write_source(changed)
                with self.assertRaisesRegex(exporter.ExportError, diagnostic):
                    exporter.export_kit(self._profile_args())
                self._unchanged_outputs()

    def test_repinned_source_rejects_wrong_lock_chain(self) -> None:
        files = self._profile_files()
        for key, value, diagnostic in (("base_manifest_sha256", sha(b"wrong"), "base manifest pin mismatch"),
                ("nut_commit", "0" * 40, "NUT baseline mismatch"),
                ("reused_generated_input_sha256", {}, "generated inputs differ"),
                ("post_hidapi_016_sha256", {}, "source inventories differ")):
            with self.subTest(key=key):
                profile = json.loads(files[PROFILE_MANIFEST])
                profile[key] = value
                self._write_source({**files, PROFILE_MANIFEST: json.dumps(profile).encode()})
                with self.assertRaisesRegex(exporter.ExportError, diagnostic):
                    exporter.export_kit(self._profile_args())
                self._unchanged_outputs()

    def test_repinned_source_checks_each_delta_after_manifest_digests_match(self) -> None:
        files = self._profile_files()
        cancel_path = NATIVE + "production_source_post_write_cancel.json"
        for change_cancel in (True, False):
            with self.subTest(change_cancel=change_cancel):
                changed = files.copy()
                profile = json.loads(files[PROFILE_MANIFEST])
                if change_cancel:
                    cancel = json.loads(files[cancel_path])
                    cancel["post_write_cancel_sha256"]["drivers/file-0.c"] = sha(b"unexpected cancel delta")
                    changed[cancel_path] = json.dumps(cancel, sort_keys=True).encode()
                    profile["base_manifest_sha256"] = sha(changed[cancel_path])
                else:
                    profile["post_hidapi_016_sha256"]["drivers/file-0.c"] = sha(b"unexpected gate delta")
                changed[PROFILE_MANIFEST] = json.dumps(profile, sort_keys=True).encode()
                self._write_source(changed)
                with self.assertRaisesRegex(exporter.ExportError, "wrong write-cancel source delta" if change_cancel
                                            else "wrong HIDAPI 0.16 source delta"):
                    exporter.export_kit(self._profile_args())
                self._unchanged_outputs()

    def test_rejects_missing_and_mutated_ring_and_license(self) -> None:
        self._write_source(self._profile_files())
        for name in (RING, "LICENSE-bsd.txt"):
            for missing in (True, False):
                with self.subTest(name=name, missing=missing):
                    path = self.hidapi_016 / name
                    original = self.hid_016_blobs[name]
                    if missing:
                        path.unlink()
                    else:
                        path.write_bytes(b"X" + original[1:])
                    with self.assertRaisesRegex(exporter.ExportError, "cannot stat input" if missing else "SHA-256 mismatch"):
                        exporter.export_kit(self._profile_args())
                    self._unchanged_outputs()
                    path.write_bytes(original)

    def test_rejects_symlink_ancestors_of_vendor_root_and_ring(self) -> None:
        self._write_source(self._profile_files())
        external = self.root / "external"
        external.mkdir()
        vendor = external / "hidapi-016"
        self.hidapi_016.rename(vendor)
        alias = self.root / "alias"
        alias.symlink_to(external, target_is_directory=True)
        args = self._profile_args()
        args.hidapi_016_source = alias / "hidapi-016"
        with self.assertRaisesRegex(exporter.ExportError, "source ancestor.*symlink"):
            exporter.export_kit(args)
        args.hidapi_016_source = vendor
        core = vendor / "src/core"
        real_core = self.root / "core"
        core.rename(real_core)
        core.symlink_to(real_core, target_is_directory=True)
        with self.assertRaisesRegex(exporter.ExportError, "hidapi_input_ring.h parent.*symlink"):
            exporter.export_kit(args)
        self._unchanged_outputs()

    def test_rejects_duplicate_traversing_and_invalid_size_vendor_rows(self) -> None:
        files = self._profile_files()
        for edit, diagnostic in (({"path": "../mac/hid.c"}, "duplicate or unsafe"),
                                 ({"path": "/mac/hid.c"}, "duplicate or unsafe"),
                                 ({"path": "mac/hid.c"}, "duplicate or unsafe"),
                                 ({"bytes": True}, "invalid size"),
                                 ({"bytes": 0}, "invalid size"),
                                 ({"sha256": "A" * 64}, "invalid SHA-256")):
            with self.subTest(edit=edit):
                profile = json.loads(files[PROFILE_MANIFEST])
                profile["hidapi"]["files"][0].update(edit)
                self._write_source({**files, PROFILE_MANIFEST: json.dumps(profile).encode()})
                with self.assertRaisesRegex(exporter.ExportError, diagnostic):
                    exporter.export_kit(self._profile_args())
                self._unchanged_outputs()

    def test_rejects_duplicate_and_traversing_repinned_tar_members(self) -> None:
        files = self._profile_files()
        for extra, diagnostic in ((PROFILE_GATE, "duplicate source archive member"),
                                  ("../outside", "unsafe or non-canonical archive path")):
            with self.subTest(extra=extra):
                self._write_source(files, extra=(extra,))
                with self.assertRaisesRegex(exporter.ExportError, diagnostic):
                    exporter.export_kit(self._profile_args())
                self._unchanged_outputs()

    def test_rejects_dot_tar_member_as_an_unsafe_path(self) -> None:
        self._write_source(self._profile_files())
        with tarfile.open(self.source, "a", format=tarfile.USTAR_FORMAT) as archive:
            archive.addfile(exporter.tar_info(".", size=1), io.BytesIO(b"X"))
        with self.assertRaisesRegex(exporter.ExportError, "unsafe or non-canonical archive path"):
            exporter.export_kit(self._profile_args())
        self._unchanged_outputs()

    def test_rejects_duplicate_json_key_in_repinned_profile(self) -> None:
        files = self._profile_files()
        files[PROFILE_MANIFEST] = b'{"hidapi":null,' + files[PROFILE_MANIFEST][1:]
        self._write_source(files)
        with self.assertRaisesRegex(exporter.ExportError, "duplicate JSON key"):
            exporter.export_kit(self._profile_args())
        self._unchanged_outputs()

    def test_016_streaming_mutation_leaves_no_output_or_temp(self) -> None:
        self._write_source(self._profile_files())
        args = self._profile_args()
        ring = self.hidapi_016 / RING
        original = ring.read_bytes()
        for mutated, diagnostic in ((b"X" + original[1:], "input changed while being archived"),
                                    (original + b"X", "input grew while being archived")):
            with self.subTest(diagnostic=diagnostic):
                ring.write_bytes(original)
                files = exporter.build_file_set(args.source, args.source_sha256, args.nut_archive, args.hidapi_source,
                                                args.pbs_archive, args.wheels, native_profile=args.native_profile,
                                                hidapi_016_source=args.hidapi_016_source)
                ring.write_bytes(mutated)
                with self.assertRaisesRegex(exporter.ExportError, diagnostic):
                    exporter.publish_tar(self.output, files)
                self._unchanged_outputs()


if __name__ == "__main__":
    unittest.main()
