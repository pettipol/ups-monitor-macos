#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare the post-CAL native adapters with the cancellation fix using fake HID."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
from threading import Event
import time

SUPERVISOR_SHA256 = "81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e"
BASE_MANIFEST_SHA256 = "51fd7e265ca407352357ea8c1d883f9f4822af5320dac102bf985623a9c786a0"
MANIFEST_SHA256 = "ae9c3fbb61ba0224dc9929bad2f91e19718b42532ff70ddd74b20f3ecc1cb6a4"
FIXTURE_SHA256 = "ff5f6da5ab8c345d82dae4cca786221463a4b4aab73a111283f12b292e7d1f18"
UNITS = ("apcmicrolink-hidapi-native.c", "apcmicrolink-hidapi-shared.c",
         "apcmicrolink-hid-descriptor-checked.c")
HEADERS = ("apcmicrolink-hidapi-native.h", "apcmicrolink-hidapi-shared-host.h",
           "apcmicrolink-hidapi-session.h", "apcmicrolink-hid-descriptor-checked.h",
           "apcmicrolink-usb.h")


def checked_bytes(path: Path, expected: str | None = None) -> bytes:
    """Read a regular, non-redirected input with a 1 MiB cap."""
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("redirected input: " + path.name)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1_048_576:
        raise ValueError("input type/size: " + path.name)
    with path.open("rb") as stream:
        data = stream.read(1_048_577)
    if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("invalid input pin: " + path.name)
    if len(data) > 1_048_576 or (expected is not None and hashlib.sha256(data).hexdigest() != expected):
        raise ValueError("input digest/size: " + path.name)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path,
                        help="Verified post-CAL source, with staged HIDAPI headers")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="New private receipt directory, outside all inputs")
    parser.add_argument("--developer-dir", type=Path, default=Path("/Applications/Xcode.app/Contents/Developer"))
    args = parser.parse_args()
    if sys.platform != "darwin" or sys.flags.optimize:
        parser.error("requires macOS Python without optimization")
    if any(".." in path.parts for path in (args.source_dir, args.output_dir)):
        raise ValueError("parent traversal in source/output path")
    os.umask(0o077)
    here = Path(__file__).absolute().parent
    source = args.source_dir.absolute()
    output = args.output_dir.absolute()
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("output must be a new directory without symlink parents")
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in (here, source)):
        raise ValueError("output overlaps inputs")
    inputs: dict[Path, bytes] = {}

    def admit(path: Path, digest: str | None = None) -> bytes:
        data = checked_bytes(path, digest)
        inputs[path] = data
        return data

    base = json.loads(admit(here / "native-build/production_source_post_cal.json", BASE_MANIFEST_SHA256))
    manifest = json.loads(admit(here / "native-build/production_source_post_write_cancel.json", MANIFEST_SHA256))
    if (manifest["schema"] != 1 or manifest["base_manifest_sha256"] != BASE_MANIFEST_SHA256 or
            manifest["status"] != "SOURCE_CANDIDATE_NOT_HARDWARE_QUALIFIED"):
        raise ValueError("invalid candidate manifest")
    before, after = base["post_cal_sha256"], manifest["post_write_cancel_sha256"]
    if len(before) != 190 or set(before) != set(after):
        raise ValueError("source checkpoint size/names differ")
    changed = {"drivers/" + n for n in (UNITS[0], UNITS[1], HEADERS[1])}
    if {n for n in before if before[n] != after[n]} != changed:
        raise ValueError("unexpected cancellation delta")
    for name, digest in before.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("invalid source name")
        admit(source / name, digest)
    patch = admit(here / "native-build/nut-write-cancel-boundary-v2.patch", manifest["patch_sha256"])
    fixture = admit(here / "test_hidapi_native.c", FIXTURE_SHA256)
    test = admit(here / "test_hidapi_cancel_boundary.c", manifest["test_sha256"])
    cases = json.loads(admit(here / "native-build/write_cancel_cases.json", manifest["cases_sha256"]))
    if len(cases) != 10 or len(set(cases)) != 10 or any(not re.fullmatch(r"[a-z0-9-]+", n) for n in cases):
        raise ValueError("invalid boundary matrix")
    vendor = {}
    for name in ("hidapi/hidapi.h", "mac/hidapi_darwin.h"):
        leaf = Path(name).name
        vendor[leaf] = admit(source / "drivers/hidapi-candidate" / leaf, base["hidapi"]["source_sha256"][name])
    helper_path = here / "process_deadline.py"
    helper_data = admit(helper_path, SUPERVISOR_SHA256)
    spec = importlib.util.spec_from_file_location("write_cancel_deadline", helper_path)
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    exec(compile(helper_data, str(helper_path), "exec"), helper.__dict__)
    output.mkdir(mode=0o700)
    cancel = Event()
    previous = {sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    started = time.monotonic()
    phases: list[dict] = []
    receipt: dict = {"state": "FAIL", "scope": "native/shared adapters with fake HID only", "phases": phases}
    receipt["binary_sha256"] = {}

    def run(argv: list[str], label: str, timeout: float = 15, pinned_digest: str | None = None) -> str:
        remaining = 300 - (time.monotonic() - started)
        if remaining <= 0 or cancel.is_set():
            raise RuntimeError("campaign cancelled or expired")
        executable = Path(argv[0]).resolve(strict=True)
        argv[0] = str(executable)
        log = output / (f"{len(phases):02d}-" + label)
        result = helper.run_bounded(argv, executable_sha256=pinned_digest or hashlib.sha256(executable.read_bytes()).hexdigest(),
            output_directory=log, timeout_seconds=min(timeout, remaining), termination_grace_seconds=1,
            maximum_output_bytes=1_048_576, cancel_event=cancel)
        phases.append({"label": label, "status": result.status.value, "trigger": result.trigger.value,
                       "returncode": result.returncode, "stdout_bytes": result.stdout_bytes,
                       "stderr_bytes": result.stderr_bytes})
        if result.status != helper.RunStatus.EXITED or result.trigger != helper.RunTrigger.COMPLETED or result.returncode:
            raise RuntimeError("phase failed: " + label)
        return (log / "stdout.bin").read_text()

    try:
        with tempfile.TemporaryDirectory(prefix="ups-write-cancel-", dir="/private/tmp") as temporary:
            root = Path(temporary)
            drivers = root / "drivers"
            drivers.mkdir()
            for name in (*UNITS, *HEADERS):
                (drivers / name).write_bytes(inputs[source / "drivers" / name])
            for leaf, data in vendor.items():
                (drivers / leaf).write_bytes(data)
            (drivers / "test_hidapi_native.c").write_bytes(fixture)
            (drivers / "test_hidapi_cancel_boundary.c").write_bytes(test)
            patch_path = root / "candidate.patch"
            patch_path.write_bytes(patch)
            staged_before = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in drivers.rglob("*") if p.is_file()}
            developer = args.developer_dir.resolve(strict=True)
            compiler = developer / "Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
            sdk = developer / "Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
            for variant in ("baseline", "candidate"):
                if variant == "candidate":
                    run(["/usr/bin/patch", "--batch", "--forward", "--fuzz=0", "--no-backup-if-mismatch", "-p1", "-d", str(root), "-i", str(patch_path)], "apply")
                    staged_after = {p.relative_to(root): hashlib.sha256(checked_bytes(p)).hexdigest()
                                    for p in drivers.rglob("*") if p.is_file() or p.is_symlink()}
                    expected = {n: after[str(n)] if str(n) in changed else h for n, h in staged_before.items()}
                    if staged_after != expected:
                        raise RuntimeError("patch changed unexpected staged input")
                for mode, flags, test_name in (
                    ("v1", [], "test_hidapi_native.c"),
                    ("v2", ["-DMLINK_HIDAPI_OPERATIONAL_V2=1"], "test_hidapi_native.c"),
                    ("boundary", ["-DMLINK_HIDAPI_OPERATIONAL_V2=1"] +
                        (["-DEXPECT_DISTINCT_STOP=1"] if variant == "candidate" else []), "test_hidapi_cancel_boundary.c")):
                    label = variant + "-" + mode
                    binary = root / label
                    run(["/usr/bin/env", "TMPDIR=" + str(root), "DEVELOPER_DIR=" + str(developer), str(compiler),
                         "--no-default-config", "-isysroot", str(sdk), "-std=c11", "-Wall", "-Wextra", "-Werror", "-DMLINK_HIDAPI_SHARED_TEST",
                         *flags, "-I" + str(drivers), *(str(drivers / n) for n in UNITS),
                         str(drivers / test_name), "-o", str(binary)], label + "-build", 30)
                    binary.chmod(0o600)
                    binary_digest = hashlib.sha256(binary.read_bytes()).hexdigest()
                    receipt["binary_sha256"][label] = binary_digest
                    libs = run(["/usr/bin/otool", "-L", str(binary)], label + "-libs")
                    symbols = run(["/usr/bin/nm", str(binary)], label + "-symbols")
                    if hashlib.sha256(binary.read_bytes()).hexdigest() != binary_digest:
                        raise RuntimeError("binary changed during audit")
                    if [line.strip().split()[0] for line in libs.splitlines()[1:]] != ["/usr/lib/libSystem.B.dylib"]:
                        raise RuntimeError("unexpected fake binary library")
                    if re.search(r"\bU _(hid_|libusb_|IOHID|IOService|dlopen|socket|connect)", symbols):
                        raise RuntimeError("hardware/network import in fake binary")
                    for symbol in ("hid_init", "hid_enumerate", "hid_open_path", "hid_read_timeout", "hid_write", "hid_close", "hid_exit"):
                        if not re.search(r"\bT _" + symbol + r"$", symbols, re.M):
                            raise RuntimeError("missing fake HID definition: " + symbol)
                    try:
                        binary.chmod(0o700)
                        for case in cases if mode == "boundary" else [None]:
                            run([str(binary)] + ([case] if case else []), label + ("-" + case if case else "-suite"),
                                pinned_digest=binary_digest)
                        if hashlib.sha256(binary.read_bytes()).hexdigest() != binary_digest:
                            raise RuntimeError("binary changed during matrix")
                    finally:
                        binary.chmod(0o600)
        for path, data in inputs.items():
            if checked_bytes(path) != data:
                raise RuntimeError("input changed during replay: " + path.name)
        if cancel.is_set() or time.monotonic() - started >= 300:
            raise RuntimeError("campaign cancelled or expired before acceptance")
        receipt.update(state="PASS_FAKE_ONLY", boundary_cases_per_variant=len(cases), scratch_removed=not root.exists(),
                       source_manifest_sha256=BASE_MANIFEST_SHA256, patch_sha256=manifest["patch_sha256"],
                       test_sha256=manifest["test_sha256"])
    except BaseException as error:
        receipt["error"] = str(error)
        raise
    finally:
        if cancel.is_set():
            receipt["state"] = "FAIL"
            receipt["error"] = "campaign cancelled"
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        receipt["duration_seconds"] = time.monotonic() - started
        (output / "RESULT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["state"] != "PASS_FAKE_ONLY":
        return 1
    print("PASS_FAKE_ONLY: 10 boundary cases per variant and original V1/V2 suites; no hardware")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
