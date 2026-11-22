#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replay extracted NUT protocol over real inactive modules and fake HIDAPI only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

EXTRACTOR_PIN = "54282ba3dde93578f36976fb6905dee7cffe87739938d00edc9a6f6b40433dad"
LEGACY_CONFIG_PIN = "2efcc93b54fc93fc77f8e160f8639253b7746a2fd47a6cfc57a3030657a5c04b"
PORTABLE_CONFIG_PIN = "4521ce77521f4be3b9dac37270d2fdc0f31abdea5b7d08d44d42c7dd7cdc859b"
SUPERVISOR_PIN = "4562795add6758cef368c9ca56c149d6329659e58a18f52d2ec2ec2d6d23d743"
DEADLINE_PIN = "56f25ba1511b947ff9a54534cfa7b0f30e6c2ed531c000920e6951568620dc92"
MODULE_PINS = {
    "apcmicrolink-hidapi-shared.c": "a87a7d001b992b7b1cfd1afd96d4432cb5a5d9bfe40550c1877ebd646ba83a21",
    "apcmicrolink-hidapi-native.c": "3a1205741d62e02871d96c4e3091674b8131e8d3d95e58b156f2f95e9de1d2a5",
    "apcmicrolink-hid-descriptor-checked.c": "7db55b980569f8385196d10c30a966b0e78f1f9266c624f05a3c2459d13ebc85",
    "apcmicrolink-hidapi-shared-host.h": "606caa96cef85055c68c3b0d7c999e57e24efeb7bac16427dc8836bfd0631dcd",
    "apcmicrolink-hidapi-session.h": "50104ad0660fbd3c77fa185b0d8e00269f59775a1e123d3b548cb6c86f77d5ae",
    "apcmicrolink-hidapi-native.h": "648531900d7d2413a59dd36c04e3cd05a3c466ec52062b2e17437cd5b2064ada",
    "apcmicrolink-hid-descriptor-checked.h": "65c24b24313ba78c8293ede0485839c496165779f4d87cedde5e882a9f266b52",
}
HEADER_PINS = {
    "hidapi/hidapi.h": "c9cef28c53a13a9403e54d5a8a099d51afff119ab04094df89356df0833a822e",
    "mac/hidapi_darwin.h": "48854f6f6b612a90291c3de83a5755c2ed8642da173151a41377090821c39187",
}
INVALID = ("flag", "guard", "port", "fallback", "attempts", "vid-zero", "pid-zero",
           "deadline-zero", "deadline-large", "deadline-overflow", "filter", "baudrate")
FATAL = ("init", "open", "descriptor", "descriptor-read", "descriptor-stop", "exclusive", "after-open")
SCENARIOS = (
    "positive-protocol", "probe-exhaustion", "cleanup-stop", "cleanup-signal",
    "cleanup-deadline", "partial-write", "stop-after-stop", "auth-denial",
    "reentrant-finish", "read-stop", "read-deadline", "no-fallback", "retained-exit",
    *("invalid-" + name for name in INVALID), *("fatal-" + name for name in FATAL),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(command: list[str], *, timeout: int = 30,
            temporary_directory: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                   "PYTHONDONTWRITEBYTECODE": "1"}
    if temporary_directory is not None:
        environment["TMPDIR"] = str(temporary_directory)
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                            env=environment)
    if result.returncode:
        raise SystemExit(f"HOLD command exit={result.returncode}: {command[0]}\n"
                         + result.stdout + result.stderr)
    return result


def verify(path: Path, expected: str) -> None:
    if not path.is_file() or path.is_symlink() or sha256(path) != expected:
        raise SystemExit(f"HOLD pinned input mismatch: {path.name}")


