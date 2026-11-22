#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""DRAFT ONLY: reconstruct E28 production sources; no build or replay."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
from threading import Event

BASE_RUNNER = "101f5b5c9ec95d7feb18c53e531e4554589a3f0477884c55cc062a889f9c5006"
BASE_MANIFEST = "9020f7675b89f996d6c78dfd48ca63cc61a1f27349f97254dffd9cb6f21f189e"
E32_MANIFEST = "4e2d6b6ea7f191af4262a113f6a692eebbdaafbb35617f4eb2b91c20b23ba8d5"
HELPER = "81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e"
MANIFEST = "afd2425d9951f236f9c3b94df3681d1562571b4491b8eabe49b23bd4505a8ee1"
ORDER = ("nut-hidapi-continuous-pacing-v2-73c4502.patch", "nut-operational-formatter-v2.patch",
         "nut-operational-health-v2.patch", "nut-operational-cleanup-v2.patch",
         "nut-operational-driver-v2.patch")
DIAG = "nut-operational-cleanup-diagnostics-v1.patch"
FRESH = ("apcmicrolink-operational-freshness.c", "apcmicrolink-operational-freshness.h")
MARKERS = (b"MLINK_OPERATIONAL_REPLAY_HOOKS", b"replay_operational_hooks.h",
           b"mlink_operational_replay_", b"MLINK_REPLAY_", b"#define fwrite", b"#define fflush")


def verified(path: Path, expected: str, maximum_bytes: int = 1024**2) -> bytes:
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError("invalid input size cap")
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("unsafe input: " + path.name)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum_bytes:
        raise ValueError("input type or size refused: " + path.name)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("input changed before read: " + path.name)
        data = stream.read(maximum_bytes + 1)
        if len(data) > maximum_bytes:
            raise ValueError("input grew beyond size cap: " + path.name)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("input pin mismatch: " + path.name)
    return data


def module(path: Path, pin: str, name: str):
    data = verified(path, pin)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None or name in sys.modules:
        raise ValueError("module unavailable")
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    exec(compile(data, str(path), "exec"), obj.__dict__)
    verified(path, pin)
    return obj


