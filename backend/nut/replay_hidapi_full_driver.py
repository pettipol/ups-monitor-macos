#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build/audit whole NUT with fake HIDAPI; execution requires --run-fake."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

EXTRACTOR_PIN = "54282ba3dde93578f36976fb6905dee7cffe87739938d00edc9a6f6b40433dad"
CONFIG_PIN = "2efcc93b54fc93fc77f8e160f8639253b7746a2fd47a6cfc57a3030657a5c04b"
VERSION_PIN = "92de6ec3b776980772d00ea121c6240f32236543d3035a4c861e7e068ffdc2fb"
CHECKSUM_PIN = "3ac090edfead88994f354217bfefe40a867ecd972528dabf918f74f92bb25130"
DEADLINE_PIN = "1ec7a490f83d8cd82701b9da6e4a1d64c1a6edc4ba4cbb751e39e48813997194"
SOURCE_PINS = {
    "drivers/dstate.c": "73ebb9589bf4ed056debc50d2bc164106698d2ebf3f63ef44a23ea3e16018818",
    "drivers/apcmicrolink-maps.c": "149cf260563294b9c864d9efb35388ed5524f20ce41fac113f10de6f60841a35",
    "drivers/apc_common.c": "c7cb9f88b2ef4d0fb42e827a09d01fbcd08d7353605496e7da5cb7ee789febcc",
    "common/common.c": "86458f6fc4aca540c7d5069206418d46e31fb49de8870b06f3f86ad729b64caa",
    "common/common-nut_version.c": "bb27531ae260d90b2855691dd2d473105697608b06ebb95c053241dbbeaf51ea",
}
MODULE_PINS = {
    "apcmicrolink-hidapi-shared.c": "a87a7d001b992b7b1cfd1afd96d4432cb5a5d9bfe40550c1877ebd646ba83a21",
    "apcmicrolink-hidapi-native.c": "3a1205741d62e02871d96c4e3091674b8131e8d3d95e58b156f2f95e9de1d2a5",
    "apcmicrolink-hid-descriptor-checked.c": "7db55b980569f8385196d10c30a966b0e78f1f9266c624f05a3c2459d13ebc85",
    "apcmicrolink-hidapi-shared-host.h": "606caa96cef85055c68c3b0d7c999e57e24efeb7bac16427dc8836bfd0631dcd",
    "apcmicrolink-hidapi-session.h": "50104ad0660fbd3c77fa185b0d8e00269f59775a1e123d3b548cb6c86f77d5ae",
    "apcmicrolink-hidapi-native.h": "648531900d7d2413a59dd36c04e3cd05a3c466ec52062b2e17437cd5b2064ada",
    "apcmicrolink-hid-descriptor-checked.h": "65c24b24313ba78c8293ede0485839c496165779f4d87cedde5e882a9f266b52",
    "test_hidapi_full_frames.h": "6d6ff2b8affb769ff5684317122a8204966c3cf238f2648928779cb918c65c0b",
    "test_hidapi_full_frames.c": "583f30b6dd2248c4efa5a32a84ed6528a3ffc007a0de7fa7e11e22dc4278ee45",
    "test_hidapi_full_frames_test.c": "c1137a85e0787da6359bf7a63935de2697fe91ee778783e7e23f8892b7b7a488",
}
HEADER_PINS = {
    "hidapi/hidapi.h": "c9cef28c53a13a9403e54d5a8a099d51afff119ab04094df89356df0833a822e",
    "mac/hidapi_darwin.h": "48854f6f6b612a90291c3de83a5755c2ed8642da173151a41377090821c39187",
}
ARCHIVE_PINS = {
    "libcommon.a": "626eccf61f2c1ce3a7c52f251e0a6217b0f196b753e86eeee8a28605c61f2363",
    "libcommonversion.a": "be20d21e4aacc0034dcc0f6c185725a9574bd83debe523352ce50144067a230b",
    "libparseconf.a": "c6159cd681a6cba09b148372f39c804b20e8d92a2551b003ec7fc3ca0f2b5dcc",
}
PORTABLE_CONFIG_PIN = "87ffcca2680a21dff59285c28e6910f6245134fbfe8b7034c37f4a106708859b"
PORTABLE_VERSION_PIN = "72c46517ffed4e458472b58b729ea3b893b4081388df35b7bd99a57904b0f512"
PORTABLE_SOURCE_PINS = {
    "common/state.c": "d7e43db9bbd967228a88bc4d92a990d1cea201a04b35244e0f057f5b3e7ffa75",
    "common/str.c": "2373a99660865c8468ae777deb0aafd994ac6e105ea51fee2eaeeaed56fcbc93",
    "common/upsconf.c": "8dc8781c99b753d33d00756def5363dd3760c650af80da15135a4a128ba3c175",
    "common/parseconf.c": "4a0f99d732037a2a0e31e024f771d044e75bfe209737e46f5adb873c2d0c939d",
}
SCENARIOS = ("metrics-dump", "metadata-only", "bad-checksum", "signal-term",
             "invalid-hid-descriptor", "expiry-after-init")
ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
               "PYTHONDONTWRITEBYTECODE": "1"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path: Path, expected: str) -> None:
    current = path.absolute()
    if any(candidate.is_symlink() for candidate in (current, *current.parents)):
        raise SystemExit("HOLD symlink pinned input path")
    if not path.is_file() or path.is_symlink() or digest(path) != expected:
        raise SystemExit(f"HOLD pinned input mismatch: {path.name}")


