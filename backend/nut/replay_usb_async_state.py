#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replay three extracted Microlink scalar races, without NUT or USB.

The active-state reader models the original raw read; it does not execute
get_char. Pump/callback/helpers are extracted, not main or start/stop integration.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys


PIN = "73c4502191d025e35122463986a80c676e734b04"
SOURCE = Path("drivers/apcmicrolink-usb.c")
BASELINE_SHA256 = "6b81bac1498ce4868a96bca9ee98682155cc1f063eb36c72c4cb29c21bcf01f9"
CANDIDATE_SHA256 = "7929a4869cfee9c08734c1b9b5c091c3f7c62496e0981031c2c9ad149ecc33b0"
STATE_END = "/* Defined below microlink_usb_try_decode_fallback(), which the transfer\n * callback calls. */"
PUMP_START = "static void *microlink_usb_async_pump(void *arg)"
CALLBACK_START = "static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer)"
TSAN_OPTIONS = "halt_on_error=1:exitcode=66:abort_on_error=0"


class ValidationError(Exception):
    pass


def git_output(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValidationError("could not verify pinned source checkout") from error
    return result.stdout.strip()


def read_pinned_source(root: Path, expected_hash: str) -> bytes:
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir() or git_output(resolved_root, "rev-parse", "HEAD") != PIN:
        raise ValidationError("source checkout HEAD does not match pinned revision")
    source_path = resolved_root / SOURCE
    if source_path.is_symlink() or not source_path.is_file():
        raise ValidationError("pinned USB source is missing or a symlink")
    content = source_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValidationError("pinned USB source SHA-256 mismatch")
    return content


def _unique_span(source: str, start_marker: str, end_marker: str) -> str:
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker)) if start >= 0 else -1
    if (
        start < 0 or end < 0
        or source.find(start_marker, start + 1) >= 0
        or source.find(end_marker, end + 1) >= 0
    ):
        raise ValidationError("source extraction marker is missing or ambiguous")
    return source[start:end]


def extract_state_declarations(source: str) -> str:
    start = source.find("#define MLINK_USB_ASYNC_QUEUE_LEN")
    end_marker = "#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */"
    end = source.find(end_marker, start) if start >= 0 else -1
    if start < 0 or end < 0:
        raise ValidationError("could not extract pinned async state declarations")
    block = source[start:end + len(end_marker)]
    # These declarations have no definitions in the bounded replay.
    for prototype in (
        "static int microlink_usb_async_start(void);\n",
        "static void microlink_usb_async_stop(void);\n",
    ):
        if block.count(prototype) != 1:
            raise ValidationError("unreviewed async start/stop prototype structure")
        block = block.replace(prototype, "", 1)
    return block


def function_body(source: str, signature: str, *, allow_multiple: bool = False) -> str:
    positions = [match.start() for match in re.finditer(re.escape(signature), source)]
    if not positions:
        raise ValidationError(f"function marker is missing: {signature}")
    definitions = []
    for position in positions:
        opening = source.find("{", position + len(signature))
        semicolon = source.find(";", position + len(signature))
        if opening >= 0 and (semicolon < 0 or opening < semicolon):
            definitions.append(position)
    if len(definitions) != 1 and not allow_multiple:
        raise ValidationError(f"function definition marker is missing or ambiguous: {signature}")
    if not definitions:
        raise ValidationError(f"function definition marker is missing: {signature}")
    marker = definitions[0]
    opening = source.find("{", marker + len(signature))
    if opening < 0:
        raise ValidationError("function body opening brace is missing")
    depth = 0
    state = "code"
    index = opening
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "line_comment":
            if char == "\n":
                state = "code"
        elif state == "block_comment":
            if char == "*" and next_char == "/":
                state = "code"
                index += 1
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif char == "/" and next_char == "*":
            state = "block_comment"
            index += 1
        elif char == "/" and next_char == "/":
            state = "line_comment"
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
                return source[opening:index + 1]
        index += 1
    raise ValidationError("function body braces are unbalanced")


