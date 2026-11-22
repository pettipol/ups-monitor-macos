#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reconstruct and audit a pinned, fake-only continuous NUT replay offline.

Default: compile only. --run-fake explicitly admits the closed diagnostic suite.
All generated files must remain in a new directory below the system TMPDIR.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
from threading import Event, Thread
import time
import unittest

HERE = Path(__file__).resolve().parent
MANIFEST_NAME = "replay_continuous_portable_inputs.json"
MAX_TREE_BYTES = 1_073_741_824
MAX_ARCHIVE_BYTES = 134_217_728
MAX_SELECTED_BYTES = 16_777_216
ENV = Path("/usr/bin/env")
MAX_SUITE_SECONDS = 600
MAX_FAKE_PROCESSES = 24
MAX_FAKE_CAPTURE_BYTES = 32 * 1_048_576
REQUIRED_FAKE_DEFINITIONS = (
    "main", "mlink_hidapi_native_create", "mlink_hidapi_native_dispose",
    "mlink_hidapi_native_post_finish_clock_ms", "mlink_continuous_replay_wait",
    "clock_gettime", "time", "fixture_os_socket", "fixture_os_fork", "fixture_chdir",
)
FORBIDDEN_IMPORTS = {
    "fork", "vfork", "kill", "setsid", "socket", "connect", "bind", "listen",
    "accept", "getsockopt", "pipe", "dlopen", "ioctl", "system", "posix_spawn",
    "posix_spawnp", "execve", "execv", "execl", "setuid", "setgid", "seteuid",
    "setegid", "initgroups", "chroot", "getpwnam", "getpwuid", "getgrnam",
    "openlog", "syslog", "unlink", "chmod", "fchmod", "chown", "fchown", "chdir",
}
PUBLIC_UNITS = (
    "drivers/main.c", "drivers/dstate.c", "drivers/apcmicrolink.c",
    "drivers/apcmicrolink-maps.c", "drivers/apc_common.c", "common/common.c",
    "common/common-nut_version.c", "common/state.c", "common/str.c",
    "common/upsconf.c", "common/parseconf.c",
)
COPIED_MODULES = (
    "apcmicrolink-hidapi-shared.c", "apcmicrolink-hidapi-shared-host.h",
    "apcmicrolink-hidapi-session.h", "apcmicrolink-hidapi-native.c", "apcmicrolink-hidapi-native.h",
    "apcmicrolink-hid-descriptor-checked.c", "apcmicrolink-hid-descriptor-checked.h",
)


class ReplayError(RuntimeError):
    """A closed failure message, without device data or private paths."""


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(path: Path, *, exists: bool = True) -> Path:
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ReplayError("symlink path component refused")
    if exists and not absolute.exists():
        raise ReplayError("required input absent")
    return absolute


def verify(path: Path, expected: str) -> None:
    safe_path(path)
    if not path.is_file() or sha(path) != expected:
        raise ReplayError("pinned input mismatch: " + path.name)


def load_pinned(path: Path, expected: str, name: str):
    verify(path, expected)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None or name in sys.modules:
        raise ReplayError("helper module unavailable or already loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def read_contract() -> dict:
    # A committed, reviewable manifest is the trust root, like SOURCE_PINS in
    # replay_hidapi_full_driver.py. It is not an authenticity signature.
    path = safe_path(HERE / MANIFEST_NAME)
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract["schema"] != 1:
        raise ReplayError("unsupported input manifest schema")
    for name, expected in contract["local_pins"].items():
        if Path(name).name != name:
            raise ReplayError("invalid local input name")
        verify(HERE / name, expected)
    for item in contract["patches"]:
        if contract["local_pins"].get(item["name"]) != item["sha256"]:
            raise ReplayError("patch pin differs from admitted local input")
    return contract


def output_location(raw: Path, protected: tuple[Path, ...]) -> Path:
    output = safe_path(raw, exists=False)
    temporary = Path(os.environ.get("TMPDIR", "/private/tmp")).resolve(strict=True)
    if not temporary.is_dir() or temporary == Path("/"):
        raise ReplayError("invalid temporary root")
    allowed = (temporary, Path("/private/tmp"))
    if not any(root in output.parents for root in allowed):
        raise ReplayError("output must be strictly below a system temporary root")
    if output.exists() or not output.parent.is_dir():
        raise ReplayError("output must be new with an existing parent")
    info = output.parent.stat()
    # /private/tmp itself is intentionally shared; the new output is 0700.
    if output.parent not in allowed and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022):
        raise ReplayError("output parent must be privately owned")
    for path in protected:
        if output == path or path in output.parents or output in path.parents:
            raise ReplayError("output overlaps protected inputs")
    return output


