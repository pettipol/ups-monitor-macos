#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute synthetic HIDAPI symbols; optionally link real mac HIDAPI, never run it."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
from threading import Event
from typing import Callable, TypeVar

from process_deadline import RunStatus, RunTrigger, run_bounded

CANCEL_EVENT = Event()
T = TypeVar("T")

PINS = {
    "hidapi/hidapi.h": "c9cef28c53a13a9403e54d5a8a099d51afff119ab04094df89356df0833a822e",
    "mac/hidapi_darwin.h": "48854f6f6b612a90291c3de83a5755c2ed8642da173151a41377090821c39187",
    "mac/hid.c": "0770e9b42138f9a42e91c8ddb4ddbd0696ebaf6f6535c969b7b36b8caa90ae80",
}
ABI_PIN = "b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29"
OPERATIONAL_ABI_PIN = "3ef32b7ce9836c0497d0d09697f39862a6d018eca9656628eb951ab4b6a2ef5f"
BASE_PINS = {
    "apcmicrolink-hidapi-native.c": "3a1205741d62e02871d96c4e3091674b8131e8d3d95e58b156f2f95e9de1d2a5",
    "apcmicrolink-hidapi-native.h": "648531900d7d2413a59dd36c04e3cd05a3c466ec52062b2e17437cd5b2064ada",
    "apcmicrolink-hidapi-shared.c": "a87a7d001b992b7b1cfd1afd96d4432cb5a5d9bfe40550c1877ebd646ba83a21",
    "apcmicrolink-hidapi-shared-host.h": "606caa96cef85055c68c3b0d7c999e57e24efeb7bac16427dc8836bfd0631dcd",
    "apcmicrolink-hidapi-session.h": "50104ad0660fbd3c77fa185b0d8e00269f59775a1e123d3b548cb6c86f77d5ae",
    "apcmicrolink-hid-descriptor-checked.c": "7db55b980569f8385196d10c30a966b0e78f1f9266c624f05a3c2459d13ebc85",
    "apcmicrolink-hid-descriptor-checked.h": "65c24b24313ba78c8293ede0485839c496165779f4d87cedde5e882a9f266b52",
    "nut-hidapi-continuous-73c4502.patch": "f57a3cebd4cc70701be8d40c3af2484f3bf8a9f5b0c9ddde3af15f58e20e6aa8",
    "nut-operational-health-v2.patch": "3bac2388c2bae0a63232748d6e402ef2b8e3be83945edf9f8e8b0464c4fc1995",
}
OPERATIONAL_BASE_PINS = {
    "apcmicrolink-hidapi-native.c": "1fa086f34a5cfe46f987c44b1df6452aea0a979268b6e7724415343bfd743cde",
    "apcmicrolink-hidapi-native.h": "03555a828c4d159948b9919a8b7d743400d884725050f82e4513ee68e58cbba8",
    "apcmicrolink-hidapi-shared.c": "99f3f7fb8db9e1df4a1790803daa5f7ac2a15d92848caac05d9363c23c25f896",
    "apcmicrolink-hidapi-session.h": "c81be418cf4510bc41868b8a61c8fd90a4de7c28670ac1ab16c80253a237515b",
    "apcmicrolink-usb.h": OPERATIONAL_ABI_PIN,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="hidapi-command-") as temporary:
        output = Path(temporary) / "capture"
        result = run_bounded(command, executable_sha256=sha256(Path(command[0])),
                             output_directory=output, timeout_seconds=timeout,
                             termination_grace_seconds=0.5, maximum_output_bytes=1_048_576,
                             cancel_event=CANCEL_EVENT)
        stdout = (output / "stdout.bin").read_text(errors="replace") if output.exists() else ""
        stderr = (output / "stderr.bin").read_text(errors="replace") if output.exists() else ""
    if result.status is not RunStatus.EXITED or result.trigger is not RunTrigger.COMPLETED or result.returncode:
        raise SystemExit(
            f"HOLD: command failed ({result.returncode}): {command[0]}\n"
            + stdout + stderr
        )
    return subprocess.CompletedProcess(command, result.returncode, stdout, stderr)


def selected_patch(text: str, targets: set[str]) -> str:
    """Select complete, known diff sections, refusing target redirection."""
    sections = re.split(r"(?m)(?=^--- a/)", text)
    selected: dict[str, str] = {}
    for section in sections:
        lines = section.splitlines(keepends=True)
        if not lines or not lines[0].startswith("--- a/"):
            continue
        path = lines[0].removeprefix("--- a/").strip()
        if path not in targets:
            continue
        if len(lines) < 2 or lines[1].strip() != "+++ b/" + path or path in selected:
            raise SystemExit("HOLD: patch target mismatch")
        # A git diff preamble belongs to the next section, not this hunk.
        selected[path] = "".join(lines).split("\ndiff --git ", 1)[0].rstrip() + "\n"
    if set(selected) != targets:
        raise SystemExit("HOLD: missing patch target")
    return "".join(selected.values())