def code_only(source: str) -> str:
    """Blank comments and literals so callsite checks inspect C tokens only."""
    result = list(source)
    state = "code"
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                result[index] = " "
        elif state == "block_comment":
            result[index] = " "
            if char == "*" and next_char == "/":
                result[index + 1] = " "
                state = "code"
                index += 1
        elif state in ("string", "char"):
            result[index] = " "
            if char == "\\":
                if index + 1 < len(source):
                    result[index + 1] = " "
                    index += 1
            elif (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = "code"
        elif char == "/" and next_char == "*":
            result[index] = result[index + 1] = " "
            state = "block_comment"
            index += 1
        elif char == "/" and next_char == "/":
            result[index] = result[index + 1] = " "
            state = "line_comment"
            index += 1
        elif char == '"':
            result[index] = " "
            state = "string"
        elif char == "'":
            result[index] = " "
            state = "char"
        index += 1
    return "".join(result)


def validate_baseline(source: str) -> None:
    pump = function_body(source, PUMP_START)
    callback = function_body(source, CALLBACK_START)
    start = function_body(source, "static int microlink_usb_async_start(void)")
    stop = function_body(source, "static void microlink_usb_async_stop(void)")
    getter = function_body(source, "int microlink_usb_device_gone(void)")
    get_char = function_body(source, "int microlink_usb_get_char(unsigned char *ch, long d_usec)", allow_multiple=True)
    checks = (
        ("while (!async_pump_stop)" in pump, "baseline pump no longer reads its raw stop flag"),
        ("usb_device_gone = 1;" in callback, "baseline callback no longer marks device-gone directly"),
        ("async_xfer_active = 0;" in callback, "baseline callback no longer updates transfer state directly"),
        ("if (async_xfer_active)" in start and "async_xfer_active = 1;" in start,
         "baseline start no longer reads/writes transfer state directly"),
        ("async_pump_stop = 1;" in stop and "async_xfer_active" in stop,
         "baseline stop no longer touches shared async state directly"),
        ("return usb_device_gone;" in getter, "baseline device-gone getter changed"),
        ("if (!async_xfer_active)" in get_char, "baseline getchar no longer reads transfer state directly"),
    )
    for passed, message in checks:
        if not passed:
            raise ValidationError(message)


def validate_helper_locks(source: str) -> None:
    protected_helpers = (
        ("static int microlink_usb_async_xfer_active_get(void)",
         r"active\s*=\s*async_xfer_active\s*;"),
        ("static void microlink_usb_async_xfer_active_set(int active)",
         r"async_xfer_active\s*=\s*active\s*;"),
        ("static int microlink_usb_async_pump_stop_get(void)",
         r"stop\s*=\s*async_pump_stop\s*;"),
        ("static void microlink_usb_async_pump_stop_set(int stop)",
         r"async_pump_stop\s*=\s*stop\s*;"),
        ("static int microlink_usb_device_gone_get(void)",
         r"gone\s*=\s*usb_device_gone\s*;"),
        ("static void microlink_usb_device_gone_set(int gone)",
         r"usb_device_gone\s*=\s*gone\s*;"),
    )
    for signature, operation_pattern in protected_helpers:
        body = code_only(function_body(source, signature))
        lock_at = body.find("pthread_mutex_lock(&async_lock)")
        operation = re.search(operation_pattern, body)
        unlock_at = body.find("pthread_mutex_unlock(&async_lock)")
        if (
            lock_at < 0 or operation is None or unlock_at < 0
            or not lock_at < operation.start() < unlock_at
        ):
            raise ValidationError(f"helper lacks its own lock/read-or-write/unlock: {signature}")


def validate_candidate(source: str) -> str:
    declarations = _unique_span(source, "#define MLINK_USB_ASYNC_QUEUE_LEN", STATE_END)
    if "static volatile int async_pump_stop" in declarations:
        raise ValidationError("candidate still relies on volatile pump-stop state")
    validate_helper_locks(source)
    pump = function_body(source, PUMP_START)
    callback = function_body(source, CALLBACK_START)
    start = function_body(source, "static int microlink_usb_async_start(void)")
    stop = function_body(source, "static void microlink_usb_async_stop(void)")
    device_getter = function_body(source, "int microlink_usb_device_gone(void)")
    device_setter = function_body(source, "static void microlink_usb_device_gone_set(int gone)")
    get_char = function_body(source, "int microlink_usb_get_char(unsigned char *ch, long d_usec)", allow_multiple=True)

    cases = (
        ("async_pump_stop", (pump, start, stop), "pump-stop"),
        ("async_xfer_active", (callback, start, stop, get_char), "transfer-active"),
        ("usb_device_gone", (callback, device_getter), "device-gone"),
    )
    for raw_name, bodies, label in cases:
        if any(re.search(rf"\b{raw_name}\b", code_only(body)) for body in bodies):
            raise ValidationError(f"candidate {label} call path bypasses its getter/setter")

    required_calls = (
        ("microlink_usb_async_pump_stop_get()", pump),
        ("microlink_usb_async_pump_stop_set(0)", start),
        ("microlink_usb_async_pump_stop_set(1)", stop),
        ("microlink_usb_async_xfer_active_get()", start),
        ("microlink_usb_async_xfer_active_get()", stop),
        ("microlink_usb_async_xfer_active_get()", get_char),
        ("microlink_usb_async_xfer_active_set(0)", callback),
        ("microlink_usb_device_gone_set(1)", callback),
        ("microlink_usb_device_gone_get()", device_getter),
        ("usb_device_gone = gone;", device_setter),
    )
    if any(call not in body for call, body in required_calls):
        raise ValidationError("candidate callback/pump/getchar/device/start-stop contract is incomplete")

    notice_end = source.find("*/")
    if notice_end < 0:
        raise ValidationError("upstream source license notice is missing")
    state_declarations = extract_state_declarations(source)
    device_helpers = "\n\n".join(
        signature + "\n" + function_body(source, signature)
        for signature in (
            "static int microlink_usb_device_gone_get(void)",
            "static void microlink_usb_device_gone_set(int gone)",
            "int microlink_usb_device_gone(void)",
        )
    )
    pump_source = function_body(source, PUMP_START)
    callback_source = function_body(source, CALLBACK_START)
    return (
        source[:notice_end + 2] + "\n\n"
        "#include <pthread.h>\n#include <sys/time.h>\n#include <stdlib.h>\n"
        "#define WITH_LIBUSB_1_0 1\n#define HAVE_PTHREAD 1\n"
        "#define MLINK_USB_REPORT_TOTAL_LEN 64U\n"
        "#define NUT_UNUSED_VARIABLE(value) ((void)(value))\n"
        "struct libusb_transfer;\n\n"
        "#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)\n"
        + state_declarations
        + "\n\nstatic int usb_device_gone = 0;\n\n"
        + device_helpers + "\n\n"
        + PUMP_START + "\n" + pump_source + "\n\n"
        + CALLBACK_START + "\n" + callback_source + "\n"
    )


def scratch_path(path: Path, forbidden_roots: tuple[Path, ...]) -> Path:
    requested = path.absolute()
    if path.is_symlink() or path.exists():
        raise ValidationError("scratch output must be a new, non-symlink path")
    resolved = path.resolve()
    if requested != resolved:
        raise ValidationError("scratch path must not traverse symlinks")
    for root in forbidden_roots:
        try:
            resolved.relative_to(root.resolve(strict=True))
        except ValueError:
            continue
        raise ValidationError("scratch output overlaps a repository or source checkout")
    return resolved


def run_replay(unit: str, scratch: Path, mode: str,
               forbidden_roots: tuple[Path, ...]) -> int:
    repository_root = Path(__file__).resolve().parents[2]
    scratch = scratch_path(scratch, (repository_root, *forbidden_roots))
    scratch.mkdir(parents=True, exist_ok=False)
    generated = scratch / "usb_async_state_generated.c"
    generated.write_text(unit, encoding="utf-8")
    if mode == "extract":
        print("extracted exact pump and async state declarations; compile/run NOT_REQUESTED")
        return 0

    binary = scratch / "test_usb_async_state"
    test_source = Path(__file__).with_name("test_usb_async_state.c")
    command = [
        "cc", "-std=c99", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-pthread", "-fsanitize=thread", "-fno-omit-frame-pointer",
        *(["-DEXPECT_CANDIDATE=1"] if mode == "green" else []),
        "-I", str(scratch), str(test_source), "-o", str(binary),
    ]
    try:
        build = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError("ThreadSanitizer harness compiler unavailable; runtime evidence NOT_RUN") from error
    (scratch / "compiler.stdout.txt").write_text(build.stdout, encoding="utf-8")
    (scratch / "compiler.stderr.txt").write_text(build.stderr, encoding="utf-8")
    if build.returncode != 0:
        raise ValidationError("ThreadSanitizer harness compile failed; runtime evidence NOT_RUN")
    try:
        nm = subprocess.run(["nm", "-u", str(binary)], check=True, capture_output=True, text=True, timeout=10)
        otool = subprocess.run(["otool", "-L", str(binary)], check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValidationError("binary inspection failed; runtime evidence NOT_RUN") from error
    (scratch / "symbols.txt").write_text(nm.stdout, encoding="utf-8")
    (scratch / "libraries.txt").write_text(otool.stdout, encoding="utf-8")
    library_lines = "\n".join(otool.stdout.splitlines()[1:])
    linkage = (nm.stdout + library_lines).lower()
    if any(token in linkage for token in ("libusb", "usb_", "upsdrv_", "libnut")):
        raise ValidationError("synthetic replay unexpectedly links USB or NUT symbols")
    print("symbol/library fence passed before test process")
    environment = os.environ.copy()
    # macOS defaults to aborting; retain the reviewed diagnostic exit code.
    environment["TSAN_OPTIONS"] = TSAN_OPTIONS
    cases = (
        ("pump", "async pump shared-state check passed\n",
         "microlink_usb_async_pump", "writer_thread", "async_pump_stop"),
        ("device", "device-gone callback shared-state check passed\n",
         "microlink_usb_async_cb", "device_reader_thread", "usb_device_gone"),
        ("active", "active callback shared-state check passed\n",
         "microlink_usb_async_cb", "active_reader_thread", "async_xfer_active"),
    )
    for case, expected_stdout, expected_frame, expected_thread, expected_global in cases:
        try:
            result = subprocess.run([str(binary), case], capture_output=True,
                                    text=True, timeout=15, cwd=scratch, env=environment)
        except subprocess.TimeoutExpired as error:
            raise ValidationError("synthetic TSan process exceeded its 15 second bound") from error
        (scratch / f"{case}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (scratch / f"{case}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        (scratch / f"{case}.returncode.txt").write_text(str(result.returncode) + "\n", encoding="utf-8")
        if mode == "red":
            if not red_output_is_expected(result.returncode, result.stdout, result.stderr,
                                          expected_frame, expected_thread, expected_global):
                raise ValidationError(f"baseline did not report expected {case} state race")
        elif not green_output_is_expected(result.returncode, result.stdout,
                                          result.stderr, expected_stdout):
            raise ValidationError(f"candidate TSan {case} run failed or emitted unexpected output")
    if mode == "red":
        print("baseline RED: TSan reproduced pump-stop, device-gone and transfer-active races")
    else:
        print("candidate GREEN: extracted pump and callback state passed TSan")
    return 0


def red_output_is_expected(returncode: int, stdout: str, stderr: str,
                           expected_frame: str, expected_thread: str,
                           expected_global: str = "") -> bool:
    return (
        returncode == 66 and stdout == ""
        and "ThreadSanitizer: data race" in stderr
        and expected_frame in stderr and expected_thread in stderr
        and (not expected_global or f"Location is global '{expected_global}'" in stderr)
        and "ThreadSanitizer: unexpected memory mapping" not in stderr
    )


def green_output_is_expected(returncode: int, stdout: str, stderr: str,
                             expected_stdout: str) -> bool:
    return returncode == 0 and stderr == "" and stdout == expected_stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--mode", choices=("red", "green", "extract"), required=True)
    args = parser.parse_args()
    try:
        baseline_bytes = read_pinned_source(args.baseline_root, BASELINE_SHA256)
        candidate_bytes = read_pinned_source(args.candidate_root, CANDIDATE_SHA256)
        baseline = baseline_bytes.decode("utf-8")
        candidate = candidate_bytes.decode("utf-8")
        validate_baseline(baseline)
        if args.mode == "red":
            source = baseline
            notice_end = source.find("*/")
            if notice_end < 0:
                raise ValidationError("could not extract pinned baseline state")
            state_declarations = extract_state_declarations(source)
            pump = function_body(source, PUMP_START)
            callback = function_body(source, CALLBACK_START)
            device_getter = function_body(source, "int microlink_usb_device_gone(void)")
            unit = (
                source[:notice_end + 2] + "\n\n#include <pthread.h>\n#include <sys/time.h>\n#include <stdlib.h>\n"
                "#define WITH_LIBUSB_1_0 1\n#define HAVE_PTHREAD 1\n"
                "#define MLINK_USB_REPORT_TOTAL_LEN 64U\n"
                "#define NUT_UNUSED_VARIABLE(value) ((void)(value))\n"
                "struct libusb_transfer;\n\n"
                "static int usb_device_gone = 0;\n\n"
                "#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)\n"
                + state_declarations + "\n\n"
                + "int microlink_usb_device_gone(void)\n" + device_getter + "\n\n"
                + PUMP_START + "\n" + pump + "\n\n"
                + CALLBACK_START + "\n" + callback + "\n"
            )
        else:
            unit = validate_candidate(candidate)
        return run_replay(unit, args.scratch, args.mode,
                          (args.baseline_root, args.candidate_root))
    except (ValidationError, UnicodeDecodeError, OSError) as error:
        print(f"validation error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