def tree_bytes(root: Path) -> int:
    total = 0
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(parent) / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                # Compiler-owned temporary files may be renamed between walk
                # and stat; generated stable inputs are rechecked separately.
                continue
            if stat.S_ISLNK(info.st_mode):
                raise ReplayError("generated symlink refused")
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > MAX_TREE_BYTES:
                    raise ReplayError("temporary tree exceeded 1 GiB")
    return total


def command(helper, argv: list[str], output: Path, label: str,
            *, timeout: int = 120, expected: int = 0,
            developer_dir: Path | None = None) -> str:
    tree_bytes(output)
    cancelled, done = Event(), Event()
    limit_hit: list[bool] = []

    def monitor() -> None:
        while not done.wait(0.1):
            try:
                tree_bytes(output)
            except (OSError, ReplayError):
                limit_hit.append(True)
                cancelled.set()
                return

    watcher = Thread(target=monitor, daemon=True)
    watcher.start()
    selected = ["DEVELOPER_DIR=" + str(developer_dir)] if developer_dir is not None else []
    closed = [str(ENV), "TMPDIR=" + str(output), "PYTHONDONTWRITEBYTECODE=1", *selected, *argv]
    try:
        result = helper.run_bounded(
            closed, executable_sha256=sha(ENV), output_directory=output / label,
            timeout_seconds=timeout, termination_grace_seconds=2,
            maximum_output_bytes=1_048_576, cancel_event=cancelled,
        )
    finally:
        done.set()
        watcher.join(timeout=1)
    tree_bytes(output)
    record = {"argv": closed, "executable_pins": {str(Path(argv[0])): sha(Path(argv[0])), str(ENV): sha(ENV)},
              "result": asdict(result), "timeout_seconds": timeout,
              "maximum_output_bytes": 1_048_576, "owned_process_group": True}
    (output / (label + ".json")).write_text(json.dumps(record, indent=2) + "\n")
    if limit_hit or result.status is not helper.RunStatus.EXITED or result.returncode != expected:
        raise ReplayError("bounded command failed: " + label)
    return (output / label / "stdout.bin").read_text(encoding="utf-8")


def discover_toolchain(output: Path, contract: dict, helper) -> dict:
    raw_developer = os.environ.get("DEVELOPER_DIR")
    if raw_developer is None:
        raw_developer = command(helper, ["/usr/bin/xcode-select", "-p"], output,
                                "selected-developer-directory", timeout=30).strip()
    if not raw_developer or not Path(raw_developer).is_absolute():
        raise ReplayError("selected developer directory must be absolute")
    developer = safe_path(Path(raw_developer).resolve(strict=True))
    if not developer.is_dir():
        raise ReplayError("selected developer directory is unavailable")
    resolved = {}
    for name in ("clang", "xcodebuild"):
        value = command(helper, ["/usr/bin/xcrun", "--find", name], output,
                        "selected-" + name, timeout=30, developer_dir=developer).strip()
        if not Path(value).is_absolute():
            raise ReplayError("nonabsolute selected compiler tool")
        path = safe_path(Path(value).resolve(strict=True))
        if not path.is_file() or not path.is_relative_to(developer) or not os.access(path, os.X_OK):
            raise ReplayError("selected compiler tool escaped developer directory")
        resolved[name] = path
    value = command(helper, ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
                    output, "selected-sdk", timeout=30, developer_dir=developer).strip()
    if not Path(value).is_absolute():
        raise ReplayError("nonabsolute selected SDK")
    sdk = safe_path(Path(value).resolve(strict=True))
    if not sdk.is_dir() or not sdk.is_relative_to(developer):
        raise ReplayError("selected SDK escaped developer directory")
    sdk_version = command(helper, ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-version"],
                          output, "selected-sdk-version", timeout=30, developer_dir=developer).strip()
    xcode_version = command(helper, [str(resolved["xcodebuild"]), "-version"], output,
                            "selected-xcode-version", timeout=30, developer_dir=developer)
    expected = contract["toolchain"]
    if sdk_version != expected["macos_sdk_version"] or not xcode_version.startswith("Xcode " + expected["xcode_version"] + "\n"):
        raise ReplayError("selected toolchain version differs from admitted input")
    return {"developer_dir": str(developer), "selection": "DEVELOPER_DIR" if os.environ.get("DEVELOPER_DIR") else "xcode-select",
            "clang": str(resolved["clang"]), "clang_sha256": sha(resolved["clang"]),
            "xcodebuild": str(resolved["xcodebuild"]), "xcodebuild_sha256": sha(resolved["xcodebuild"]),
            "sdk": str(sdk), "sdk_version": sdk_version, "xcode_version_output": xcode_version,
            "sdk_settings_sha256": sha(sdk / "SDKSettings.json")}


