#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Observe the pinned Microlink listener lifecycle with local-only mocks.

The generated C preserves the pinned driver function bodies. No NUT, USB,
IOKit, or libusb library is linked; the C fixture supplies local stubs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_usb_async_state as async_replay  # noqa: E402
import replay_usb_guard_deadline as deadline_replay  # noqa: E402


SOURCE_FILES = {
    "drivers/apcmicrolink-usb.c": deadline_replay.CANDIDATE_USB_SHA,
    "drivers/apcmicrolink-usb.h": deadline_replay.CANDIDATE_HEADER_SHA,
    "drivers/apcmicrolink.c": deadline_replay.CANDIDATE_MAIN_SHA,
}
EXPECTED_CASES = {
    f"{profile}-{scenario}": (1, "RED pending transfer observed at close with owner cleared\n")
    for profile in ("ordinary", "guarded")
    for scenario in ("create-failure", "cancel-pending", "cancel-not-found")
}
EXPECTED_CASES.update({
    f"{profile}-cancel-completed": (0, "CONTROL cancellation callback reaped before close\n")
    for profile in ("ordinary", "guarded")
})
CASE_TIMEOUT_SECONDS = 10
COMPILE_TIMEOUT_SECONDS = 30
TEST_SOURCE = Path(__file__).with_name("test_usb_lifecycle_observation.c")
GENERATED_NAME = "usb_lifecycle_observation_generated.c"


class ReplayError(Exception):
    """A source, extraction, toolchain, or replay contract failed."""


def read_candidate(source_root: Path) -> tuple[Path, dict[str, bytes]]:
    if source_root.is_symlink() or not source_root.is_dir():
        raise ReplayError("source root must be a real directory")
    root = source_root.resolve(strict=True)
    repository = Path(__file__).resolve().parents[2]
    if root == repository or root.is_relative_to(repository) or repository.is_relative_to(root):
        raise ReplayError("source root must be external to the product repository")
    try:
        head = deadline_replay.run_checked(["git", "rev-parse", "HEAD"], timeout=5, cwd=root)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReplayError("source HEAD verification failed or timed out") from error
    if head.returncode != 0 or head.stdout.strip() != deadline_replay.BASE_HEAD:
        raise ReplayError("source HEAD does not match frozen candidate")
    contents: dict[str, bytes] = {}
    for relative, expected_hash in SOURCE_FILES.items():
        try:
            path = deadline_replay.checked_file(root, relative, expected_hash)
            contents[relative] = path.read_bytes()
        except (OSError, ValueError) as error:
            raise ReplayError(f"source pin failed: {relative}") from error
    return root, contents


def _one_source_declaration(source: str, declaration: str) -> str:
    if source.count(declaration) != 1:
        raise ReplayError("required source declaration is missing or ambiguous")
    return declaration


def _exact_function(source: str, signature: str) -> str:
    try:
        return signature + "\n" + async_replay.function_body(source, signature)
    except async_replay.ValidationError as error:
        raise ReplayError("source lifecycle function is missing or ambiguous") from error