def stage_operational(here: Path, abi: Path, root: Path) -> Path:
    drivers = root / "drivers"
    drivers.mkdir()
    for name, digest in BASE_PINS.items():
        if sha256(here / name) != digest:
            raise SystemExit("HOLD: operational base pin mismatch: " + name)
        if not name.endswith(".patch"):
            shutil.copyfile(here / name, drivers / name)
    shutil.copyfile(abi, drivers / abi.name)
    steps = (
        ("nut-hidapi-continuous-73c4502.patch", {
            "drivers/apcmicrolink-hidapi-native.c", "drivers/apcmicrolink-hidapi-native.h",
            "drivers/apcmicrolink-hidapi-shared.c", "drivers/apcmicrolink-usb.h"}),
        ("nut-operational-health-v2.patch", {
            "drivers/apcmicrolink-hidapi-shared.c", "drivers/apcmicrolink-hidapi-session.h"}),
        ("nut-operational-cleanup-v2.patch", {
            "drivers/apcmicrolink-hidapi-native.c", "drivers/apcmicrolink-hidapi-shared.c",
            "drivers/apcmicrolink-hidapi-shared-host.h"}),
    )
    for index, (name, targets) in enumerate(steps):
        if index == 2:
            for filename, digest in OPERATIONAL_BASE_PINS.items():
                if sha256(drivers / filename) != digest:
                    raise SystemExit("HOLD: operational reconstruction mismatch: " + filename)
        patch = root / (str(index) + ".patch")
        patch.write_text(selected_patch((here / name).read_text(), targets))
        checked(["/usr/bin/patch", "--batch", "--forward", "--fuzz=0", "-p1",
                 "-d", str(root), "-i", str(patch)])
    return drivers


def audit_fake(binary: Path) -> None:
    undefined = checked(["/usr/bin/nm", "-u", str(binary)]).stdout
    defined = checked(["/usr/bin/nm", str(binary)]).stdout
    dependencies = checked(["/usr/bin/otool", "-L", str(binary)]).stdout
    dependency_lines = "\n".join(dependencies.splitlines()[1:])
    forbidden = ("libusb", "libhidapi", "IOKit", "CoreFoundation", "IOHID", "IOService",
                 "socket", "connect", "dlopen")
    if any(token.lower() in (undefined + dependency_lines).lower() for token in forbidden):
        raise SystemExit("HOLD: fake binary has hardware/network linkage\n"
                         + undefined + dependency_lines)
    for symbol in ("_hid_init", "_hid_enumerate", "_hid_open_path", "_hid_read_timeout",
                   "_hid_write", "_hid_get_report_descriptor", "_hid_close", "_hid_exit"):
        if symbol in undefined or not any(line.endswith(" " + symbol) for line in defined.splitlines()):
            raise SystemExit(f"HOLD: missing synthetic definition: {symbol}")


def run_with_cancellation(function: Callable[[], T]) -> T:
    """Keep supervising the owned child if the harness itself is interrupted."""
    previous = {}
    def cancel(_signal, _frame):
        CANCEL_EVENT.set()
    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, cancel)
        return function()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def main() -> int:
    return run_with_cancellation(main_body)