def verify_selected_objects(link_map: str, objects: list[Path], developer: Path) -> None:
    # Same exact-object policy as the reused portable full-driver check, with
    # the verified selected developer root replacing its fixed Xcode.app root.
    entries: list[str] = []
    in_objects = False
    for line in link_map.splitlines():
        if line == "# Object files:":
            in_objects = True
            continue
        if in_objects and line.startswith("#"):
            break
        if in_objects:
            match = re.fullmatch(r"\[\s*\d+\]\s+(.+)", line)
            if match:
                entries.append(match.group(1))
            elif line.strip():
                raise ReplayError("malformed portable link map object entry")
    expected = {str(path.resolve(strict=True)) for path in objects}
    actual: list[str] = []
    for entry in entries:
        if entry in expected:
            actual.append(entry)
        elif entry != "linker synthesized":
            path = Path(entry)
            # System dylibs can exist only in the macOS shared cache. Match
            # the existing portable audit's canonical, non-strict resolution.
            canonical = path.resolve()
            if (not path.is_absolute() or path.suffix not in (".tbd", ".dylib")
                    or not (canonical.is_relative_to(developer) or canonical.is_relative_to(Path("/usr/lib")))):
                raise ReplayError("unexpected portable link map object or archive")
    if not entries or len(actual) != len(expected) or set(actual) != expected:
        raise ReplayError("portable link map differs from selected objects")


def patch_targets(path: Path) -> set[str]:
    targets = set()
    for name in re.findall(r"^\+\+\+ b/(\S+)", path.read_text(encoding="utf-8"), re.MULTILINE):
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts:
            raise ReplayError("unsafe patch target")
        targets.add(name)
    return targets


def reconstruct(archive: Path, contract: dict, output: Path, helper) -> Path:
    verify(archive, contract["archive_sha256"])
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ReplayError("source archive exceeds admitted size")
    needed = set(PUBLIC_UNITS)
    for item in contract["patches"]:
        needed.update(patch_targets(HERE / item["name"]))
    source = output / "source"
    source.mkdir(mode=0o700)
    selected = 0
    seen: set[str] = set()
    with tarfile.open(archive, "r:") as stream:
        for member in stream:
            name = member.name
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ReplayError("unsafe source archive member")
            header = pure.parent.as_posix() in ("include", "drivers", "common") and pure.suffix == ".h"
            if name not in needed and not header:
                continue
            if name in seen or not member.isfile():
                raise ReplayError("duplicate or nonregular selected archive member")
            seen.add(name)
            selected += member.size
            if selected > MAX_SELECTED_BYTES:
                raise ReplayError("selected source pack exceeds 16 MiB")
            target = source / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = stream.extractfile(member)
            if data is None:
                raise ReplayError("source member unavailable")
            with target.open("xb") as destination:
                destination.write(data.read())
            target.chmod(0o600)
    # These seven public project modules are the H03-compatible baseline.
    # The full continuous patch updates native.c/native.h/shared.c, so stage
    # them BEFORE the chain and never overwrite the resulting patched files.
    # native.c participates only in source reconstruction, never compilation.
    for name in COPIED_MODULES:
        target = source / "drivers" / name
        target.write_bytes((HERE / name).read_bytes())
        target.chmod(0o600)
        verify(target, contract["local_pins"][name])
    for index, item in enumerate(contract["patches"]):
        path = HERE / item["name"]
        # patch is allowed to mutate this newly reconstructed TMP source only.
        # --fuzz=0 and exact stage hashes reject ambiguous source alignment.
        command(helper, ["/usr/bin/patch", "--batch", "--fuzz=0", "-p1",
                         "--no-backup-if-mismatch", "-d", str(source), "-i", str(path)],
                output, f"patch-{index:02d}")
        for name, expected in item.get("after", {}).items():
            verify(source / name, expected)
    for name, expected in contract["source_after"].items():
        verify(source / name, expected)
    return source


