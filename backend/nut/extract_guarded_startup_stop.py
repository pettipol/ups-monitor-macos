#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract pinned Microlink startup/stop callsites for an offline fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


MAIN = "drivers/main.c"
HEADER = "drivers/main.h"
DRIVER = "drivers/apcmicrolink.c"
USB = "drivers/apcmicrolink-usb.c"
MAIN_SHA256 = "b40ccaef148aa0396d8a81bc83e961c4af8d286bccb5e26e745f0252b6709dba"
HEADER_SHA256 = "19bb6da2a1a05434ad5d845baa26a2b2137c8eae02802f080261fe162883c7dc"
DRIVER_SHA256 = "efdad6737c377931e5130f00d9e1257091584670d149d49015d06e2854fa14a5"
USB_SHA256 = "d6f61c595fd87e3f7d4e416ba8f8d6e04293ea3ff12c93dce60ad0384b4d056d"
BASELINE_MAIN_SHA256 = "a5bee8705ddb293c216ab57f03add7702cb967fd56d2b582187b2a164d0ba074"
BASELINE_HEADER_SHA256 = "d6891c0b86585cfa29dbdcaf9f3de7b797472fdbbb7a094ec1626cefc3e34ba8"
BASELINE_DRIVER_SHA256 = "3bc7eadc8e2fae657df1b8f0e37f3baf53fd9a6e20a7da3c029d218193d2177d"
BASELINE_USB_SHA256 = USB_SHA256
GENERATED = "guarded_startup_stop_generated.c"
FIXTURE = "test_guarded_startup_stop.c"


class ReplayError(Exception):
    pass


def exact_function(source: str, signature: str) -> str:
    found: list[tuple[int, int]] = []
    offset = 0
    while True:
        at = source.find(signature, offset)
        if at < 0:
            break
        brace = source.find("{", at + len(signature), at + len(signature) + 300)
        semicolon = source.find(";", at + len(signature), at + len(signature) + 300)
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            found.append((at, brace))
        offset = at + len(signature)
    if len(found) != 1:
        raise ReplayError(f"source function missing or ambiguous: {signature}")
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
    raise ReplayError(f"unterminated function: {signature}")