@contextmanager
def cancellation_bridge(helper, receipt_path: Path | None = None):
    """Forward campaign signals to the active per-command process group."""
    campaign = Event()
    active = [None]
    original = helper.run_bounded
    previous = {}

    def request_cancel(_signum, _frame):
        campaign.set()
        child = active[0]
        if child is not None:
            child.set()

    def bridged(*args, **kwargs):
        child = kwargs.get("cancel_event")
        if not isinstance(child, Event):
            raise ValueError("frozen supervisor cancellation API differs")
        active[0] = child
        if campaign.is_set():
            child.set()
            active[0] = None
            raise ValueError("source reconstruction cancelled")
        try:
            result = original(*args, **kwargs)
        finally:
            active[0] = None
        if campaign.is_set():
            raise ValueError("source reconstruction cancelled")
        return result

    helper.run_bounded = bridged
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, request_cancel)
        yield campaign
        if campaign.is_set():
            if receipt_path is not None and receipt_path.exists():
                receipt_path.unlink()
            raise ValueError("source reconstruction cancelled")
    finally:
        helper.run_bounded = original
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend-dir", type=Path, required=True)
    p.add_argument("--nut-archive", type=Path, required=True)
    p.add_argument("--deadline-helper", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if (sys.version_info[:3] != (3, 15, 2) or sys.platform != "darwin" or
            not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or sys.flags.optimize):
        raise ValueError("requires macOS Python 3.15.2 -I -S -B without optimization")
    os.umask(0o077)
    admission = json.loads(verified(Path(__file__).with_name("SOURCE_PREPARATION_INPUTS.json"), MANIFEST))
    if (admission["baseline_runner_sha256"] != BASE_RUNNER or
            admission["baseline_manifest_sha256"] != BASE_MANIFEST or
            admission["e32_manifest_sha256"] != E32_MANIFEST or
            admission["supervisor_sha256"] != HELPER):
        raise ValueError("admission pins differ")
    backend = a.backend_dir.absolute()
    base_path = backend / "replay_continuous_portable_inputs.json"
    e32_path = backend / "replay_operational_portable_inputs_e32.json"
    base = json.loads(verified(base_path, BASE_MANIFEST))
    e32 = json.loads(verified(e32_path, E32_MANIFEST))
    if base["archive_sha256"] != admission["source_archive_sha256"]:
        raise ValueError("archive pin differs")
    verified(a.nut_archive, base["archive_sha256"], 128 * 1024**2)
    r = module(backend / "replay_continuous_portable.py", BASE_RUNNER, "e63_baseline")
    helper = module(a.deadline_helper, HELPER, "e63_deadline")
    for name in (*r.COPIED_MODULES, *(item["name"] for item in base["patches"])):
        if Path(name).name != name:
            raise ValueError("invalid baseline name")
        verified(backend / name, base["local_pins"][name])
    checkpoint_bytes = {}
    for name in (*ORDER, *FRESH, DIAG, "production_source_pre_e28.json", "production_source_post_e28.json"):
        checkpoint_bytes[name] = verified(backend / name, e32["new_pins"][name])
    pre = json.loads(checkpoint_bytes["production_source_pre_e28.json"])["source_sha256"]
    post = json.loads(checkpoint_bytes["production_source_post_e28.json"])["source_sha256"]
    if len(pre) != 190 or len(post) != 190 or set(pre) != set(post):
        raise ValueError("source closure mismatch")
    if e32["new_pins"]["production_source_post_e28.json"] != admission["source_post_e28_map_sha256"]:
        raise ValueError("postimage pin differs")
    output = r.output_location(a.output_dir, (backend, a.nut_archive.absolute(), a.deadline_helper.absolute()))
    output.mkdir(mode=0o700)
    r.MAX_TREE_BYTES = 134217728
    receipt_path = output / "SOURCE_RECEIPT.json"
    with cancellation_bridge(helper, receipt_path) as campaign:
        source = r.reconstruct(a.nut_archive, base, output, helper)

        def snapshot() -> dict[str, str]:
            r.tree_bytes(source)
            files = sorted(source.rglob("*"))
            if any(path.is_symlink() for path in files):
                raise ValueError("source symlink")
            return {str(path.relative_to(source)): r.sha(path) for path in files if path.is_file()}

        for index, name in enumerate(ORDER):
            entry = e32["patches"][name]
            for target, pin in entry["before"].items():
                r.verify(source / target, pin)
            r.command(helper, ["/usr/bin/patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch",
                               "-d", str(source), "-i", str(backend / name)], output, f"production-{index}", timeout=30)
            for target, pin in entry["after"].items():
                r.verify(source / target, pin)
        for name in FRESH:
            target = source / "drivers" / name
            with target.open("xb") as stream:
                stream.write(verified(backend / name, e32["new_pins"][name]))
            target.chmod(0o600)
        if snapshot() != pre:
            raise ValueError("production pre-E28 snapshot mismatch")
        entry = e32["patches"][DIAG]
        for target, pin in entry["before"].items():
            r.verify(source / target, pin)
        r.command(helper, ["/usr/bin/patch", "--batch", "--fuzz=0", "-p1", "--no-backup-if-mismatch",
                           "-d", str(source), "-i", str(backend / DIAG)], output, "production-e28", timeout=30)
        if snapshot() != post:
            raise ValueError("production post-E28 snapshot mismatch")
        for name in post:
            if Path(name).suffix in (".c", ".h") and any(x in (source / name).read_bytes() for x in MARKERS):
                raise ValueError("operational replay marker in production")
        receipt = {"state": "SOURCE_ONLY_PASS", "input_manifest_sha256": MANIFEST, "source_sha256": post,
                   "vendor_build_inputs": "NOT_INCLUDED", "build_native_hardware": "NOT_RUN"}
        if campaign.is_set():
            raise ValueError("source reconstruction cancelled")
        with receipt_path.open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        if campaign.is_set():
            receipt_path.unlink()
            raise ValueError("source reconstruction cancelled")


if __name__ == "__main__":
    main()
