# SPDX-License-Identifier: MIT
"""Synthetic unit tests for the full-driver replay result gate."""

from __future__ import annotations

import importlib.util
import importlib.machinery
import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import py_compile
import tempfile
import types
import unittest
import sys
from unittest import mock


RUNNER_PATH = Path(__file__).resolve().with_name("replay_hidapi_full_driver.py")
SPEC = importlib.util.spec_from_file_location("full_driver_replay_under_test", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
exec(compile(RUNNER_PATH.read_bytes(), str(RUNNER_PATH), "exec"), runner.__dict__)


FACTS = (
    "init=1 open=1 layout=1 read=1 write=2 close=1 exit=1 update=0 dump=0 "
    "cleanup=1 dataok=0 flag=1"
)
VALID_EVENTS = (
    "WRAPPER_VALIDATED",
    "INIT=1",
    "READY",
    "NUT_SIGNAL_FLAG=1",
    "CLEANUP_ENTER=1",
    "HID_CLOSE=1",
    "HID_EXIT=1",
    "CLEANUP_RETURN",
    f"FINAL {FACTS}",
)


class FakeProcessHelper:
    class RunStatus:
        EXITED = object()

    def __init__(self, events: tuple[str, ...] = VALID_EVENTS) -> None:
        self.events = events
        self.calls: list[dict[str, object]] = []

    def run_bounded(self, argv, *, executable_sha256, output_directory,
                    timeout_seconds, termination_grace_seconds,
                    maximum_output_bytes, private_nut_environment):
        output = Path(output_directory)
        (output / "state").mkdir(parents=True, mode=0o700)
        (output / "state/full-fake.events").write_text(
            "\n".join(self.events) + "\n", encoding="ascii"
        )
        (output / "stdout.bin").write_bytes(b"")
        self.calls.append({
            "argv": argv,
            "executable_sha256": executable_sha256,
            "timeout_seconds": timeout_seconds,
            "termination_grace_seconds": termination_grace_seconds,
            "maximum_output_bytes": maximum_output_bytes,
            "private_nut_environment": private_nut_environment,
        })
        return types.SimpleNamespace(status=self.RunStatus.EXITED, returncode=1)


class ExecuteFakeGateTests(unittest.TestCase):
    def run_signal_scenario(self, events: tuple[str, ...] = VALID_EVENTS):
        with tempfile.TemporaryDirectory(prefix="replay-gate-") as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            output = root / "out"
            output.mkdir(mode=0o700)
            nonexistent_binary = root / "does-not-exist"
            helper = FakeProcessHelper(events)
            supplied_pin = "a" * 64
            with mock.patch.object(runner, "SCENARIOS", ("signal-term",)):
                result = runner.execute_fake(
                    nonexistent_binary, output, helper,
                    executable_sha256=supplied_pin,
                )
            return result, helper, supplied_pin, nonexistent_binary

    def test_valid_sequence_passes_supplied_pin_without_binary_hashing(self) -> None:
        result, helper, supplied_pin, binary = self.run_signal_scenario()
        self.assertFalse(binary.exists())
        self.assertEqual(helper.calls[0]["executable_sha256"], supplied_pin)
        self.assertEqual(helper.calls[0]["argv"], [str(binary), "signal-term"])
        self.assertEqual(helper.calls[0]["timeout_seconds"], 30)
        self.assertEqual(helper.calls[0]["termination_grace_seconds"], 2)
        self.assertEqual(helper.calls[0]["maximum_output_bytes"], 1048576)
        self.assertIs(helper.calls[0]["private_nut_environment"], True)
        self.assertEqual(result[0]["scenario"], "signal-term")
        self.assertEqual(result[0]["returncode"], 1)
        self.assertEqual(result[0]["status"], "PASS_FULL_NUT_FAKE")
        self.assertIs(result[0]["data_qualified"], False)

    def test_protocol_stop_after_ready_is_rejected(self) -> None:
        events = list(VALID_EVENTS)
        events.insert(events.index("NUT_SIGNAL_FLAG=1"), "STOP=1")
        with self.assertRaisesRegex(SystemExit, "post-signal protocol write"):
            self.run_signal_scenario(tuple(events))

    def test_duplicate_cleanup_marker_is_rejected(self) -> None:
        events = list(VALID_EVENTS)
        events.insert(events.index("HID_CLOSE=1"), "CLEANUP_ENTER=1")
        with self.assertRaisesRegex(SystemExit, "cleanup counts"):
            self.run_signal_scenario(tuple(events))

    def test_signal_flag_before_ready_is_rejected(self) -> None:
        events = list(VALID_EVENTS)
        events.remove("NUT_SIGNAL_FLAG=1")
        events.insert(events.index("READY"), "NUT_SIGNAL_FLAG=1")
        with self.assertRaisesRegex(SystemExit, "unordered cleanup"):
            self.run_signal_scenario(tuple(events))


class PortableReplayPlanningTests(unittest.TestCase):
    def test_missing_nut_build_selects_portable_default(self) -> None:
        args = runner.parse_args([
            "--nut-source", "/public/nut", "--hidapi-source", "/hidapi",
            "--output-dir", "/out", "--compile-only",
        ])
        self.assertIsNone(args.nut_build)
        self.assertTrue(args.compile_only)

    def test_explicit_nut_build_remains_legacy_selection(self) -> None:
        args = runner.parse_args([
            "--nut-source", "/nut", "--nut-build", "/build",
            "--hidapi-source", "/hidapi", "--output-dir", "/out",
        ])
        self.assertEqual(args.nut_build, Path("/build"))
        self.assertEqual(len(runner.compile_units(Path("/nut"), Path("/repo/backend/nut"), False)), 12)

    def test_compile_only_and_run_fake_are_mutually_exclusive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                runner.parse_args([
                    "--nut-source", "/nut", "--hidapi-source", "/hidapi",
                    "--output-dir", "/out", "--compile-only", "--run-fake",
                ])

    def test_portable_plan_adds_only_four_guarded_nut_translation_units(self) -> None:
        nut = Path("/public/nut")
        here = Path("/repo/backend/nut")
        portable = runner.compile_units(nut, here, True)
        legacy = runner.compile_units(nut, here, False)
        added = portable[7:11]
        self.assertEqual(
            [source.relative_to(nut).as_posix() for source, _, guarded in added],
            list(runner.PORTABLE_SOURCE_PINS),
        )
        self.assertTrue(all(guarded for _, _, guarded in added))
        self.assertEqual(portable[11:], legacy[7:])
        self.assertEqual(len(portable), len(legacy) + 4)

    def test_shadow_header_in_source_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="full-replay-shadow-") as temporary:
            root = Path(temporary)
            nut = root / "nut"
            (nut / "common").mkdir(parents=True)
            (nut / "drivers").mkdir()
            hidapi = root / "hidapi"
            (hidapi / "hidapi").mkdir(parents=True)
            (hidapi / "mac").mkdir()
            here = root / "repo/backend/nut"
            here.mkdir(parents=True)
            shadow = nut / "common/config.h"
            shadow.write_text("/* generated shadow */\n", encoding="ascii")
            with self.assertRaisesRegex(SystemExit, "shadow generated header"):
                runner.reject_header_shadows(nut, hidapi, here)

    def test_public_header_pins_match_source_bytes(self) -> None:
        config = RUNNER_PATH.with_name("test_hidapi_full_config.h")
        version = RUNNER_PATH.with_name("test_hidapi_full_version.h")
        self.assertEqual(hashlib.sha256(config.read_bytes()).hexdigest(), runner.PORTABLE_CONFIG_PIN)
        self.assertEqual(hashlib.sha256(version.read_bytes()).hexdigest(), runner.PORTABLE_VERSION_PIN)

    def test_portable_macos_config_defines_empty_executable_suffix(self) -> None:
        config = RUNNER_PATH.with_name("test_hidapi_full_config.h").read_text(encoding="ascii")
        definitions = [line for line in config.splitlines() if line.startswith("#define EXEEXT")]
        self.assertEqual(definitions, ['#define EXEEXT ""'], "NUT requires a non-NULL EXEEXT string on macOS")

    def test_portable_macos_config_keeps_varargs_copy_capabilities(self) -> None:
        config = RUNNER_PATH.with_name("test_hidapi_full_config.h").read_text(encoding="ascii").splitlines()
        for name in ("HAVE_VA_COPY", "HAVE_VA_COPY_VARIANT"):
            definitions = [line for line in config if line.startswith("#define " + name + " ")]
            self.assertEqual(definitions, ["#define " + name + " 1"], "NUT log formatting requires the available va_copy branch")

    def test_dependency_file_requires_the_staged_header(self) -> None:
        with tempfile.TemporaryDirectory(prefix="full-replay-trace-") as temporary:
            root = Path(temporary)
            trace = root / "clang.stderr"
            staged = root / "include/config.h"
            staged.parent.mkdir()
            staged.write_text("/* synthetic */\n", encoding="ascii")
            trace.write_text(f"ups_full_fake_dependency_target: \\\n  {staged.resolve()} \\\n  /usr/include/stdio.h\n", encoding="utf-8")
            runner.verify_includes(trace, {staged.resolve()}, "fake.c")
            with self.assertRaisesRegex(SystemExit, "staged header not included"):
                runner.verify_includes(trace, {root / "missing.h"}, "fake.c")

    def test_dependency_paths_reject_make_escaping_explicitly(self) -> None:
        for name in ("with space", "with\ttab", "with$dollar", "with\\backslash", "with#hash", "with:colon"):
            with self.subTest(name=name), self.assertRaisesRegex(SystemExit, "unsupported Make characters"):
                runner.verify_dependency_paths([Path("/synthetic") / name])


