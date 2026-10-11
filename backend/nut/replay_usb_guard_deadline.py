# SPDX-License-Identifier: MIT
"""Build and run a bounded synthetic replay of the guarded USB callback."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_usb_async_state import function_body as source_function_body
from replay_usb_async_state import code_only, scratch_path, ValidationError


BASE_HEAD = "73c4502191d025e35122463986a80c676e734b04"
BASE_USB_SHA = "7929a4869cfee9c08734c1b9b5c091c3f7c62496e0981031c2c9ad149ecc33b0"
BASE_HEADER_SHA = "2998edbfed84914339f3cdf3f0f0bb501e165a27a9628f2e355635a06e2ab34c"
BASE_DRIVER_SHA = "958919e06e333a1b7137711811f4984d65db51ff6988ec04d6f8105d1b438ee1"
CANDIDATE_USB_SHA = "1b7e3d3b8cdb54910e68f28a8bea4e10b6f4cdef4f5143ffacd64ff2aa6af42a"
CANDIDATE_HEADER_SHA = "1b0ac143a8c99a161930562b441f1340ca8bd971d4bb2315e46a98e1b8a75ba8"
CANDIDATE_MAIN_SHA = "3bc7eadc8e2fae657df1b8f0e37f3baf53fd9a6e20a7da3c029d218193d2177d"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(root: Path, relative: str, expected: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or sha256(path) != expected:
        raise ValueError(f"source pin failed: {relative}")
    return path


def run_checked(args: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False)


def extract_function(source: str, name: str) -> str:
    signature_matches = list(re.finditer(r"(?m)^(?:static[ \t]+)?(?:int|void)[ \t]+(?:LIBUSB_CALL[ \t]+)?"
                                        + re.escape(name) + r"\s*\([^;{}]*\)(?=\s*\{)", source))
    conditional_exports = name in ("microlink_usb_guard_begin", "microlink_usb_guard_expired")
    if len(signature_matches) != 1 and not (conditional_exports and len(signature_matches) == 2):
        raise ValueError(f"expected one definition of {name}, found {len(signature_matches)}")
    signature = signature_matches[0].group(0)
    try:
        return signature + "\n" + source_function_body(source, signature, allow_multiple=conditional_exports)
    except ValidationError as error:
        raise ValueError(f"invalid function body: {name}") from error


def extract_region(source: str) -> str:
    start = source.find("#define MLINK_USB_ASYNC_QUEUE_LEN")
    end_marker = "#endif /* WITH_LIBUSB_1_0 && HAVE_PTHREAD */"
    end = source.find(end_marker, start)
    if start < 0 or end < 0 or source.find("#define MLINK_USB_ASYNC_QUEUE_LEN", start + 1) >= 0:
        raise ValueError("async state region markers missing or ambiguous")
    return source[start:end + len(end_marker)]


def validate_candidate_callpaths(usb: str, driver: str) -> None:
    usb = code_only(usb)
    driver = code_only(driver)
    cb = source_function_body(usb, "static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer)")
    start = source_function_body(usb, "static int microlink_usb_async_start(void)")
    getter = source_function_body(usb, "int microlink_usb_get_char(unsigned char *ch, long d_usec)", allow_multiple=True)
    flush = source_function_body(usb, "void microlink_usb_flush_io(void)")
    initups = source_function_body(driver, "void upsdrv_initups(void)")
    initinfo = source_function_body(driver, "void upsdrv_initinfo(void)")
    reopen = source_function_body(usb, "int microlink_usb_reset_and_reopen(void)")
    opening = source_function_body(usb, "int microlink_usb_open(void)")
    if cb.count("microlink_usb_guard_expired_locked()") < 2:
        raise ValueError("callback lacks expiry gates before decode and resubmit")
    decode_at = cb.find("microlink_usb_try_decode_fallback(")
    queue_at = cb.find("async_queue_count++")
    resubmit_at = cb.find("libusb_submit_transfer(transfer)")
    resubmit_budget_at = cb.rfind("microlink_usb_guard_timeout_ms_locked(", 0, resubmit_at)
    if not (0 <= decode_at and 0 <= queue_at and 0 <= resubmit_budget_at < resubmit_at):
        raise ValueError("callback deadline does not fence decode/queue/resubmit")
    initial_fill = start.find("libusb_fill_interrupt_transfer(")
    initial_budget = start.rfind("microlink_usb_guard_timeout_ms_locked(", 0, initial_fill)
    initial_submit = start.find("libusb_submit_transfer(", initial_fill)
    allocation = start.find("libusb_alloc_transfer(")
    final_budget = start.rfind("microlink_usb_guard_timeout_ms_locked(", 0, initial_submit)
    if not (0 <= allocation < initial_budget < initial_fill < final_budget < initial_submit):
        raise ValueError("initial transfer timeout is not derived before submit")
    if "async_xfer->timeout = timeout_ms;" not in start[final_budget:initial_submit]:
        raise ValueError("refreshed timeout is not assigned before initial submit")
    if "timeout_ms" not in start[initial_fill:initial_submit]:
        raise ValueError("initial transfer does not receive the bounded timeout")
    if "microlink_usb_get_char_sync" not in getter or "if (!guarded" not in getter:
        raise ValueError("ordinary synchronous fallback path is no longer visibly preserved")
    if "guarded && (expired || !async_xfer_active)" not in getter:
        raise ValueError("guarded getter does not reject expired/inactive listener")
    if "microlink_usb_guard_expired_locked()" not in flush or "!async_xfer_active" not in flush:
        raise ValueError("flush lacks guarded inactive/expiry gate")
    begin_at = initups.find("microlink_usb_guard_begin(")
    open_at = initups.find("microlink_usb_open(")
    if not (0 <= begin_at < open_at) or initups.count("microlink_usb_guard_begin(") != 1:
        raise ValueError("deadline must begin exactly once before USB open")
    if "microlink_guard_deadline_begin" in driver or driver.count("microlink_usb_guard_begin(") != 1:
        raise ValueError("session/reconnect must not renew the observation budget")
    initinfo_gate = initinfo.find("microlink_guard_deadline_expired()")
    if not (0 <= initinfo_gate < initinfo.find("memset(objects")):
        raise ValueError("initinfo must reject a terminal listener before session setup")
    start_failure = source_function_body(opening, "if (!microlink_usb_async_start())")
    if ("microlink_usb_guard_invalidate();" not in start_failure or "return 0;" not in start_failure
            or any(call in start_failure for call in ("fatalx(", "close_dev(", "libusb_free_transfer(", "free("))):
        raise ValueError("open must defer guarded listener failure without premature fatal/close")
    first_reopen_gate = reopen.find("microlink_usb_guard_expired()")
    reopen_call = reopen.find("comm_driver->open_dev(")
    second_reopen_gate = reopen.rfind("microlink_usb_guard_expired()", 0, reopen_call)
    if not (0 <= first_reopen_gate < second_reopen_gate < reopen_call):
        raise ValueError("reopen must check the unchanged budget twice before opening")


def extract_device_setter(source: str) -> str:
    return extract_function(source, "microlink_usb_device_gone_set")


def generate(usb: str, generated: Path, candidate: bool) -> None:
    region = extract_region(usb)
    first_helper = "static int microlink_usb_guard_remaining_ms_locked" if candidate else "static int microlink_usb_async_xfer_active_get"
    declaration_end = region.find(first_helper)
    if declaration_end < 0:
        raise ValueError("state declarations do not precede the reviewed helpers")
    declarations = region[:declaration_end]
    names = ["microlink_usb_async_xfer_active_get", "microlink_usb_async_xfer_active_set"]
    if candidate:
        names = ["microlink_usb_guard_remaining_ms_locked", "microlink_usb_guard_expired_locked",
                 "microlink_usb_guard_invalidate", "microlink_usb_guard_timeout_ms_locked",
                 "microlink_usb_guard_begin", "microlink_usb_guard_expired", *names]
    helpers = "\n\n".join(extract_function(usb, name) for name in names)
    callback = extract_function(usb, "microlink_usb_async_cb")
    setter = extract_device_setter(usb)
    preamble = usb.split("#include \"config.h\"", 1)[0] + """/* Synthetic replay: no NUT driver or USB API is executed. */
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define WITH_LIBUSB_1_0 1
#define HAVE_PTHREAD 1
#define HAVE_CLOCK_GETTIME 1
#define HAVE_CLOCK_MONOTONIC 1
#define clock_gettime fake_clock_gettime
#define MLINK_USB_REPORT_TOTAL_LEN 64U
static int usb_device_gone;
"""
    body = declarations + "\n" + helpers + "\n" + setter + "\n" + callback
    generated.write_text(preamble + body + "\n")


def inspect_binary(binary: Path, scratch: Path) -> None:
    nm = run_checked(["nm", "-u", str(binary)], timeout=5)
    otool = run_checked(["otool", "-L", str(binary)], timeout=5)
    if nm.returncode != 0 or otool.returncode != 0:
        raise ValueError("binary inspection failed")
    # Only shared-library rows are relevant; the first otool row is the binary path.
    libraries = "\n".join(otool.stdout.splitlines()[1:])
    if re.search(r"libusb|libnut|libhidapi|IOKit|usb_|upsdrv_", nm.stdout + libraries, re.I):
        raise ValueError("synthetic harness unexpectedly links USB/NUT/system USB libraries")
    (scratch / "nm.txt").write_text(nm.stdout)
    (scratch / "otool.txt").write_text(otool.stdout)


def run_replay(mode: str, source: Path, scratch: Path, compiler: str = "cc") -> int:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("invalid or symlink source root")
    root = source.resolve(strict=True)
    repo = Path(__file__).resolve().parents[2]
    scratch = scratch_path(scratch, (repo, root))
    candidate = mode != "red"
    head = run_checked(["git", "rev-parse", "HEAD"], timeout=5, cwd=root)
    if head.returncode != 0 or head.stdout.strip() != BASE_HEAD:
        raise ValueError("source HEAD mismatch")
    usb_hash = CANDIDATE_USB_SHA if candidate else BASE_USB_SHA
    header_hash = CANDIDATE_HEADER_SHA if candidate else BASE_HEADER_SHA
    usb_path = checked_file(root, "drivers/apcmicrolink-usb.c", usb_hash)
    checked_file(root, "drivers/apcmicrolink-usb.h", header_hash)
    driver_path = checked_file(root, "drivers/apcmicrolink.c", CANDIDATE_MAIN_SHA if candidate else BASE_DRIVER_SHA)
    usb = usb_path.read_text()
    if candidate:
        validate_candidate_callpaths(usb, driver_path.read_text())
    scratch.mkdir(parents=True, exist_ok=False)
    generated = scratch / "usb_guard_deadline_generated.c"
    generate(usb, generated, candidate)
    if mode == "extract":
        print("PASS extract: no compilation or execution requested")
        return 0
    source_test = Path(__file__).with_name("test_usb_guard_deadline.c")
    shutil.copyfile(source_test, scratch / source_test.name)
    binary = scratch / "replay"
    compile_args = [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pthread",
                    "-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
    if candidate:
        compile_args.append("-DEXPECT_CANDIDATE=1")
    compile_args += [str(scratch / source_test.name), "-o", str(binary)]
    compiled = run_checked(compile_args, timeout=30, cwd=scratch)
    (scratch / "compile.stdout").write_text(compiled.stdout)
    (scratch / "compile.stderr").write_text(compiled.stderr)
    if compiled.returncode != 0 or compiled.stderr:
        raise ValueError("synthetic harness compile failed or emitted diagnostics")
    inspect_binary(binary, scratch)
    expected = {
        "expired": "expired callback suppressed decode, queue, and resubmit\n",
        "valid": "fixed budget rounded up and valid callback resubmitted within remainder\n",
        "clock-error": "monotonic clock failure made guard terminal\n",
        "invalid-clock": "invalid monotonic timestamp rejected\n",
        "boundary": "fractional boundary and exact expiry handled correctly\n",
        "negative": "negative elapsed time made guard terminal\n",
        "normal": "normal callback and terminal statuses preserved\n",
        "maximum": "maximum budget remained finite and nonrenewable\n",
        "invalidate": "explicit invalidation remained terminal\n",
    }
    cases = ["expired"] if not candidate else list(expected)
    for case in cases:
        result = run_checked([str(binary), case], timeout=10, cwd=scratch)
        (scratch / f"{case}.stdout").write_text(result.stdout)
        (scratch / f"{case}.stderr").write_text(result.stderr)
        (scratch / f"{case}.returncode").write_text(str(result.returncode) + "\n")
        if result.stderr:
            raise ValueError(f"{case}: unexpected stderr")
        if not candidate:
            if (result.returncode, result.stdout) != (1, "FAIL callback continued after observation deadline\n"):
                raise ValueError("baseline did not produce exact expected RED")
        elif (result.returncode, result.stdout) != (0, expected[case]):
            raise ValueError(f"{case}: candidate did not produce exact expected GREEN")
    static_note = "candidate callpaths checked statically" if candidate else "baseline callback only"
    print(f"PASS {mode}: synthetic extracted helpers/callback replay; {static_note}; logs={scratch}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("red", "green", "extract"), required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--compiler", default="cc")
    args = parser.parse_args()
    try:
        return run_replay(args.mode, args.source, args.scratch, args.compiler)
    except (OSError, ValueError, ValidationError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL {args.mode}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
