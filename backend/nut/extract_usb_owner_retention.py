#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract pinned Microlink ownership functions for offline integration replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from replay_usb_async_state import ValidationError, scratch_path


USB_FILE = "drivers/apcmicrolink-usb.c"
USB_HEADER = "drivers/apcmicrolink-usb.h"
BACKEND_FILE = "drivers/libusb1.c"
BACKEND_HEADER = "drivers/nut_libusb.h"
DRIVER_CONTROL = "drivers/apcmicrolink.c"
GENERATED = "usb_owner_retention_generated.c"
FIXTURE = "test_usb_owner_retention.c"
PINNED_HASHES = {
    USB_FILE: "d6f61c595fd87e3f7d4e416ba8f8d6e04293ea3ff12c93dce60ad0384b4d056d",
    USB_HEADER: "b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29",
    BACKEND_FILE: "633fe750df7c4f74079caf9fa8d57e42483023b2009d068c286d3850b1570c42",
    BACKEND_HEADER: "6472654d77b2acc349ea1e886450190500bef4525699df26f56a5cc77bd518c4",
    DRIVER_CONTROL: "3bc7eadc8e2fae657df1b8f0e37f3baf53fd9a6e20a7da3c029d218193d2177d",
}
SCENARIOS = (
    "flush-active-race",
    "guarded-reopen-no-reset",
    "pending-open-reopen-flush",
    "open-start-pending",
    "reopen-start-pending",
    "open-fallback",
)

USB_FUNCTIONS = (
    "static int async_pending_get_locked(void)",
    "static int microlink_usb_async_owner_exists(void)",
    "static int microlink_usb_async_pending(void)",
    "static int microlink_usb_guard_remaining_ms_locked(unsigned int *remaining_ms)",
    "static int microlink_usb_guard_expired_locked(void)",
    "static int microlink_usb_guard_timeout_ms_locked(unsigned int *timeout_ms)",
    "int microlink_usb_guard_begin(long seconds)",
    "int microlink_usb_guard_expired(void)",
    "static void microlink_usb_guard_invalidate(void)",
    "static int microlink_usb_async_xfer_active_get(void)",
    "static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer)",
    "static void *microlink_usb_async_pump(void *arg)",
    "static int microlink_usb_async_reap_locked(void)",
    "static int microlink_usb_async_wait_ack(microlink_async_owner_t *owner,",
    "static int microlink_usb_async_start(void)",
    "static int microlink_usb_async_stop(void)",
    "void microlink_usb_close(void)",
    "int microlink_usb_open(void)",
    "static void microlink_usb_reset_handle(void *handle)",
    "int microlink_usb_reset_and_reopen(void)",
    "void microlink_usb_flush_io(void)",
    "static int microlink_usb_get_char_sync(unsigned char *ch, long d_usec)",
    "int microlink_usb_get_char(unsigned char *ch, long d_usec)",
)
BACKEND_FUNCTIONS = (
    "static void nut_libusb_cleanup_atexit(void)",
    "void nut_libusb_context_hold(void)",
    "void nut_libusb_context_release(void)",
)


class ReplayError(Exception):
    pass


def exact_function(source: str, signature: str) -> str:
    """Extract one balanced C function body, ignoring braces in comments/strings."""
    candidates: list[tuple[int, int]] = []
    offset = 0
    while True:
        at = source.find(signature, offset)
        if at < 0:
            break
        brace = source.find("{", at + len(signature), at + len(signature) + 300)
        semicolon = source.find(";", at + len(signature), at + len(signature) + 300)
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            candidates.append((at, brace))
        offset = at + len(signature)
    if len(candidates) != 1:
        raise ReplayError(f"function missing or ambiguous: {signature}")
    start, brace = candidates[0]
    depth = 0
    state = "code"
    escaped = False
    i = brace
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state == "line_comment":
            if ch == "\n":
                state = "code"
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 1
        elif state in ("string", "char"):
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                state = "code"
        else:
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch == '"':
                state = "string"
            elif ch == "'":
                state = "char"
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start : i + 1]
        i += 1
    raise ReplayError(f"unterminated function: {signature}")