class PinnedSourceLoaderTests(unittest.TestCase):
    def test_load_rejects_symlink_before_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="full-replay-load-link-") as temporary:
            root = Path(temporary)
            source = root / "helper.py"
            source.write_text("marker = 'source-bytes'\n", encoding="ascii")
            link = root / "linked.py"
            link.symlink_to(source)
            pin = hashlib.sha256(source.read_bytes()).hexdigest()
            with self.assertRaisesRegex(SystemExit, "symlink helper"):
                runner.load(link, "test_symlink_pinned_module", pin)
            self.assertNotIn("test_symlink_pinned_module", sys.modules)

    def test_load_executes_verified_source_bytes_without_using_loader(self) -> None:
        with tempfile.TemporaryDirectory(prefix="full-replay-load-") as temporary:
            source = Path(temporary).resolve() / "helper.py"
            source.write_text("marker = 'cached-bytes'\n", encoding="ascii")
            original_stat = source.stat()
            py_compile.compile(str(source), doraise=True)
            source.write_text("marker = 'source-bytes'\n", encoding="ascii")
            os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            pin = hashlib.sha256(source.read_bytes()).hexdigest()
            name = "test_pinned_source_loader_module"
            self.addCleanup(sys.modules.pop, name, None)
            loader = mock.Mock()
            spec = importlib.machinery.ModuleSpec(name, loader)
            with mock.patch.object(runner.importlib.util, "spec_from_file_location", return_value=spec):
                module = runner.load(source, name, pin)
            self.assertEqual(module.marker, "source-bytes")
            loader.exec_module.assert_not_called()

    def test_load_rejects_changed_source_before_module_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="full-replay-load-pin-") as temporary:
            source = Path(temporary).resolve() / "helper.py"
            source.write_text("marker = 'changed'\n", encoding="ascii")
            with self.assertRaisesRegex(SystemExit, "pinned helper mismatch"):
                runner.load(source, "test_changed_pinned_module", "0" * 64)
            self.assertNotIn("test_changed_pinned_module", sys.modules)


