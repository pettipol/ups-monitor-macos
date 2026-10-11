#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replay guarded-dump signal handling from source-pinned NUT main.c excerpts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys


PIN = "73c4502191d025e35122463986a80c676e734b04"
MAIN_SOURCE = Path("drivers/main.c")
BASELINE_SHA256 = "113fd840bb22bc2d9dea9d6761a3e86e36c0eef60b2854ce12cfcc68373fe8ed"
CANDIDATE_SHA256 = "a5bee8705ddb293c216ab57f03add7702cb967fd56d2b582187b2a164d0ba074"
EXPECTED_RED = (
    "FAIL SIGTERM did not exit cooperatively with atexit",
    "FAIL SIGINT did not exit cooperatively with atexit",
    "FAIL SIGQUIT did not exit cooperatively with atexit",
    "FAIL inherited ignored SIGTERM was not handled cooperatively",
    "4 synthetic termination check(s) failed",
)


class ValidationError(Exception):
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
        raise ValidationError("could not verify source checkout") from error
    return result.stdout.strip()


def read_pinned_main(root: Path, expected_sha256: str) -> bytes:
    root = root.resolve(strict=True)
    if not root.is_dir() or git_output(root, "rev-parse", "HEAD") != PIN:
        raise ValidationError("source checkout HEAD does not match the pinned revision")
    source_path = root / MAIN_SOURCE
    if source_path.is_symlink() or not source_path.is_file():
        raise ValidationError("pinned main.c is missing or is a symlink")
    content = source_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValidationError("pinned main.c SHA-256 mismatch")
    return content


def extract_candidate_unit(content: bytes) -> str:
    source = content.decode("utf-8")
    notice_end = source.find("*/")
    start_marker = "static volatile sig_atomic_t guarded_dump_signal = 0;"
    end_marker = "\n# ifndef DRIVERS_MAIN_WITHOUT_MAIN\nstatic\n# endif /* DRIVERS_MAIN_WITHOUT_MAIN */\nvoid setup_signals(void)"
    start = source.find(start_marker)
    end = source.find(end_marker, start)
    if notice_end < 0 or start < 0 or end < 0 or source.find(start_marker, start + 1) >= 0:
        raise ValidationError("could not locate unique guarded dump signal helpers")
    return source[:notice_end + 2] + "\n\n" + source[start:end].rstrip() + "\n"