def generate(source: str) -> str:
    """Return a TU containing source-exact state and lifecycle definitions."""
    try:
        region = deadline_replay.extract_region(source)
        state_end = region.find("static int microlink_usb_guard_remaining_ms_locked")
        if state_end < 0:
            raise ReplayError("guarded async state declarations are missing")
        declarations = region[:state_end]
        helpers_and_guard = region[state_end:]
        functions = [
            _exact_function(source, "static int microlink_usb_device_gone_get(void)"),
            _exact_function(source, "static void microlink_usb_device_gone_set(int gone)"),
            _exact_function(source, "static void *microlink_usb_async_pump(void *arg)"),
            _exact_function(source, "static void LIBUSB_CALL microlink_usb_async_cb(struct libusb_transfer *transfer)"),
            _exact_function(source, "static int microlink_usb_async_start(void)"),
            _exact_function(source, "static void microlink_usb_async_stop(void)"),
            _exact_function(source, "void microlink_usb_close(void)"),
        ]
        device_state = _one_source_declaration(source, "static int usb_device_gone = 0;")
        license_end = source.find("*/")
        if license_end < 0:
            raise ReplayError("candidate GPL source header is missing")
    except (ValueError, async_replay.ValidationError) as error:
        if isinstance(error, ReplayError):
            raise
        raise ReplayError("source lifecycle extraction failed") from error

    return (
        source[:license_end + 2]
        + "\n\n/* Source-exact lifecycle subset; mocks live in the C fixture. */\n"
        + "#include <pthread.h>\n#include <stdlib.h>\n#include <string.h>\n"
        + "#include <sys/time.h>\n#include <time.h>\n"
        + "#define WITH_LIBUSB_1_0 1\n#define HAVE_PTHREAD 1\n"
        + "#define HAVE_CLOCK_GETTIME 1\n#define HAVE_CLOCK_MONOTONIC 1\n"
        + "#define MLINK_USB_REPORT_TOTAL_LEN 64U\n"
        + "#define NUT_UNUSED_VARIABLE(value) ((void)(value))\n"
        + device_state + "\n\n"
        + "#if WITH_LIBUSB_1_0 && defined(HAVE_PTHREAD)\n"
        + declarations + "\n\n"
        + helpers_and_guard + "\n\n"
        + "\n\n".join(functions) + "\n"
    )


def scope_manifest(mode: str, contents: dict[str, bytes], generated: bytes | None = None,
                   fixture: bytes | None = None,
                   compiler_command: list[str] | None = None) -> dict[str, object]:
    manifest: dict[str, object] = {
        "mode": mode,
        "source_head": deadline_replay.BASE_HEAD,
        "source_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
        "extracted_functions": [
            "microlink_usb_device_gone_get", "microlink_usb_device_gone_set",
            "microlink_usb_async_pump", "microlink_usb_async_cb",
            "microlink_usb_async_start", "microlink_usb_async_stop", "microlink_usb_close",
        ],
        "case_expectations": EXPECTED_CASES,
        "runtime_scope": "synthetic local mocks only; no USB/NUT/IOKit libraries",
        "generated_sha256": hashlib.sha256(generated).hexdigest() if generated is not None else None,
        "c_fixture_sha256": hashlib.sha256(fixture).hexdigest() if fixture is not None else None,
        "compiler_command": compiler_command,
    }
    return manifest


def validate_case_result(case: str, returncode: int, stdout: str, stderr: str) -> None:
    if case not in EXPECTED_CASES:
        raise ReplayError("unknown lifecycle case")
    expected_code, expected_stdout = EXPECTED_CASES[case]
    if returncode != expected_code or stdout != expected_stdout or stderr != "":
        raise ReplayError(f"{case}: unexpected return code or output")


def run_case(binary: Path, case: str, scratch: Path) -> None:
    try:
        result = deadline_replay.run_checked([str(binary), case],
                                             timeout=CASE_TIMEOUT_SECONDS, cwd=scratch)
    except subprocess.TimeoutExpired as error:
        (scratch / f"{case}.timeout").write_text("timeout\n", encoding="utf-8")
        raise ReplayError(f"{case}: synthetic lifecycle process timed out") from error
    (scratch / f"{case}.stdout").write_text(result.stdout, encoding="utf-8")
    (scratch / f"{case}.stderr").write_text(result.stderr, encoding="utf-8")
    (scratch / f"{case}.returncode").write_text(f"{result.returncode}\n", encoding="utf-8")
    validate_case_result(case, result.returncode, result.stdout, result.stderr)


