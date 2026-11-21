#!/usr/bin/env python3
"""Opt-in, offline staging of the bounded continuous diagnostics patch."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict
from threading import Event


HERE = Path(__file__).resolve().parent
BASE_STAGER = HERE / "stage_hidapi_continuous.py"
DIAGNOSTIC_PATCH = HERE / "nut-hidapi-continuous-diag-v1-73c4502.patch"
BASE_APC_SHA256 = "dc0b5b632883a45850fdfd54594c3abc9987914c8aca2347dfa6e1f8f534d081"
DIAGNOSTIC_PATCH_SHA256 = "dc83e44236dfe91be87dee76f068c5d449cd7c4c32bff25717604f19b2d0b2b5"
OPT_IN_FLAG = "-DMLINK_CONTINUOUS_DIAGNOSTICS_V1"
SUPERVISOR_SHA256 = "e53afffbb3a3525e90a6ca3576a335ea6d797a62b22754218fbde569e138cb7a"


class StageError(RuntimeError):
    """Safe refusal from this offline-only staging operation."""

    def __init__(self, message: str, *, retained_output: Path | None = None) -> None:
        super().__init__(message)
        # Local caller metadata only; str(error) never embeds a private path.
        self.retained_output = retained_output


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_base_stager():
    spec = importlib.util.spec_from_file_location("stage_hidapi_continuous_base", BASE_STAGER)
    if spec is None or spec.loader is None:
        raise StageError("base continuous stager unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_supervisor():
    path = HERE / "process_deadline.py"
    if sha256(path) != SUPERVISOR_SHA256:
        raise StageError("bounded supervisor hash mismatch")
    spec = importlib.util.spec_from_file_location("process_deadline", path)
    if spec is None or spec.loader is None:
        raise StageError("bounded supervisor unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolved_tmpdir() -> Path:
    raw = os.environ.get("TMPDIR", "/tmp")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise StageError("TMPDIR must be absolute")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise StageError("TMPDIR is not a directory")
    return resolved


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _check_destination(output: Path, tmpdir: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(output)))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:-1]:
        current = current / component
        try:
            info = current.lstat()
        except OSError as exc:
            raise StageError("destination parent unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise StageError("unsafe destination path component")
    parent = absolute.parent
    try:
        info = parent.lstat()
    except OSError as exc:
        raise StageError("destination parent unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StageError("destination parent must be a real directory")
    parent = parent.resolve(strict=True)
    resolved_output = parent / absolute.name
    if not _inside(resolved_output, tmpdir) or resolved_output == tmpdir:
        raise StageError("destination must be a new child of resolved TMPDIR")
    if os.path.lexists(resolved_output):
        raise StageError("destination already exists")
    return resolved_output


def stage(source: Path, inventory: Path, output: Path, *, compile_opt_in: bool) -> dict[str, object]:
    tmpdir = _resolved_tmpdir()
    output = _check_destination(output, tmpdir)
    if sha256(DIAGNOSTIC_PATCH) != DIAGNOSTIC_PATCH_SHA256:
        raise StageError("diagnostic patch hash mismatch")
    base = _load_base_stager()
    try:
        receipt = base.stage(source, inventory, output)
    except (OSError, base.StageError, subprocess.CalledProcessError) as exc:
        raise StageError("base continuous staging refused") from exc
    owned_identity = (output.stat().st_dev, output.stat().st_ino)
    child_completion_proven = True
    try:
        output.chmod(0o700)
        apc = output / "drivers" / "apcmicrolink.c"
        if not apc.is_file() or sha256(apc) != BASE_APC_SHA256:
            raise StageError("H04 intermediate APC hash mismatch")
        before = {"drivers/apcmicrolink.c": sha256(apc)}
        supervisor = _load_supervisor()
        patch_executable = Path("/usr/bin/patch")
        patch_executable_hash = sha256(patch_executable)
        child_completion_proven = False
        patch_result = supervisor.run_bounded(
            [str(patch_executable), "--batch", "--forward", "-p1", "-d", str(output), "-i", str(DIAGNOSTIC_PATCH)],
            executable_sha256=patch_executable_hash,
            output_directory=output / ".diagnostic-patch-log", timeout_seconds=20,
            termination_grace_seconds=2, maximum_output_bytes=1_048_576,
            cancel_event=Event(),
        )
        child_completion_proven = patch_result.status is not supervisor.RunStatus.UNREAPED
        if patch_result.status is not supervisor.RunStatus.EXITED or patch_result.trigger.value != "completed" or patch_result.returncode != 0:
            raise StageError("bounded diagnostic patch failed")
        after = {"drivers/apcmicrolink.c": sha256(apc)}
        if before == after:
            raise StageError("diagnostic patch did not change the expected file")
        diagnostic_receipt = {
            "state": "STAGED_UNBUILT",
            "target_identity": "apcmicrolink-hidapi-continuous-diagnostics-v1",
            "build_identity": "nut-73c4502-continuous-diag-v1",
            "base_state": receipt["state"],
            "h03_inventory_sha256": receipt["source_inventory_sha256"],
            "continuous_patch_sha256": receipt["patch_sha256"],
            "diagnostic_patch_sha256": DIAGNOSTIC_PATCH_SHA256,
            "h04_apc_sha256": BASE_APC_SHA256,
            "touched_file_hashes_before": before,
            "touched_file_hashes_after": after,
            "compile_opt_in": compile_opt_in,
            "compile_opt_in_flag": OPT_IN_FLAG if compile_opt_in else None,
            "build_status": "NOT_RUN",
            "patch_executable_sha256": patch_executable_hash,
            "patch_run": asdict(patch_result),
            "base_stage_patch_boundary": "historical base stager unchanged; caller must bound the whole staging invocation",
        }
        receipt_path = output / "continuous-diagnostics-stage-receipt.json"
        receipt_path.write_text(json.dumps(diagnostic_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt_path.chmod(0o600)
        return diagnostic_receipt
    except Exception as exc:
        retained = True
        if child_completion_proven:
            try:
                if output.is_dir() and not output.is_symlink() and _inside(output, tmpdir):
                    current = output.stat()
                    if (current.st_dev, current.st_ino) == owned_identity:
                        shutil.rmtree(output)
                        retained = False
            except OSError:
                # Identity uncertainty or failed cleanup must preserve evidence;
                # never replace the original failure with a destructive retry.
                pass
        if isinstance(exc, StageError):
            if retained:
                exc.retained_output = output
            raise
        raise StageError("diagnostic patch staging failed", retained_output=output if retained else None) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="immutable admitted H03 source")
    parser.add_argument("--inventory", type=Path, required=True, help="pinned H03 inventory JSON")
    parser.add_argument("--output", type=Path, required=True, help="new directory under resolved TMPDIR")
    parser.add_argument("--compile-opt-in", action="store_true", help="record explicit diagnostic compile opt-in")
    args = parser.parse_args()
    try:
        receipt = stage(args.source, args.inventory, args.output, compile_opt_in=args.compile_opt_in)
    except (OSError, StageError) as exc:
        if isinstance(exc, StageError) and exc.retained_output is not None:
            print(json.dumps({"state": "STAGING_FAILED_OUTPUT_RETAINED",
                              "output": str(exc.retained_output)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(f"stage refused: {exc}") from exc
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