def select_nut_config(explicit: Path | None, default_path: Path | None = None
                      ) -> tuple[Path, str, str]:
    default = default_path or Path(__file__).resolve().with_name("test_hidapi_nut_config.h")
    if explicit is None:
        verify(default, PORTABLE_CONFIG_PIN)
        return default, "portable-test", PORTABLE_CONFIG_PIN
    selected = Path(explicit)
    digest = sha256(selected) if selected.is_file() and not selected.is_symlink() else ""
    if digest == PORTABLE_CONFIG_PIN:
        return selected, "portable-test", PORTABLE_CONFIG_PIN
    if digest == LEGACY_CONFIG_PIN:
        return selected, "legacy-private-generated", LEGACY_CONFIG_PIN
    raise SystemExit("HOLD --nut-config is not one of the pinned config headers")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"HOLD cannot load local helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    if name in sys.modules:
        raise SystemExit(f"HOLD helper module already loaded: {name}")
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def audit_fake(binary: Path, output: Path) -> None:
    undefined = checked(["/usr/bin/nm", "-u", str(binary)]).stdout
    defined = checked(["/usr/bin/nm", str(binary)]).stdout
    dependencies = checked(["/usr/bin/otool", "-L", str(binary)]).stdout
    (output / "audit-undefined.txt").write_text(undefined, encoding="utf-8")
    (output / "audit-defined.txt").write_text(defined, encoding="utf-8")
    (output / "audit-dependencies.txt").write_text(dependencies, encoding="utf-8")
    dependency_lines = "\n".join(dependencies.splitlines()[1:]).lower()
    if any(token in (undefined.lower() + dependency_lines)
           for token in ("libusb", "libhidapi", "iokit", "corefoundation", "iohid", "ioservice")):
        raise SystemExit("HOLD fake binary links hardware code")
    undefined_names = {line.split()[-1] for line in undefined.splitlines() if line.split()}
    # _open/_fdopen create only the new O_EXCL0600 lifecycle sidecar in the
    # two explicitly selected supervisor scenarios; no device file is opened.
    if undefined_names.intersection({"_socket", "_connect", "_dlopen", "_ioctl",
                                     "_kill", "_system", "_execve", "_posix_spawn"}):
        raise SystemExit("HOLD fake binary imports network/device/process control")
    if "mlink_shared_test_bind" in defined or "mlink_shared_test_unbind" in defined:
        raise SystemExit("HOLD production replay exposes test binding")
    for name in ("hid_init", "hid_exit", "hid_enumerate", "hid_free_enumeration",
                 "hid_open_path", "hid_get_report_descriptor", "hid_read_timeout", "hid_write",
                 "hid_close", "hid_darwin_set_open_exclusive", "hid_darwin_get_open_exclusive",
                 "hid_darwin_is_device_open_exclusive", "clock_gettime"):
        symbol = "_" + name
        if symbol in undefined_names or not any(line.endswith(" " + symbol) for line in defined.splitlines()):
            raise SystemExit(f"HOLD missing fake definition: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nut-source", required=True, type=Path)
    parser.add_argument("--nut-config", type=Path,
                        help="optional pinned legacy config; default is the repository's test-only USB1 header")
    parser.add_argument("--hidapi-source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    extractor_path = here / "extract_hidapi_nut.py"
    verify(extractor_path, EXTRACTOR_PIN)
    extractor = load_module(extractor_path, "pinned_nut_extractor")
    config, config_kind, config_pin = select_nut_config(args.nut_config)
    for path in (args.nut_source, args.hidapi_source, config, args.output_dir):
        if extractor._has_symlink_component(path):
            raise SystemExit("HOLD input/output path contains a symlink component")
    nut = args.nut_source.resolve(strict=True)
    hidapi = args.hidapi_source.resolve(strict=True)
    config = config.resolve(strict=True)
    supervisor_path = here / "test_hidapi_nut_supervisor.py"
    deadline_path = here / "process_deadline.py"
    verify(supervisor_path, SUPERVISOR_PIN)
    verify(deadline_path, DEADLINE_PIN)
    verify(config, config_pin)
    for relative, digest in MODULE_PINS.items():
        verify(here / relative, digest)
    for relative, digest in HEADER_PINS.items():
        verify(hidapi / relative, digest)
    for relative, digest in extractor.PINNED_INPUTS.items():
        verify(nut / relative, digest)
    if any(line.lstrip().startswith(("#include", "# include")) for line in config.read_text().splitlines()):
        raise SystemExit("HOLD pinned config unexpectedly includes another header")
    inputs = [Path(__file__).resolve(), here / "test_hidapi_nut.c", extractor_path, config,
              supervisor_path, deadline_path,
              *(here / name for name in MODULE_PINS), *(hidapi / name for name in HEADER_PINS),
              *(nut / name for name in extractor.PINNED_INPUTS)]
    before = {path: sha256(path) for path in inputs}
    output = args.output_dir.absolute()
    protected = [nut, hidapi, here.parents[1]]
    if config_kind == "legacy-private-generated":
        protected.append(config.parent)
    for protected_root in protected:
        if extractor.paths_overlap(output, protected_root):
            raise SystemExit("HOLD output overlaps a protected source tree")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    extracted = output / "extracted"
    checked([sys.executable, "-I", "-B", str(extractor_path), "--nut-source", str(nut),
             "--output-dir", str(extracted)])
    manifest = json.loads((extracted / "manifest.json").read_text())
    generated = extracted / "hidapi_nut_generated.c"
    verify(generated, manifest["generated_sha256"])
    if {item["path"]: item["sha256"] for item in manifest["source_files"]} != extractor.PINNED_INPUTS:
        raise SystemExit("HOLD extracted manifest source pins disagree")
    if manifest["extracted"] != [name for name, _ in extractor.FUNCTIONS]:
        raise SystemExit("HOLD extracted function list disagrees")
    binary = output / "synthetic-hidapi-nut"
    command = ["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-H",
               "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               "-DMLINK_HIDAPI_NATIVE_CANDIDATE=1", "-include", str(config),
               "-I", str(here), "-I", str(nut / "drivers"), "-I", str(extracted),
               "-I", str(hidapi / "hidapi"), "-I", str(hidapi / "mac"),
               str(here / "test_hidapi_nut.c"),
               *(str(here / name) for name in MODULE_PINS if name.endswith(".c")),
               "-o", str(binary)]
    build = checked(command, timeout=60, temporary_directory=output)
    (output / "build.stderr").write_text(build.stderr, encoding="utf-8")
    for header in (nut / "drivers/apcmicrolink.h", nut / "drivers/apcmicrolink-usb.h",
                   nut / "drivers/nut-guarded-policy.h", hidapi / "hidapi/hidapi.h",
                   hidapi / "mac/hidapi_darwin.h"):
        if str(header) not in build.stderr:
            raise SystemExit(f"HOLD compiler trace omitted pinned header {header.name}")
    audit_fake(binary, output)  # Mandatory BEFORE the first process runs.
    binary_sha = sha256(binary)
    results = []
    try:
        for scenario in SCENARIOS:
            result = subprocess.run([str(binary), scenario], capture_output=True, text=True,
                                    timeout=10, check=False,
                                    env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                                         "TMPDIR": str(output)})
            (output / f"{scenario}.stdout").write_text(result.stdout, encoding="utf-8")
            (output / f"{scenario}.stderr").write_text(result.stderr, encoding="utf-8")
            expected_exit = 73 if scenario.startswith(("invalid-", "fatal-")) else 0
            marker = f"PASS scenario={scenario} reached=1 "
            if result.returncode != expected_exit or sum(line.startswith(marker) for line in result.stdout.splitlines()) != 1:
                raise SystemExit(f"HOLD scenario {scenario}: exit={result.returncode}\n" + result.stdout + result.stderr)
            if expected_exit == 0 and result.stderr:
                raise SystemExit(f"HOLD unexpected stderr: {scenario}\n" + result.stderr)
            if expected_exit == 73 and (result.stderr.count("FATAL_STUB:") != 1 or "Sanitizer" in result.stderr):
                raise SystemExit(f"HOLD fatal path did not reach its sole expected boundary: {scenario}")
            print(result.stdout, end="")
            results.append({"scenario": scenario, "exit": result.returncode, "status": "PASS"})
        load_module(deadline_path, "process_deadline")
        supervisor = load_module(supervisor_path, "pinned_fake_nut_supervisor")
        supervisor_result = supervisor.run_supervisor_checks(
            binary, output, executable_sha256=binary_sha)
        if supervisor_result.get("status") != "PASS":
            raise SystemExit("HOLD synthetic supervisor checks did not pass")
        (output / "supervisor-results.json").write_text(
            json.dumps(supervisor_result, indent=2) + "\n", encoding="utf-8")
        print("PASS synthetic supervisor cooperative and blocked cancellation; data_qualified=false")
        for path, digest in before.items():
            verify(path, digest)
        verify(binary, binary_sha)
        receipt = {"status": "PASS_EXTRACTED_COUPLED_FAKE", "config_kind": config_kind,
                   "scenarios": results,
                   "binary_sha256": binary_sha, "generated_sha256": manifest["generated_sha256"],
                   "supervisor": supervisor_result,
                   "pins": {str(path): digest for path, digest in before.items()},
                   "full_nut_main": "NOT_RUN", "full_receive_decoder": "STUBBED",
                   "real_hidapi": "NOT_LINKED_NOT_RUN"}
        (output / "results.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    finally:
        binary.chmod(0o600)
    print(f"PASS coupled isolated scenarios={len(results)}; no full main or full receive decoder")
    print(f"SHA-256 binary={binary_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
