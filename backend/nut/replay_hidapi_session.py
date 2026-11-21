#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build and run isolated synthetic production-session lifecycle scenarios."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

ABI_SHA256 = "b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29"
HEADER_PINS = {
    "hidapi/hidapi.h": "c9cef28c53a13a9403e54d5a8a099d51afff119ab04094df89356df0833a822e",
    "mac/hidapi_darwin.h": "48854f6f6b612a90291c3de83a5755c2ed8642da173151a41377090821c39187",
}
SCENARIOS = (
    "no-prepare", "invalid-config", "prepare-one-shot", "guard-stop", "guard-clock",
    "sequence", "open-failure", "descriptor-error", "descriptor-stop",
    "descriptor-invalid", "reentrant-read", "reentrant-write",
    "reentrant-close", "close-failure-stop", "close-failure-clock", "dispose-failure",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def checked(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    result = run(command, timeout)
    if result.returncode:
        raise SystemExit(
            f"HOLD: command failed ({result.returncode}): {command[0]}\n"
            + result.stdout + result.stderr
        )
    return result


def audit_fake(binary: Path, *, native_symbols: bool = True) -> None:
    undefined = checked(["/usr/bin/nm", "-u", str(binary)]).stdout
    defined = checked(["/usr/bin/nm", str(binary)]).stdout
    dependencies = checked(["/usr/bin/otool", "-L", str(binary)]).stdout
    dependency_lines = "\n".join(dependencies.splitlines()[1:])
    linked = (undefined + dependency_lines).lower()
    forbidden = ("libusb", "libhidapi", "iokit", "corefoundation", "iohid",
                 "ioservice", "socket", "connect", "dlopen")
    if any(token in linked for token in forbidden):
        raise SystemExit("HOLD: fake binary has hardware/network linkage\n" + linked)
    if "mlink_shared_test_bind" in defined or "mlink_shared_test_unbind" in defined:
        raise SystemExit("HOLD: production candidate binary exports test injection")
    if not native_symbols:
        if any(symbol in defined for symbol in (
            "mlink_shared_prepare_native", "mlink_shared_finish_native", "mlink_hidapi_native_",
        )):
            raise SystemExit("HOLD: default OFF binary exports native candidate functionality")
        return
    required = (
        "_hid_init", "_hid_enumerate", "_hid_open_path", "_hid_read_timeout",
        "_hid_write", "_hid_get_report_descriptor", "_hid_close", "_hid_exit",
        "_hid_darwin_set_open_exclusive", "_hid_darwin_get_open_exclusive",
    )
    for symbol in required:
        if symbol in undefined or not any(line.endswith(" " + symbol) for line in defined.splitlines()):
            raise SystemExit(f"HOLD: missing synthetic HIDAPI definition: {symbol}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidapi-source", required=True, type=Path)
    parser.add_argument("--abi-header", required=True, type=Path)
    args = parser.parse_args()
    source_root = args.hidapi_source.resolve(strict=True)
    abi = args.abi_header.resolve(strict=True)
    if abi.name != "apcmicrolink-usb.h" or sha256(abi) != ABI_SHA256:
        raise SystemExit("HOLD: pinned NUT ABI header missing or hash mismatch")
    for relative, expected in HEADER_PINS.items():
        if sha256(source_root / relative) != expected:
            raise SystemExit(f"HOLD: pinned HIDAPI 0.15.0 header mismatch: {relative}")

    here = Path(__file__).resolve().parent
    sources = (
        here / "apcmicrolink-hidapi-shared.c",
        here / "apcmicrolink-hidapi-native.c",
        here / "apcmicrolink-hid-descriptor-checked.c",
        here / "test_hidapi_session.c",
    )
    pinned_inputs = (
        *sources,
        here / "apcmicrolink-hidapi-native.h",
        here / "apcmicrolink-hidapi-session.h",
        here / "apcmicrolink-hidapi-shared-host.h",
        here / "apcmicrolink-hid-descriptor-checked.h",
        abi,
        source_root / "hidapi/hidapi.h",
        source_root / "mac/hidapi_darwin.h",
        Path(__file__).resolve(),
    )
    before = {path: sha256(path) for path in pinned_inputs}
    compiler = Path("/usr/bin/clang")
    if not compiler.is_file():
        raise SystemExit("HOLD: required compiler /usr/bin/clang is absent")
    base = [str(compiler), "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-H",
            "-I", str(source_root / "hidapi"), "-I", str(source_root / "mac"),
            "-I", str(abi.parent)]
    with tempfile.TemporaryDirectory(prefix="hidapi-session-fake-") as temporary:
        default_binary = Path(temporary) / "candidate-default-off"
        checked([*base, str(sources[0]), str(sources[3]), "-o", str(default_binary)], timeout=60)
        audit_fake(default_binary, native_symbols=False)
        default_result = checked([str(default_binary)], timeout=10)
        print(default_result.stdout, end="")
        print(default_result.stderr, end="")

        binary = Path(temporary) / "synthetic-session"
        build = checked([
            *base, "-DMLINK_HIDAPI_NATIVE_CANDIDATE", *(str(path) for path in sources),
            "-o", str(binary),
        ], timeout=60)
        for include in (abi, source_root / "hidapi/hidapi.h",
                        source_root / "mac/hidapi_darwin.h"):
            if os.path.realpath(include) not in build.stderr:
                raise SystemExit(f"HOLD: compiler trace omitted pinned header {include.name}")
        audit_fake(binary)

        for scenario in SCENARIOS:
            result = checked([str(binary), scenario], timeout=10)
            marker = f"PASS scenario={scenario} "
            if sum(line.startswith(marker) for line in result.stdout.splitlines()) != 1:
                raise SystemExit(f"HOLD: scenario did not report its completed assertions: {scenario}")
            print(result.stdout, end="")
            print(result.stderr, end="")

        conflict = run([
            *base, "-DMLINK_HIDAPI_NATIVE_CANDIDATE", "-DMLINK_HIDAPI_SHARED_TEST",
            "-fsyntax-only", str(sources[0]),
        ], timeout=30)
        diagnostic = conflict.stdout + conflict.stderr
        if conflict.returncode == 0 or "mutually exclusive" not in diagnostic:
            raise SystemExit("HOLD: candidate/test macro combination did not fail closed\n"
                             + diagnostic)
        print("PASS candidate and test macros are mutually exclusive")
        print(f"PASS isolated one-shot scenarios={len(SCENARIOS)}")

    if any(sha256(path) != digest for path, digest in before.items()):
        raise SystemExit("HOLD: pinned input changed during replay")
    for path in (*sources, here / "apcmicrolink-hidapi-session.h", Path(__file__).resolve()):
        print(f"SHA-256 {path.name}: {before[path]}")
    print(f"HIDAPI 0.15.0 hidapi.h SHA-256: {HEADER_PINS['hidapi/hidapi.h']}")
    print(f"HIDAPI 0.15.0 Darwin header SHA-256: {HEADER_PINS['mac/hidapi_darwin.h']}")
    print(f"NUT ABI header SHA-256: {ABI_SHA256}")
    print("Only synthetic HIDAPI symbols ran; no authentic HIDAPI, device, driver or app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