def between(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ReplayError("state declaration markers missing or ambiguous")
    left = source.index(begin)
    right = source.index(end, left)
    if right <= left:
        raise ReplayError("state declaration marker order is invalid")
    return source[left:right]


def first_region(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1:
        raise ReplayError(f"scoped source start missing or ambiguous: {begin}")
    left = source.index(begin)
    right = source.find(end, left + len(begin))
    if right < 0:
        raise ReplayError(f"scoped source end missing: {end}")
    return source[left:right]


def generate(usb: str, backend: str) -> tuple[str, list[str]]:
    macro = "#define MLINK_USB_ASYNC_QUEUE_LEN"
    report_definitions = between(
        usb, "#define MLINK_USB_REPORT_PAYLOAD_LEN", "#define MLINK_USB_WRITE_TIMEOUT_MS"
    )
    state = between(usb, macro, "static int async_pending_get_locked(void)")
    state = re.sub(r"\s+$", "", state)
    async_region = first_region(
        usb,
        "#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)\n/* Always-outstanding async interrupt-IN listener",
        "#else\nstatic int microlink_usb_async_owner_exists(void)",
    )
    getter_region = first_region(
        usb,
        "/* Mirrors ser_get_char()'s contract, same as the synchronous version above:",
        "#else /* !(WITH_LIBUSB_1_0 && HAVE_PTHREAD) */",
    )
    scoped_async = {
        "static int async_pending_get_locked(void)",
        "static int microlink_usb_async_owner_exists(void)",
        "static int microlink_usb_async_pending(void)",
        "int microlink_usb_guard_begin(long seconds)",
        "int microlink_usb_guard_expired(void)",
    }
    scoped_getter = {"int microlink_usb_get_char(unsigned char *ch, long d_usec)"}
    usb_bodies = []
    pending_sig = "static int microlink_usb_async_pending(void)"
    for sig in USB_FUNCTIONS:
        region = async_region if sig in scoped_async else getter_region if sig in scoped_getter else usb
        body = exact_function(region, sig)
        if sig == pending_sig:
            body = (
                "#define microlink_usb_async_pending integration_pending_source\n"
                + body
                + "\n#undef microlink_usb_async_pending"
            )
        elif sig == "static int microlink_usb_async_xfer_active_get(void)":
            body = (
                "#define microlink_usb_async_xfer_active_get integration_active_source\n"
                + body
                + "\n#undef microlink_usb_async_xfer_active_get"
            )
        usb_bodies.append(body)
    source_open = exact_function(usb, "int microlink_usb_open(void)")
    source_reopen = exact_function(usb, "int microlink_usb_reset_and_reopen(void)")
    source_flush = exact_function(usb, "void microlink_usb_flush_io(void)")
    source_getchar = exact_function(
        getter_region, "int microlink_usb_get_char(unsigned char *ch, long d_usec)"
    )
    for path_name, body in (("open", source_open), ("reset/reopen", source_reopen)):
        if body.index("async_ret <= 0") > body.index("async_ret < 0"):
            raise ReplayError(f"{path_name} path does not handle pending before fallback")
        if body.index("async_ret < 0") > body.index("falling back to per-call"):
            raise ReplayError(f"{path_name} path may use sync fallback while ownership is pending")
    if source_open.index("async_ret <= 0") > source_open.index("falling back to per-call"):
        raise ReplayError("open path does not reject pending startup before fallback")
    if source_reopen.index("microlink_usb_async_stop") > source_reopen.index("comm_driver->close_dev"):
        raise ReplayError("reopen path closes the device before async stop")
    if source_reopen.index("if (!microlink_usb_async_stop())") > source_reopen.index("comm_driver->close_dev"):
        raise ReplayError("reopen path does not return while async ownership is pending")
    if source_getchar.index("microlink_usb_async_owner_exists") > source_getchar.index("microlink_usb_get_char_sync"):
        raise ReplayError("read path may take synchronous fallback with an owner")
    if source_flush.index("microlink_usb_async_pending") > source_flush.index("comm_driver->get_interrupt"):
        raise ReplayError("flush path may read synchronously while ownership is pending")
    if source_flush.index("microlink_usb_async_owner_exists") > source_flush.index("comm_driver->get_interrupt"):
        raise ReplayError("flush path may read synchronously after async terminal transition")
    if source_open.index("if (microlink_usb_async_owner_exists())") > source_open.index("USBNewRegexMatcher"):
        raise ReplayError("open path touches matcher before rejecting a retained owner")
    if source_open.index("if (async_ret < 0)") > source_open.index("falling back to per-call"):
        raise ReplayError("open path permits sync fallback after pending startup")
    backend_state = between(backend, "static libusb_context\t*nut_usb_ctx = NULL;",
                            "static int nut_libusb_guarded_monitor(void)")
    backend_bodies = [exact_function(backend, sig) for sig in BACKEND_FUNCTIONS]
    declarations = (
        "static int usb_device_gone = 0;\n"
        "static int guarded_monitor = 0;\n"
        "static usb_dev_handle *udev = NULL;\n"
        "static USBDevice_t curDevice;\n"
        "static USBDeviceMatcher_t *regex_matcher = NULL;\n"
        "static usb_communication_subdriver_t usb_subdriver;\n"
        "static usb_communication_subdriver_t *comm_driver = &usb_subdriver;\n"
        "static size_t in_report_len = 0;\n"
        "static size_t in_report_pos = 0;\n"
        "static unsigned char in_report[MLINK_USB_REPORT_TOTAL_LEN];\n"
        "static unsigned char mlink_report_in = 0;\n"
    )
    generated = (
        "/* Generated from exact source bodies; see manifest for hashes. */\n"
        "#define WITH_LIBUSB_1_0 1\n#define HAVE_PTHREAD 1\n"
        "#define HAVE_CLOCK_GETTIME 1\n#define HAVE_CLOCK_MONOTONIC 1\n"
        "#define NUT_UNUSED_VARIABLE(v) ((void)(v))\n"
        "#define USBMATCHER_REGEXP_ARRAY_LIMIT 8\n"
        "#define LOG_WARNING 4\n"
        "#define MLINK_USB_FLUSH_TIMEOUT_MS 20U\n"
        "#define MLINK_USB_FLUSH_MAX_REPORTS 32U\n"
        "#include <stdbool.h>\n"
        "typedef int nut_bool_t;\n"
        + report_definitions + backend_state + declarations + state + "\n"
        + "int microlink_usb_guard_expired(void);\n"
        + "static void microlink_usb_try_decode_fallback(const unsigned char *, size_t);\n"
        + "static void microlink_usb_handle_busy(const char *);\n"
        + "static void microlink_usb_device_gone_set(int);\n"
        + "static void microlink_usb_guard_invalidate(void);\n"
        + "static int microlink_usb_async_start(void);\n"
        + "static int microlink_usb_async_stop(void);\n"
        + "static int microlink_usb_async_pending(void);\n"
        + "static int integration_pending_source(void);\n"
        + "static int microlink_usb_async_xfer_active_get(void);\n"
        + "static int integration_active_source(void);\n"
        + "static int microlink_usb_report_callback(usb_dev_handle *, USBDevice_t *, usb_ctrl_charbuf, usb_ctrl_charbufsize);\n"
        + "static USBDeviceMatcher_t microlink_usb_device_matcher;\n"
        + "void nut_libusb_context_hold(void);\nvoid nut_libusb_context_release(void);\n"
        + "libusb_context *nut_libusb_get_context(void);\n"
        + "static void USBFreeRegexMatcher(USBDeviceMatcher_t *);\n"
        + "\n".join(usb_bodies) + "\n"
        + "\n".join(backend_bodies) + "\n"
    )
    names = list(USB_FUNCTIONS) + list(BACKEND_FUNCTIONS)
    return generated, names


def source_preamble(source: str) -> str:
    marker = '#include "config.h"'
    if source.count(marker) != 1:
        raise ReplayError("source copyright header boundary is missing or ambiguous")
    preamble = source[:source.index(marker)].rstrip()
    if not preamble:
        raise ReplayError("source copyright header is empty")
    return preamble


def compose_headers(usb: str, backend: str) -> str:
    return (
        "/* SPDX-License-Identifier: GPL-2.0-or-later */\n"
        + source_preamble(usb) + "\n\n" + source_preamble(backend)
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def read_source(root: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    if root.is_symlink() or not root.is_dir():
        raise ReplayError("candidate source must be a real, non-symlink directory")
    resolved = root.resolve(strict=True)
    repository = Path(__file__).resolve().parents[2]
    if _is_within(resolved, repository) or _is_within(repository, resolved):
        raise ReplayError("candidate source must be external to the product repository")
    driver_dir = resolved / "drivers"
    if driver_dir.is_symlink() or not driver_dir.is_dir():
        raise ReplayError("candidate drivers directory must be real and non-symlink")
    contents: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for relative in PINNED_HASHES:
        path = resolved / relative
        if path.is_symlink() or not path.is_file():
            raise ReplayError(f"candidate source file missing or symlinked: {relative}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != PINNED_HASHES[relative]:
            raise ReplayError(f"candidate source SHA-256 mismatch: {relative}")
        contents[relative] = data
        hashes[relative] = digest
    return contents, hashes


def validate_fixture() -> tuple[bytes, str]:
    path = Path(__file__).with_name(FIXTURE)
    if path.is_symlink() or not path.is_file():
        raise ReplayError("integration fixture is missing or symlinked")
    data = path.read_bytes()
    if b"SPDX-License-Identifier: GPL-2.0-or-later" not in data[:160]:
        raise ReplayError("integration fixture does not carry the expected GPL SPDX identifier")
    return data, hashlib.sha256(data).hexdigest()


def validate_scratch(path: Path, source: Path) -> Path:
    if path.is_symlink() or path.exists():
        raise ReplayError("scratch output must be a new, non-symlink path")
    try:
        # Canonicalize the parent first; common macOS temp roots include aliases
        # such as /var -> /private/var, which are not user-created scratch links.
        canonical = path.parent.resolve(strict=True) / path.name
        return scratch_path(canonical, [Path(__file__).resolve().parents[2], source])
    except ValidationError as error:
        raise ReplayError(str(error)) from error


def extract(source_root: Path, requested_scratch: Path) -> Path:
    contents, hashes = read_source(source_root)
    fixture, fixture_hash = validate_fixture()
    usb = contents[USB_FILE].decode("utf-8")
    backend = contents[BACKEND_FILE].decode("utf-8")
    generated, extracted = generate(usb, backend)
    generated = compose_headers(usb, backend) + "\n\n" + generated
    scratch = validate_scratch(requested_scratch, source_root.resolve(strict=True))
    manifest = {
        "mode": "extract-only",
        "status": "EXTRACTED_NOT_RUN",
        "generated_c": GENERATED,
        "generated_sha256": hashlib.sha256(generated.encode("utf-8")).hexdigest(),
        "c_fixture": FIXTURE,
        "fixture_sha256": fixture_hash,
        "source_sha256_pinned": hashes,
        "extracted_function_bodies": extracted,
        "integration_cases_expected_not_run": list(SCENARIOS),
        "assumptions": [
            "Public driver entrypoints are called by one main thread.",
            "Extracted function bodies are source-exact; the fixture supplies local doubles.",
            "The six named cases are the integration scope; inherited fixture cases have no new result here.",
        ],
        "stubs": ["libusb API", "NUT matcher/logging/dstate APIs", "backend context APIs", "mock device state"],
        "limitations": [
            "No C compilation or execution is performed by this extractor.",
            "No NUT binary, real libusb, IOKit, USB hardware, STOP path, or process-exit behavior is qualified.",
            "Synthetic barriers do not establish kernel URB cancellation, platform scheduling, or hard deadlines.",
        ],
    }
    # All source, fixture, and scratch validation completes before this first write.
    scratch.mkdir(parents=True, exist_ok=False)
    (scratch / GENERATED).write_text(generated, encoding="utf-8")
    (scratch / FIXTURE).write_bytes(fixture)
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return scratch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("extract",), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    try:
        scratch = extract(args.source, args.scratch)
        print(f"EXTRACTED exact bodies; NOT_RUN; output={scratch}")
        return 0
    except (OSError, UnicodeError, ReplayError, ValidationError) as error:
        print(f"ERROR: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
