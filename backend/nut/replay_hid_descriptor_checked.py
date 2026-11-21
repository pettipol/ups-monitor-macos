#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile and run only the checked HID descriptor synthetic tests."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

PINNED_NUT = {
    "hidparser.c": "8294a17df65c9ed35b5ba482eb1c543a6f321fe951965bb071851bbc01f22216",
    "hidtypes.h": "4269271dae5b023b4bb6aec62c7b19edfa91b74dda7ad85cf755f7703100aedb",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nut-source", required=True, type=Path,
                        help="directory containing the pinned NUT drivers/hidparser.c and hidtypes.h")
    args = parser.parse_args()
    source_root = args.nut_source.resolve(strict=True)
    for name, expected in PINNED_NUT.items():
        path = source_root / name
        if not path.is_file() or sha256(path) != expected:
            raise SystemExit(f"HOLD: pinned NUT provenance mismatch: {path}")

    here = Path(__file__).resolve().parent
    implementation = here / "apcmicrolink-hid-descriptor-checked.c"
    test = here / "test_hid_descriptor_checked.c"
    compiler = Path("/usr/bin/clang")
    if not compiler.is_file():
        raise SystemExit("HOLD: required compiler /usr/bin/clang is absent")

    with tempfile.TemporaryDirectory(prefix="hid-desc-checked-") as tmp:
        binary = Path(tmp) / "hid-descriptor-checked-test"
        command = [str(compiler), "-std=c11", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                   str(implementation), str(test), "-o", str(binary)]
        build = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if build.returncode:
            print(build.stdout, end="")
            print(build.stderr, end="")
            return build.returncode
        run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
        print(run.stdout, end="")
        print(run.stderr, end="")
        if run.returncode:
            return run.returncode
        undefined = subprocess.run(["/usr/bin/nm", "-u", str(binary)],
                                   capture_output=True, text=True, timeout=10)
        dependencies = subprocess.run(["/usr/bin/otool", "-L", str(binary)],
                                      capture_output=True, text=True, timeout=10)
        dependency_lines = "\n".join(dependencies.stdout.splitlines()[1:])
        forbidden = ("libusb", "hidapi", "iokit", "iohid", "usbdevice", "hid_open",
                     "hid_enumerate", "socket", "connect", "dlopen")
        joined = (undefined.stdout + dependency_lines).lower()
        if undefined.returncode or dependencies.returncode or any(x in joined for x in forbidden):
            raise SystemExit("HOLD: unexpected hardware/network linkage\n" + joined)

    print("NUT hidparser.c SHA-256: " + PINNED_NUT["hidparser.c"])
    print("NUT hidtypes.h SHA-256: " + PINNED_NUT["hidtypes.h"])
    print("Checked parser SHA-256: " + sha256(implementation))
    print("Synthetic tests SHA-256: " + sha256(test))
    print("Scope: parser fixtures only; no USB/HID, device, driver, network, or app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
