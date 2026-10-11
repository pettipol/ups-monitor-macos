#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check preservation boundaries for the guarded NUT rebase (static only)."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

import replay_hid_fallback as replay


MERGED_REVISION = "73c4502191d025e35122463986a80c676e734b04"
RECEIVE_PATH = Path("drivers/apcmicrolink.c")
USB_SOURCE_PATH = Path("drivers/apcmicrolink-usb.c")
MAPS_PATH = Path("drivers/apcmicrolink-maps.c")
USB_HEADER_PATH = Path("drivers/apcmicrolink-usb.h")
GUARDED_POLICY_PATH = Path("drivers/nut-guarded-policy.h")
PINNED_UNCHANGED_SHA256 = {
    MAPS_PATH: "149cf260563294b9c864d9efb35388ed5524f20ce41fac113f10de6f60841a35",
    USB_HEADER_PATH: "2998edbfed84914339f3cdf3f0f0bb501e165a27a9628f2e355635a06e2ab34c",
}
EXPECTED_PATCHED_PATHS = {
    "drivers/Makefile.am",
    "drivers/apcmicrolink-usb.c",
    "drivers/apcmicrolink.c",
    "drivers/libusb1.c",
    "drivers/main.c",
    "drivers/nut-guarded-policy.h",
}
DEADLINE_BLOCK = (
    "#ifdef WITH_USB\n"
    "\t\tif (is_usb && microlink_guard_deadline_expired()) {\n"
    "\t\t\treturn 0;\n"
    "\t\t}\n"
    "#endif /* WITH_USB */\n\n"
)
EXTRACT_MARKER = "\t\tif (microlink_try_extract_frame(frame, &framelen)) {"
RECEIVE_END_MARKER = "\nstatic int microlink_poll_once("


class CheckError(Exception):
    pass


