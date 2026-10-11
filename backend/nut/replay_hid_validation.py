#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replay exact pristine and patched NUT HID fallback excerpts offline."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

import replay_hid_fallback as replay


PIN = "73c4502191d025e35122463986a80c676e734b04"
UPSTREAM_USB = Path("drivers/apcmicrolink-usb.c")
UPSTREAM_PUBLISHER = Path("drivers/apcmicrolink.c")
SOURCES = (UPSTREAM_USB, UPSTREAM_PUBLISHER)
PATCHED_SHA256 = {
    UPSTREAM_USB: "12f7edde6e5da02372fffc24726c21dc56aa2b6de2c2eb85e5071499bb8ff3ff",
    UPSTREAM_PUBLISHER: "91e3921a8cfea955ffef0c1d38ada2ee48f2d3dc0c55e94d5c284766cd7c5e50",
}
FORBIDDEN = (
    "libusb_", "usb_interrupt_transfer", "usb_interrupt_read",
    "usb_interrupt_write", "usb_control_msg", "usb_open(",
    "usb_claim_interface(",
)
EXPECTED_RED = (
    "FAIL incomplete report ID-only unavailable",
    "FAIL failed getter leaves outputs untouched",
    "FAIL incomplete sibling does not refresh cache",
    "FAIL incomplete sibling keeps pair unavailable",
    "FAIL incomplete report preserves prior status cache and timestamp",
    "FAIL incomplete report cannot refresh prior status pair",
    "FAIL ID-only optional report preserves neutral missing values",
    "FAIL complete optional field updates independently",
    "FAIL partial straddling optional field preserves cache",
    "FAIL 32-bit partial report preserves cache",
    "FAIL rollback invalidates pair",
    "FAIL rollback clears both timestamps",
    "FAIL rollback leaves caller outputs untouched",
    "FAIL catch-up cannot resurrect old pair",
    "FAIL one new status report is insufficient",
    "FAIL publisher suppresses invalid status",
    "FAIL invalid fallback emits no events",
    "FAIL publisher suppresses status after rollback",
    "FAIL rollback emits no publisher events",
)


class ValidationError(Exception):
    pass


def output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.rstrip("\n")


def read_candidate(root: Path) -> dict[Path, bytes]:
    root = root.resolve(strict=True)
    if output(root, "rev-parse", "HEAD") != PIN:
        raise ValidationError("candidate HEAD must equal the pristine merged pin")
    changed = output(root, "diff", "--name-only", PIN, "--", *map(str, SOURCES)).splitlines()
    if changed != [str(UPSTREAM_USB)]:
        raise ValidationError("candidate must modify only the pinned USB source file")
    status = output(root, "status", "--porcelain", "--untracked-files=all")
    allowed = f" M {UPSTREAM_USB.as_posix()}"
    if status.splitlines() != [allowed]:
        raise ValidationError("candidate checkout contains unexpected staged or untracked changes")
    sources: dict[Path, bytes] = {}
    for relative in SOURCES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValidationError(f"candidate source missing or symlink: {relative}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != PATCHED_SHA256[relative]:
            raise ValidationError(f"candidate SHA-256 mismatch: {relative}")
        sources[relative] = content
    return sources


def validate_unit(unit: str, candidate: bool) -> None:
    if any(token in unit for token in FORBIDDEN):
        raise ValidationError("generated source contains a forbidden I/O token")
    required = (
        "static unsigned long hid_extract_bits(",
        "static void microlink_usb_try_decode_fallback(",
        "int microlink_usb_get_hid_fallback(",
        "static int microlink_publish_hid_fallback(void)",
    )
    if any(unit.count(symbol) != 1 for symbol in required):
        raise ValidationError("generated source does not contain expected exact excerpts")
    if candidate and unit.count("static int hid_field_fits_report(") != 1:
        raise ValidationError("candidate helper excerpt is missing")


def compile_and_run(unit: str, output_dir: Path, test_source: Path, mode: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=False)
    generated = output_dir / "hid_fallback_validation_generated.c"
    generated.write_text(unit, encoding="utf-8")
    if mode == "extract":
        print(f"extracted fenced source to {generated}")
        return 0
    binary = output_dir / "test_hid_fallback_validation"
    command = [
        "cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
        "-fno-sanitize-recover=undefined",
        "-DWITH_USB=1", "-DWITH_LIBUSB_1_0=0", "-I", str(output_dir),
        f"-DVALIDATION_CANDIDATE={1 if mode == 'green' else 0}",
        str(test_source), "-o", str(binary),
    ]
    subprocess.run(command, check=True)
    print("synthetic C harness compiled with UBSan; no NUT driver or USB API linked")
    result = subprocess.run([str(binary)], check=False, capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if mode == "red":
        expected_lines = (*EXPECTED_RED, f"{len(EXPECTED_RED)} validation check(s) failed")
        if (
            result.returncode != 1
            or result.stderr
            or tuple(result.stdout.splitlines()) != expected_lines
        ):
            raise ValidationError("baseline did not produce the exact expected controlled RED checks")
        print("RED reproduced: expected validation checks fail on pristine source")
        return 0
    if result.returncode != 0 or result.stderr:
        raise ValidationError(f"candidate C harness returned {result.returncode}")
    if result.stdout.strip() != "all HID fallback validation checks passed":
        raise ValidationError("candidate C harness emitted unexpected output")
    print("candidate GREEN: all synthetic checks pass")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--mode", choices=("extract", "red", "green"), required=True)
    args = parser.parse_args()
    try:
        _, pristine = replay.verify_source(args.source_root, PIN)
        candidate = read_candidate(args.candidate_root)
        repository_root = Path(__file__).resolve().parents[2]
        scratch = args.scratch
        if scratch.is_symlink():
            raise ValidationError("scratch root must not be a symlink")
        scratch = scratch.resolve()
        for forbidden_root in (repository_root, args.source_root.resolve(), args.candidate_root.resolve()):
            try:
                scratch.relative_to(forbidden_root)
            except ValueError:
                continue
            raise ValidationError("scratch output must be outside repository and source checkouts")
        source_label = "pristine" if args.mode == "red" else "candidate"
        files = pristine if args.mode == "red" else candidate
        unit = replay.extract_translation_unit(files, f"merged-{source_label}")
        validate_unit(unit, args.mode == "green")
        test_source = Path(__file__).with_name("test_hid_fallback_validation.c")
        return compile_and_run(unit, scratch / source_label, test_source, args.mode)
    except (OSError, subprocess.CalledProcessError, ValidationError) as error:
        print(f"validation replay failed: {error}", file=sys.stderr)
        return 2
    except replay.ReplayError as error:
        print(f"validation replay failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
