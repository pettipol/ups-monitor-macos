#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract pinned APC Microlink candidate functions for a private C fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


CONFIGURE = "configure.ac"
MAKEFILE = "drivers/Makefile.am"
DRIVER = "drivers/apcmicrolink.c"
MAIN = "drivers/main.c"
USB_HEADER = "drivers/apcmicrolink-usb.h"
DRIVER_HEADER = "drivers/apcmicrolink.h"
POLICY_HEADER = "drivers/nut-guarded-policy.h"
PINNED_INPUTS = {
    CONFIGURE: "c4460862c11dab70f295db6a85d911e153c58c74b800137bdce632f94cd7745a",
    MAKEFILE: "23fe8fcf7ee3cc52906b6cef1eab5656fdc6f5d8e367e96d46a833662474bdeb",
    DRIVER: "77022c0cf0f6a3255a3c6afd5cc774cdbb28a047aa90ce85742bf3c490be7c91",
    MAIN: "ee3943ff3ce8fca9ef960cf376d31462f96e9ee7935729fbc8e07560be621df5",
    USB_HEADER: "b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29",
    DRIVER_HEADER: "be894253a3da4ef956e8327f891c5245b8d958c1696434eaa228b2953f7a2c66",
    POLICY_HEADER: "3abba1931d7608c60c4cfa5626ec9fe3b3abfc92b08220b8a15485bb19d5023b",
}
FUNCTIONS = (
    ("microlink_hidapi_finish", "static void microlink_hidapi_finish(void)"),
    ("microlink_hidapi_stop", "static int microlink_hidapi_stop(void *user)"),
    ("microlink_guard_deadline_expired", "static int microlink_guard_deadline_expired(void)"),
    ("microlink_guarded_stop_requested", "static int microlink_guarded_stop_requested(void)"),
    ("microlink_guard_probe_require_device_present", "static void microlink_guard_probe_require_device_present(void)"),
    ("microlink_checksum", "static void microlink_checksum(const unsigned char *buf, size_t len,"),
    ("microlink_send_write", "static int microlink_send_write(unsigned char id, unsigned char offset,"),
    ("microlink_send_simple_raw", "static int microlink_send_simple_raw(unsigned char byte)"),
    ("microlink_send_simple", "static int microlink_send_simple(unsigned char byte)"),
    ("microlink_send_descriptor_write", "static int microlink_send_descriptor_write(const char *path, const unsigned char *payload,"),
    ("microlink_start_session_impl", "static int microlink_start_session_impl(unsigned int max_attempts)"),
    ("microlink_hidapi_initups", "static void microlink_hidapi_initups(void)"),
    ("microlink_prime_poll", "static int microlink_prime_poll(void)"),
    ("upsdrv_cleanup", "void upsdrv_cleanup(void)"),
)
GENERATED = "hidapi_nut_generated.c"
MANIFEST = "manifest.json"
OUTPUT_ROOT = "hidapi-nut-generated"