def validate_candidate_source(content: bytes) -> str:
    source = content.decode("utf-8")
    unit = extract_candidate_unit(content)
    helper_start = source.find("static volatile sig_atomic_t guarded_dump_signal = 0;")
    posix_signal_block_start = source.find(
        "#ifndef WIN32\n"
        "/* TODO: Equivalent for WIN32 - see SIGCMD_RELOAD in upd and upsmon */\n"
        "static void handle_dstate_dump(int sig)"
    )
    posix_signal_block_end = source.find("#endif /* !WIN32*/", helper_start)
    if not (posix_signal_block_start < helper_start < posix_signal_block_end):
        raise ValidationError("signal helper and flag must remain inside the POSIX-only source block")
    handler = re.search(
        r"static void guarded_dump_signal_handler\(int sig\)\s*\{\s*"
        r"guarded_dump_signal\s*=\s*sig;\s*\}",
        unit,
    )
    if handler is None:
        raise ValidationError("signal handler must only assign the sig_atomic_t flag")
    if "exit(EXIT_FAILURE);" not in unit:
        raise ValidationError("cooperative dump cancellation must not report a successful dump")
    if unit.count("static int setup_guarded_dump_signals(void)") != 1:
        raise ValidationError("dedicated guarded dump setup function is missing or ambiguous")
    if "int signals[] = {SIGTERM, SIGINT, SIGQUIT};" not in unit:
        raise ValidationError("dedicated setup signal set is incomplete or reordered")
    if "sigaction(signals[i], &sa, NULL)" not in unit:
        raise ValidationError("dedicated setup does not install the reviewed signal set")
    if "sigaction(" not in unit or "return -1;" not in unit:
        raise ValidationError("dedicated setup must report sigaction failures")

    guarded_checkpoint = re.compile(
        r"(?m)^# ifndef WIN32\s*\n[ \t]*"
        r"exit_if_guarded_dump_signal_requested\(\);\s*\n"
        r"# endif\s*/\* !WIN32 \*/$"
    )
    guarded_checkpoints = list(guarded_checkpoint.finditer(source))
    if len(guarded_checkpoints) != 7:
        raise ValidationError("POSIX-only checkpoint calls must each be guarded from Windows builds")
    if source.count("exit_if_guarded_dump_signal_requested();") != 8:
        raise ValidationError("unexpected guarded dump checkpoint call count")
    while_guard = (
        "while (!exit_flag\n"
        "# ifndef WIN32\n"
        "\t\t&& !guarded_dump_signal\n"
        "# endif\t/* !WIN32 */\n"
        "\t) {"
    )
    if while_guard not in source:
        raise ValidationError("main loop signal predicate is not excluded from Windows builds")

    setup_call = source.find("setup_guarded_dump_signals() != 0")
    guarded_gate = source.find('if (testvar("guarded_monitor"))')
    first_open = source.find("upsdrv_callbacks.upsdrv_initups();")
    if not (0 <= guarded_gate < setup_call < first_open):
        raise ValidationError("guarded dump signals are not installed before driver initialization")
    setup_context = source[guarded_gate:setup_call]
    if "nut_guard_allows_dump_mode(" not in setup_context or "fatalx(EXIT_FAILURE" not in setup_context:
        raise ValidationError("signal setup is not gated by guarded dump mode validation")
    if "# ifdef WIN32" not in setup_context or "# else" not in setup_context:
        raise ValidationError("guarded setup must be excluded from the Windows branch")
    guarded_branch_end = source.find("# endif\t/* WIN32 */", setup_call)
    guarded_branch_checkpoint = source.find("exit_if_guarded_dump_signal_requested();", setup_call)
    if not (setup_call < guarded_branch_checkpoint < guarded_branch_end):
        raise ValidationError("guarded setup checkpoint must remain inside the POSIX-only guarded branch")
    pre_open_check = source.rfind("exit_if_guarded_dump_signal_requested();", 0, first_open)
    if pre_open_check < setup_call or source[pre_open_check:first_open].count("exit_if_guarded_dump_signal_requested();") != 1:
        raise ValidationError("missing cooperative cancellation checkpoint immediately before driver initialization")
    failure_block = source[setup_call:source.find("\n\t\t}", setup_call) + 4]
    if "fatal_with_errno(EXIT_FAILURE" not in failure_block:
        raise ValidationError("sigaction setup failure is not fatal before driver initialization")

    loop_start = source.find(while_guard)
    final_exit = source.rfind("exit(exit_flag == EF_EXIT_FAILURE ? EXIT_FAILURE : EXIT_SUCCESS);")
    final_checkpoint = source.rfind(
        "# ifndef WIN32\n"
        "\texit_if_guarded_dump_signal_requested();\n"
        "# endif\t/* !WIN32 */\n"
        "\t/* if we get here, the exit flag was set by a signal handler */",
        0,
        final_exit,
    )
    if not (loop_start >= 0 and loop_start < final_checkpoint < final_exit):
        raise ValidationError("missing final cancellation checkpoint after the main loop")
    checkpoints = (
        source.find("exit_if_guarded_dump_signal_requested();", setup_call),
        source.find("atexit(exit_upsdrv_cleanup);"),
        source.find("exit_if_guarded_dump_signal_requested();", source.find("atexit(exit_upsdrv_cleanup);")),
        source.find("upsdrv_callbacks.upsdrv_initinfo();"),
        source.find("exit_if_guarded_dump_signal_requested();", source.find("upsdrv_callbacks.upsdrv_initinfo();")),
        source.find("upsdrv_callbacks.upsdrv_updateinfo();", source.find("upsdrv_callbacks.upsdrv_initinfo();")),
        source.find("exit_if_guarded_dump_signal_requested();", source.find("upsdrv_callbacks.upsdrv_updateinfo();", source.find("upsdrv_callbacks.upsdrv_initinfo();"))),
        loop_start,
    )
    if any(position < 0 for position in checkpoints) or tuple(checkpoints) != tuple(sorted(checkpoints)):
        raise ValidationError("guarded dump cancellation checkpoints are missing or out of order")
    if source.count("exit_if_guarded_dump_signal_requested();") < 5:
        raise ValidationError("expected cooperative checkpoints are incomplete")
    return unit