class MainCompileOnlyGateTests(unittest.TestCase):
    def run_main_with_stubs(self, mode: tuple[str, ...], *, reject_audit: bool = False,
                            legacy: bool = False, mutation: str | None = None,
                            reject_stage: str | None = None):
        calls: list[tuple[str, list[str]]] = []

        def command_stub(argv, output_dir, label, timeout=60):
            argv = list(argv)
            calls.append((label, argv))
            if label == "native-clock-imports":
                return "                 U _fixture_native_clock_gettime\n"
            stdout_path = output_dir / f"{label}.stdout"
            stderr_path = output_dir / f"{label}.stderr"
            stdout_path.write_text("stub\n", encoding="utf-8")
            if label.startswith("compile-") and "-H" in argv:
                trace = []
                staged_config = output_dir / "include/config.h"
                staged_version = output_dir / "include/nut_version.h"
                source = Path(argv[argv.index("-c") + 1]) if "-c" in argv else Path()
                if "-include" in argv or source.name == "test_hidapi_full_driver.c":
                    trace.append(f". {staged_config}\n")
                if source.name == "common-nut_version.c":
                    trace.append(f". {staged_version}\n")
                stderr_path.write_text("".join(trace), encoding="utf-8")
                dependencies = [str(source), *(line.lstrip(". ").strip() for line in trace)]
                Path(argv[argv.index("-MF") + 1]).write_text(
                    "ups_full_fake_dependency_target: " + " \\\n  ".join(dependencies) + "\n", encoding="utf-8"
                )
            else:
                stderr_path.write_text("", encoding="utf-8")
            (output_dir / f"{label}.argv.json").write_text(json.dumps(argv) + "\n", encoding="utf-8")
            if "-o" in argv:
                target = Path(argv[argv.index("-o") + 1])
                target.write_bytes(b"synthetic compiler output\n")
                target.chmod(0o700)
            if label == "link-full-fake":
                objects = [arg for arg in argv if arg.endswith(".o")]
                (output_dir / "full-fake.map").write_text(
                    "# Object files:\n[ 0] linker synthesized\n"
                    + "".join(f"[ {index}] {path}\n" for index, path in enumerate(objects, 1))
                    + "# Sections:\n", encoding="utf-8"
                )
            if label == "run-pure-frames":
                self.assertTrue(Path(argv[0]).stat().st_mode & 0o100)
            if label == reject_stage:
                raise SystemExit("HOLD test stage rejection")
            return "stub output\n"

        def audit_stub(binary, output_dir, *, pure_frames=False):
            calls.append(("audit-pure" if pure_frames else "audit-full", [str(binary)]))
            self.assertEqual(binary.stat().st_mode & 0o777, 0o600)
            if reject_audit and not pure_frames:
                raise SystemExit("HOLD test audit rejection")
            if reject_stage == ("audit-pure" if pure_frames else "audit-full"):
                raise SystemExit("HOLD test stage rejection")
            return {"binary_sha256": runner.digest(binary), "audit": "PASS_STATIC_IMPORTS",
                    "native_hidapi": "NOT_LINKED"}

        with tempfile.TemporaryDirectory(prefix="full-replay-main-") as temporary:
            root = Path(temporary).resolve()
            root.chmod(0o700)
            output = root / "out"
            nut = root / "nut"
            hidapi = root / "hidapi"
            here = root / "repo/backend/nut"
            here.mkdir(parents=True)
            build = root / "build"

            def fixture(path: Path, content: bytes) -> str:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                return hashlib.sha256(content).hexdigest()

            source_pins = {
                relative: fixture(nut / relative, ("/* synthetic " + relative + " */\n").encode())
                for relative in runner.SOURCE_PINS
            }
            original_pins = {
                relative: fixture(nut / relative, ("/* synthetic " + relative + " */\n").encode())
                for relative in ("drivers/main.c", "drivers/apcmicrolink.c")
            }
            portable_pins = {
                relative: fixture(nut / relative, ("/* synthetic " + relative + " */\n").encode())
                for relative in runner.PORTABLE_SOURCE_PINS
            }
            module_pins = {
                relative: fixture(here / relative, ("/* synthetic " + relative + " */\n").encode())
                for relative in runner.MODULE_PINS
            }
            header_pins = {
                relative: fixture(hidapi / relative, b"/* synthetic HID header */\n")
                for relative in runner.HEADER_PINS
            }
            extractor_code = (
                "from pathlib import Path\n"
                f"PINNED_INPUTS = {original_pins!r}\n"
                "FUNCTIONS = tuple(('synthetic', 'synthetic') for _ in range(6))\n"
                "def _has_symlink_component(path):\n"
                "    path = Path(path).absolute()\n"
                "    return any(p.is_symlink() for p in (path, *path.parents))\n"
                "def paths_overlap(left, right):\n"
                "    left, right = Path(left).resolve(), Path(right).resolve()\n"
                "    return left == right or left in right.parents or right in left.parents\n"
                "def extract_notice(source): return 'synthetic notice'\n"
                "def exact_function(source, signature): return 'synthetic checksum'\n"
            ).encode("ascii")
            extractor_pin = fixture(here / "extract_hidapi_nut.py", extractor_code)
            deadline_pin = fixture(here / "process_deadline.py", b"marker = 'synthetic helper'\n")
            config_pin = fixture(here / "test_hidapi_full_config.h", b"/* synthetic config */\n")
            version_pin = fixture(here / "test_hidapi_full_version.h", b"/* synthetic version */\n")
            for name in ("test_hidapi_full_driver.c", "test_hidapi_full_os.h", "replay_hidapi_full_driver.py"):
                fixture(here / name, b"/* synthetic local source */\n")
            checksum_pin = hashlib.sha256(
                b"/* SPDX-License-Identifier: GPL-2.0-or-later */\nsynthetic notice\n\nsynthetic checksum\n"
            ).hexdigest()
            archive_pins = {
                name: fixture(build / "common/.libs" / name, b"synthetic archive\n")
                for name in runner.ARCHIVE_PINS
            }
            fixture(build / "include/config.h", b"/* synthetic config */\n")
            fixture(build / "include/nut_version.h", b"/* synthetic version */\n")
            if mutation == "header":
                (here / "test_hidapi_full_config.h").write_bytes(b"changed header")
            if mutation == "shadow":
                fixture(nut / "common/config.h", b"/* shadow */\n")
            if mutation == "legacy":
                (build / "include/config.h").unlink()
            if mutation == "source-symlink":
                external_common = root / "external-common"
                (nut / "common").rename(external_common)
                (nut / "common").symlink_to(external_common, target_is_directory=True)
            if mutation == "path-space":
                renamed_nut = root / "nut with space"
                nut.rename(renamed_nut)
                nut = renamed_nut
            args = ["--nut-source", str(nut), "--hidapi-source", str(hidapi),
                    "--output-dir", str(output), *mode]
            if legacy:
                args.extend(["--nut-build", str(build)])
            pins = {"__file__": str(here / "replay_hidapi_full_driver.py"),
                    "EXTRACTOR_PIN": extractor_pin, "DEADLINE_PIN": deadline_pin,
                    "PORTABLE_CONFIG_PIN": config_pin, "PORTABLE_VERSION_PIN": version_pin,
                    "CONFIG_PIN": config_pin, "VERSION_PIN": version_pin,
                    "CHECKSUM_PIN": checksum_pin, "SOURCE_PINS": source_pins,
                    "PORTABLE_SOURCE_PINS": portable_pins, "MODULE_PINS": module_pins,
                    "HEADER_PINS": header_pins, "ARCHIVE_PINS": archive_pins}
            with mock.patch.dict(runner.__dict__, pins), mock.patch.dict(sys.modules), \
                    mock.patch.object(runner, "command", side_effect=command_stub), \
                    mock.patch.object(runner, "audit", side_effect=audit_stub), \
                    mock.patch.object(runner.subprocess, "run", side_effect=AssertionError("real command forbidden")):
                if reject_audit or mutation or reject_stage:
                    expected = ("test audit rejection" if reject_audit else
                                "test stage rejection" if reject_stage else
                                "unsupported Make characters" if mutation == "path-space" else
                                "symlink pinned input path" if mutation == "source-symlink" else
                                "shadow generated header" if mutation == "shadow" else "pinned input mismatch")
                    with self.assertRaisesRegex(SystemExit, expected):
                        runner.main(args)
                else:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(runner.main(args), 0)
            for name in ("full-nut-hidapi-fake", "pure-frames-unit"):
                if (output / name).exists():
                    self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)
            receipt = json.loads((output / "manifest.json").read_text(encoding="utf-8")) if (output / "manifest.json").exists() else None
            return calls, receipt

    def test_compile_only_main_never_invokes_any_binary(self) -> None:
        calls, receipt = self.run_main_with_stubs(("--compile-only",))
        labels = [label for label, _ in calls]
        self.assertNotIn("run-pure-frames", labels)
        self.assertNotIn("run-full-fake", labels)
        self.assertEqual(receipt["state"], "COMPILE_ONLY_FULL_NOT_RUN")
        self.assertEqual(receipt["scenarios"], [])
        self.assertEqual(receipt["pure_frames"], "NOT_RUN")
        self.assertEqual(receipt["build_configuration"], "PORTABLE_SYNTHETIC")
        link = next(argv for label, argv in calls if label == "link-full-fake")
        self.assertFalse(any(arg.endswith(".a") for arg in link))

    def test_default_main_still_runs_pure_frames_after_audit(self) -> None:
        calls, _ = self.run_main_with_stubs(())
        labels = [label for label, _ in calls]
        self.assertIn("run-pure-frames", labels)
        self.assertLess(labels.index("audit-full"), labels.index("run-pure-frames"))
        self.assertLess(labels.index("audit-pure"), labels.index("run-pure-frames"))

    def test_full_audit_rejection_prevents_any_binary_invocation(self) -> None:
        calls, _ = self.run_main_with_stubs(("--compile-only",), reject_audit=True)
        self.assertNotIn("run-pure-frames", [label for label, _ in calls])

    def test_explicit_legacy_main_keeps_three_archives(self) -> None:
        calls, receipt = self.run_main_with_stubs(("--compile-only",), legacy=True)
        link = next(argv for label, argv in calls if label == "link-full-fake")
        self.assertEqual([Path(arg).name for arg in link if arg.endswith(".a")], list(runner.ARCHIVE_PINS))
        self.assertEqual(receipt["full_config_portability"], "OPEN_PRIVATE_INPUT")
        self.assertEqual(sum(label.startswith("compile-") for label, _ in calls), 13)

    def test_bad_explicit_legacy_does_not_fall_back(self) -> None:
        calls, receipt = self.run_main_with_stubs(("--compile-only",), legacy=True, mutation="legacy")
        self.assertEqual(calls, [])
        self.assertIsNone(receipt)

    def test_bad_portable_header_and_shadow_fail_before_compile(self) -> None:
        for mutation in ("header", "shadow", "source-symlink", "path-space"):
            with self.subTest(mutation=mutation):
                calls, receipt = self.run_main_with_stubs(("--compile-only",), mutation=mutation)
                self.assertEqual(calls, [])
                self.assertIsNone(receipt)

    def test_pure_audit_failure_keeps_both_binaries_nonexecutable(self) -> None:
        calls, receipt = self.run_main_with_stubs((), reject_stage="audit-pure")
        self.assertNotIn("run-pure-frames", [label for label, _ in calls])
        self.assertIsNone(receipt)

    def test_link_and_unit_execution_failures_restore_nonexecutable_mode(self) -> None:
        for stage in ("link-full-fake", "compile-pure-frames", "run-pure-frames"):
            with self.subTest(stage=stage):
                _, receipt = self.run_main_with_stubs((), reject_stage=stage)
                self.assertIsNone(receipt)