class ExtractError(Exception):
    """Fail-closed source or output error."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def exact_function(source: str, signature: str) -> str:
    found: list[tuple[int, int]] = []
    offset = 0
    while True:
        at = source.find(signature, offset)
        if at < 0:
            break
        brace = source.find("{", at + len(signature), at + len(signature) + 500)
        semicolon = source.find(";", at + len(signature), at + len(signature) + 500)
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            found.append((at, brace))
        offset = at + len(signature)
    if len(found) != 1:
        raise ExtractError(f"source function missing or ambiguous: {signature}")
    start, brace = found[0]
    depth = 0
    state = "code"
    escaped = False
    index = brace
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if char == "*" and following == "/":
                state = "code"
                index += 1
        elif state in ("string", "char"):
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = "code"
        elif char == "/" and following == "/":
            state = "line"
            index += 1
        elif char == "/" and following == "*":
            state = "block"
            index += 1
        elif char == '"':
            state = "string"
        elif char == "'":
            state = "char"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise ExtractError(f"unterminated function: {signature}")


def _descriptor_write(source: str) -> str:
    start_marker = FUNCTIONS[9][1]
    next_marker = "static int microlink_send_descriptor_mask_value(const char *path, uint64_t mask)"
    candidates = []
    offset = 0
    while True:
        at = source.find(start_marker, offset)
        if at < 0:
            break
        brace = source.find("{", at + len(start_marker), at + len(start_marker) + 500)
        semicolon = source.find(";", at + len(start_marker), at + len(start_marker) + 500)
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            candidates.append(at)
        offset = at + len(start_marker)
    if len(candidates) != 1:
        raise ExtractError("descriptor write source marker missing or ambiguous")
    start = candidates[0]
    end = source.find(next_marker, start + len(start_marker))
    if end < 0:
        raise ExtractError("descriptor write next-function boundary missing")
    body = source[start:end].rstrip("\n")
    if not body.endswith("}"):
        raise ExtractError("descriptor write boundary does not end at a function close")
    return body


def extract_notice(source: str) -> str:
    if not source.startswith("/*"):
        raise ExtractError("upstream GPL notice missing")
    end = source.find("*/")
    if end < 0:
        raise ExtractError("upstream GPL notice is unterminated")
    notice = source[:end + 2]
    if "GNU General Public License" not in notice or "either version 2" not in notice:
        raise ExtractError("upstream GPL-2-or-later notice not recognized")
    return notice


def _extract_declaration(source: str) -> str:
    marker = "static const char *const hidapi_forbidden_options[] = {"
    if source.count(marker) != 1:
        raise ExtractError("forbidden-options declaration missing or ambiguous")
    start = source.index(marker)
    end = source.find("\n};", start)
    if end < 0:
        raise ExtractError("forbidden-options declaration boundary missing")
    return source[start:end + 3]


def generate(driver: str) -> str:
    notice = extract_notice(driver)
    blocks = ["/* SPDX-License-Identifier: GPL-2.0-or-later */", notice]
    for macro in ("MLINK_STOP_BYTE", "MLINK_INIT_BYTE", "MLINK_NEXT_BYTE"):
        matches = re.findall(rf"(?m)^#define {macro}\s+[^\n]+$", driver)
        if len(matches) != 1:
            raise ExtractError(f"control-byte macro missing or ambiguous: {macro}")
        blocks.append(matches[0])
    blocks.append(_extract_declaration(driver))
    for name, signature in FUNCTIONS:
        blocks.append(_descriptor_write(driver) if name == "microlink_send_descriptor_write"
                      else exact_function(driver, signature))
    return "\n\n".join(blocks) + "\n"


def _read_pinned_sources(root: Path, pins: dict[str, str]) -> dict[str, bytes]:
    if _has_symlink_component(root):
        raise ExtractError("NUT source path contains a symlink")
    root = root.absolute()
    if not root.is_dir():
        raise ExtractError("NUT source root is not a directory")
    product = Path(__file__).resolve().parents[2]
    resolved_root = root.resolve(strict=True)
    if paths_overlap(resolved_root, product):
        raise ExtractError("NUT source root must be outside the product repository")
    result: dict[str, bytes] = {}
    for relative, expected in pins.items():
        path = root / relative
        if _has_symlink_component(path) or not path.is_file():
            raise ExtractError(f"pinned source missing or symlinked: {relative}")
        data = path.read_bytes()
        if _sha256(data) != expected:
            raise ExtractError(f"pinned source SHA-256 mismatch: {relative}")
        result[relative] = data
    return result


def _existing_ancestors(path: Path) -> tuple[Path, ...]:
    current = Path(os.path.abspath(path))
    ancestors: list[Path] = []
    while True:
        if current.exists():
            ancestors.append(current)
        parent = current.parent
        if parent == current:
            return tuple(ancestors)
        current = parent


def _samefile_is_ancestor(existing: Path, descendant: Path) -> bool:
    if not existing.exists():
        return False
    for ancestor in _existing_ancestors(descendant):
        try:
            if os.path.samefile(existing, ancestor):
                return True
        except OSError:
            continue
    return False


def paths_overlap(left: Path, right: Path) -> bool:
    """Compare existing ancestor identities, including case-folded FS aliases."""
    left = Path(os.path.abspath(left))
    right = Path(os.path.abspath(right))
    return _samefile_is_ancestor(left, right) or _samefile_is_ancestor(right, left)


def _validate_output(output: Path, source_root: Path) -> Path:
    output = output.absolute()
    if _has_symlink_component(output):
        raise ExtractError("output path contains a symlink")
    if output.exists():
        raise ExtractError("output directory already exists")
    parent = output.parent
    if not parent.is_dir():
        raise ExtractError("output parent must already exist")
    product = Path(__file__).resolve().parents[2]
    for protected in (product, source_root.resolve(strict=True)):
        if paths_overlap(output, protected):
            raise ExtractError("output overlaps product repository or pinned input")
    return output


def stage_candidate(nut_source: Path, output_dir: Path) -> Path:
    """Validate all pinned inputs, then create a new generated-source bundle."""
    source_root = Path(nut_source)
    output = Path(output_dir)
    files = _read_pinned_sources(source_root, PINNED_INPUTS)
    driver = files[DRIVER].decode("utf-8")
    generated = generate(driver).encode("utf-8")
    output = _validate_output(output, source_root)
    os.mkdir(output, 0o700)
    generated_path = output / GENERATED
    with generated_path.open("xb") as stream:
        stream.write(generated)
    manifest = {
        "format": "hidapi-nut-extracted-source-v1",
        "state": "EXTRACTED_ONLY_NOT_COMPILED_NOT_RUN",
        "source_files": [
            {"path": rel, "sha256": _sha256(data)}
            for rel, data in sorted(files.items())
        ],
        "generated_sha256": _sha256(generated),
        "generated": {"path": GENERATED, "sha256": _sha256(generated)},
        "notice": "GPL-2.0-or-later upstream NUT notice preserved verbatim",
        "extracted": [name for name, _ in FUNCTIONS],
        "additional_source": ["hidapi_forbidden_options[]", "MLINK_STOP_BYTE", "MLINK_INIT_BYTE", "MLINK_NEXT_BYTE"],
    }
    manifest_path = output / MANIFEST
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nut-source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        stage_candidate(args.nut_source, args.output_dir)
    except (ExtractError, OSError, UnicodeError) as exc:
        print(f"extract_hidapi_nut: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
