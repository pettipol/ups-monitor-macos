#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reconstruct and audit the pinned NUT full-driver replay; compile only by default."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
from threading import Event, Thread
import time

HERE = Path(__file__).resolve().parent
INPUTS = "replay_operational_portable_inputs_e31.json"
BASELINE_RUNNER_PIN = "101f5b5c9ec95d7feb18c53e531e4554589a3f0477884c55cc062a889f9c5006"
BASELINE_MANIFEST_PIN = "9020f7675b89f996d6c78dfd48ca63cc61a1f27349f97254dffd9cb6f21f189e"
PATCH_ORDER = (
    "nut-hidapi-continuous-pacing-v2-73c4502.patch",
    "nut-operational-formatter-v2.patch",
    "nut-operational-health-v2.patch",
    "nut-operational-cleanup-v2.patch",
    "nut-operational-driver-v2.patch",
    "nut-operational-replay-hooks.patch",
)
FRESHNESS = ("apcmicrolink-operational-freshness.c", "apcmicrolink-operational-freshness.h")
REQUIRED_NEW_PINS = set(PATCH_ORDER) | set(FRESHNESS) | {
    "replay_operational_native.c", "replay_operational_hooks.h",
    "replay_continuous_pacing.c", "validate_operational_replay.py",
    "bounded_stream_dispatch.py",
}
MODES = ("operational", "v1-macro-off", "v1-opt-in-unused")
SCENARIOS = (
    "healthy-700s", "high-absolute-anchor", "stale-only", "partial-only",
    "stop-pre-open", "stop-layout", "stop-read", "read-transport-error",
    "stop-write", "stop-cleanup", "cleanup-short", "cleanup-late",
    "clock-regression", "flush-startup-14000", "flush-startup-10000",
    "flush-startup-10001", "pre-output-stale", "flush-active-stale",
    "pre-open-dispose-fail", "pre-open-postclock-invalid", "stop-before-wait",
    "stop-before-published", "error-before-stop",
)
BASE = (
    "-s", "replay", "-d1", "-x", "port=auto", "-x", "hidapi_shared",
    "-x", "guarded_monitor", "-x", "guard_vid=0001", "-x", "guard_pid=0002",
    "-x", "guard_deadline=35", "-x", "guard_probe_attempts=1",
    "-x", "hid_fallback=no", "-x", "monitor_stream_v2",
)
CHILD_SECONDS = 15
GRACE_SECONDS = 2
SUITE_SECONDS = 600
CHILD_BYTES = 1_048_576
TOTAL_BYTES = 33 * CHILD_BYTES
MAX_TREE_BYTES = 1_073_741_824
ENV_PATH = Path("/usr/bin/env")
LIMITS = {
    "tree_bytes": MAX_TREE_BYTES, "fake_processes": 33, "suite_seconds": SUITE_SECONDS,
    "child_seconds": CHILD_SECONDS, "termination_grace_seconds": GRACE_SECONDS,
    "child_capture_bytes": CHILD_BYTES, "aggregate_capture_bytes": TOTAL_BYTES,
}


class ReplayError(RuntimeError):
    """Closed failure without captured output or private path details."""


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def safe(path: Path, *, exists: bool = True) -> Path:
    absolute = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ReplayError("symlink path component refused")
    if exists and not absolute.exists():
        raise ReplayError("required input absent")
    return absolute


def verify(path: Path, expected: str) -> None:
    safe(path)
    if not path.is_file() or sha(path) != expected:
        raise ReplayError("pinned input mismatch: " + path.name)


