#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile and run only the deterministic C fake transport tests."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

PINNED_HEADER_SHA256 = "b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abi-header", required=True, type=Path)
    args = parser.parse_args()
    header = args.abi_header.resolve(strict=True)
    if header.name != "apcmicrolink-usb.h" or sha256(header) != PINNED_HEADER_SHA256:
        raise SystemExit("HOLD: pinned ABI header missing or hash mismatch")

    here = Path(__file__).resolve().parent
    source = here / "apcmicrolink-hidapi-shared.c"
    test = here / "test_hidapi_shared_transport.c"
    compiler = Path("/usr/bin/clang")
    if not compiler.is_file():
        raise SystemExit("HOLD: required compiler /usr/bin/clang is absent")

    with tempfile.TemporaryDirectory(prefix="hidapi-shared-fake-") as tmp:
        sanitizer = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        for name, define in (("synthetic", "-DMLINK_HIDAPI_SHARED_TEST"), ("production", None)):
            binary = Path(tmp) / f"shared-transport-{name}"
            command = [str(compiler), "-std=c11", "-Wall", "-Wextra", "-Werror",
                       *sanitizer, "-H", "-I", str(header.parent)]
            if define:
                command.append(define)
            command.extend([str(source), str(test), "-o", str(binary)])
            build = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if build.returncode:
                print(build.stdout, end="")
                print(build.stderr, end="")
                return build.returncode
            included = os.path.realpath(str(header))
            if included not in build.stderr:
                raise SystemExit("HOLD: compiler trace did not include the pinned ABI header")
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            print(run.stdout, end="")
            print(run.stderr, end="")
            if run.returncode:
                return run.returncode
            if name == "production":
                nm = subprocess.run(["/usr/bin/nm", "-u", str(binary)],
                                    capture_output=True, text=True, timeout=10)
                defined = subprocess.run(["/usr/bin/nm", str(binary)],
                                         capture_output=True, text=True, timeout=10)
                deps = subprocess.run(["/usr/bin/otool", "-L", str(binary)],
                                      capture_output=True, text=True, timeout=10)
                dependency_lines = "\n".join(deps.stdout.splitlines()[1:])
                forbidden = ("libusb", "hidapi", "IOKit", "socket", "connect", "dlopen")
                if (nm.returncode or defined.returncode or deps.returncode
                    or "mlink_shared_test_bind" in defined.stdout
                    or any(word.lower() in (nm.stdout + dependency_lines).lower()
                           for word in forbidden)):
                    raise SystemExit("HOLD: unexpected hardware/network linkage in fail-closed binary\n"
                                     + nm.stdout + dependency_lines)

    print(f"ABI header SHA-256: {PINNED_HEADER_SHA256}")
    print(f"C backend SHA-256: {sha256(source)}")
    print(f"C fake-test SHA-256: {sha256(test)}")
    print("Scope: fake API only; no HIDAPI, device, driver, socket, app, or probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