def load(path: Path, name: str, expected_pin: str):
    if name in sys.modules:
        raise SystemExit("HOLD helper module already loaded")
    current = path.absolute()
    if any(candidate.is_symlink() for candidate in (current, *current.parents)):
        raise SystemExit("HOLD symlink helper path")
    if not path.is_file():
        raise SystemExit("HOLD invalid local helper")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected_pin:
        raise SystemExit("HOLD pinned helper mismatch: " + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit("HOLD invalid local helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nut-source", type=Path, required=True)
    parser.add_argument("--nut-build", type=Path)
    parser.add_argument("--hidapi-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run-fake", action="store_true", help="Explicit synthetic execution after mandatory build/audit")
    mode.add_argument("--compile-only", action="store_true", help="Compile and audit both binaries without executing either")
    args = parser.parse_args(argv)
    return args


def reject_header_shadows(nut: Path, hidapi: Path, here: Path) -> None:
    roots = (nut, nut / "include", nut / "common", nut / "drivers", here,
             hidapi / "hidapi", hidapi / "mac")
    for root in roots:
        for name in ("config.h", "nut_version.h"):
            candidate = root / name
            if candidate.exists() or candidate.is_symlink():
                raise SystemExit("HOLD shadow generated header: " + name)


def verify_dependency_paths(paths: list[Path]) -> None:
    # The portable depfile reader accepts a deliberately restricted path grammar.
    for path in paths:
        if any(character.isspace() or character in "\\$#:" for character in str(path)):
            raise SystemExit("HOLD portable dependency paths contain unsupported Make characters")


def verify_includes(dependency_path: Path, required: set[Path], label: str) -> None:
    content = dependency_path.read_text(encoding="utf-8").replace("\\\r\n", " ").replace("\\\n", " ")
    prefix = "ups_full_fake_dependency_target:"
    if not content.startswith(prefix):
        raise SystemExit("HOLD invalid portable dependency target")
    names = content[len(prefix):].split()
    paths = [Path(name) for name in names]
    verify_dependency_paths(paths)
    if any(not path.is_absolute() for path in paths):
        raise SystemExit("HOLD nonabsolute portable dependency")
    missing = required - {path.resolve() for path in paths}
    if missing:
        raise SystemExit("HOLD staged header not included by " + label)


def verify_portable_objects(link_map: str, objects: list[Path]) -> None:
    entries = []
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
                raise SystemExit("HOLD malformed portable link map object entry")
    expected = {str(path.resolve()) for path in objects}
    actual = []
    for entry in entries:
        if entry in expected:
            actual.append(entry)
        elif entry != "linker synthesized":
            path = Path(entry)
            canonical = str(path.resolve())
            if (not path.is_absolute() or path.suffix not in (".tbd", ".dylib")
                    or not canonical.startswith(("/Applications/Xcode.app/Contents/Developer/", "/usr/lib/"))):
                raise SystemExit("HOLD portable link map has unexpected source objects or archive members")
    if not entries or len(actual) != len(expected) or set(actual) != expected:
        raise SystemExit("HOLD portable link map has unexpected source objects or archive members")


def compile_units(nut: Path, here: Path, portable: bool):
    units = [
        (nut / "drivers/main.c", ["-DFULL_FAKE_MAIN", "-Dmain=nut_real_main"], True),
        (nut / "drivers/dstate.c", ["-Ddstate_dump=fixture_real_dump", "-Ddstate_dataok=fixture_real_dataok"], True),
        (nut / "drivers/apcmicrolink.c", ["-Dupsdrv_updateinfo=fixture_real_updateinfo", "-Dupsdrv_cleanup=fixture_real_cleanup"], True),
        (nut / "drivers/apcmicrolink-maps.c", [], True),
        (nut / "drivers/apc_common.c", [], True),
        (nut / "common/common.c", ["-DNUT_WANT_INET_NTOP_XX=1"], True),
        (nut / "common/common-nut_version.c", [], True),
    ]
    if portable:
        units.extend((nut / source, [], True) for source in PORTABLE_SOURCE_PINS)
    units.extend([
        (here / "apcmicrolink-hidapi-shared.c", [], False),
        (here / "apcmicrolink-hidapi-native.c", ["-Dclock_gettime=fixture_native_clock_gettime"], False),
        (here / "apcmicrolink-hid-descriptor-checked.c", [], False),
        (here / "test_hidapi_full_frames.c", [], False),
        (here / "test_hidapi_full_driver.c", [], False),
    ])
    return units


def command(argv: list[str], output: Path, label: str, timeout: int = 60) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env={**ENVIRONMENT, "TMPDIR": str(output)})
    (output / f"{label}.stdout").write_text(result.stdout, encoding="utf-8")
    (output / f"{label}.stderr").write_text(result.stderr, encoding="utf-8")
    (output / f"{label}.argv.json").write_text(json.dumps(argv) + "\n", encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"HOLD {label} exit={result.returncode}\n" + result.stdout + result.stderr)
    return result.stdout