def validate_baseline_source(content: bytes) -> None:
    source = content.decode("utf-8")
    if "guarded_dump_signal" in source or "setup_guarded_dump_signals" in source:
        raise ValidationError("RED source unexpectedly contains the guarded signal fix")
    start = source.find("if (do_forceshutdown || dump_data) {")
    end = source.find("# endif\t/* !WIN32 */", start)
    block = source[start:end] if start >= 0 and end >= 0 else ""
    if (
        not block
        or "else {" not in block
        or block.count("setup_signals();") != 1
        or block.find("setup_signals();") < block.find("else {")
    ):
        raise ValidationError("baseline does not show dump mode skipping the regular signal setup")


def run_harness(unit: str, scratch: Path, mode: str, source_roots: tuple[Path, ...]) -> int:
    if scratch.is_symlink() or scratch.exists():
        raise ValidationError("scratch output must be a new, non-symlink path")
    requested_scratch = scratch.absolute()
    scratch = scratch.resolve()
    if requested_scratch != scratch:
        raise ValidationError("scratch output path must not traverse symlinks")
    repository_root = Path(__file__).resolve().parents[2]
    forbidden_roots = (repository_root, *(root.resolve(strict=True) for root in source_roots))
    for forbidden_root in forbidden_roots:
        try:
            scratch.relative_to(forbidden_root)
        except ValueError:
            continue
        raise ValidationError("scratch output must be outside the product repository")
    scratch.mkdir(parents=True, exist_ok=False)
    generated = scratch / "guarded_dump_signal_generated.c"
    generated.write_text(unit, encoding="utf-8")
    if mode == "extract":
        print("extracted the pinned signal helper; compilation not requested")
        return 0

    binary = scratch / "test_guarded_dump_signals"
    test_source = Path(__file__).with_name("test_guarded_dump_signals.c")
    command = [
        "cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
        "-fno-sanitize-recover=undefined", "-I", str(scratch), str(test_source), "-o", str(binary),
    ]
    subprocess.run(command, check=True)
    print("synthetic signal harness compiled; no NUT driver or USB API linked")
    nm_result = subprocess.run(["nm", "-u", str(binary)], check=True, capture_output=True, text=True)
    otool_result = subprocess.run(["otool", "-L", str(binary)], check=True, capture_output=True, text=True)
    linkage = (nm_result.stdout + otool_result.stdout).lower()
    if any(token in linkage for token in ("libusb", "usb_", "upsdrv_", "libnut")):
        raise ValidationError("synthetic test binary unexpectedly references USB or NUT symbols/libraries")
    print("nm/otool linkage fence passed before synthetic child execution")
    result = subprocess.run(
        [str(binary)], check=False, capture_output=True, text=True, timeout=15, cwd=scratch
    )
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if mode == "red":
        if result.returncode != 1 or result.stderr or tuple(result.stdout.splitlines()) != EXPECTED_RED:
            raise ValidationError("baseline did not produce the exact controlled RED result")
        print("RED models baseline default/ignored dispositions in a synthetic child; main.c is not executed")
        print(result.stdout, end="")
        print("baseline RED reproduced")
        return 0
    if result.returncode != 0 or result.stderr or result.stdout != "all guarded dump signal validation checks passed\n":
        raise ValidationError("candidate synthetic signal harness failed or emitted unexpected output")
    print(result.stdout, end="")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--mode", choices=("red", "green", "extract"), required=True)
    args = parser.parse_args()
    try:
        baseline = read_pinned_main(args.baseline_root, BASELINE_SHA256)
        candidate = read_pinned_main(args.candidate_root, CANDIDATE_SHA256)
        validate_baseline_source(baseline)
        if args.mode == "red":
            unit = (
                "static volatile sig_atomic_t guarded_dump_signal = 0;\n"
                "static int setup_guarded_dump_signals(void) { return 0; }\n"
                "static void exit_if_guarded_dump_signal_requested(void) { "
                "if (guarded_dump_signal) { exit(EXIT_FAILURE); } }\n"
            )
        else:
            unit = validate_candidate_source(candidate)
        return run_harness(unit, args.scratch, args.mode, (args.baseline_root, args.candidate_root))
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValidationError) as error:
        print(f"signal replay failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