def audit(binary: Path, output: Path, helper) -> dict:
    undefined = command(helper, ["/usr/bin/nm", "-u", str(binary)], output, binary.name + "-undefined")
    defined = command(helper, ["/usr/bin/nm", str(binary)], output, binary.name + "-defined")
    dependencies = command(helper, ["/usr/bin/otool", "-L", str(binary)], output, binary.name + "-linked")
    imports = {line.split()[-1].split("$", 1)[0].removeprefix("_")
               for line in undefined.splitlines() if line.split()}
    if imports & FORBIDDEN_IMPORTS or any(name.startswith(("hid_", "libusb_", "IOHID")) for name in imports):
        raise ReplayError("forbidden OS import in fake replay")
    linked = (undefined + "\n".join(dependencies.splitlines()[1:])).lower()
    if any(token in linked for token in ("libusb", "iokit", "corefoundation", "hidapi", "iohid")):
        raise ReplayError("genuine HID or USB linkage in fake replay")
    symbols = {line.split()[-1] for line in defined.splitlines() if line.split()}
    for name in REQUIRED_FAKE_DEFINITIONS:
        if name in imports or "_" + name not in symbols:
            raise ReplayError("required fake definition absent: " + name)
    return {"sha256": sha(binary), "imports": sorted(imports),
            "state": "PASS_STATIC_NO_HID_LINKAGE", "hardware": "NOT_RUN"}


def build_pair(source: Path, output: Path, contract: dict, helper, portable, toolchain: dict) -> dict:
    clang = Path(toolchain["clang"])
    sdk = Path(toolchain["sdk"])
    developer = Path(toolchain["developer_dir"])
    verify(clang, toolchain["clang_sha256"])
    generated = output / "include"
    generated.mkdir(mode=0o700)
    for original, name in (("test_hidapi_full_config.h", "config.h"),
                           ("test_hidapi_full_version.h", "nut_version.h")):
        (generated / name).write_bytes((HERE / original).read_bytes())
        (generated / name).chmod(0o600)
    for root in (source, source / "drivers", source / "include", source / "common", HERE):
        for name in ("config.h", "nut_version.h"):
            if (root / name).exists():
                raise ReplayError("shadow generated header refused")
    paths = [source, output, HERE]
    portable.verify_dependency_paths(paths)
    base = [str(clang), "-std=gnu99", "-g", "-O0", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Wno-unused-parameter",
            "-isysroot", str(sdk), "-DMLINK_HIDAPI_NATIVE_CANDIDATE=1",
            "-DMLINK_HIDAPI_CONTINUOUS_CANDIDATE=1", "-DMLINK_HIDAPI_CONTINUOUS_REPLAY=1",
            "-I", str(generated), "-I", str(source / "include"),
            "-I", str(source / "drivers"), "-I", str(HERE)]
    units = [(source / name, True) for name in PUBLIC_UNITS]
    units.extend((source / "drivers" / name, False) for name in
                 ("apcmicrolink-continuous.c", "apcmicrolink-hidapi-shared.c",
                  "apcmicrolink-hid-descriptor-checked.c"))
    units.extend((HERE / name, False) for name in
                 ("replay_continuous_diagnostics.c", "replay_continuous_os.c"))
    pair = {}
    for mode in ("off", "on"):
        flags = ["-DMLINK_CONTINUOUS_DIAGNOSTICS_V1=1"] if mode == "on" else []
        objects = []
        for index, (unit, guarded) in enumerate(units):
            label = f"{mode}-compile-{index:02d}"
            obj = output / (label + ".o")
            dep = output / (label + ".d")
            # common.c's chroot_start also contains chdir(), outside main's
            # FULL_FAKE_MAIN aliases. Redirect it in every guarded unit; the
            # command-line macro also aliases the unistd.h declaration.
            guard = ["-include", str(HERE / "test_hidapi_full_os.h"), "-Dchdir=fixture_chdir"] if guarded else []
            special = ["-DFULL_FAKE_MAIN=1"] if unit.name == "main.c" else []
            if unit.name == "common.c":
                special += ["-DNUT_WANT_INET_NTOP_XX=1"]
            command(helper, [*base, *flags, *guard, *special,
                             "-MD", "-MF", str(dep), "-MT", "ups_full_fake_dependency_target",
                             "-c", str(unit), "-o", str(obj)], output, label, developer_dir=developer)
            required = {generated / "config.h"} if guarded else set()
            if unit.name == "common-nut_version.c":
                required.add(generated / "nut_version.h")
            portable.verify_includes(dep, required, unit.name)
            # Every project dependency is an archive-derived or pinned file.
            contents = dep.read_text().replace("\\\n", " ")
            deps = [Path(value) for value in contents.split(":", 1)[1].split()]
            for path in deps:
                resolved = path.resolve(strict=True)
                if resolved.is_relative_to(source) or resolved.is_relative_to(generated):
                    continue
                if resolved.parent == HERE and resolved.name in contract["local_pins"]:
                    verify(resolved, contract["local_pins"][resolved.name])
                elif not (resolved.is_relative_to(sdk) or resolved.is_relative_to(clang.parents[1])):
                    raise ReplayError("unadmitted compilation dependency")
            objects.append(obj)
        binary = output / ("continuous-fake-" + mode)
        link_map = output / (mode + ".map")
        try:
            command(helper, [*base, *flags, *(str(path) for path in objects), "-lm",
                             "-Wl,-map," + str(link_map), "-o", str(binary)], output, mode + "-link", developer_dir=developer)
        finally:
            if binary.exists():
                binary.chmod(0o600)
        verify_selected_objects(link_map.read_text(), objects, developer)
        pair[mode] = {"path": str(binary), **audit(binary, output, helper)}
    return pair