def audit(binary: Path, output: Path, *, pure_frames: bool = False) -> dict[str, str]:
    undefined = command(["/usr/bin/nm", "-u", str(binary)], output, binary.name + "-undefined")
    defined = command(["/usr/bin/nm", str(binary)], output, binary.name + "-defined")
    deps = command(["/usr/bin/otool", "-L", str(binary)], output, binary.name + "-deps")
    names = {line.split()[-1].split("$", 1)[0] for line in undefined.splitlines() if line.split()}
    forbidden_names = {"_fork", "_vfork", "_kill", "_setsid", "_socket", "_connect", "_bind", "_listen",
                       "_accept", "_getsockopt", "_pipe", "_dlopen", "_ioctl", "_system", "_posix_spawn", "_posix_spawnp",
                       "_execve", "_execv", "_execl", "_setuid", "_setgid", "_seteuid", "_setegid",
                       "_initgroups", "_chroot", "_getpwnam", "_getpwuid", "_getgrnam", "_openlog", "_syslog",
                       "_unlink", "_chmod", "_fchmod", "_chown", "_fchown"}
    dangerous = names & forbidden_names
    linked = (undefined + "\n".join(deps.splitlines()[1:])).lower()
    if dangerous or any(term in linked for term in ("libusb", "iokit", "corefoundation", "libhidapi", "iohid")):
        raise SystemExit("HOLD forbidden fake binary imports/linkage: " + ",".join(sorted(dangerous)))
    if "mlink_shared_test_bind" in defined:
        raise SystemExit("HOLD test binding exposed")
    required = () if pure_frames else (
        "hid_init", "hid_exit", "hid_enumerate", "hid_free_enumeration", "hid_open_path",
        "hid_get_report_descriptor", "hid_read_timeout", "hid_write", "hid_close",
        "hid_darwin_set_open_exclusive", "hid_darwin_get_open_exclusive",
        "hid_darwin_is_device_open_exclusive", "fixture_native_clock_gettime",
        "nut_real_main", "fixture_real_updateinfo", "fixture_real_dump", "fixture_real_cleanup",
        "nut_guarded_dump_signal_requested")
    for name in required:
        if "_" + name in names or not any(line.endswith(" _" + name) for line in defined.splitlines()):
            raise SystemExit("HOLD missing fake/whole-NUT definition: " + name)
    return {"binary_sha256": digest(binary), "audit": "PASS_STATIC_IMPORTS", "native_hidapi": "NOT_LINKED"}


