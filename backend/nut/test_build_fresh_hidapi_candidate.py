#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Data-only tests for the fresh HIDAPI 0.16 build checks."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


path = Path(__file__).with_name("build_fresh_hidapi_candidate.py")
spec = importlib.util.spec_from_file_location("build_fresh_hidapi_candidate", path)
fresh = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fresh
spec.loader.exec_module(fresh)


def tar_bytes(rows: list[tuple[str, bytes]]) -> bytes:
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode="w:", format=tarfile.USTAR_FORMAT) as archive:
        root = tarfile.TarInfo(fresh.KIT_ROOT)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, raw in rows:
            row = tarfile.TarInfo(fresh.KIT_ROOT + "/" + name)
            row.size = len(raw)
            archive.addfile(row, io.BytesIO(raw))
    return blob.getvalue()


def ar_member(name: str, payload: bytes) -> bytes:
    body = name.encode() + payload
    header = f"{'#1/' + str(len(name)):<16}{1:<12}{1:<6}{1:<6}{100644:<8}{len(body):<10}`\n".encode()
    return header + body + (b"\n" if len(body) % 2 else b"")


def ar_bytes(names: tuple[str, ...]) -> bytes:
    objects = [ar_member(name, bytes.fromhex("cffaedfe0c0000010000000001000000")) for name in names]
    index_size = 4 + 8 * len(names) + 4 + 2
    first = 8 + len(ar_member("__.SYMDEF SORTED", b"0" * index_size))
    index = struct.pack("<I", 8 * len(names))
    for obj in objects:
        index += struct.pack("<II", 0, first)
        first += len(obj)
    index += struct.pack("<I", 2) + b"x\0"
    return b"!<arch>\n" + ar_member("__.SYMDEF SORTED", index) + b"".join(objects)


class RunState(str, Enum):
    EXITED = "exited"
    TIMED_OUT = "timed_out"
    OUTPUT_LIMIT = "output_limit"
    UNREAPED = "unreaped"
    COMPLETED = "completed"
    TIMEOUT = "timeout"


@dataclass
class RunResult:
    status: RunState
    trigger: RunState
    returncode: int | None
    observation: dict | None


class FreshBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve()

    def test_authenticate_before_parsing_and_check_23_listed_files(self) -> None:
        files = [("source/project.tar", b"data")]
        files.extend((f"unused/f-{n}", bytes([n])) for n in range(22))
        checksum_rows = "".join(f"{hashlib.sha256(blob).hexdigest()}  {name}\n" for name, blob in files).encode()
        files.append(("SHA256SUMS", checksum_rows))
        kit = self.root / "in.tar"
        kit.write_bytes(tar_bytes(files))
        target = self.root / "new"
        target.mkdir()
        with self.assertRaisesRegex(ValueError, "developer kit SHA-256 mismatch"):
            fresh.kit_inputs(kit, "0" * 64, target, {})
        # The intact checksum set advances through the kit gate. This inert
        # fixture deliberately has no locked NUT archive or project source.
        with self.assertRaisesRegex(KeyError, "native/nut.tar"):
            fresh.kit_inputs(kit, fresh.sha_file(kit), target, {})
        files[0] = ("source/project.tar", b"changed")
        kit.write_bytes(tar_bytes(files))
        with self.assertRaisesRegex(ValueError, "kit member SHA-256 mismatch"):
            fresh.kit_inputs(kit, fresh.sha_file(kit), target, {})
        self.assertEqual(list(target.iterdir()), [])

    def test_traversal_duplicate_and_file_as_parent_refused(self) -> None:
        for members in ([("dir/../outside", b"x")], [("dir/file", b"x"), ("dir/file", b"y")],
                        [("file", b"x"), ("file/child", b"y")]):
            with self.subTest(members=members), self.assertRaises(ValueError):
                with tarfile.open(fileobj=io.BytesIO(tar_bytes(members)), mode="r:") as archive:
                    fresh.archive_rows(archive, 1024)

    def test_expected_archive_and_wrong_member_or_wrong_index(self) -> None:
        names = ("first.o", "second.o")
        raw = ar_bytes(names)
        self.assertEqual(tuple(row["name"] for row in fresh.ar_inventory(raw, names)["members"]), names)
        with self.assertRaisesRegex(ValueError, "archive member closure"):
            fresh.ar_inventory(raw, tuple(reversed(names)))
        with self.assertRaisesRegex(ValueError, "bad static archive signature"):
            fresh.ar_inventory(b"!<thin>\n" + raw[8:], names)
        bad_index = bytearray(raw)
        bad_index[68 + len("__.SYMDEF SORTED") + 8] = 0
        with self.assertRaisesRegex(ValueError, "archive index"):
            fresh.ar_inventory(bytes(bad_index), names)

    def test_fresh_inputs_have_content_checks_and_are_rehashed_at_link(self) -> None:
        source, build = self.root / "source", self.root / "build"
        cfg = ("--prefix=" + str(fresh.PREFIX), "--disable-inplace-runtime", "--with-all=no")
        libusb = "/opt/homebrew/Cellar/libusb/1.0.30/lib/libusb-1.0.0.dylib"
        macros = {"ABS_TOP_SRCDIR": str(source), "ABS_TOP_BUILDDIR": str(build),
                  "CONFPATH": str(fresh.PREFIX / "etc/nut"), "LIBDIR": str(fresh.PREFIX / "lib"),
                  "STATEPATH": "/var/state/ups", "ALTPIDPATH": "/var/state/ups", "PIDPATH": "/var/run",
                  "SOPATH_LIBUSB1": libusb, "CONFIG_FLAGS": " ".join((cfg[0], cfg[2]))}
        config = "".join(f'#define {name} "{value}"\n' for name, value in macros.items()).encode()
        config += b"#define HAVE_LIBUSB_H 1\n#define WITH_USB 1\n#define WITH_LIBUSB_1_0 1\n#define WITH_LIBUSB_0_1 0\n"
        version = (b'#define NUT_VERSION_MACRO "2.8.5.1"\n#define NUT_VERSION_SEMVER_MACRO "2.8.5"\n'
                   b'#define NUT_VERSION_IS_RELEASE 0\n#define NUT_VERSION_IS_PRERELEASE 0\n')
        raw = {"include/config.h": config, "include/nut_version.h": version}
        raw.update({name: ar_bytes(members) for name, members in fresh.ARCHIVES.items()})
        self.assertEqual(set(fresh.check_generated(raw, source, build, libusb, cfg)["archives"]), set(fresh.ARCHIVES))
        for name, data in raw.items():
            fresh.write_file(build / name, data)
        pins = {name: fresh.digest(data) for name, data in raw.items()}
        fresh.verify_generated(build, pins)
        (build / "include/config.h").write_bytes(config.replace(b"/var/run", b"/var/tmp"))
        with self.assertRaisesRegex(ValueError, "changed before or during link"):
            fresh.verify_generated(build, pins)
        mutated = fresh.read_generated(build)
        with self.assertRaisesRegex(ValueError, "wrong generated configuration"):
            fresh.check_generated(mutated, source, build, libusb, cfg)

    def test_link_map_rejects_extra_object_or_stub(self) -> None:
        work = SimpleNamespace(root=self.root, build=self.root / "build")
        sdk = self.root / "sdk"
        for name in fresh.SDK_INPUTS:
            fresh.write_file(sdk / name, b"stub")
        rows = (["linker synthesized"] + [str(self.root / "tmp" / (Path(unit).stem + "-a42.o")) for unit in fresh.UNITS]
                + [str(work.build / name) for name in fresh.archive_link_members()]
                + [str(sdk / name) for name in fresh.SDK_INPUTS])

        def listing(paths: list[str]) -> str:
            return "# Arch: arm64\n# Object files:\n" + "\n".join(
                f"[ {i}] {name}" for i, name in enumerate(paths)) + "\n# Sections:\n"

        self.assertEqual(len(fresh.link_objects(listing(rows), work, sdk)), len(rows))
        for name in (str(self.root / "tmp/unapproved-123.o"), str(sdk / "usr/lib/unapproved.tbd")):
            target = Path(name)
            if target.is_relative_to(sdk):
                fresh.write_file(target, b"stub")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "closure mismatch"):
                fresh.link_objects(listing(rows + [name]), work, sdk)

    def test_inert_or_redirected_reader_fails_without_static_tool(self) -> None:
        product = self.root / "PRODUCT"
        product.write_bytes(b"")
        product.chmod(0o600)
        work = SimpleNamespace(run=lambda *args: self.fail("static tool called for invalid product"))
        with self.assertRaisesRegex(ValueError, "thin arm64 Mach-O"):
            fresh.audit_product(work, product)
        link = self.root / "product-link"
        link.symlink_to(product)
        with self.assertRaises(ValueError):
            fresh.audit_product(work, link)

    def test_hold_preserves_valid_diagnostics_next_to_rejected_file(self) -> None:
        work = SimpleNamespace(root=self.root, build=self.root / "build", out=self.root / "out", receipt={})
        fresh.write_file(work.build / "include/config.h", b"configuration")
        fresh.write_file(work.build / "config.log", b"diagnostic")
        (work.build / "include/nut_version.h").symlink_to(work.build / "include/config.h")
        with self.assertRaisesRegex(ValueError, "could not be retained"):
            fresh.retain_diagnostics(work)
        self.assertEqual((work.out / "audit/config.log").read_bytes(), b"diagnostic")
        self.assertEqual((work.out / "generated/include/config.h").read_bytes(), b"configuration")
        self.assertIn("generated/include/nut_version.h", work.receipt["unretained_artifacts"])

    def test_first_io_overlay_changes_only_three_selected_files_and_returns_full_map(self) -> None:
        source = self.root / "first-io-source"
        delta_names = ("drivers/apcmicrolink-hidapi-session.h", "drivers/apcmicrolink-hidapi-shared.c",
                       "drivers/apcmicrolink.c")
        base = {f"drivers/file-{i:03}.c": fresh.digest(f"base-{i}".encode()) for i in range(7)}
        base.update({name: fresh.digest(("base-" + name).encode()) for name in delta_names})
        vendor = {f"vendor-{i}.h": fresh.digest(f"vendor-vendor-{i}.h".encode()) for i in range(8)}
        for i in range(7):
            name = f"drivers/file-{i:03}.c"
            fresh.write_file(source / name, f"base-{i}".encode())
        for name in delta_names:
            fresh.write_file(source / name, ("base-" + name).encode())
        for name, pin in vendor.items():
            fresh.write_file(source / fresh.VENDOR_016 / name, f"vendor-{name}".encode())
        overlay_names = delta_names
        overlay = {name: f"after-{name}".encode() for name in overlay_names}
        post = dict(base); post.update({name: fresh.digest(raw) for name, raw in overlay.items()})
        selected = SimpleNamespace(native_base_map=base, native_map=post,
                                   native_overlay=overlay, vendor_map=vendor)
        result = fresh.apply_first_io_source_overlay(source, selected, vendor)
        self.assertEqual(result, post)
        actual = {name: fresh.digest(fresh.read_file(source / name)) for name in base}
        self.assertEqual(actual, post)
        self.assertEqual(sum(base[name] != actual[name] for name in base), 3)
        self.assertEqual({name: fresh.digest(fresh.read_file(source / fresh.VENDOR_016 / name))
                          for name in vendor}, vendor)

    def test_first_io_overlay_rejects_vendor_or_base_mismatch_before_overlay(self) -> None:
        source = self.root / "first-io-source-mismatch"
        base = {"drivers/file.c": fresh.digest(b"base")}
        fresh.write_file(source / "drivers/file.c", b"base")
        selected = SimpleNamespace(native_base_map=base, native_map={"drivers/file.c": fresh.digest(b"after")},
                                   native_overlay={"drivers/file.c": b"after"}, vendor_map={"vendor.h": "0" * 64})
        with self.assertRaisesRegex(ValueError, "vendor map mismatch"):
            fresh.apply_first_io_source_overlay(source, selected, {"vendor.h": "1" * 64})
        self.assertEqual((source / "drivers/file.c").read_bytes(), b"base")

    def test_compile_audit_uses_selected_closure_for_dependencies_and_both_link_gates(self) -> None:
        cases = ((False, False), (True, False), (True, True))
        for use_first_io, change_during_link in cases:
            with self.subTest(first_io=use_first_io, change_during_link=change_during_link):
                self.assert_compile_audit_closure(use_first_io, change_during_link)

    def assert_compile_audit_closure(self, use_first_io: bool, change_during_link: bool) -> None:
        root = self.root / f"mock-native-{use_first_io}-{change_during_link}"
        source, build, out, sdk = (root / name for name in ("source", "build", "out", "sdk"))
        clang = root / "toolchain/bin/clang"
        resource = clang.parent.parent / "lib/clang"
        resource.mkdir(parents=True)
        overlay = {name: f"first-io:{name}".encode() for name in (
            "drivers/apcmicrolink-hidapi-session.h", "drivers/apcmicrolink-hidapi-shared.c",
            "drivers/apcmicrolink.c",
        )}
        project_names = set(overlay) | (set(fresh.UNITS) - {fresh.HID_TU}) | set(fresh.NUT_NOTICE_PATHS)
        project_names.update(f"drivers/file-{i:03}.c" for i in range(190 - len(project_names)))
        base = {name: fresh.digest(f"post-016:{name}".encode()) for name in project_names}
        for name in project_names:
            fresh.write_file(source / name, f"post-016:{name}".encode())
        cancel = dict(base)
        cancel[fresh.NATIVE_ADAPTER] = fresh.digest(b"post-cancel")
        (source / fresh.NATIVE_ADAPTER).write_bytes(b"post-cancel")
        vendor = {name: f"vendor:{name}".encode() for name in (
            "mac/hid.c", "mac/hidapi_darwin.h", "hidapi/hidapi.h", "src/core/hidapi_input_ring.h",
            "LICENSE.txt", "LICENSE-bsd.txt", "LICENSE-gpl3.txt", "LICENSE-orig.txt",
        )}
        vendor_map = {name: fresh.digest(raw) for name, raw in vendor.items()}
        legacy_map = fresh.stage_vendor(source / fresh.VENDOR_015, {"legacy.h": b"inert old vendor"})
        generated = {}
        for name in fresh.GENERATED:
            raw = f"generated:{name}".encode()
            fresh.write_file(build / name, raw)
            generated[name] = fresh.digest(raw)
        post = dict(base)
        post.update({name: fresh.digest(raw) for name, raw in overlay.items()})
        stage_identity = {"profile": "first-io-v1", "source_receipt_sha256": "1" * 64}
        selection = SimpleNamespace(native_base_map=base, native_map=post, vendor_map=vendor_map,
                                    native_overlay=overlay, identity=stage_identity)
        expected_native = post if use_first_io else base
        expected_pins = {f"source/{name}": pin for name, pin in expected_native.items()}
        expected_pins.update({f"source/{fresh.VENDOR_016}/{name}": pin for name, pin in vendor_map.items()})
        expected_pins.update({f"build/{name}": pin for name, pin in generated.items()})
        self.assertEqual(len(expected_pins), 190 + 8 + 7)
        events = []
        product_bytes = b"inert simulated product, never executed"

        def patch(label, _path, _pin):
            events.append(label)
            if label == "apply-hidapi-version-gate":
                target = source / fresh.NATIVE_ADAPTER
                target.write_bytes(f"post-016:{fresh.NATIVE_ADAPTER}".encode())

        def run(label, _cwd, executable, *arguments):
            self.assertEqual(executable, str(clang))
            events.append(label)
            if label == "clang-resource-dir":
                return str(resource)
            if label == "link-dependencies":
                return "synthetic dependency listing"
            if label == "compile-link":
                self.assertEqual(arguments[-1], root / fresh.PRODUCT)
                fresh.write_file(root / "native.map", b"synthetic link map")
                fresh.write_file(root / fresh.PRODUCT, product_bytes)
                if change_during_link:
                    (source / "drivers/apcmicrolink.c").write_bytes(b"unadmitted edit")
                return ""
            self.fail(f"unexpected external phase {label}")

        def dependency_check(deps, work, audit_sdk, pins, clang_resources):
            self.assertEqual(deps, "synthetic dependency listing")
            self.assertEqual(work.root, root)
            self.assertEqual(audit_sdk, sdk)
            self.assertEqual(clang_resources, resource)
            self.assertEqual(pins, expected_pins)
            events.append("dependency-gate")
            return {}, {}

        original_check = fresh.checked_tree

        def check_tree(tree, pins):
            if tree == root:
                self.assertEqual(pins, expected_pins)
                events.append("post-link-gate" if "compile-link" in events else "pre-link-gate")
            original_check(tree, pins)

        def audit_product(_work, product):
            self.assertEqual(product.read_bytes(), product_bytes)
            self.assertEqual(product.stat().st_mode & 0o777, 0o600)
            events.append("product-audit")
            return {"sha256": fresh.digest(product_bytes)}

        receipt = {"source_checkpoints": {}, "legacy_hidapi": legacy_map,
                   "nut": {"notices": {name: base[name] for name in fresh.NUT_NOTICE_PATHS}}}
        work = SimpleNamespace(root=root, source=source, build=build, out=out, receipt=receipt,
                               patch=patch, run=run, tools={"clang": {"path": str(clang)}},
                               verify_tools=mock.Mock(), cancel=mock.Mock())
        work.cancel.is_set.return_value = False
        locks = {"cancel": {"post_write_cancel_sha256": cancel, "patch_sha256": "2" * 64},
                 "profile": {"post_hidapi_016_sha256": base, "gate_patch_sha256": "3" * 64}}
        mask = os.umask(0o077)
        try:
            with mock.patch.multiple(fresh, checked_tree=check_tree, link_dependencies=dependency_check,
                                     link_objects=mock.Mock(return_value=[]), audit_product=audit_product):
                args = (work, self.root / "backend", sdk, locks, {fresh.VENDOR_016: vendor}, generated)
                if change_during_link:
                    with self.assertRaisesRegex(ValueError, "source checkpoint mismatch"):
                        fresh.compile_and_audit(*args, first_io_stage=selection)
                elif use_first_io:
                    fresh.compile_and_audit(*args, first_io_stage=selection)
                else:
                    fresh.compile_and_audit(*args)
        finally:
            os.umask(mask)
        self.assertEqual(events, ["apply-write-cancel", "apply-hidapi-version-gate", "clang-resource-dir",
                                  "link-dependencies", "dependency-gate", "pre-link-gate", "compile-link",
                                  "product-audit", "post-link-gate"])
        self.assertEqual(receipt["source_checkpoints"]["post_hidapi_016"], base)
        if use_first_io:
            self.assertEqual(receipt["source_checkpoints"]["post_first_io"], post)
            self.assertEqual(receipt["first_io_source_stage"], stage_identity)
        else:
            self.assertNotIn("post_first_io", receipt["source_checkpoints"])
            self.assertNotIn("first_io_source_stage", receipt)
        if change_during_link:
            self.assertFalse((out / fresh.PRODUCT).exists())
            self.assertNotIn("product", receipt)
        else:
            self.assertEqual((out / fresh.PRODUCT).read_bytes(), product_bytes)
            self.assertEqual(receipt["product"]["sha256"], fresh.digest(product_bytes))

    def test_failed_supervisor_phase_retains_status_and_does_not_accept(self) -> None:
        for i, state in enumerate((RunState.EXITED, RunState.TIMED_OUT, RunState.OUTPUT_LIMIT, RunState.UNREAPED)):
            with self.subTest(status=state):
                target = self.root / str(i)
                target.mkdir()
                out = target / "out"
                out.mkdir()
                root = target / "scratch"
                root.mkdir()
                seen = []

                def run(command, **kwargs):
                    seen.append(command)
                    return RunResult(state, RunState.TIMEOUT, 1, None)

                supervisor = SimpleNamespace(RunStatus=RunState, RunTrigger=RunState, run_bounded=run,
                                             BoundedRunError=RuntimeError)
                receipt = {"phases": []}
                work = fresh.Build(root, out, receipt, supervisor, time.monotonic() + 5)
                work.tools = {"env": fresh.identity(Path("/usr/bin/env"))}
                with self.assertRaisesRegex(ValueError, "phase failed: make-common"):
                    work.run("make-common", root, "/fixture-only/not-executed")
                self.assertEqual(len(seen), 1)
                self.assertEqual(receipt["phases"][0]["result"]["status"], state)
                self.assertEqual(work.owned_clean, state != RunState.UNREAPED)


if __name__ == "__main__":
    unittest.main()
