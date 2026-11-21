#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pinned offline pacing adapter: compile only by default, two fakes on opt-in.

Offline replay adapter. Reuses the pinned portable runner without changing it.
Only build_pair is derived, to substitute one admitted fake host and build the
same patched source with diagnostics always on and pacing explicitly off/on.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import Event, Thread
import time

HERE = Path(__file__).resolve().parent
RUNNER_PIN = "101f5b5c9ec95d7feb18c53e531e4554589a3f0477884c55cc062a889f9c5006"
MANIFEST_PIN = "9020f7675b89f996d6c78dfd48ca63cc61a1f27349f97254dffd9cb6f21f189e"
INPUTS_NAME = "replay_continuous_pacing_inputs.json"
PATCH = "nut-hidapi-continuous-pacing-v2-73c4502.patch"
HOST = "replay_continuous_pacing.c"
TEST = "test_continuous_pacing.py"
TARGET = "drivers/apcmicrolink.c"
FAKE_TAIL = ["-s", "replay", "-d1", "-x", "port=auto", "-x", "hidapi_shared",
             "-x", "guarded_monitor", "-x", "guard_vid=0001", "-x", "guard_pid=0002",
             "-x", "guard_deadline=130", "-x", "guard_probe_attempts=1", "-x",
             "hid_fallback=no", "-x", "monitor_stream_v1"]