def execute_fake(binary: Path, output: Path, process_helper, *, executable_sha256: str) -> list[dict[str, object]]:
    results = []
    for scenario in SCENARIOS:
        run_dir = output / ("run-" + scenario)
        result = process_helper.run_bounded(
            [str(binary), scenario], executable_sha256=executable_sha256, output_directory=run_dir,
            timeout_seconds=30, termination_grace_seconds=2, maximum_output_bytes=1048576,
            private_nut_environment=True)
        events_path = run_dir / "state/full-fake.events"
        lines = events_path.read_text(encoding="ascii").splitlines()
        stdout = (run_dir / "stdout.bin").read_text(encoding="utf-8")
        expected_rc = 0 if scenario in ("metrics-dump", "metadata-only") else 1
        if result.status is not process_helper.RunStatus.EXITED or result.returncode != expected_rc:
            raise SystemExit(f"HOLD full fake scenario {scenario}: {result}")
        if any(line.startswith("FORBIDDEN:") for line in lines) or not lines[-1].startswith("FINAL "):
            raise SystemExit("HOLD OS sentinel or missing final atexit observer: " + scenario)
        facts = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", lines[-1])}
        if facts["open"] != 1 or facts["close"] != 1 or facts["exit"] != 1:
            raise SystemExit("HOLD ownership cleanup counts: " + scenario)
        # main.c:3327 performs init.updateinfo before the two dump-loop updates
        # at main.c:3592 for the closed -d 1 invocation.
        if scenario == "metrics-dump":
            if "battery.charge: 76\n" not in stdout or "battery.runtime: 590\n" not in stdout or facts["update"] != 3 or facts["dump"] != 1:
                raise SystemExit("HOLD full decoder/update/dump did not publish expected synthetic fields")
        elif "battery.charge:" in stdout or "battery.runtime:" in stdout:
            raise SystemExit("HOLD unexpected metric in negative/metadata case")
        if scenario == "metadata-only" and (facts["dump"] != 1 or facts["update"] != 3):
            raise SystemExit("HOLD metadata counterexample did not traverse the real dump")
        if scenario == "signal-term":
            sequence = ("READY", "NUT_SIGNAL_FLAG=1", "CLEANUP_ENTER=1", "HID_CLOSE=1",
                        "HID_EXIT=1", "CLEANUP_RETURN")
            if (facts["flag"] != 1 or facts["dump"] != 0 or facts["cleanup"] != 1
                    or any(lines.count(marker) != 1 for marker in sequence)):
                raise SystemExit("HOLD real NUT signal handler/cleanup counts not observed")
            positions = [lines.index(marker) for marker in sequence]
            if positions != sorted(positions) or any(
                    line.startswith(("STOP=", "INIT=", "NEXT=")) for line in lines[positions[0]:]):
                raise SystemExit("HOLD post-signal protocol write or unordered cleanup")
        if scenario == "invalid-hid-descriptor" and (facts["read"] or facts["write"] or facts["cleanup"]):
            raise SystemExit("HOLD early-fatal admission path was not isolated")
        if scenario == "expiry-after-init" and (facts["read"] or facts["write"] != 2 or facts["dump"]):
            raise SystemExit("HOLD expiry failed to exclude queued page and subsequent writes")
        results.append({"scenario": scenario, "returncode": result.returncode,
                        "status": "PASS_FULL_NUT_FAKE", "facts": facts, "data_qualified": False})
    return results


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    portable = args.nut_build is None
    here = Path(__file__).resolve().parent
    extractor_path = here / "extract_hidapi_nut.py"
    extractor = load(extractor_path, "full_fake_pinned_extractor", EXTRACTOR_PIN)
    paths = [args.nut_source, args.hidapi_source, args.output_dir]
    if args.nut_build is not None:
        paths.append(args.nut_build)
    for path in paths:
        if extractor._has_symlink_component(path):
            raise SystemExit("HOLD symlink path component")
    nut = args.nut_source.resolve(strict=True)
    hidapi = args.hidapi_source.resolve(strict=True)
    build = args.nut_build.resolve(strict=True) if args.nut_build is not None else None
    output = args.output_dir.absolute()
    protected_paths = [nut, hidapi, here.parents[1]]
    if build is not None:
        protected_paths.append(build)
    for protected in protected_paths:
        if extractor.paths_overlap(output, protected):
            raise SystemExit("HOLD output overlaps protected inputs")
    fixed = {extractor_path: EXTRACTOR_PIN, here / "process_deadline.py": DEADLINE_PIN}
    if portable:
        verify_dependency_paths([nut, hidapi, here, output])
        config_source = here / "test_hidapi_full_config.h"
        version_source = here / "test_hidapi_full_version.h"
        fixed.update({config_source: PORTABLE_CONFIG_PIN, version_source: PORTABLE_VERSION_PIN})
        fixed.update({nut / name: pin for name, pin in PORTABLE_SOURCE_PINS.items()})
        reject_header_shadows(nut, hidapi, here)
    else:
        config_source = build / "include/config.h"
        version_source = build / "include/nut_version.h"
        fixed.update({config_source: CONFIG_PIN, version_source: VERSION_PIN})
    fixed.update({nut / name: pin for name, pin in {**extractor.PINNED_INPUTS, **SOURCE_PINS}.items()})
    fixed.update({here / name: pin for name, pin in MODULE_PINS.items()})
    fixed.update({hidapi / name: pin for name, pin in HEADER_PINS.items()})
    archives = []
    if build is not None:
        archives = [build / "common/.libs" / name for name in ARCHIVE_PINS]
        fixed.update({path: ARCHIVE_PINS[path.name] for path in archives})
    for path, pin in fixed.items():
        verify(path, pin)
    local_sources = [here / "test_hidapi_full_driver.c", here / "test_hidapi_full_os.h", Path(__file__).resolve()]
    # Additional NUT headers are a read-only input pack, hashed before/after.
    headers = [*sorted((nut / "include").glob("*.h")), *sorted((nut / "drivers").glob("*.h"))]
    before = {path: digest(path) for path in {*fixed, *local_sources, *headers}}
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    include_dir = output / "include"
    staged_config = staged_version = None
    if portable:
        include_dir.mkdir(mode=0o700)
        staged_config = include_dir / "config.h"
        staged_version = include_dir / "nut_version.h"
        staged_config.write_bytes(config_source.read_bytes())
        staged_version.write_bytes(version_source.read_bytes())
        staged_config.chmod(0o600)
        staged_version.chmod(0o600)
        verify(staged_config, fixed[config_source])
        verify(staged_version, fixed[version_source])
        before[staged_config] = fixed[config_source]
        before[staged_version] = fixed[version_source]
    driver = (nut / "drivers/apcmicrolink.c").read_text(encoding="utf-8")
    checksum = "/* SPDX-License-Identifier: GPL-2.0-or-later */\n" + extractor.extract_notice(driver) + "\n\n" + extractor.exact_function(driver, extractor.FUNCTIONS[5][1]) + "\n"
    checksum_path = output / "full_checksum_generated.inc"
    checksum_path.write_text(checksum, encoding="utf-8")
    verify(checksum_path, CHECKSUM_PIN)
    include_paths = [str(include_dir)] if portable else [str(build / "include")]
    base = ["/usr/bin/clang", "-std=gnu99", "-g", "-O0", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Wno-unused-parameter",
            "-DMLINK_HIDAPI_NATIVE_CANDIDATE=1", "-I", *include_paths,
            "-I", str(nut / "include"), "-I", str(nut / "drivers"), "-I", str(here),
            "-I", str(output), "-I", str(hidapi / "hidapi"), "-I", str(hidapi / "mac")]
    units = compile_units(nut, here, portable)
    objects = []
    for index, (source, flags, guarded) in enumerate(units):
        obj = output / f"unit-{index:02d}.o"
        guard = ["-include", str(here / "test_hidapi_full_os.h")] if guarded else []
        dependency_path = output / f"compile-{index:02d}.d"
        trace_flag = ["-H", "-MD", "-MF", str(dependency_path),
                      "-MT", "ups_full_fake_dependency_target"] if portable else []
        command([*base, *trace_flag, *guard, *flags, "-c", str(source), "-o", str(obj)], output, f"compile-{index:02d}")
        if portable:
            required_headers = set()
            if guarded or source == here / "test_hidapi_full_driver.c":
                required_headers.add(staged_config.resolve())
            if source == nut / "common/common-nut_version.c":
                required_headers.add(staged_version.resolve())
            if required_headers:
                verify_includes(dependency_path, required_headers, source.name)
        if source.name == "apcmicrolink-hidapi-native.c":
            imports = command(["/usr/bin/nm", "-u", str(obj)], output, "native-clock-imports")
            symbols = {line.split()[-1] for line in imports.splitlines() if line.split()}
            if "_fixture_native_clock_gettime" not in symbols or "_clock_gettime" in symbols:
                raise SystemExit("HOLD native clock was not isolated per translation unit")
        objects.append(obj)
    binary = output / "full-nut-hidapi-fake"
    try:
        command([*base, *(str(path) for path in objects), *(str(path) for path in archives),
                 "-lm", "-Wl,-map," + str(output / "full-fake.map"), "-o", str(binary)], output, "link-full-fake")
    finally:
        if binary.exists():
            binary.chmod(0o600)
    binary_audit = audit(binary, output)
    link_map = (output / "full-fake.map").read_text()
    if "libcommon_la-common.o" in link_map or "common-nut_version.o" in link_map or any(token in link_map for token in ("hidapi-candidate/", "libdummy_serial", "libdummy_libusb", "libdummy_upsdrvquery")):
        raise SystemExit("HOLD unexpected real/common duplicate archive object in link map")
    if portable:
        verify_portable_objects(link_map, objects)
    unit_binary = output / "pure-frames-unit"
    try:
        command([*base, "-Werror", str(here / "test_hidapi_full_frames.c"), str(here / "test_hidapi_full_frames_test.c"), "-o", str(unit_binary)], output, "compile-pure-frames")
    finally:
        if unit_binary.exists():
            unit_binary.chmod(0o600)
    audit(unit_binary, output, pure_frames=True)
    pure_frames_state = "NOT_RUN"
    if not args.compile_only:
        try:
            unit_binary.chmod(0o700)
            unit_result = command([str(unit_binary)], output, "run-pure-frames", timeout=10)
        finally:
            unit_binary.chmod(0o600)
        pure_frames_state = "PASS"
        print(unit_result, end="")
    unit_binary.chmod(0o600)
    results = []
    try:
        if args.run_fake:
            process_helper = load(here / "process_deadline.py", "process_deadline", DEADLINE_PIN)
            binary.chmod(0o700)
            results = execute_fake(binary, output, process_helper,
                                   executable_sha256=binary_audit["binary_sha256"])
        for path, pin in before.items():
            verify(path, pin)
        verify(binary, binary_audit["binary_sha256"])
        state = ("PASS_FULL_NUT_FAKE" if args.run_fake else
                 "COMPILE_ONLY_FULL_NOT_RUN" if args.compile_only else "BUILT_AUDITED_FULL_NOT_RUN")
        receipt = {"state": state,
                   "audit": binary_audit, "scenarios": results, "pure_frames": pure_frames_state,
                   "pins": {str(path): pin for path, pin in sorted(before.items())},
                   "checksum_sha256": CHECKSUM_PIN,
                   "build_configuration": "PORTABLE_SYNTHETIC" if portable else "LEGACY_NUT_BUILD",
                   "full_config_portability": "PUBLIC_SYNTHETIC_TEST_CONFIG" if portable else "OPEN_PRIVATE_INPUT",
                   "required_auth": "OPEN_NOT_PROVEN_FOR_SMC", "hardware": "NOT_RUN", "data_qualified": False}
        (output / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    finally:
        binary.chmod(0o600)
    print(f"{receipt['state']}; SHA-256 fake={binary_audit['binary_sha256']}; actual HIDAPI NOT_LINKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