def _write_manifest(scratch: Path, manifest: dict[str, object]) -> None:
    (scratch / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(mode: str, source_root: Path, scratch: Path, compiler: str = "cc") -> int:
    if mode not in ("observe", "extract"):
        raise ReplayError("invalid mode")
    source, contents = read_candidate(source_root)
    repository = Path(__file__).resolve().parents[2]
    scratch = async_replay.scratch_path(scratch, (repository, source))
    usb = contents["drivers/apcmicrolink-usb.c"].decode("utf-8")
    driver = contents["drivers/apcmicrolink.c"].decode("utf-8")
    try:
        deadline_replay.validate_candidate_callpaths(usb, driver)
    except ValueError as error:
        raise ReplayError("pinned candidate callpath validation failed") from error

    generated_text = generate(usb)
    generated_bytes = generated_text.encode("utf-8")
    scratch.mkdir(parents=True, exist_ok=False)
    (scratch / GENERATED_NAME).write_bytes(generated_bytes)
    fixture_bytes = TEST_SOURCE.read_bytes() if TEST_SOURCE.is_file() and not TEST_SOURCE.is_symlink() else None
    manifest = scope_manifest(mode, contents, generated_bytes, fixture_bytes)
    if mode == "extract":
        manifest["result"] = "extracted; compile and execution not requested"
        _write_manifest(scratch, manifest)
        print(f"EXTRACT lifecycle functions preserved; logs={scratch}")
        return 0

    if not TEST_SOURCE.is_file() or TEST_SOURCE.is_symlink():
        manifest["result"] = "failed: synthetic C test source missing"
        _write_manifest(scratch, manifest)
        raise ReplayError("synthetic lifecycle C test source is missing")
    test_copy = scratch / TEST_SOURCE.name
    if fixture_bytes is None:
        manifest["result"] = "failed: synthetic C test source missing"
        _write_manifest(scratch, manifest)
        raise ReplayError("synthetic lifecycle C test source is missing")
    test_copy.write_bytes(fixture_bytes)
    binary = scratch / "lifecycle-observation"
    command = [
        compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pthread",
        "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
        "-I", str(scratch), str(test_copy), "-o", str(binary),
    ]
    manifest["compiler_command"] = command
    _write_manifest(scratch, manifest)
    try:
        compiled = deadline_replay.run_checked(command, timeout=COMPILE_TIMEOUT_SECONDS, cwd=scratch)
    except subprocess.TimeoutExpired as error:
        (scratch / "compile.timeout").write_text("timeout\n", encoding="utf-8")
        manifest["result"] = "failed: compile timed out"
        _write_manifest(scratch, manifest)
        raise ReplayError("synthetic lifecycle compile timed out") from error
    (scratch / "compile.stdout").write_text(compiled.stdout, encoding="utf-8")
    (scratch / "compile.stderr").write_text(compiled.stderr, encoding="utf-8")
    if compiled.returncode != 0 or compiled.stderr:
        manifest["result"] = "failed: compile contract"
        _write_manifest(scratch, manifest)
        raise ReplayError("synthetic lifecycle C test failed compilation")

    try:
        deadline_replay.inspect_binary(binary, scratch)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        manifest["result"] = "failed: binary inspection contract"
        _write_manifest(scratch, manifest)
        raise ReplayError("binary inspection rejected synthetic lifecycle executable") from error

    for case in EXPECTED_CASES:
        try:
            run_case(binary, case, scratch)
        except ReplayError as error:
            manifest["result"] = f"failed: {error}"
            _write_manifest(scratch, manifest)
            raise

    manifest["result"] = "PASS: six expected RED source observations and two controls"
    _write_manifest(scratch, manifest)
    print(f"PASS lifecycle observation: 6 expected RED + 2 CONTROL cases; logs={scratch}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("observe", "extract"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--compiler", default="cc")
    args = parser.parse_args()
    try:
        return run(args.mode, args.source, args.scratch, args.compiler)
    except (OSError, ReplayError, async_replay.ValidationError) as error:
        print(f"FAIL {args.mode}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
