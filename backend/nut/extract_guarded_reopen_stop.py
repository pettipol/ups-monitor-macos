#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract pinned base-7 and RF-04 source bodies for offline replay only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import extract_usb_owner_retention as owner
from replay_usb_async_state import ValidationError, scratch_path


SOURCE_FILES = dict(owner.PINNED_HASHES)
SOURCE_FILES.update({
    "drivers/apcmicrolink.c": "efdad6737c377931e5130f00d9e1257091584670d149d49015d06e2854fa14a5",
    "drivers/main.c": "b40ccaef148aa0396d8a81bc83e961c4af8d286bccb5e26e745f0252b6709dba",
    "drivers/main.h": "19bb6da2a1a05434ad5d845baa26a2b2137c8eae02802f080261fe162883c7dc",
    "drivers/nut-guarded-policy.h": "3abba1931d7608c60c4cfa5626ec9fe3b3abfc92b08220b8a15485bb19d5023b",
})
BASE_USB_SHA256 = "d6f61c595fd87e3f7d4e416ba8f8d6e04293ea3ff12c93dce60ad0384b4d056d"
CANDIDATE_USB_SHA256 = "6023981a06e8b1a3f2eb6db13c91b712060275d4566f398fcd7cb05cd3fe4f99"
BASELINE_HASHES = dict(SOURCE_FILES)
BASELINE_HASHES[owner.USB_FILE] = BASE_USB_SHA256
CANDIDATE_HASHES = dict(SOURCE_FILES)
CANDIDATE_HASHES[owner.USB_FILE] = CANDIDATE_USB_SHA256
STOP_HELPER = "static int microlink_usb_guarded_stop_requested(void)"
FIXTURE = "test_usb_owner_retention.c"
WRAPPER = "test_guarded_reopen_stop.c"
GENERATED = owner.GENERATED
CASES = (
    # Historical ownership controls are dispatched unchanged to the prior fixture.
    "flush-active-race",
    "guarded-reopen-no-reset",
    "pending-open-reopen-flush",
    "open-start-pending",
    "reopen-start-pending",
    "open-fallback",
    "stop-entry",
    "stop-after-close",
    "stop-after-open",
    "stop-prepublish",
    "start-active-owner-stop",
    "start-no-owner-stop",
    "start-stop-quiescent",
    "start-stop-pending",
    "ordinary-reopen-stop-flag",
    "healthy-guarded-reopen",
    "ordinary-fallback",
)
INTERPOSE_PRELUDE = """\
/* Fixture-only API interposition. Extracted function bodies remain unchanged. */
static void guarded_fill_interrupt_transfer(libusb_transfer *, usb_dev_handle *, unsigned char,
    unsigned char *, int, libusb_transfer_cb_fn, void *, unsigned int);
static int guarded_submit_transfer(libusb_transfer *);
static int guarded_cancel_transfer(libusb_transfer *);
static int guarded_pthread_create(pthread_t *, const pthread_attr_t *, void *(*)(void *), void *);
#undef libusb_fill_interrupt_transfer
#define libusb_fill_interrupt_transfer guarded_fill_interrupt_transfer
#undef libusb_submit_transfer
#define libusb_submit_transfer guarded_submit_transfer
#undef libusb_cancel_transfer
#define libusb_cancel_transfer guarded_cancel_transfer
#undef pthread_create
#define pthread_create guarded_pthread_create
"""