class SuiteAbort(KeyboardInterrupt):
    """Stop unittest immediately after a supervisor or budget failure."""


def run_suite(pair: dict, output: Path, contract: dict, helper) -> dict:
    # Import the exact admitted assertions and parser; __main__ is not run.
    # Every fake remains a direct child of this runner. There is no Python
    # suite subprocess whose death could orphan an independently sessioned fake.
    module = load_pinned(HERE / "test_continuous_diagnostics.py",
                         contract["local_pins"]["test_continuous_diagnostics.py"], "portable_continuous_assertions")
    module.protocol = load_pinned(HERE / "continuous_protocol.py",
                                  contract["local_pins"]["continuous_protocol.py"], "portable_continuous_protocol")
    module.RunStatus = helper.RunStatus
    module.ENV_SHA256 = sha(ENV)
    module.FAKE_OFF, module.FAKE_ON = Path(pair["off"]["path"]), Path(pair["on"]["path"])
    module.FAKE_OFF_SHA256, module.FAKE_ON_SHA256 = pair["off"]["sha256"], pair["on"]["sha256"]
    module.MAX_CAPTURE_TOTAL = MAX_FAKE_CAPTURE_BYTES
    module.capture_total = 0
    module.run_receipts = []
    module.PAIR_CACHE = {}
    module.run_root = output / "diagnostic-suite"
    module.run_root.mkdir(mode=0o700)
    cancelled, done = Event(), Event()
    deadline = time.monotonic() + MAX_SUITE_SECONDS
    invocations: list[dict] = []
    capture_bytes = 0
    abort_reason: list[str] = []
    scenarios = {"same-payload", "cache-no-rebuild", "unrelated-refresh", "corrupt-recovery",
                 "implausible-page0", "handshake-then-silent", "no-handshake-success",
                 "cancelled", "clock-guard", "silent-close-fails", "stop-fails", "duration-cleanup-fails"}
    tail = ["-s", "replay", "-d1", "-x", "port=auto", "-x", "hidapi_shared",
            "-x", "guarded_monitor", "-x", "guard_vid=0001", "-x", "guard_pid=0002",
            "-x", "guard_deadline=130", "-x", "guard_probe_attempts=1", "-x",
            "hid_fallback=no", "-x", "monitor_stream_v1"]

    def abort(reason: str) -> None:
        abort_reason.append(reason)
        cancelled.set()
        raise SuiteAbort(reason)

    def monitor() -> None:
        while not done.wait(0.05):
            try:
                tree_bytes(output)
            except (OSError, ReplayError):
                abort_reason.append("temporary storage guard")
                cancelled.set()
                return
            if time.monotonic() >= deadline:
                abort_reason.append("suite deadline")
                cancelled.set()
                return

    def owned_run(argv, **kwargs):
        nonlocal capture_bytes
        if cancelled.is_set() or time.monotonic() >= deadline:
            abort("suite cancelled before child spawn")
        if len(invocations) >= MAX_FAKE_PROCESSES:
            abort("fake process budget exceeded")
        allowed_binaries = {str(item["path"]): item["sha256"] for item in pair.values()}
        scenario = argv[1].removeprefix("MLINK_CONTINUOUS_REPLAY_SCENARIO=") if len(argv) > 1 else ""
        expected_output = module.run_root / f"{len(invocations):02d}"
        if (len(argv) != len(tail) + 3 or argv[0] != str(ENV)
                or argv[1] != "MLINK_CONTINUOUS_REPLAY_SCENARIO=" + scenario
                or scenario not in scenarios or argv[2] not in allowed_binaries or list(argv[3:]) != tail
                or kwargs.get("executable_sha256") != module.ENV_SHA256
                or Path(kwargs.get("output_directory", "")) != expected_output
                or kwargs.get("timeout_seconds") != 20 or kwargs.get("termination_grace_seconds") != 2
                or kwargs.get("maximum_output_bytes") != 1_048_576
                or set(kwargs) != {"executable_sha256", "output_directory", "timeout_seconds",
                                    "termination_grace_seconds", "maximum_output_bytes", "cancel_event"}):
            abort("fake child arguments differ from closed suite contract")
        verify(Path(argv[2]), allowed_binaries[argv[2]])
        # Replace the fresh Event requested by the unchanged suite with the
        # sole event owned by this runner and its storage/deadline monitor.
        kwargs["cancel_event"] = cancelled
        kwargs["timeout_seconds"] = min(20.0, max(0.001, deadline - time.monotonic()))
        try:
            result = helper.run_bounded(argv, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            cancelled.set()
            raise
        except BaseException as exc:
            cancelled.set()
            code = getattr(getattr(exc, "code", None), "value", "unknown")
            abort("child supervisor raised a safe failure: " + str(code))
        invocations.append({"scenario": scenario, "binary_sha256": allowed_binaries[argv[2]],
                            "owned_process_group": True, "supervisor": asdict(result)})
        capture_bytes += result.stdout_bytes + result.stderr_bytes
        if result.status is not helper.RunStatus.EXITED or result.trigger.value != "completed":
            # UNREAPED is an explicit HOLD; it can never become a cleanup PASS.
            abort("child supervisor did not prove completed/reaped process group: " + result.status.value)
        if capture_bytes > MAX_FAKE_CAPTURE_BYTES or cancelled.is_set():
            abort("suite storage/time/capture budget exceeded")
        tree_bytes(output)
        return result

    class BoundedReport(io.StringIO):
        written_bytes = 0

        def write(self, text: str) -> int:
            self.written_bytes += len(text.encode("utf-8"))
            if self.written_bytes > 1_048_576:
                abort("unittest report exceeded 1 MiB")
            return super().write(text)

    module.run_bounded = owned_run
    cases = unittest.defaultTestLoader.loadTestsFromModule(module)
    if cases.countTestCases() != 10:
        raise ReplayError("pinned assertion suite does not contain ten tests")
    report = BoundedReport()
    watcher = Thread(target=monitor, daemon=True)
    watcher.start()
    result = None
    try:
        for item in pair.values():
            verify(Path(item["path"]), item["sha256"])
            Path(item["path"]).chmod(0o700)
        result = unittest.TextTestRunner(stream=report, verbosity=1, failfast=True).run(cases)
    except SuiteAbort as exc:
        raise ReplayError("bounded diagnostic suite aborted: " + str(exc)) from None
    finally:
        done.set()
        watcher.join(timeout=1)
        for item in pair.values():
            Path(item["path"]).chmod(0o600)
        receipt = {"schema": 2, "orchestration": "IN_PROCESS_ASSERTIONS_DIRECT_OWNED_FAKE_CHILDREN",
                   "maximum_suite_seconds": MAX_SUITE_SECONDS, "maximum_fake_processes": MAX_FAKE_PROCESSES,
                   "maximum_child_seconds": 20, "maximum_child_capture_bytes": 1_048_576,
                   "maximum_aggregate_capture_bytes": MAX_FAKE_CAPTURE_BYTES,
                   "capture_total_bytes": capture_bytes, "invocations": invocations,
                   "runs": module.run_receipts, "abort_reasons": abort_reason,
                   "tests_run": result.testsRun if result is not None else None,
                   "successful": result.wasSuccessful() if result is not None else False}
        receipt_path = module.run_root / "run-receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        (module.run_root / "unittest.txt").write_text(report.getvalue())
    if watcher.is_alive() or cancelled.is_set() or time.monotonic() >= deadline:
        raise ReplayError("suite deadline, storage guard or monitor completion not satisfied")
    if result is None or not result.wasSuccessful() or result.testsRun != 10:
        raise ReplayError("pinned diagnostic assertions failed")
    if len(invocations) != MAX_FAKE_PROCESSES or len(module.run_receipts) != MAX_FAKE_PROCESSES:
        raise ReplayError("expected exactly 24 directly supervised fake children")
    return {"tests": 10, "fake_processes": 24, "receipt_sha256": sha(receipt_path),
            "capture_bytes": capture_bytes, "state": "PASS_FAKE_ONLY"}


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nut-archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--compile-only", action="store_true", help="Default: no binary execution")
    mode.add_argument("--run-fake", action="store_true", help="Run exactly the pinned synthetic diagnostic suite")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if sys.version_info[:3] != (3, 15, 2) or sys.platform != "darwin":
        raise ReplayError("requires the admitted macOS Python 3.15.2 runtime")
    contract = read_contract()
    manifest_pin = sha(HERE / MANIFEST_NAME)
    archive = safe_path(args.nut_archive)
    verify(archive, contract["archive_sha256"])
    repository = HERE.parents[1] if HERE.name == "nut" and HERE.parent.name == "backend" else HERE
    output = output_location(args.output_dir, (archive, repository))
    for path in (ENV, Path("/usr/bin/xcode-select"), Path("/usr/bin/xcrun"), Path("/usr/bin/patch"), Path("/usr/bin/nm"), Path("/usr/bin/otool")):
        safe_path(path)
    helper = load_pinned(HERE / "process_deadline.py", contract["local_pins"]["process_deadline.py"], "portable_continuous_process")
    portable = load_pinned(HERE / "replay_hidapi_full_driver.py", contract["local_pins"]["replay_hidapi_full_driver.py"], "portable_continuous_reuse")
    output.mkdir(mode=0o700)
    started = time.monotonic()
    pair: dict = {}
    try:
        toolchain = discover_toolchain(output, contract, helper)
        source = reconstruct(archive, contract, output, helper)
        pair = build_pair(source, output, contract, helper, portable, toolchain)
        suite = run_suite(pair, output, contract, helper) if args.run_fake else {"state": "NOT_RUN"}
        # Recheck every admitted input after compilation and optional execution.
        read_contract()
        verify(HERE / MANIFEST_NAME, manifest_pin)
        verify(archive, contract["archive_sha256"])
        for name, expected in contract["source_after"].items():
            verify(source / name, expected)
        # source_after includes the seven staged modules with their final
        # post-patch hashes. Their public baseline input pins differ for the
        # three modules intentionally updated by the full continuous patch.
        for item in pair.values():
            verify(Path(item["path"]), item["sha256"])
        verify(Path(toolchain["clang"]), toolchain["clang_sha256"])
        verify(Path(toolchain["xcodebuild"]), toolchain["xcodebuild_sha256"])
        verify(Path(toolchain["sdk"]) / "SDKSettings.json", toolchain["sdk_settings_sha256"])
        result = {"schema": 1, "state": "PASS_PORTABLE_CONTINUOUS_FAKE" if args.run_fake else "COMPILE_ONLY_FAKE_NOT_RUN",
                  "nut_revision": contract["nut_revision"], "archive_sha256": contract["archive_sha256"],
                  "source_after": contract["source_after"], "input_manifest_sha256": manifest_pin,
                  "binaries": pair, "suite": suite, "temporary_bytes": tree_bytes(output),
                  "toolchain": toolchain,
                  "elapsed_seconds": time.monotonic() - started, "python_version": sys.version,
                  "python_sha256": sha(Path(sys.executable).resolve()),
                  "hardware": "NOT_RUN", "genuine_hidapi": "NOT_LINKED", "data_qualified": False}
        (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
        print(result["state"])
        return 0
    finally:
        for item in pair.values():
            binary = Path(item["path"])
            if binary.exists():
                binary.chmod(0o600)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReplayError as exc:
        raise SystemExit("HOLD " + str(exc)) from None
