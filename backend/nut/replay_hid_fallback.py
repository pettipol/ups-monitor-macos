#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract and replay the pinned NUT HID fallback code without USB dependencies."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys


BASE_REVISION = "1a8369f8688443a500527059167d2f66ca27535f"
FIX_REVISION = "e0bb8ea64f7f8a140ad8908904186a05a324c295"
REVISIONS = {
    BASE_REVISION: "base",
    FIX_REVISION: "fix",
}
SOURCE_SHA256 = {
    BASE_REVISION: "6e35c6fdbd6a60abbf76f70d638079f0fcf710c07105ec717f52e8c4b1cd96be",
    FIX_REVISION: "5f4073e7597ce7b5f2fb2f9b2b3ebc49278eb78d29ec5e09b999896112a19a21",
}
SOURCE_RELATIVE_PATH = Path("drivers/apcmicrolink-usb.c")
GENERATED_NAME = "hid_fallback_replay_generated.c"


class ReplayError(Exception):
    pass


def git_output(source_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReplayError("could not verify the local source checkout") from error
    return result.stdout.strip()


def verify_source(source_root: Path, expected_revision: str) -> tuple[str, Path, bytes]:
    if expected_revision not in REVISIONS:
        raise ReplayError("expected revision must be one of the two pinned full hashes")

    resolved = source_root.resolve(strict=True)
    if not resolved.is_dir():
        raise ReplayError("source root is not a directory")

    actual_revision = git_output(resolved, "rev-parse", "HEAD")
    if actual_revision != expected_revision:
        raise ReplayError("source HEAD does not match the requested pinned revision")
    if git_output(resolved, "status", "--porcelain", "--untracked-files=all"):
        raise ReplayError("source checkout must be clean; modified source is refused")

    source_file = resolved / SOURCE_RELATIVE_PATH
    if not source_file.is_file() or source_file.is_symlink():
        raise ReplayError("expected tracked HID source file is missing or is a symlink")
    source_bytes = source_file.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    if digest != SOURCE_SHA256[actual_revision]:
        raise ReplayError("HID source file SHA-256 does not match the pinned source blob")
    return REVISIONS[actual_revision], source_file, source_bytes


def take_region(source: str, start_marker: str, end_marker: str, label: str) -> str:
    start = source.find(start_marker)
    if start < 0:
        raise ReplayError(f"could not locate upstream {label} start marker")
    end = source.find(end_marker, start + len(start_marker))
    if end < 0:
        raise ReplayError(f"could not locate upstream {label} end marker")
    return source[start:end].rstrip() + "\n"


def extract_translation_unit(source_bytes: bytes, revision: str) -> str:
    source = source_bytes.decode("utf-8")
    declarations_start = source.find(
        "typedef struct {\n\tint report_id;",
        source.find("/* Standard HID Power/Battery System Page"),
    )
    if declarations_start < 0:
        raise ReplayError("could not locate upstream fallback declarations")
    declarations_end = source.find("\n/* Output/Input reports are 64 bytes", declarations_start)
    if declarations_end < 0:
        raise ReplayError("could not locate end of upstream fallback declarations")
    declarations = source[declarations_start:declarations_end].rstrip() + "\n"

    extract_bits = take_region(
        source,
        "static unsigned long hid_extract_bits(",
        "\n/* Decode the standard HID PDC fallback fields",
        "hid_extract_bits",
    )
    decode_fallback = take_region(
        source,
        "static void microlink_usb_try_decode_fallback(",
        "\n#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)",
        "microlink_usb_try_decode_fallback",
    )
    get_fallback = take_region(
        source,
        "int microlink_usb_get_hid_fallback(",
        "\nint microlink_usb_hid_fallback_supported(",
        "microlink_usb_get_hid_fallback",
    )
    license_start = source.find(" * Copyright (C)\n")
    if license_start < 0:
        raise ReplayError("could not locate upstream copyright and GPL notice")
    license_end = source.find("\n */", license_start)
    if license_end < 0:
        raise ReplayError("could not locate end of upstream copyright and GPL notice")
    upstream_license = "/*\n" + source[license_start : license_end + len("\n */")] + "\n\n"

    unit = upstream_license + (
        "/* SPDX-License-Identifier: GPL-2.0-or-later */\n"
        f"/* Exact upstream excerpts from NUT {revision}; replay-only TU. */\n"
        "#include <stddef.h>\n"
        "#include <stdint.h>\n"
        "#include <time.h>\n"
        "#include <math.h>\n\n"
        "/* microlink_now is provided by the controlled test clock. */\n\n"
        + declarations
        + "\n"
        + extract_bits
        + "\n"
        + decode_fallback
        + "\n"
        + get_fallback
    )

    forbidden = (
        "libusb_",
        "usb_interrupt_transfer",
        "usb_interrupt_read",
        "usb_interrupt_write",
        "usb_control_msg",
        "usb_open(",
        "usb_claim_interface(",
    )
    if any(token in unit for token in forbidden):
        raise ReplayError("extracted translation unit contains a forbidden I/O/concurrency token")
    expected_symbols = (
        "static unsigned long hid_extract_bits(",
        "static void microlink_usb_try_decode_fallback(",
        "int microlink_usb_get_hid_fallback(",
    )
    if any(unit.count(symbol) != 1 for symbol in expected_symbols):
        raise ReplayError("extracted translation unit does not contain the exact expected functions")
    return unit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument(
        "--action", choices=("extract", "compile", "run"), default="extract"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        label, _source_file, source_bytes = verify_source(
            args.source_root, args.expected_revision
        )
        repository_root = Path(__file__).resolve().parents[2]
        if args.scratch.is_symlink():
            raise ReplayError("scratch root must not be a symlink")
        scratch_root = args.scratch.resolve()
        source_root = args.source_root.resolve(strict=True)
        try:
            scratch_root.relative_to(repository_root)
        except ValueError:
            pass
        else:
            raise ReplayError("scratch output must be outside the repository")
        try:
            scratch_root.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise ReplayError("scratch output must be outside the source checkout")

        variant_dir = scratch_root / label
        variant_dir.mkdir(parents=True, exist_ok=False)
        generated_path = variant_dir / GENERATED_NAME
        generated_unit = extract_translation_unit(source_bytes, args.expected_revision)
        with generated_path.open("x", encoding="utf-8") as generated_file:
            generated_file.write(generated_unit)
        print(f"extracted exact {label} fallback source to {generated_path}")
        if args.action == "extract":
            return 0

        project_root = repository_root
        test_source = project_root / "backend/nut/test_hid_fallback_replay.c"
        binary_path = variant_dir / "test_hid_fallback_replay"
        is_fix = "1" if label == "fix" else "0"
        command = [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DWITH_LIBUSB_1_0=0",
            f"-DREPLAY_EXPECT_FIX={is_fix}",
            "-I",
            str(variant_dir),
            str(test_source),
            "-o",
            str(binary_path),
        ]
        subprocess.run(command, check=True)
        print("replay C test compiled; no NUT driver or USB API is linked")
        if args.action == "run":
            subprocess.run([str(binary_path)], check=True)
        return 0
    except (OSError, ReplayError, subprocess.CalledProcessError) as error:
        print(f"replay preparation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