def checked_module(name: str, path: Path, expected: str):
    verify(path, expected)
    if name in sys.modules:
        raise ReplayError("module name already loaded")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ReplayError("module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        # Compile the exact hashed bytes; SourceFileLoader may otherwise prefer
        # a stale or substituted __pycache__ entry even under -B.
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != expected:
            raise ReplayError("pinned module changed before execution")
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    verify(path, expected)
    return module


def snapshot(r, source: Path) -> dict[str, str]:
    r.tree_bytes(source)
    return {str(path.relative_to(source)): r.sha(path)
            for path in sorted(source.rglob("*")) if path.is_file()}


def require_snapshot(actual: dict[str, str], expected: dict[str, str]) -> None:
    if actual != expected:
        raise ReplayError("source snapshot differs")


def validate_patch_entry(r, backend: Path, name: str, entry: dict) -> None:
    targets = set(entry.get("targets", ()))
    if (not targets or r.patch_targets(backend / name) != targets
            or set(entry.get("before", {})) != targets
            or set(entry.get("after", {})) != targets):
        raise ReplayError("patch target or image coverage differs")


def apply_overrides(contract: dict, overrides: dict) -> dict:
    """Copy a frozen baseline and allow precisely the declared two pin updates."""
    names = {"process_deadline.py", "continuous_protocol.py"}
    if set(overrides) != names:
        raise ReplayError("baseline override set differs")
    copied = json.loads(json.dumps(contract))
    pins = copied.get("local_pins")
    if not isinstance(pins, dict):
        raise ReplayError("baseline local pin map unavailable")
    for name in names:
        row = overrides[name]
        if set(row) != {"before", "after"} or pins.get(name) != row["before"]:
            raise ReplayError("baseline override preimage differs")
        pins[name] = row["after"]
    return copied


def validate_process_deadline_override(overrides: dict) -> None:
    """Admit only the E31 helper pin while retaining the frozen baseline preimage."""
    if (not isinstance(overrides, dict)
            or set(overrides) != {"process_deadline.py", "continuous_protocol.py"}
            or overrides["process_deadline.py"].get("after") !=
            "e84b48400e0e5f9561bb2f2fa733b828f52fe6bf80cb9833710ad1f985c10b01"):
        raise ReplayError("E31 process deadline pin differs")


def load_portable(backend: Path, manifest: dict):
    if (manifest.get("baseline_runner_sha256") != BASELINE_RUNNER_PIN
            or manifest.get("baseline_manifest_sha256") != BASELINE_MANIFEST_PIN):
        raise ReplayError("frozen baseline trust root differs")
    if manifest.get("limits") != LIMITS:
        raise ReplayError("replay limits differ")
    if manifest.get("qualification") != {
        "hardware": "NOT_RUN", "data_qualified": False,
        "app_widget_daily_use": "NOT_QUALIFIED", "public_reconstruction": "NOT_RUN",
    }:
        raise ReplayError("qualification contract differs")
    verify(Path(__file__), manifest["adapter_sha256"])
    runner = safe(backend / "replay_continuous_portable.py")
    verify(runner, BASELINE_RUNNER_PIN)
    spec = importlib.util.spec_from_file_location("e31_portable_runner", runner)
    if spec is None or spec.loader is None or spec.name in sys.modules:
        raise ReplayError("baseline runner unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        source = runner.read_bytes()
        if hashlib.sha256(source).hexdigest() != BASELINE_RUNNER_PIN:
            raise ReplayError("baseline runner changed before execution")
        exec(compile(source, str(runner), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def read_inputs(r, backend: Path, manifest: dict) -> tuple[dict, dict]:
    """Verify frozen baseline bytes, then apply only its exact v2 pin overrides."""
    if manifest.get("schema") != 1 or manifest.get("status") != "PUBLIC_OPERATIONAL_REPLAY_CANDIDATE_NOT_RUN":
        raise ReplayError("v2 manifest state differs")
    if set(manifest.get("patches", {})) != set(PATCH_ORDER) or tuple(manifest["patches"]) != PATCH_ORDER:
        raise ReplayError("patch order differs")
    if (manifest.get("baseline_runner_sha256") != BASELINE_RUNNER_PIN
            or manifest.get("baseline_manifest_sha256") != BASELINE_MANIFEST_PIN):
        raise ReplayError("frozen baseline trust root differs")
    if manifest.get("limits") != LIMITS:
        raise ReplayError("replay limits differ")
    if manifest.get("qualification") != {
        "hardware": "NOT_RUN", "data_qualified": False,
        "app_widget_daily_use": "NOT_QUALIFIED", "public_reconstruction": "NOT_RUN",
    }:
        raise ReplayError("qualification contract differs")
    baseline_path = safe(backend / "replay_continuous_portable_inputs.json")
    r.verify(baseline_path, BASELINE_MANIFEST_PIN)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("schema") != 1:
        raise ReplayError("unsupported baseline schema")
    overrides = manifest.get("baseline_overrides", {})
    if set(overrides) != {"process_deadline.py", "continuous_protocol.py"}:
        raise ReplayError("baseline override set differs")
    validate_process_deadline_override(overrides)
    for name, pin in baseline["local_pins"].items():
        if Path(name).name != name:
            raise ReplayError("invalid baseline pin name")
        if name in overrides:
            row = overrides[name]
            if set(row) != {"before", "after"} or row["before"] != pin:
                raise ReplayError("baseline override preimage differs")
        else:
            r.verify(backend / name, pin)
    for entry in baseline["patches"]:
        if baseline["local_pins"].get(entry["name"]) != entry["sha256"]:
            raise ReplayError("baseline patch pin differs")
    effective = apply_overrides(baseline, manifest.get("baseline_overrides", {}))
    effective_pins = effective["local_pins"]
    for name, pin in effective_pins.items():
        r.verify(backend / name, pin)
    if set(manifest.get("new_pins", {})) != REQUIRED_NEW_PINS:
        raise ReplayError("new pin coverage differs")
    for name, pin in manifest["new_pins"].items():
        r.verify(backend / name, pin)
    if set(manifest.get("extra_definitions", ())) != {
        "mlink_operational_replay_fwrite", "mlink_operational_replay_fflush",
        "mlink_operational_replay_checkpoint",
    }:
        raise ReplayError("fake definition contract differs")
    for name in PATCH_ORDER:
        entry = manifest["patches"][name]
        validate_patch_entry(r, backend, name, entry)
    expected = manifest.get("expected_source_after")
    if not isinstance(expected, dict) or not expected:
        raise ReplayError("expected source closure absent")
    return effective, dict(effective_pins)


def admit_adapter(r, backend: Path, manifest: dict) -> None:
    r.verify(Path(__file__), manifest["adapter_sha256"])
    for name, pin in manifest["new_pins"].items():
        r.verify(backend / name, pin)


def admit_archive(r, archive: Path, baseline: dict, manifest: dict) -> None:
    archived = manifest.get("archive")
    if (not isinstance(archived, dict)
            or archived.get("revision") != baseline.get("nut_revision")
            or archived.get("sha256") != baseline.get("archive_sha256")):
        raise ReplayError("archive provenance differs from frozen baseline")
    r.verify(archive, baseline["archive_sha256"])


def check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise ReplayError("replay cancelled")


def check_tree_bytes(r, output: Path, cancel: Event) -> bool:
    try:
        r.tree_bytes(output)
    except (OSError, ReplayError, r.ReplayError):
        cancel.set()
        return False
    return True


def install_cancel_bridge(r, helper, cancel: Event):
    """Bridge the frozen runner's per-command Event to the campaign Event."""
    original_command = r.command
    original_run_bounded = helper.run_bounded

    def bridged_run_bounded(*args, **kwargs):
        child_event = kwargs.get("cancel_event")
        check_cancel(cancel)
        if child_event is None or child_event is cancel:
            return original_run_bounded(*args, **kwargs)
        if not isinstance(child_event, Event):
            raise ReplayError("frozen supervisor cancellation API differs")
        done = Event()

        def bridge() -> None:
            while not done.wait(0.025):
                if cancel.is_set():
                    child_event.set()
                    return

        watcher = Thread(target=bridge, name="e27-command-cancel-bridge", daemon=True)
        watcher.start()
        try:
            return original_run_bounded(*args, **kwargs)
        finally:
            done.set()
            watcher.join(timeout=1)
            if watcher.is_alive():
                raise ReplayError("command cancellation bridge did not stop")

    def guarded_command(*args, **kwargs):
        check_cancel(cancel)
        result = original_command(*args, **kwargs)
        check_cancel(cancel)
        return result

    r.command = guarded_command
    helper.run_bounded = bridged_run_bounded

    def restore() -> None:
        r.command = original_command
        helper.run_bounded = original_run_bounded

    return restore


def stage_source(r, archive: Path, baseline: dict, output: Path, helper, backend: Path,
                 manifest: dict, cancel: Event) -> tuple[Path, dict, dict]:
    check_cancel(cancel)
    source = r.reconstruct(archive, baseline, output, helper)
    check_cancel(cancel)
    expected = snapshot(r, source)
    stages = {"baseline": dict(expected)}
    for index, name in enumerate(PATCH_ORDER):
        check_cancel(cancel)
        entry = manifest["patches"][name]
        for target, pin in entry["before"].items():
            r.verify(source / target, pin)
        r.command(helper, ["/usr/bin/patch", "--batch", "--fuzz=0", "-p1",
                           "--no-backup-if-mismatch", "-d", str(source), "-i", str(backend / name)],
                  output, "operational-patch-" + str(index), timeout=30)
        expected.update(entry["after"])
        require_snapshot(snapshot(r, source), expected)
        check_cancel(cancel)
        stages["after-" + name] = dict(expected)
    for name in FRESHNESS:
        target = source / "drivers" / name
        if target.exists() or target.is_symlink():
            raise ReplayError("freshness source collision")
        target.write_bytes((backend / name).read_bytes())
        target.chmod(0o600)
        expected["drivers/" + name] = manifest["new_pins"][name]
    require_snapshot(snapshot(r, source), expected)
    if expected != manifest["expected_source_after"]:
        raise ReplayError("full source closure differs from admitted final tree")
    stages["final"] = dict(expected)
    return source, expected, stages


FAKE_UNITS = ("replay_operational_native.c", "replay_continuous_pacing.c", "replay_continuous_os.c")


def stage_fake_units(backend: Path, output: Path, pins: dict) -> dict[str, Path]:
    """Keep quote includes away from the backend's frozen preimage headers."""
    directory = output / "fake-units"
    directory.mkdir(mode=0o700)
    staged = {}
    for name in FAKE_UNITS:
        original = backend / name
        verify(original, pins[name])
        data = original.read_bytes()
        if hashlib.sha256(data).hexdigest() != pins[name]:
            raise ReplayError("fake unit changed before staging")
        target = directory / name
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(0o600)
        staged[name] = target
    verify_fake_units(staged, pins)
    return staged


def verify_fake_units(staged: dict[str, Path], pins: dict) -> None:
    directory = safe(staged[FAKE_UNITS[0]].parent)
    if (set(staged) != set(FAKE_UNITS)
            or set(directory.iterdir()) != set(staged.values())
            or any(path != directory / name for name, path in staged.items())):
        raise ReplayError("fake unit directory closure differs")
    for name, path in staged.items():
        verify(path, pins[name])


def require_fake_header_provenance(unit: Path, dependencies: list[str], source: Path,
                                   backend: Path) -> None:
    if unit.name not in FAKE_UNITS:
        return
    headers = {
        "replay_operational_native.c": ("drivers/apcmicrolink-hidapi-native.h",
            "drivers/apcmicrolink-hidapi-session.h", "drivers/apcmicrolink-hidapi-shared-host.h"),
        "replay_continuous_pacing.c": ("drivers/apcmicrolink-hidapi-native.h",
            "drivers/apcmicrolink-hidapi-shared-host.h"),
        "replay_continuous_os.c": ("include/common.h", "drivers/serial.h", "drivers/upsdrvquery.h"),
    }[unit.name]
    actual = {Path(value).resolve(strict=True) for value in dependencies}
    if not {source / name for name in headers}.issubset(actual):
        raise ReplayError("fake unit patched header provenance differs")
    for path in actual:
        if path.parent == backend and path.suffix == ".h" and any(
                (source / root / path.name).is_file() for root in ("drivers", "include", "common")):
            raise ReplayError("fake unit consumed backend preimage header")


def build(r, source: Path, output: Path, baseline: dict, baseline_pins: dict,
          helper, portable, toolchain: dict, backend: Path, manifest: dict,
          cancel: Event) -> dict:
    check_cancel(cancel)
    clang, sdk = Path(toolchain["clang"]), Path(toolchain["sdk"])
    developer = Path(toolchain["developer_dir"])
    generated = output / "include"
    generated.mkdir(mode=0o700)
    for original, name in (("test_hidapi_full_config.h", "config.h"),
                           ("test_hidapi_full_version.h", "nut_version.h")):
        (generated / name).write_bytes((backend / original).read_bytes())
        (generated / name).chmod(0o600)
    for root in (source, source / "drivers", source / "include", source / "common", backend):
        for name in ("config.h", "nut_version.h"):
            if (root / name).exists() or (root / name).is_symlink():
                raise ReplayError("shadow configuration header")
    portable.verify_dependency_paths([source, output, backend])
    common = [str(clang), "-std=gnu99", "-g", "-O0", "-fsanitize=address,undefined",
              "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Wno-unused-parameter",
              "-isysroot", str(sdk), "-DMLINK_HIDAPI_NATIVE_CANDIDATE=1",
              "-DMLINK_HIDAPI_CONTINUOUS_CANDIDATE=1", "-DMLINK_HIDAPI_CONTINUOUS_REPLAY=1",
              "-DMLINK_CONTINUOUS_PACING_V2=1", "-I", str(generated),
              "-I", str(source / "include"), "-I", str(source / "drivers"), "-I", str(backend)]
    all_pins = {**baseline_pins, **manifest["new_pins"]}
    fake_units = stage_fake_units(backend, output, all_pins)
    results = {}
    for mode in MODES:
        check_cancel(cancel)
        flags = [] if mode == "v1-macro-off" else ["-DMLINK_HIDAPI_OPERATIONAL_V2=1"]
        if mode == "operational":
            flags += ["-DMLINK_OPERATIONAL_REPLAY_HOOKS=1"]
        units = [(source / name, True) for name in r.PUBLIC_UNITS]
        units += [(source / "drivers" / name, False) for name in (
            "apcmicrolink-continuous.c", "apcmicrolink-hidapi-shared.c",
            "apcmicrolink-hid-descriptor-checked.c", "apcmicrolink-operational-freshness.c")]
        host = fake_units["replay_operational_native.c" if mode == "operational"
                          else "replay_continuous_pacing.c"]
        units += [(host, False), (fake_units["replay_continuous_os.c"], False)]
        if len(units) != 17 or any(unit.name == "replay_operational_native.c" for unit, _ in units if unit != host):
            raise ReplayError("compile unit matrix differs")
        objects: list[Path] = []
        for index, (unit, guarded) in enumerate(units):
            check_cancel(cancel)
            label = mode + "-compile-" + str(index)
            obj, dep = output / (label + ".o"), output / (label + ".d")
            guards = ["-include", str(backend / "test_hidapi_full_os.h"), "-Dchdir=fixture_chdir"] if guarded else []
            special = ["-DFULL_FAKE_MAIN=1"] if unit.name == "main.c" else []
            if unit.name == "common.c":
                special += ["-DNUT_WANT_INET_NTOP_XX=1"]
            if unit.name == "apcmicrolink.c" and mode == "operational":
                special += ["-Dfwrite=mlink_operational_replay_fwrite",
                            "-Dfflush=mlink_operational_replay_fflush"]
            verify_fake_units(fake_units, all_pins)
            r.verify(clang, toolchain["clang_sha256"])
            r.command(helper, [*common, *flags, *guards, *special, "-MD", "-MF", str(dep),
                               "-MT", "ups_full_fake_dependency_target", "-c", str(unit), "-o", str(obj)],
                      output, label, timeout=120, developer_dir=developer)
            required = {generated / "config.h"} if guarded else set()
            if unit.name == "common-nut_version.c":
                required.add(generated / "nut_version.h")
            portable.verify_includes(dep, required, unit.name)
            dep_items = dep.read_text().replace("\\\n", " ").split(":", 1)[1].split()
            require_fake_header_provenance(unit, dep_items, source, backend)
            for value in dep_items:
                resolved = Path(value).resolve(strict=True)
                if resolved.is_relative_to(source) or resolved.is_relative_to(generated):
                    continue
                if resolved in fake_units.values():
                    verify(resolved, all_pins[resolved.name])
                    continue
                if resolved.parent == backend and resolved.name in all_pins:
                    r.verify(resolved, all_pins[resolved.name])
                elif not (resolved.is_relative_to(sdk) or resolved.is_relative_to(clang.parents[1])):
                    raise ReplayError("unadmitted compile dependency")
            if unit.name in {"apcmicrolink.c", "replay_operational_native.c"} and mode == "operational":
                if str(backend / "replay_operational_hooks.h") not in dep_items:
                    raise ReplayError("operational hooks header missing from dependency closure")
            objects.append(obj)
            check_cancel(cancel)
        binary, link_map = output / ("operational-fake-" + mode), output / (mode + ".map")
        try:
            check_cancel(cancel)
            r.command(helper, [*common, *flags, *(str(obj) for obj in objects), "-lm",
                               "-Wl,-map," + str(link_map), "-o", str(binary)],
                      output, mode + "-link", timeout=120, developer_dir=developer)
        finally:
            if binary.exists():
                binary.chmod(0o600)
        r.verify_selected_objects(link_map.read_text(), objects, developer)
        item = r.audit(binary, output, helper)
        check_cancel(cancel)
        symbol_text = (output / (binary.name + "-defined") / "stdout.bin").read_text()
        symbols = {line.split()[-1] for line in symbol_text.splitlines() if line.split()}
        definitions = manifest["extra_definitions"]
        if mode == "operational":
            if any("_" + name not in symbols for name in definitions):
                raise ReplayError("operational fake definition absent")
        elif any("_" + name in symbols for name in definitions):
            raise ReplayError("operational fake definition leaked into v1")
        results[mode] = {"path": str(binary), **item, "objects": [str(obj) for obj in objects]}
    return results


def fixed_cases() -> list[tuple[str, str, str, tuple[str, ...]]]:
    cases = [(name, "operational", name, BASE) for name in SCENARIOS]
    negatives = {
        "no-stream": BASE[:-2],
        "both-streams": BASE + ("-x", "monitor_stream_v1"),
        "debug-level": tuple("-d2" if item == "-d1" else item for item in BASE),
        "probe-retry": tuple("guard_probe_attempts=2" if item == "guard_probe_attempts=1" else item for item in BASE),
        "fallback": tuple("hid_fallback=yes" if item == "hid_fallback=no" else item for item in BASE),
        "old-deadline": tuple("guard_deadline=130" if item == "guard_deadline=35" else item for item in BASE),
        "zero-vid": tuple("guard_vid=0000" if item == "guard_vid=0001" else item for item in BASE),
        "no-shared": BASE[:5] + BASE[7:],
    }
    cases += [("cli-" + name, "operational", "cli-negative", argv)
              for name, argv in negatives.items()]
    old = tuple("monitor_stream_v1" if item == "monitor_stream_v2" else
                "guard_deadline=130" if item == "guard_deadline=35" else item for item in BASE)
    cases += [(mode, mode, "next-gap-budget", old)
              for mode in ("v1-macro-off", "v1-opt-in-unused")]
    if len(cases) != 33 or len({row[0] for row in cases}) != 33:
        raise ReplayError("fixed suite matrix differs")
    return cases


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def new_suite_receipt() -> dict:
    return {"state": "NOT_RUN", "expected_cases": 33, "attempted_cases": 0,
            "completed_cases": 0, "validated_cases": 0, "captured_bytes": 0,
            "duration_seconds": 0.0, "results": []}


def require_suite_success(receipt: dict) -> None:
    if (receipt.get("state") != "PASS_FAKE_ONLY"
            or any(receipt.get(key) != 33 for key in (
                "expected_cases", "attempted_cases", "completed_cases", "validated_cases"))):
        raise ReplayError("suite receipt does not prove complete success")


def write_final_receipt(r, output: Path, receipt: dict, cancel: Event | None = None) -> str:
    """Reserve the exact manifest bytes; never keep PASS after storage failure.

    If storage cannot be measured, or even a small failure receipt cannot fit,
    leave the existing command/child receipts untouched and return failure.
    Writing past the hard tree limit to record that limit is not permitted.
    """
    try:
        used = r.tree_bytes(output)
    except (OSError, ReplayError, r.ReplayError):
        receipt.update(state="STOPPED_NOT_QUALIFIED", error="final_storage_unavailable",
                       temporary_bytes="LIMIT_EXCEEDED_OR_UNREADABLE")
        return receipt["state"]
    receipt["temporary_bytes"] = used

    def encode(value: dict) -> bytes:
        return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    if cancel is not None and cancel.is_set():
        receipt.update(state="STOPPED_NOT_QUALIFIED", error="late_cancellation")
    data = encode(receipt)
    # link() gives atomic publication without replacing an existing name.
    # Until the private pending name is removed, tree_bytes counts both links.
    if used + 2 * len(data) > MAX_TREE_BYTES:
        receipt.update(state="STOPPED_NOT_QUALIFIED", error="final_manifest_storage_limit")
        # Preserve a bounded pointer to existing partial command/child receipts
        # when the complete source-map manifest cannot fit.
        data = encode({"schema": 1, "state": receipt["state"], "error": receipt["error"],
                       "temporary_bytes": used, "partial_receipts_retained": True,
                       "hardware": "NOT_RUN", "data_qualified": False})
    if used + 2 * len(data) > MAX_TREE_BYTES:
        return receipt["state"]
    pending = output / ".manifest.pending"
    created = False
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        try:
            os.fchmod(descriptor, 0o600)
            view = memoryview(data)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("final manifest write made no progress")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if cancel is not None and cancel.is_set():
            raise ReplayError("late cancellation before manifest publication")
        os.link(pending, output / "manifest.json", follow_symlinks=False)
        # All failure-sensitive preparation finished before the atomic link.
        # Cleanup below cannot reverse a published result or exceed reservation.
    except (OSError, ReplayError):
        receipt.update(state="STOPPED_NOT_QUALIFIED", error="final_manifest_write_failed")
    finally:
        if created:
            try:
                pending.unlink()
            except OSError:
                pass  # Both names were already reserved against the hard limit.
    return receipt["state"]


def run_suite(pair: dict, output: Path, helper, validator, manifest: dict,
              cancel: Event, started: float, env_binary_sha256: str,
              receipt: dict | None = None) -> dict:
    receipt = receipt if receipt is not None else new_suite_receipt()
    receipt.update(state="IN_PROGRESS", expected_cases=33)
    rows: list[dict] = receipt["results"]
    deadline = started + SUITE_SECONDS
    error = None
    timer_stop = Event()

    def enforce_suite_deadline() -> None:
        remaining = max(0.0, deadline - time.monotonic())
        if not timer_stop.wait(remaining):
            cancel.set()

    deadline_monitor = Thread(target=enforce_suite_deadline, name="e27-suite-deadline", daemon=True)
    deadline_monitor.start()
    try:
        if len(pair) != 3:
            raise ReplayError("fake build matrix incomplete")
        cases = fixed_cases()
        verify(ENV_PATH, env_binary_sha256)
        for number, (name, mode, scenario, arguments) in enumerate(cases, 1):
            check_cancel(cancel)
            remaining = deadline - time.monotonic()
            child_window = remaining - GRACE_SECONDS - 1.0
            if child_window <= 0:
                raise ReplayError("suite deadline leaves no bounded child window")
            binary = Path(pair[mode]["path"])
            expected_sha = pair[mode]["sha256"]
            verify(binary, expected_sha)
            if stat.S_IMODE(binary.stat().st_mode) != 0o600:
                raise ReplayError("fake mode before launch differs")
            env_name = "MLINK_OPERATIONAL_REPLAY_SCENARIO" if mode == "operational" else "MLINK_CONTINUOUS_REPLAY_SCENARIO"
            env_value = "healthy-700s" if scenario == "cli-negative" else scenario
            environment = ["PATH=/usr/bin:/bin", "LC_ALL=C",
                           "ASAN_OPTIONS=abort_on_error=1:detect_leaks=0:symbolize=0:log_path=stderr",
                           "UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=0",
                           env_name + "=" + env_value]
            env_hash = hashlib.sha256("\0".join(environment).encode("utf-8")).hexdigest()
            if hashlib.sha256("\0".join(environment).encode("utf-8")).hexdigest() != env_hash:
                raise ReplayError("child environment contract changed")
            verify(ENV_PATH, env_binary_sha256)
            argv = [str(ENV_PATH), "-i", *environment, str(binary), *arguments]
            row = {"name": name, "mode": mode, "scenario": scenario, "argv": argv,
                   "binary_sha256": expected_sha, "environment_sha256": env_hash,
                   "env_executable_sha256": env_binary_sha256, "hardware": "NOT_RUN",
                   "state": "CHILD_STARTED"}
            rows.append(row)
            receipt["attempted_cases"] = len(rows)
            case_dir = output / f"{number:02d}-{name}"
            binary.chmod(0o700)
            try:
                bounded = helper.run_bounded(
                    argv, executable_sha256=env_binary_sha256, output_directory=case_dir,
                    timeout_seconds=min(CHILD_SECONDS, child_window),
                    termination_grace_seconds=GRACE_SECONDS,
                    maximum_output_bytes=CHILD_BYTES, cancel_event=cancel)
            except BaseException as exc:
                row.update(state="SUPERVISOR_FAILED", failure=type(exc).__name__)
                write_json(output / f"{number:02d}-{name}.receipt.json", row)
                raise ReplayError("fake supervisor failed") from None
            finally:
                binary.chmod(0o600)
            row["supervisor"] = asdict(bounded)
            row["state"] = "CHILD_COMPLETED"
            receipt["completed_cases"] += 1
            write_json(output / f"{number:02d}-{name}.receipt.json", row)
            if time.monotonic() >= deadline:
                row["failure"] = "suite_deadline"
                raise ReplayError("suite deadline reached after child")
            if (bounded.status != helper.RunStatus.EXITED
                    or bounded.trigger != helper.RunTrigger.COMPLETED
                    or bounded.observation is None or bounded.returncode is None):
                row["failure"] = "child_not_cleanly_reaped"
                raise ReplayError("fake child did not exit and reap cleanly")
            verify(binary, expected_sha)
            stdout_path, stderr_path = case_dir / "stdout.bin", case_dir / "stderr.bin"
            stdout, stderr = stdout_path.read_bytes(), stderr_path.read_bytes()
            row["capture_bytes"] = len(stdout) + len(stderr)
            receipt["captured_bytes"] += len(stdout) + len(stderr)
            if (len(stdout) != bounded.stdout_bytes or len(stderr) != bounded.stderr_bytes
                    or len(stdout) + len(stderr) > CHILD_BYTES
                    or hashlib.sha256(stdout).hexdigest() != bounded.observation.stdout_sha256
                    or hashlib.sha256(stderr).hexdigest() != bounded.observation.stderr_sha256):
                row["failure"] = "capture_length_or_hash"
                raise ReplayError("fake capture length or hash differs")
            if receipt["captured_bytes"] > TOTAL_BYTES:
                row["failure"] = "aggregate_capture_limit"
                raise ReplayError("aggregate capture limit exceeded")
            try:
                row["validation"] = validator.validate(mode, scenario, stdout, stderr, bounded.returncode)
            except BaseException as exc:
                row["failure"] = "validator_exception"
                row["validator_error"] = type(exc).__name__
                raise ReplayError("operational validator failed") from None
            if (not isinstance(row["validation"], dict)
                    or row["validation"].get("state") != "PASS_SCOPE_ONLY"):
                row["failure"] = "validator_state"
                row["state"] = "VALIDATION_REJECTED"
                write_json(output / f"{number:02d}-{name}.validated.json", row)
                raise ReplayError("validator did not return PASS_SCOPE_ONLY")
            row["state"] = "VALIDATED"
            receipt["validated_cases"] += 1
            write_json(output / f"{number:02d}-{name}.validated.json", row)
        check_cancel(cancel)
        if len(rows) != 33 or time.monotonic() >= deadline:
            raise ReplayError("suite incomplete or deadline reached")
    except BaseException as exc:
        error = str(exc) if type(exc) is ReplayError else type(exc).__name__
        receipt["state"] = "STOPPED_NOT_QUALIFIED"
        receipt["error"] = error
        raise
    else:
        receipt["state"] = "PASS_FAKE_ONLY"
    finally:
        timer_stop.set()
        deadline_monitor.join(timeout=1)
        if deadline_monitor.is_alive():
            receipt["state"] = "STOPPED_NOT_QUALIFIED"
            receipt["error"] = "suite_deadline_monitor_unjoined"
            cancel.set()
        receipt["expected_cases"] = 33
        receipt["attempted_cases"] = len(rows)
        receipt["duration_seconds"] = time.monotonic() - started
        receipt["env_executable_sha256"] = env_binary_sha256
        receipt["results"] = rows
        if error and "error" not in receipt:
            receipt["error"] = error
    require_suite_success(receipt)
    return receipt


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-dir", type=Path, required=True)
    parser.add_argument("--nut-archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compile-only", action="store_true")
    group.add_argument("--run-fake", action="store_true")
    return parser.parse_args(argv)


def require_runtime() -> None:
    if (sys.version_info[:3] != (3, 15, 2) or sys.platform != "darwin"
            or not sys.flags.isolated or not sys.flags.no_site
            or not sys.flags.dont_write_bytecode or sys.flags.optimize):
        raise ReplayError("requires macOS Python 3.15.2 with -I -S -B")


def main(argv=None) -> int:
    args = parse_args(argv)
    require_runtime()
    backend = safe(args.backend_dir)
    manifest_path = safe(HERE / INPUTS)
    if manifest_path.name != INPUTS:
        raise ReplayError("manifest name differs")
    manifest_sha = sha(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify(Path(__file__), manifest.get("adapter_sha256", ""))
    r = load_portable(backend, manifest)
    baseline, baseline_pins = read_inputs(r, backend, manifest)
    archive = safe(args.nut_archive)
    admit_archive(r, archive, baseline, manifest)
    output = r.output_location(args.output_dir, (backend, archive, HERE))
    for path in (ENV_PATH, Path("/usr/bin/patch"), Path("/usr/bin/nm"), Path("/usr/bin/otool"),
                 Path("/usr/bin/xcode-select"), Path("/usr/bin/xcrun")):
        safe(path)
    # Import the lazy helper dependency under its exact name before helper load.
    new = manifest["new_pins"]
    checked_module("bounded_stream_dispatch", backend / "bounded_stream_dispatch.py",
                   new["bounded_stream_dispatch.py"])
    helper = checked_module("e31_process_deadline", backend / "process_deadline.py",
                            baseline_pins["process_deadline.py"])
    portable = checked_module("e31_hidapi_full_driver", backend / "replay_hidapi_full_driver.py",
                              baseline_pins["replay_hidapi_full_driver.py"])
    protocol = checked_module("e31_continuous_protocol", backend / "continuous_protocol.py",
                              baseline_pins["continuous_protocol.py"])
    validator = checked_module("e31_validate_operational_replay", backend / "validate_operational_replay.py",
                               new["validate_operational_replay.py"])
    validator.protocol = protocol
    output.mkdir(mode=0o700)
    started = time.monotonic()
    cancel = Event()
    handlers = {}
    monitor_done = Event()
    monitor_failed: list[str] = []
    binaries = {}
    source = None
    expected_source = {}
    stages = {}
    state = "INCOMPLETE"
    suite = {"state": "NOT_RUN"}
    pure_checks = []
    error = None
    restore_cancellation = lambda: None

    def monitor_storage() -> None:
        while not monitor_done.wait(0.1):
            if not check_tree_bytes(r, output, cancel):
                monitor_failed.append("tree_limit")
                return

    watcher = Thread(target=monitor_storage, name="e27-storage-guard", daemon=True)
    watcher.start()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, lambda _sig, _frame: cancel.set())
        restore_cancellation = install_cancel_bridge(r, helper, cancel)
        check_cancel(cancel)
        # Both admission-provided pure mutation suites run before the first compiler call.
        pure_checks = [validator.run_pure_mutation_selfchecks(),
                       validator.run_transport_error_mutation_selfchecks()]
        check_cancel(cancel)
        toolchain = r.discover_toolchain(output, baseline, helper)
        check_cancel(cancel)
        source, expected_source, stages = stage_source(r, archive, baseline, output, helper,
                                                       backend, manifest, cancel)
        check_cancel(cancel)
        binaries = build(r, source, output, baseline, baseline_pins, helper, portable,
                         toolchain, backend, manifest, cancel)
        if args.run_fake:
            suite = new_suite_receipt()
            run_suite(binaries, output, helper, validator, manifest, cancel,
                      time.monotonic(), sha(ENV_PATH), suite)
            require_suite_success(suite)
        if monitor_failed or cancel.is_set():
            raise ReplayError("storage guard or cancellation")
        if snapshot(r, source) != expected_source:
            raise ReplayError("source changed after build or execution")
        if expected_source != manifest["expected_source_after"]:
            raise ReplayError("full source closure differs")
        # Recheck every declared input and its effective baseline pin closure.
        admit_adapter(r, backend, manifest)
        _, final_pins = read_inputs(r, backend, manifest)
        if final_pins != baseline_pins or sha(manifest_path) != manifest_sha:
            raise ReplayError("input changed during replay")
        admit_archive(r, archive, baseline, manifest)
        if args.run_fake:
            verify(ENV_PATH, suite["env_executable_sha256"])
        for name, item in binaries.items():
            verify(Path(item["path"]), item["sha256"])
        for key in ("clang", "xcodebuild"):
            verify(Path(toolchain[key]), toolchain[key + "_sha256"])
        verify(Path(toolchain["sdk"]) / "SDKSettings.json", toolchain["sdk_settings_sha256"])
        state = "PASS_FAKE_ONLY" if args.run_fake else "COMPILE_ONLY_FAKE_NOT_RUN"
    except BaseException as exc:
        error = str(exc) if type(exc) is ReplayError else type(exc).__name__
        state = "STOPPED_NOT_QUALIFIED"
    finally:
        restore_cancellation()
        for mode in MODES:
            row = binaries.get(mode)
            if row:
                binary = Path(row["path"])
                if binary.is_file() and not binary.is_symlink():
                    binary.chmod(0o600)
        monitor_done.set()
        watcher.join(timeout=2)
        if watcher.is_alive():
            error, state = "storage_monitor_unjoined", "STOPPED_NOT_QUALIFIED"
        if monitor_failed or cancel.is_set():
            error, state = "late_storage_guard_or_cancellation", "STOPPED_NOT_QUALIFIED"
        receipt = {
            "schema": 1, "state": state, "error": error, "adapter_sha256": sha(Path(__file__)),
            "inputs_sha256": manifest_sha, "baseline_manifest_sha256": manifest["baseline_manifest_sha256"],
            "baseline_overrides": manifest["baseline_overrides"], "effective_baseline_pins": baseline_pins,
            "source_after": expected_source, "stage_source_hashes": stages,
            "binaries": binaries, "suite": suite, "pure_checks": pure_checks,
            "env_executable_sha256": sha(ENV_PATH),
            "toolchain": locals().get("toolchain"), "python_version": sys.version,
            "python_sha256": sha(Path(sys.executable).resolve()),
            "duration_seconds": time.monotonic() - started, "temporary_bytes": None,
            "hardware": "NOT_RUN", "data_qualified": False,
        }
        try:
            state = write_final_receipt(r, output, receipt, cancel)
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
    print(state)
    return 0 if state in ("COMPILE_ONLY_FAKE_NOT_RUN", "PASS_FAKE_ONLY") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit("HOLD operational replay: " + type(exc).__name__) from None
