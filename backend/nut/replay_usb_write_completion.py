#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replay the exact pinned APC Microlink USB write function offline."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys


PIN = "73c4502191d025e35122463986a80c676e734b04"
SOURCE = Path("drivers/apcmicrolink-usb.c")
USB_COMMON = Path("drivers/usb-common.h")
BASELINE_SHA256 = "87b4554132782ee7104d4d18f2204a573d7f68e580129e2280df80fa6cc3fb4e"
CANDIDATE_SHA256 = "6b81bac1498ce4868a96bca9ee98682155cc1f063eb36c72c4cb29c21bcf01f9"
USB_COMMON_SHA256 = "6a5cee01ca1b0a0d31992983f061d55e62ca8da37d4559b800a228ebb957325f"
EXPECTED_RED = (
    "FAIL zero-byte short write rejected",
    "FAIL one-byte short write rejected",
    "FAIL 63-byte short write rejected",
    "FAIL unexpected oversized completion rejected",
)


class ReplayError(Exception):
    pass


def git_output(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReplayError("could not verify source checkout HEAD") from error
    return result.stdout.rstrip("\n")


def read_sources(root: Path, expected_usb_hash: str, label: str) -> dict[Path, bytes]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or git_output(resolved, "rev-parse", "HEAD") != PIN:
        raise ReplayError(f"{label} checkout HEAD must equal the pinned NUT revision")
    result: dict[Path, bytes] = {}
    for relative, expected_hash in ((SOURCE, expected_usb_hash), (USB_COMMON, USB_COMMON_SHA256)):
        source = resolved / relative
        if source.is_symlink() or not source.is_file():
            raise ReplayError(f"{label} source is missing or is a symlink: {relative}")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise ReplayError(f"{label} source SHA-256 does not match its exact pin: {relative}")
        result[relative] = content
    return result


def extract_comment(source: str, label: str) -> str:
    if not source.startswith("/*"):
        raise ReplayError(f"{label} file header comment is missing")
    end = source.find("*/", 2)
    if end < 0:
        raise ReplayError(f"{label} file header comment is incomplete")
    return source[: end + len("*/")] + "\n\n"


def extract_unit(sources: dict[Path, bytes]) -> str:
    source = sources[SOURCE].decode("utf-8")
    common = sources[USB_COMMON].decode("utf-8")
    start_marker = "int microlink_usb_send_bytes(const unsigned char *buf, size_t len)"
    end_marker = "\n/* Extract a little-endian, LSB-first-packed bit field"
    if source.count(start_marker) != 1:
        raise ReplayError("expected exactly one pinned microlink_usb_send_bytes function")
    start = source.index(start_marker)
    end = source.find(end_marker, start)
    if end < 0:
        raise ReplayError("could not find the pinned end marker after send function")
    send_function = source[start:end].rstrip() + "\n"
    wrapper_start = " static inline  int usb_interrupt_write(usb_dev_handle *dev, int ep,"
    wrapper_end = "\n static inline  int usb_bulk_read("
    if common.count(wrapper_start) != 1:
        raise ReplayError("expected exactly one pinned NUT usb_interrupt_write wrapper")
    wrapper_begin = common.index(wrapper_start)
    wrapper_finish = common.find(wrapper_end, wrapper_begin)
    if wrapper_finish < 0:
        raise ReplayError("could not find the pinned end marker after USB wrapper")
    wrapper = common[wrapper_begin:wrapper_finish].strip() + "\n"
    if send_function.count(start_marker) != 1 or wrapper.count("ret = libusb_interrupt_transfer(") != 1:
        raise ReplayError("extracted unit does not contain the exact send function and wrapper")
    return (
        extract_comment(source, "apcmicrolink-usb.c")
        + extract_comment(common, "usb-common.h")
        + wrapper
        + "\n"
        + send_function
    )


def run_harness(function: str, scratch: Path, test_source: Path, mode: str) -> int:
    output_dir = scratch / mode
    output_dir.mkdir(parents=True, exist_ok=False)
    generated = output_dir / "usb_write_completion_generated.c"
    generated.write_text(function, encoding="utf-8")
    if mode == "extract":
        print(f"extracted fenced function to {generated}")
        return 0

    binary = output_dir / "test_usb_write_completion"
    command = [
        "cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
        f"-DUSB_WRITE_CANDIDATE={1 if mode == 'green' else 0}",
        "-I", str(output_dir), str(test_source), "-o", str(binary),
    ]
    subprocess.run(command, check=True, timeout=30)
    print("synthetic harness compiled with UBSan; no libusb or NUT driver linked")

    symbols = subprocess.run(
        ["nm", "-u", str(binary)], check=True, capture_output=True, text=True, timeout=30
    ).stdout
    if any(token in symbols for token in ("libusb", "usb_interrupt_transfer", "usb_interrupt_write")):
        raise ReplayError("synthetic harness unexpectedly has an unresolved USB symbol")
    print("undefined-symbol inspection found no USB/libusb dependency")

    result = subprocess.run([str(binary)], check=False, capture_output=True, text=True, timeout=30)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if mode == "red":
        expected = (*EXPECTED_RED, f"{len(EXPECTED_RED)} validation check(s) failed")
        if result.returncode != 1 or result.stderr or tuple(result.stdout.splitlines()) != expected:
            raise ReplayError("baseline did not produce the exact controlled RED checks")
        print("RED reproduced: only short/unexpected completion checks fail on baseline")
        return 0
    if result.returncode != 0 or result.stderr:
        raise ReplayError(f"candidate harness returned {result.returncode}")
    if result.stdout.strip() != "all USB write completion checks passed":
        raise ReplayError("candidate harness emitted unexpected output")
    print("candidate GREEN: all synthetic checks pass")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--mode", choices=("extract", "red", "green"), required=True)
    args = parser.parse_args()
    try:
        baseline = read_sources(args.baseline_root, BASELINE_SHA256, "baseline")
        candidate = read_sources(args.candidate_root, CANDIDATE_SHA256, "candidate")
        repository_root = Path(__file__).resolve().parents[2]
        if args.scratch.is_symlink():
            raise ReplayError("scratch root must not be a symlink")
        scratch = args.scratch.resolve()
        for forbidden_root in (
            repository_root,
            args.baseline_root.resolve(strict=True),
            args.candidate_root.resolve(strict=True),
        ):
            try:
                scratch.relative_to(forbidden_root)
            except ValueError:
                continue
            raise ReplayError("scratch output must be outside repository and source checkouts")

        selected = baseline if args.mode == "red" else candidate
        function = extract_unit(selected)
        test_source = Path(__file__).with_name("test_usb_write_completion.c")
        return run_harness(function, scratch, test_source, args.mode)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ReplayError) as error:
        print(f"USB write replay failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