def main_body() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidapi-source", type=Path, required=True)
    parser.add_argument("--abi-header", type=Path, required=True)
    parser.add_argument("--operational-v2", action="store_true",
                        help="reconstruct the operational guard and apply its isolated cleanup patch")
    parser.add_argument("--link-native-only", action="store_true",
                        help="also compile/link authentic mac/hid.c; NEVER execute that binary")
    args = parser.parse_args()
    source_root = args.hidapi_source.resolve(strict=True)
    abi = args.abi_header.resolve(strict=True)
    if abi.name != "apcmicrolink-usb.h" or sha256(abi) != ABI_PIN:
        raise SystemExit("HOLD: pinned NUT ABI header mismatch")
    required_pins = PINS if args.link_native_only else {k: v for k, v in PINS.items() if k != "mac/hid.c"}
    for relative, digest in required_pins.items():
        if sha256(source_root / relative) != digest:
            raise SystemExit(f"HOLD: authentic HIDAPI source mismatch: {relative}")

    here = Path(__file__).resolve().parent
    adapter = here / "apcmicrolink-hidapi-native.c"
    test = here / "test_hidapi_native.c"
    descriptor = here / "apcmicrolink-hid-descriptor-checked.c"
    shared = here / "apcmicrolink-hidapi-shared.c"
    inputs = [adapter, here / "apcmicrolink-hidapi-native.h", test, descriptor,
              here / "apcmicrolink-hid-descriptor-checked.h", shared,
              here / "apcmicrolink-hidapi-shared-host.h", here / "apcmicrolink-hidapi-session.h",
              here / "process_deadline.py", abi,
              *(source_root / name for name in required_pins)]
    if args.operational_v2:
        inputs.extend(here / name for name in (*BASE_PINS, "nut-operational-cleanup-v2.patch"))
    before = {path: sha256(path) for path in inputs}
    flags = ["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-H",
             "-I", str(source_root / "hidapi"), "-I", str(source_root / "mac"),
             "-I", str(abi.parent)]
    with tempfile.TemporaryDirectory(prefix="hidapi-native-fake-") as temporary:
        compiled_abi = abi
        if args.operational_v2:
            drivers = stage_operational(here, abi, Path(temporary))
            adapter, descriptor, shared = (drivers / path.name for path in (adapter, descriptor, shared))
            compiled_abi = drivers / abi.name
            # Copy the test beside staged quoted headers to avoid accidentally
            # taking the unpatched host/session header from the source tree.
            shutil.copyfile(test, drivers / test.name)
            test = drivers / test.name
            flags.extend(["-DMLINK_HIDAPI_OPERATIONAL_V2=1", "-I", str(drivers)])
            flags[flags.index(str(abi.parent))] = str(drivers)
        fake_binary = Path(temporary) / "synthetic-native-binding"
        built = checked([*flags, "-DMLINK_HIDAPI_SHARED_TEST", str(adapter), str(descriptor),
                         str(shared), str(test), "-o", str(fake_binary)])
        for header in (compiled_abi, source_root / "hidapi/hidapi.h", source_root / "mac/hidapi_darwin.h"):
            if str(header) not in built.stderr:
                raise SystemExit(f"HOLD: compiler trace missing pinned header: {header.name}")
        audit_fake(fake_binary)
        result = checked([str(fake_binary)], timeout=10)
        print(result.stdout, end="")
        print(result.stderr, end="")
        if args.link_native_only:
            native_binary = Path(temporary) / "NATIVE_LINK_ONLY_DO_NOT_RUN"
            # Compile and link the authentic mac backend only. This path never
            # passes native_binary to a process execution command.
            linked = checked([*flags, "-Wno-deprecated-declarations",
                              "-DMLINK_HIDAPI_NATIVE_LINK_ONLY", str(adapter), str(descriptor),
                              str(test), str(source_root / "mac/hid.c"),
                              "-framework", "IOKit", "-framework", "CoreFoundation",
                              "-o", str(native_binary)])
            if str(source_root / "mac/hidapi_darwin.h") not in linked.stderr:
                raise SystemExit("HOLD: native link did not trace authentic Darwin header")
            definitions = checked(["/usr/bin/nm", str(native_binary)]).stdout
            dependencies = checked(["/usr/bin/otool", "-L", str(native_binary)]).stdout
            if not any(line.endswith(" _hid_open_path") for line in definitions.splitlines()):
                raise SystemExit("HOLD: native link is missing the authentic HIDAPI implementation")
            if "/IOKit.framework/" not in dependencies or "/CoreFoundation.framework/" not in dependencies:
                raise SystemExit("HOLD: native link is missing expected macOS frameworks")
            print("PASS authentic mac/hid.c compile/link only; native executable NOT_RUN")
        else:
            print("NOT_RUN authentic mac/hid.c compile/link (explicit --link-native-only required)")

    if any(sha256(path) != digest for path, digest in before.items()):
        raise SystemExit("HOLD: source changed during the replay; result is not pinned")
    for path in inputs[:7]:
        print(f"SHA-256 {path.name}: {before[path]}")
    print(f"HIDAPI 0.15.0 header SHA-256: {PINS['hidapi/hidapi.h']}")
    print(f"Darwin header SHA-256: {PINS['mac/hidapi_darwin.h']}")
    print(f"NUT ABI header SHA-256: {ABI_PIN}")
    if args.operational_v2:
        print(f"Operational ABI after reconstruction SHA-256: {OPERATIONAL_ABI_PIN}")
    print("Only the fake executable ran; no native HIDAPI, device, driver or app was executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