def git_output(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CheckError("could not verify a local pinned source checkout") from error
    return result.stdout.rstrip()


def tracked_status_paths(root: Path) -> set[str]:
    status = git_output(root, "status", "--porcelain", "--untracked-files=all")
    paths: set[str] = set()
    for line in status.splitlines():
        if len(line) < 4:
            raise CheckError("unrecognized git status output")
        path = line[3:]
        if " -> " in path:
            raise CheckError("renamed paths are not accepted")
        paths.add(path)
    return paths


def read_pinned_files(root: Path) -> dict[Path, bytes]:
    paths = (RECEIVE_PATH, USB_SOURCE_PATH, MAPS_PATH, USB_HEADER_PATH)
    result: dict[Path, bytes] = {}
    for relative in paths:
        candidate = root / relative
        if not candidate.is_file() or candidate.is_symlink():
            raise CheckError(f"missing or symlinked source: {relative}")
        result[relative] = candidate.read_bytes()
    return result


def one_region(source: str, start: str, end: str, label: str) -> tuple[int, int, str]:
    if source.count(start) != 1:
        raise CheckError(f"ambiguous or missing {label} start marker")
    start_at = source.find(start)
    if source.count(end) != 1:
        raise CheckError(f"ambiguous or missing {label} end marker")
    end_at = source.find(end, start_at + len(start))
    if end_at < 0:
        raise CheckError(f"could not bound {label}")
    return start_at, end_at, source[start_at:end_at]


def receive_function(source: str) -> tuple[int, int, str]:
    return one_region(
        source,
        "static int microlink_receive_once(void)\n{",
        RECEIVE_END_MARKER,
        "microlink_receive_once",
    )


def padding_function(source: str) -> tuple[int, int, str]:
    return one_region(
        source,
        "size_t microlink_usb_drop_report_padding(void)\n{",
        "\n/* Per-call synchronous read:",
        "microlink_usb_drop_report_padding",
    )


def validate_sources(pristine: dict[Path, bytes], patched: dict[Path, bytes], replay: object) -> None:
    for relative in (MAPS_PATH, USB_HEADER_PATH):
        if pristine[relative] != patched[relative]:
            raise CheckError(f"upstream-preservation mismatch: {relative}")
        digest = hashlib.sha256(pristine[relative]).hexdigest()
        if digest != PINNED_UNCHANGED_SHA256[relative]:
            raise CheckError(f"pristine SHA-256 does not match the pin: {relative}")

    pristine_receive = pristine[RECEIVE_PATH].decode("utf-8")
    patched_receive = patched[RECEIVE_PATH].decode("utf-8")
    _, _, p_body = receive_function(pristine_receive)
    _, _, q_body = receive_function(patched_receive)
    if p_body.count(EXTRACT_MARKER) != 1 or q_body.count(EXTRACT_MARKER) != 1:
        raise CheckError("frame extraction marker is ambiguous")
    expected_body = p_body.replace(EXTRACT_MARKER, DEADLINE_BLOCK + EXTRACT_MARKER, 1)
    if q_body != expected_body:
        raise CheckError("receive function differs beyond the exact pre-extract deadline gate")
    if q_body.find(DEADLINE_BLOCK) > q_body.find(EXTRACT_MARKER):
        raise CheckError("deadline gate must precede frame extraction")
    pristine_usb = pristine[USB_SOURCE_PATH].decode("utf-8")
    patched_usb = patched[USB_SOURCE_PATH].decode("utf-8")
    _, _, pristine_padding = padding_function(pristine_usb)
    _, _, patched_padding = padding_function(patched_usb)
    if pristine_padding != patched_padding:
        raise CheckError("upstream report-padding function changed")
    pristine_unit = replay.extract_translation_unit(
        {path: pristine[path] for path in replay.SOURCE_RELATIVE_PATHS}, "merged"
    )
    patched_unit = replay.extract_translation_unit(
        {path: patched[path] for path in replay.SOURCE_RELATIVE_PATHS}, "merged"
    )
    if pristine_unit != patched_unit:
        raise CheckError("pinned HID fallback decoder/getter/reset/publisher changed")


def mutate_receive(root_files: dict[Path, bytes], transform) -> dict[Path, bytes]:
    changed = dict(root_files)
    source = changed[RECEIVE_PATH].decode("utf-8")
    start, end, body = receive_function(source)
    changed[RECEIVE_PATH] = (source[:start] + transform(body) + source[end:]).encode("utf-8")
    return changed


def verify_mutations(pristine: dict[Path, bytes], patched: dict[Path, bytes], replay: object) -> None:
    def must_fail(label: str, candidate: dict[Path, bytes]) -> None:
        if candidate == patched:
            raise CheckError(f"mutation self-check was a no-op: {label}")
        try:
            validate_sources(pristine, candidate, replay)
        except CheckError:
            return
        raise CheckError(f"mutation self-check survived: {label}")

    must_fail(
        "deadline removed",
        mutate_receive(patched, lambda body: body.replace(DEADLINE_BLOCK, "", 1)),
    )
    must_fail(
        "deadline moved after extraction",
        mutate_receive(
            patched,
            lambda body: body.replace(
                DEADLINE_BLOCK + EXTRACT_MARKER,
                EXTRACT_MARKER + "\n" + DEADLINE_BLOCK.rstrip(),
                1,
            ),
        ),
    )
    must_fail(
        "padding hook removed",
        mutate_receive(
            patched,
            lambda body: body.replace(
                "\t\t\tif (is_usb) {\n"
                "\t\t\t\tmicrolink_usb_drop_report_padding();\n"
                "\t\t\t}\n",
                "",
                1,
            ),
        ),
    )
    altered_padding = dict(patched)
    original_padding = altered_padding[USB_SOURCE_PATH]
    altered_padding[USB_SOURCE_PATH] = original_padding.replace(
        b"in_report[i] != 0x00", b"in_report[i] == 0x00", 1
    )
    must_fail("padding predicate changed", altered_padding)

    altered_map = dict(patched)
    altered_map[MAPS_PATH] = altered_map[MAPS_PATH].replace(b'"CAL"', b'"OL"', 1)
    must_fail("calibration map changed", altered_map)

    altered_freshness = dict(patched)
    original = altered_freshness[USB_SOURCE_PATH]
    altered_freshness[USB_SOURCE_PATH] = original.replace(
        b"fb_ac_present_update == 0", b"fb_ac_present_update != 0", 1
    )
    if altered_freshness[USB_SOURCE_PATH] == original:
        raise CheckError("could not construct freshness mutation")
    must_fail("fallback freshness predicate changed", altered_freshness)


def verify_roots(pristine_root: Path, patched_root: Path) -> tuple[dict[Path, bytes], dict[Path, bytes]]:
    pristine_root = pristine_root.resolve(strict=True)
    patched_root = patched_root.resolve(strict=True)
    if git_output(pristine_root, "rev-parse", "HEAD") != MERGED_REVISION:
        raise CheckError("pristine HEAD does not match the pinned merged revision")
    pristine_paths = tracked_status_paths(pristine_root)
    if pristine_paths:
        raise CheckError("pristine checkout must be clean")
    _, pristine_replay_files = replay.verify_source(pristine_root, MERGED_REVISION)
    pristine = read_pinned_files(pristine_root)
    for path, content in pristine_replay_files.items():
        if pristine[path] != content:
            raise CheckError("pinned replay source differs from pristine source")

    if git_output(patched_root, "rev-parse", "HEAD") != MERGED_REVISION:
        raise CheckError("patched HEAD does not match the pinned merged revision")
    if tracked_status_paths(patched_root) != EXPECTED_PATCHED_PATHS:
        raise CheckError("patched tree changes differ from the six expected guard paths")
    patched = read_pinned_files(patched_root)
    policy_path = patched_root / GUARDED_POLICY_PATH
    if not policy_path.is_file() or policy_path.is_symlink():
        raise CheckError("guard policy header is missing or symlinked")
    return pristine, patched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pristine-root", type=Path, required=True)
    parser.add_argument("--patched-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        pristine, patched = verify_roots(args.pristine_root, args.patched_root)
        validate_sources(pristine, patched, replay)
        verify_mutations(pristine, patched, replay)
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("guarded merged rebase preservation checks: PASS (static source only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