class ExtractError(Exception):
    pass


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def read_tree(root: Path, expected: dict[str, str]) -> tuple[dict[str, bytes], dict[str, str]]:
    if root.is_symlink() or not root.is_dir():
        raise ExtractError("source root must be a real, non-symlink directory")
    resolved = root.resolve(strict=True)
    product = Path(__file__).resolve().parents[2]
    if _within(resolved, product) or _within(product, resolved):
        raise ExtractError("source root must be external to the product repository")
    drivers = resolved / "drivers"
    if drivers.is_symlink() or not drivers.is_dir():
        raise ExtractError("source drivers directory must be real and non-symlink")
    contents: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for relative, pinned in expected.items():
        path = resolved / relative
        if path.is_symlink() or not path.is_file():
            raise ExtractError(f"pinned source is missing or symlinked: {relative}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != pinned:
            raise ExtractError(f"source SHA-256 mismatch: {relative}")
        contents[relative] = data
        hashes[relative] = digest
    return contents, hashes


def validate_scratch(requested: Path, roots: tuple[Path, ...]) -> Path:
    if requested.is_symlink() or requested.exists():
        raise ExtractError("scratch must be a new, non-symlink path")
    product = Path(__file__).resolve().parents[2]
    try:
        canonical = requested.parent.resolve(strict=True) / requested.name
        return scratch_path(canonical, [product, *(root.resolve(strict=True) for root in roots)])
    except ValidationError as error:
        raise ExtractError(str(error)) from error


def _render(contents: dict[str, bytes], candidate: bool) -> tuple[str, list[str]]:
    usb = contents[owner.USB_FILE].decode("utf-8")
    backend = contents[owner.BACKEND_FILE].decode("utf-8")
    extras = (STOP_HELPER,) if candidate else ()
    generated, names = owner.generate(usb, backend, extra_usb_functions=extras)
    # The test-only macro redirects calls at preprocessing time; extracted bodies
    # in the generated file are not rewritten.
    return owner.compose_headers(usb, backend) + "\n\n" + INTERPOSE_PRELUDE + generated, names


def extract(base_root: Path, candidate_root: Path, requested_scratch: Path) -> Path:
    base_contents, base_hashes = read_tree(base_root, BASELINE_HASHES)
    candidate_contents, candidate_hashes = read_tree(candidate_root, CANDIDATE_HASHES)
    fixture_data, fixture_hash = owner.validate_fixture()
    wrapper_path = Path(__file__).with_name(WRAPPER)
    if wrapper_path.is_symlink() or not wrapper_path.is_file():
        raise ExtractError("RF-04 fixture wrapper is missing or symlinked")
    wrapper_data = wrapper_path.read_bytes()
    if b"SPDX-License-Identifier: GPL-2.0-or-later" not in wrapper_data[:160]:
        raise ExtractError("RF-04 fixture wrapper is missing its GPL SPDX identifier")
    base_c, base_names = _render(base_contents, False)
    candidate_c, candidate_names = _render(candidate_contents, True)
    scratch = validate_scratch(requested_scratch, (base_root, candidate_root))
    manifest = {
        "mode": "extract-only",
        "status": "EXTRACTED_NOT_RUN",
        "base_revision_label": "NUT 73c4502 plus seven prior patches",
        "candidate_label": "same source plus RF-04 patch 8",
        "source_sha256": {"base": base_hashes, "candidate": candidate_hashes},
        "generated_sha256": {
            "base": hashlib.sha256(base_c.encode("utf-8")).hexdigest(),
            "candidate": hashlib.sha256(candidate_c.encode("utf-8")).hexdigest(),
        },
        "fixture_sha256": hashlib.sha256(fixture_data).hexdigest(),
        "wrapper_sha256": hashlib.sha256(wrapper_data).hexdigest(),
        "files": [FIXTURE, WRAPPER, GENERATED, "manifest.json"],
        "extracted_functions": {"base": base_names, "candidate": candidate_names},
        "cases_expected_not_run": list(CASES),
        "assumptions": [
            "Tests call extracted USB entrypoints on one synthetic main thread.",
            "The signal-query double is an atomic test flag, not a real POSIX signal path.",
            "A synthetic libusb/POSIX transport supplies barriers and terminal callbacks.",
        ],
        "limitations": [
            "Extractor performs no compilation or execution.",
            "No real libusb, NUT process, USB/HID device, IOKit, kernel cancellation, or hardware is tested.",
            "Check-to-API and already-in-flight races remain; this is not an atomic or hard-deadline guarantee.",
        ],
    }
    scratch.mkdir(parents=True, exist_ok=False)
    for label, generated in (("base7", base_c), ("candidate8", candidate_c)):
        output = scratch / label
        output.mkdir()
        (output / GENERATED).write_text(generated, encoding="utf-8")
        (output / FIXTURE).write_bytes(fixture_data)
        (output / WRAPPER).write_bytes(wrapper_data)
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return scratch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("extract",), required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = extract(args.base, args.candidate, args.scratch)
        print(f"EXTRACTED source-exact fixtures; NOT_RUN; output={output}")
        return 0
    except (OSError, UnicodeError, ExtractError, owner.ReplayError, ValidationError) as error:
        print(f"ERROR: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