class PortableLinkMapTests(unittest.TestCase):
    def test_foreign_object_without_o_suffix_is_rejected(self) -> None:
        objects = [Path("/synthetic/out/unit-00.o")]
        text = "# Object files:\n[ 0] linker synthesized\n[ 1] /synthetic/out/unit-00.o\n[ 2] /foreign/payload.obj\n# Sections:\n"
        with self.assertRaisesRegex(SystemExit, "unexpected source objects"):
            runner.verify_portable_objects(text, objects)

    def test_foreign_object_is_rejected_despite_expected_names_in_comment(self) -> None:
        objects = [Path("/synthetic/out/unit-00.o")]
        text = "# Object files:\n[ 0] linker synthesized\n[ 1] /foreign/unit-00.o\n# unit-00.o\n"
        with self.assertRaisesRegex(SystemExit, "unexpected source objects"):
            runner.verify_portable_objects(text, objects)


class AdmissionDiagnosticPatchTests(unittest.TestCase):
    def test_patch_reports_only_closed_diagnostic_tokens_at_failure_sites(self) -> None:
        patch_path = RUNNER_PATH.with_name("nut-hidapi-observe-73c4502.patch")
        patch_text = patch_path.read_text(encoding="utf-8")
        self.assertEqual(patch_text.count("mlink_shared_admission_diagnostic()"), 2)
        self.assertEqual(patch_text.count("stage=%s reason=%s parser=%s"), 2)
        self.assertEqual(patch_text.count("mlink_admission_stage_token(diagnostic.stage)"), 2)
        self.assertEqual(patch_text.count("mlink_admission_reason_token(diagnostic.reason)"), 2)
        self.assertEqual(patch_text.count("mlink_admission_parser_token(diagnostic.parser_status)"), 2)
        self.assertNotIn("hid_error(", patch_text)
        self.assertNotIn("errno", patch_text)

if __name__ == "__main__":
    unittest.main()