def read_source(root: Path, baseline: bool = False) -> tuple[str, str, str, str]:
    if root.is_symlink():
        raise ReplayError("source root must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ReplayError("source root is not a directory")
    product = Path(__file__).resolve().parents[2]
    try:
        root.relative_to(product)
    except ValueError:
        pass
    else:
        raise ReplayError("source root must be outside the product repository")
    drivers = root / "drivers"
    if drivers.is_symlink() or not drivers.is_dir():
        raise ReplayError("pinned drivers directory is missing or symlinked")
    expected = {
        MAIN: BASELINE_MAIN_SHA256 if baseline else MAIN_SHA256,
        HEADER: BASELINE_HEADER_SHA256 if baseline else HEADER_SHA256,
        DRIVER: BASELINE_DRIVER_SHA256 if baseline else DRIVER_SHA256,
        USB: BASELINE_USB_SHA256 if baseline else USB_SHA256,
    }
    contents: dict[str, str] = {}
    for relative, digest in expected.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ReplayError(f"source file missing or symlinked: {relative}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ReplayError(f"pinned source SHA-256 mismatch: {relative}")
        contents[relative] = data.decode("utf-8")
    return contents[MAIN], contents[HEADER], contents[DRIVER], contents[USB]


def validate_candidate(main: str, header: str, driver: str, usb: str) -> None:
    main_query = exact_function(main, "int nut_guarded_dump_signal_requested(void)")
    handler = exact_function(main, "static void guarded_dump_signal_handler(int sig)")
    if "return guarded_dump_signal != 0;" not in main_query:
        raise ReplayError("main signal query no longer reads the cooperative flag")
    if "guarded_dump_signal = sig;" not in handler or "ups" in handler or "exit(" in handler:
        raise ReplayError("signal handler must only assign the sig_atomic_t flag")
    declaration = "#ifndef WIN32\n/* Read-only checkpoint for cooperative guarded startup cancellation. */\nint nut_guarded_dump_signal_requested(void);\n#endif /* !WIN32 */"
    if declaration not in header or "extern int nut_guarded_dump_signal_requested" in driver:
        raise ReplayError("main signal query must use the shared POSIX-only declaration in main.h")

    writer = exact_function(driver, "static int microlink_send_write(unsigned char id, unsigned char offset,")
    simple = exact_function(driver, "static int microlink_send_simple(unsigned char byte)")
    raw = exact_function(driver, "static int microlink_send_simple_raw(unsigned char byte)")
    checkpoint = exact_function(driver, "static int microlink_guarded_stop_requested(void)")
    startup = exact_function(driver, "static int microlink_start_session_impl(unsigned int max_attempts)")
    initups = exact_function(driver, "void upsdrv_initups(void)")
    cleanup = exact_function(driver, "void upsdrv_cleanup(void)")
    if "guarded_monitor && nut_guarded_dump_signal_requested()" not in checkpoint:
        raise ReplayError("driver signal query must be limited to guarded_monitor")
    for name, body in (("descriptor writer", writer), ("simple writer", simple)):
        if "microlink_guarded_stop_requested()" not in body:
            raise ReplayError(f"{name} lacks a cooperative stop gate")
    if "microlink_send_simple_raw(MLINK_STOP_BYTE)" not in cleanup:
        raise ReplayError("cleanup STOP no longer uses the separate raw send path")
    if "microlink_send_simple_raw" in startup or "microlink_guarded_stop_requested()" not in startup:
        raise ReplayError("startup STOP/INIT path bypasses the guarded signal checkpoint")
    ordered = (
        startup.find("microlink_guarded_stop_requested()"),
        startup.find("microlink_send_simple(MLINK_STOP_BYTE)"),
        startup.find("microlink_guarded_stop_requested()", startup.find("microlink_send_simple(MLINK_STOP_BYTE)")),
        startup.find("microlink_send_simple(MLINK_INIT_BYTE)"),
        startup.find("microlink_receive_once()"),
    )
    if min(ordered) < 0 or tuple(sorted(ordered)) != ordered:
        raise ReplayError("startup checkpoints are missing or out of order")
    if "open_result != 1" not in initups:
        raise ReplayError("guarded USB open must fail closed unless it returns 1")
    open_at = initups.find("open_result = microlink_usb_open();")
    failure_at = initups.find("if (guarded_monitor && open_result != 1)", open_at)
    if open_at < 0 or failure_at < open_at:
        raise ReplayError("guarded-open failure is not checked after open")
    failure_branch = exact_function(initups, "if (guarded_monitor && open_result != 1)")
    if failure_branch.find("microlink_usb_close();") < 0 or \
            failure_branch.find("microlink_usb_close();") > failure_branch.find("fatalx(EXIT_FAILURE"):
        raise ReplayError("guarded-open failure must attempt ownership-aware USB close before fatal")
    if "microlink_send_simple_raw(unsigned char byte)" not in raw:
        raise ReplayError("cleanup raw writer signature changed")
    close = exact_function(usb, "void microlink_usb_close(void)")
    stop_at = close.find("if (!microlink_usb_async_stop())")
    device_close_at = close.find("comm_driver->close_dev(udev)")
    stop_return_at = close.find("return;", stop_at)
    if stop_at < 0 or stop_return_at < stop_at or device_close_at < stop_return_at:
        raise ReplayError("USB close no longer preserves device ownership when async stop is pending")

    setup_at = main.find("setup_guarded_dump_signals() != 0")
    initups_at = main.find("upsdrv_callbacks.upsdrv_initups();")
    initinfo_at = main.find("upsdrv_callbacks.upsdrv_initinfo();")
    after_initups = main.find("exit_if_guarded_dump_signal_requested();", initups_at)
    if not (0 <= setup_at < initups_at < after_initups < initinfo_at):
        raise ReplayError("main startup signal setup/checkpoints do not bracket initups before initinfo")
    if main.find("exit_if_guarded_dump_signal_requested();", 0, initups_at) < setup_at:
        raise ReplayError("main lacks the signal checkpoint before initups")


def extract_notice(source: str) -> str:
    if not source.startswith("/*"):
        raise ReplayError("upstream source notice is missing")
    end = source.find("*/")
    if end < 0:
        raise ReplayError("upstream source notice is unterminated")
    return source[:end + 2]


def generate(main: str, header: str, driver: str, baseline: bool = False) -> str:
    flag = "static volatile sig_atomic_t guarded_dump_signal = 0;"
    if main.count(flag) != 1:
        raise ReplayError("guarded signal state missing or ambiguous")
    functions: list[str] = [
        flag,
        exact_function(main, "static void guarded_dump_signal_handler(int sig)"),
        exact_function(main, "static int setup_guarded_dump_signals(void)"),
    ]
    signatures = (
        "static int microlink_send_write(unsigned char id, unsigned char offset,",
        "static int microlink_send_simple(unsigned char byte)",
        "static int microlink_prime_poll(void)",
        "static int microlink_start_session_impl(unsigned int max_attempts)",
        "void upsdrv_initups(void)",
        "void upsdrv_cleanup(void)",
    )
    if not baseline:
        functions.append(exact_function(main, "int nut_guarded_dump_signal_requested(void)"))
        functions.append(exact_function(driver, "static int microlink_guarded_stop_requested(void)"))
        functions.append(exact_function(driver, "static int microlink_send_simple_raw(unsigned char byte)"))
    else:
        pass
    functions.extend(exact_function(driver, signature) for signature in signatures)
    if baseline:
        # Baseline cleanup already called the public simple sender.
        pass
    notices = "\n\n".join((
        "/* SPDX-License-Identifier: GPL-2.0-or-later */",
        extract_notice(main),
        extract_notice(driver),
    ))
    return notices + "\n\n" + "\n\n".join(functions) + "\n"


def source_unit(root: Path, baseline: bool = False) -> str:
    main, header, driver, usb = read_source(root, baseline=baseline)
    if not baseline:
        validate_candidate(main, header, driver, usb)
    return generate(main, header, driver, baseline=baseline)


def validate_scratch(scratch: Path, source: Path, baseline_source: Path | None) -> Path:
    if scratch.is_symlink() or scratch.exists():
        raise ReplayError("scratch must be a new, non-symlink path")
    requested = scratch.absolute()
    resolved = scratch.resolve()
    if requested != resolved:
        raise ReplayError("scratch must not traverse a symlink")
    product = Path(__file__).resolve().parents[2]
    for forbidden in (product, source.resolve(strict=True),
                      *(item.resolve(strict=True) for item in (baseline_source,) if item)):
        try:
            resolved.relative_to(forbidden)
        except ValueError:
            continue
        raise ReplayError("scratch overlaps product or pinned source")
    return resolved


def run(source: Path, scratch: Path, mode: str, baseline_source: Path | None) -> int:
    scratch = validate_scratch(scratch, source, baseline_source)
    selected_source = baseline_source if mode == "red" else source
    assert selected_source is not None
    generated = source_unit(selected_source, baseline=mode == "red")
    scratch.mkdir(parents=True, exist_ok=False)
    (scratch / GENERATED).write_text(generated, encoding="utf-8")
    fixture_bytes = Path(__file__).with_name(FIXTURE).read_bytes()
    (scratch / FIXTURE).write_bytes(fixture_bytes)
    fixture = scratch / FIXTURE
    pinned = {relative: hashlib.sha256((selected_source / relative).read_bytes()).hexdigest()
              for relative in (MAIN, HEADER, DRIVER, USB)}
    manifest = {
        "candidate_base": "NUT 73c4502191d025e35122463986a80c676e734b04 + six prior patches",
        "status": "EXTRACTED_NOT_RUN",
        "source_sha256": pinned,
        "generated_sha256": hashlib.sha256(generated.encode("utf-8")).hexdigest(),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "fixture": FIXTURE,
        "scope": ["guarded startup STOP/INIT cancellation", "guarded USB open failure before initinfo"],
        "limitations": [
            "synthetic mocks only; main() and the NUT process were not executed",
            "no real libusb, USB, HID, UPS, kernel, firmware, or electrical behavior was exercised",
            "signal raises are confined to this bounded synthetic fixture process",
            "test continuation models initinfo immediately after the extracted upsdrv_initups call",
            "USB close mock models the hash-pinned close contract; no owner lifecycle was executed",
            "check-then-send is cooperative and does not eliminate an already-started call or race",
        ],
    }
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if mode == "extract":
        print("pinned production functions extracted; compilation and execution not requested")
        return 0
    binary = scratch / "test_guarded_startup_stop"
    command = ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
               "-fno-sanitize-recover=undefined", "-I", str(scratch), str(fixture),
               "-o", str(binary), "-pthread"]
    subprocess_run(command, timeout=30)
    nm = subprocess_run(["nm", "-u", str(binary)], timeout=10, capture=True)
    otool = subprocess_run(["otool", "-L", str(binary)], timeout=10, capture=True)
    linkage = (nm + otool).lower()
    if any(token in linkage for token in ("libusb", "usb_", "upsdrv_", "libnut", "hidapi", "iokit")):
        raise ReplayError("synthetic fixture unexpectedly links a real NUT/USB/HID API")
    print("nm/otool verified stub-only linkage before synthetic execution")
    try:
        result = subprocess.run([str(binary)], check=False, timeout=10,
                                capture_output=True, text=True, cwd=scratch)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReplayError("bounded synthetic fixture execution failed") from error
    expected_red = (
        "FAIL main-thread signal during startup STOP permitted INIT or retry\n"
        "FAIL worker-thread signal during startup STOP permitted INIT or retry\n"
        "FAIL signal after INIT permitted receive or NEXT\n"
        "FAIL guarded pending open reached initinfo or released retained ownership\n"
        "FAIL guarded failed open did not close an unowned USB handle before fatal\n"
        "5 synthetic startup/stop check(s) failed\n"
    )
    if mode == "red":
        if result.returncode != 1 or result.stdout or result.stderr != expected_red:
            raise ReplayError(
                "six-patch baseline did not produce the exact expected RF-01/RF-03 RED "
                f"(rc={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r})"
            )
        manifest["status"] = "RED_REPRODUCED"
        write_manifest(scratch, manifest)
        print("baseline RED reproduced: five named RF-01/RF-03 assertions failed")
        print(result.stderr, end="")
        return 0
    if result.returncode != 0 or result.stderr or result.stdout != \
            "all guarded startup/stop synthetic checks passed\n":
        raise ReplayError(
            "candidate synthetic fixture failed or emitted unexpected output "
            f"(rc={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r})"
        )
    manifest["status"] = "GREEN_SYNTHETIC"
    write_manifest(scratch, manifest)
    print("candidate GREEN reproduced; no NUT driver or device was executed")
    print(result.stdout, end="")
    return 0


def write_manifest(scratch: Path, manifest: dict[str, object]) -> None:
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def subprocess_run(command: list[str], timeout: int, capture: bool = False,
                   check: bool = True) -> int | str:
    try:
        result = subprocess.run(command, check=False, timeout=timeout,
                                capture_output=capture, text=True)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReplayError(f"bounded command failed: {command[0]}") from error
    if check and result.returncode != 0:
        raise ReplayError(f"bounded command returned {result.returncode}: {command[0]}")
    if capture:
        return result.stdout + result.stderr
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("extract", "red", "green"))
    parser.add_argument("source", type=Path)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("--baseline-source", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.mode == "red" and arguments.baseline_source is None:
            raise ReplayError("RED mode requires the pinned six-patch baseline source")
        if arguments.mode != "red" and arguments.baseline_source is not None:
            raise ReplayError("baseline source is accepted only in RED mode")
        return run(arguments.source, arguments.scratch, arguments.mode,
                   arguments.baseline_source)
    except ReplayError as error:
        print(f"replay rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