def bootstrap_runner(backend: Path):
    """Verify the trust-root file before importing any project code."""
    runner_path = backend / "replay_continuous_portable.py"
    for path in (backend, runner_path, backend / "replay_continuous_portable_inputs.json"):
        if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
            raise RuntimeError("unsafe canonical input path")
    for path, expected in ((runner_path, RUNNER_PIN),
                           (backend / "replay_continuous_portable_inputs.json", MANIFEST_PIN)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("canonical input pin mismatch")
    spec = importlib.util.spec_from_file_location("pacing_portable_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical runner unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(runner_path.read_bytes(), str(runner_path), "exec"), module.__dict__)
    return module


def read_inputs(r, backend: Path, new_files: Path) -> tuple[dict, dict]:
    inputs = json.loads((HERE / INPUTS_NAME).read_text(encoding="utf-8"))
    if (inputs["schema"] != 1 or inputs["canonical_runner_sha256"] != RUNNER_PIN
            or inputs["canonical_manifest_sha256"] != MANIFEST_PIN
            or set(inputs["new_pins"]) != {PATCH, HOST, TEST}):
        raise r.ReplayError("adapter input contract differs")
    r.verify(Path(__file__), inputs["adapter_sha256"])
    for name, expected in inputs["new_pins"].items():
        r.verify(new_files / name, expected)
    if r.patch_targets(new_files / PATCH) != {TARGET}:
        raise r.ReplayError("pacing patch must target only apcmicrolink.c")
    r.verify(backend / r.MANIFEST_NAME, MANIFEST_PIN)
    canonical = r.read_contract()
    if canonical["source_after"][TARGET] != inputs["source_before_sha256"]:
        raise r.ReplayError("source baseline differs")
    return inputs, canonical


def source_snapshot(r, source: Path) -> dict[str, str]:
    r.tree_bytes(source)
    return {path.relative_to(source).as_posix(): r.sha(path)
            for path in sorted(source.rglob("*")) if path.is_file()}


def verify_paced_source(r, source: Path, before: dict, expected: dict) -> None:
    after = source_snapshot(r, source)
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    if changed != {TARGET} or after != expected:
        raise r.ReplayError("pacing source delta differs from the sole admitted file")


def build_pair(r, source: Path, output: Path, contract: dict, helper, portable,
               toolchain: dict, backend: Path, new_files: Path, inputs: dict) -> dict:
    """Derived from pinned runner build_pair; same compilation/linkage fences."""
    clang, sdk = Path(toolchain["clang"]), Path(toolchain["sdk"])
    developer = Path(toolchain["developer_dir"])
    r.verify(clang, toolchain["clang_sha256"])
    generated = output / "include"
    generated.mkdir(mode=0o700)
    for original, name in (("test_hidapi_full_config.h", "config.h"),
                           ("test_hidapi_full_version.h", "nut_version.h")):
        (generated / name).write_bytes((backend / original).read_bytes())
        (generated / name).chmod(0o600)
    for root in (source, source / "drivers", source / "include", source / "common", backend, new_files):
        for name in ("config.h", "nut_version.h"):
            if (root / name).exists() or (root / name).is_symlink():
                raise r.ReplayError("shadow generated header refused")
    portable.verify_dependency_paths([source, output, backend, new_files])
    base = [str(clang), "-std=gnu99", "-g", "-O0", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Wno-unused-parameter",
            "-isysroot", str(sdk), "-DMLINK_HIDAPI_NATIVE_CANDIDATE=1",
            "-DMLINK_HIDAPI_CONTINUOUS_CANDIDATE=1", "-DMLINK_HIDAPI_CONTINUOUS_REPLAY=1",
            "-I", str(generated), "-I", str(source / "include"),
            "-I", str(source / "drivers"), "-I", str(backend)]
    units = [(source / name, True) for name in r.PUBLIC_UNITS]
    units.extend((source / "drivers" / name, False) for name in
                 ("apcmicrolink-continuous.c", "apcmicrolink-hidapi-shared.c",
                  "apcmicrolink-hid-descriptor-checked.c"))
    units.extend(((new_files / HOST, False), (backend / "replay_continuous_os.c", False)))
    pair = {}
    try:
        for mode, value in (("off", "0"), ("on", "1")):
            flags = ["-DMLINK_CONTINUOUS_DIAGNOSTICS_V1=1", "-DMLINK_CONTINUOUS_PACING_V2=" + value]
            objects = []
            for index, (unit, guarded) in enumerate(units):
                label = f"{mode}-compile-{index:02d}"
                obj, dep = output / (label + ".o"), output / (label + ".d")
                guard = ["-include", str(backend / "test_hidapi_full_os.h"), "-Dchdir=fixture_chdir"] if guarded else []
                special = ["-DFULL_FAKE_MAIN=1"] if unit.name == "main.c" else []
                if unit.name == "common.c":
                    special += ["-DNUT_WANT_INET_NTOP_XX=1"]
                r.command(helper, [*base, *flags, *guard, *special,
                                   "-MD", "-MF", str(dep), "-MT", "ups_full_fake_dependency_target",
                                   "-c", str(unit), "-o", str(obj)], output, label, developer_dir=developer)
                required = {generated / "config.h"} if guarded else set()
                if unit.name == "common-nut_version.c":
                    required.add(generated / "nut_version.h")
                portable.verify_includes(dep, required, unit.name)
                contents = dep.read_text().replace("\\\n", " ")
                deps = [Path(value) for value in contents.split(":", 1)[1].split()]
                for path in deps:
                    resolved = path.resolve(strict=True)
                    if resolved.is_relative_to(source) or resolved.is_relative_to(generated):
                        continue
                    if resolved.parent == backend and resolved.name in contract["local_pins"]:
                        r.verify(resolved, contract["local_pins"][resolved.name])
                    elif resolved == new_files / HOST:
                        r.verify(resolved, inputs["new_pins"][HOST])
                    elif not (resolved.is_relative_to(sdk) or resolved.is_relative_to(clang.parents[1])):
                        raise r.ReplayError("unadmitted compilation dependency")
                objects.append(obj)
            binary = output / ("continuous-pacing-fake-" + mode)
            link_map = output / (mode + ".map")
            try:
                r.command(helper, [*base, *flags, *(str(path) for path in objects), "-lm",
                                   "-Wl,-map," + str(link_map), "-o", str(binary)],
                          output, mode + "-link", developer_dir=developer)
            finally:
                if binary.exists():
                    binary.chmod(0o600)
            r.verify_selected_objects(link_map.read_text(), objects, developer)
            pair[mode] = {"path": str(binary), "pacing_v2": int(value), "diagnostics_v1": 1,
                          **r.audit(binary, output, helper)}
        return pair
    finally:
        for mode in ("off", "on"):
            binary = output / ("continuous-pacing-fake-" + mode)
            if binary.exists():
                binary.chmod(0o600)


def run_pair(r, pair: dict, output: Path, helper, new_files: Path, inputs: dict,
             backend: Path, canonical: dict) -> dict:
    """Two direct, owned fake children; pure in-process validator afterwards."""
    validator = r.load_pinned(new_files / TEST, inputs["new_pins"][TEST], "pacing_pair_validator")
    validator.protocol = r.load_pinned(backend / "continuous_protocol.py",
                                       canonical["local_pins"]["continuous_protocol.py"],
                                       "pacing_wire_protocol")
    run_root = output / "pacing-pair"
    run_root.mkdir(mode=0o700)
    cancelled, done = Event(), Event()
    deadline = time.monotonic() + 60
    invocations, abort_reasons, captured = [], [], {}
    capture_bytes = 0

    def monitor() -> None:
        while not done.wait(0.05):
            try:
                r.tree_bytes(output)
            except (OSError, r.ReplayError):
                abort_reasons.append("temporary storage guard")
                cancelled.set()
                return
            if time.monotonic() >= deadline:
                abort_reasons.append("pair deadline")
                cancelled.set()
                return

    watcher = Thread(target=monitor, daemon=True)
    watcher.start()
    validation = None
    try:
        for index, mode in enumerate(("off", "on")):
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise r.ReplayError("pair cancelled before child spawn")
            binary = Path(pair[mode]["path"])
            r.verify(binary, pair[mode]["sha256"])
            if pair[mode]["state"] != "PASS_STATIC_NO_HID_LINKAGE":
                raise r.ReplayError("fake audit is not admitted")
            argv = [str(r.ENV), "MLINK_CONTINUOUS_REPLAY_SCENARIO=next-gap-budget", str(binary), *FAKE_TAIL]
            binary.chmod(0o700)
            try:
                result = helper.run_bounded(argv, executable_sha256=r.sha(r.ENV),
                                            output_directory=run_root / str(index),
                                            timeout_seconds=20, termination_grace_seconds=2,
                                            maximum_output_bytes=1_048_576, cancel_event=cancelled)
            finally:
                binary.chmod(0o600)
            invocations.append({"mode": mode, "argv": argv, "binary_sha256": pair[mode]["sha256"],
                                "env_sha256": r.sha(r.ENV), "owned_process_group": True,
                                "supervisor": asdict(result)})
            capture_bytes += result.stdout_bytes + result.stderr_bytes
            if (result.status is not helper.RunStatus.EXITED or result.trigger.value != "completed"
                    or result.returncode is None or cancelled.is_set() or capture_bytes > 2_097_152):
                cancelled.set()
                raise r.ReplayError("fake supervisor did not prove bounded completed cleanup")
            r.tree_bytes(output)
            captured[mode] = ((run_root / str(index) / "stdout.bin").read_bytes(),
                              (run_root / str(index) / "stderr.bin").read_bytes(), result.returncode)
        validation = validator.validate_pair(*captured["off"], *captured["on"])
        if (not isinstance(validation, dict)
                or validation.get("state") != "PASS_SINGLE_SYNTHETIC_COUNTEREXAMPLE"):
            raise r.ReplayError("validator did not return the admitted success state")
        if len(invocations) != 2 or cancelled.is_set() or time.monotonic() >= deadline:
            raise r.ReplayError("pair bounds not satisfied")
        return {"state": "PASS_SINGLE_SYNTHETIC_COUNTEREXAMPLE", "validation": validation,
                "fake_processes": 2, "capture_bytes": capture_bytes}
    finally:
        done.set()
        watcher.join(timeout=1)
        for item in pair.values():
            Path(item["path"]).chmod(0o600)
        receipt = {"schema": 1, "orchestration": "IN_PROCESS_VALIDATOR_DIRECT_OWNED_FAKE_CHILDREN",
                   "maximum_pair_seconds": 60, "maximum_fake_processes": 2,
                   "maximum_child_seconds": 20, "termination_grace_seconds": 2,
                   "kill_reap_seconds": 1, "maximum_child_capture_bytes": 1_048_576,
                   "maximum_aggregate_capture_bytes": 2_097_152, "capture_bytes": capture_bytes,
                   "invocations": invocations, "abort_reasons": abort_reasons,
                   "validation": validation, "monitor_stopped": not watcher.is_alive()}
        (run_root / "run-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if watcher.is_alive():
            raise r.ReplayError("pair storage monitor did not stop")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-dir", type=Path, required=True)
    parser.add_argument("--nut-archive", type=Path, required=True)
    parser.add_argument("--new-files-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--compile-only", action="store_true", help="Default: build and audit, no fake execution")
    mode.add_argument("--run-fake", action="store_true", help="Explicitly run the sole synthetic scenario twice")
    args = parser.parse_args(argv)
    if (sys.version_info[:3] != (3, 15, 2) or sys.platform != "darwin"
            or not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode
            or sys.flags.optimize != 0):
        raise RuntimeError("requires admitted macOS Python 3.15.2 with -I -S -B")
    python_sha256 = hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
    r = bootstrap_runner(args.backend_dir)
    backend, new_files = r.safe_path(args.backend_dir), r.safe_path(args.new_files_dir)
    inputs, canonical = read_inputs(r, backend, new_files)
    inputs_sha = r.sha(HERE / INPUTS_NAME)
    archive = r.safe_path(args.nut_archive)
    r.verify(archive, canonical["archive_sha256"])
    output = r.output_location(args.output_dir, (archive, backend, new_files, HERE))
    for path in (r.ENV, Path("/usr/bin/xcode-select"), Path("/usr/bin/xcrun"),
                 Path("/usr/bin/patch"), Path("/usr/bin/nm"), Path("/usr/bin/otool")):
        r.safe_path(path)
    helper = r.load_pinned(backend / "process_deadline.py", canonical["local_pins"]["process_deadline.py"], "pacing_process")
    portable = r.load_pinned(backend / "replay_hidapi_full_driver.py", canonical["local_pins"]["replay_hidapi_full_driver.py"], "pacing_portable")
    output.mkdir(mode=0o700)
    pair = {}
    started = time.monotonic()
    try:
        toolchain = r.discover_toolchain(output, canonical, helper)
        source = r.reconstruct(archive, canonical, output, helper)
        before = source_snapshot(r, source)
        expected = dict(before)
        expected[TARGET] = inputs["source_after_sha256"]
        r.command(helper, ["/usr/bin/patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch",
                           "-d", str(source), "-i", str(new_files / PATCH)], output, "pacing-patch")
        verify_paced_source(r, source, before, expected)
        pair = build_pair(r, source, output, canonical, helper, portable, toolchain, backend, new_files, inputs)
        suite = run_pair(r, pair, output, helper, new_files, inputs, backend, canonical) if args.run_fake else {"state": "NOT_RUN"}
        read_inputs(r, backend, new_files)
        r.verify(HERE / INPUTS_NAME, inputs_sha)
        r.verify(archive, canonical["archive_sha256"])
        verify_paced_source(r, source, before, expected)
        for item in pair.values():
            r.verify(Path(item["path"]), item["sha256"])
        for key in ("clang", "xcodebuild"):
            r.verify(Path(toolchain[key]), toolchain[key + "_sha256"])
        r.verify(Path(toolchain["sdk"]) / "SDKSettings.json", toolchain["sdk_settings_sha256"])
        result = {"schema": 1, "state": "PASS_PACING_FAKE_ONLY" if args.run_fake else "COMPILE_ONLY_FAKE_NOT_RUN",
                  "canonical_runner_sha256": RUNNER_PIN, "canonical_manifest_sha256": MANIFEST_PIN,
                  "adapter_sha256": r.sha(Path(__file__)), "inputs_sha256": inputs_sha,
                  "new_pins": inputs["new_pins"], "archive_sha256": canonical["archive_sha256"],
                  "source_before": before, "source_after": expected, "binaries": pair, "suite": suite,
                  "toolchain": toolchain, "python_sha256": python_sha256, "python_version": sys.version,
                  "elapsed_seconds": time.monotonic() - started, "temporary_bytes": r.tree_bytes(output),
                  "hardware": "NOT_RUN", "genuine_hidapi": "NOT_LINKED", "data_qualified": False}
        manifest_text = json.dumps(result, indent=2) + "\n"
        if r.tree_bytes(output) + len(manifest_text.encode("utf-8")) > r.MAX_TREE_BYTES:
            raise r.ReplayError("final manifest would exceed temporary storage budget")
        (output / "manifest.json").write_text(manifest_text)
        r.tree_bytes(output)
        print(result["state"])
        return 0
    finally:
        for binary in output.glob("continuous-pacing-fake-*"):
            if binary.is_file():
                binary.chmod(0o600)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Private paths/OS errors are intentionally absent from the console.
        raise SystemExit("HOLD pacing adapter failed: " + type(exc).__name__) from None
