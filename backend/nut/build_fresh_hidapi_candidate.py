#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build and statically audit the macOS HIDAPI 0.16 reader from an offline developer kit."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shlex
import shutil
import signal
import stat
import sys
import tarfile
import tempfile
from threading import Event, Thread
import time


MIB = 1024 ** 2
KIT_LIMIT = 101 * MIB
ARTIFACT_LIMIT = 4 * MIB
SCRATCH_LIMIT = 2048 * MIB
PHASE_SECONDS = 600
BUILD_SECONDS = 1200
KIT_ROOT = "UPS-Monitor-Developer-Inputs"
SUPERVISOR_PIN = "81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e"
NUT_PIN = "e3ea175565c461a9e741df77dd91103d695b9c60f8d423d9b6ce6c778f98615f"
NUT_NOTICE_PATHS = ("COPYING", "LICENSE-GPL2", "LICENSE-GPL3")
VENDOR_015 = "drivers/hidapi-candidate"
VENDOR_016 = "drivers/hidapi-0.16.0"
NATIVE_ADAPTER = "drivers/apcmicrolink-hidapi-native.c"
HID_TU = VENDOR_016 + "/mac/hid.c"
UNITS = tuple("drivers/" + name + ".c" for name in (
    "main", "dstate", "apcmicrolink", "apcmicrolink-maps", "apc_common",
    "apcmicrolink-continuous", "apcmicrolink-hidapi-shared", "apcmicrolink-hid-descriptor-checked",
    "apcmicrolink-hidapi-native", "hidapi-0.16.0/mac/hid", "apcmicrolink-operational-freshness",
))
ARCHIVES = {
    "drivers/.libs/libdummy_serial.a": ("serial.o",),
    "drivers/.libs/libdummy_upsdrvquery.a": ("upsdrvquery.o",),
    "common/.libs/libcommon.a": ("libcommon_la-state.o", "libcommon_la-str.o", "libcommon_la-upsconf.o",
                                "libcommon_la-common.o", "parseconf.o"),
    "common/.libs/libcommonversion.a": ("common-nut_version.o",),
    "common/.libs/libparseconf.a": ("parseconf.o",),
}
GENERATED = ("include/config.h", "include/nut_version.h", *ARCHIVES)
SDK_INPUTS = (
    "System/Library/Frameworks/IOKit.framework/IOKit.tbd",
    "System/Library/Frameworks/CoreFoundation.framework/CoreFoundation.tbd",
    "usr/lib/libm.tbd", "usr/lib/libSystem.tbd",
    *("usr/lib/system/lib" + name + ".tbd" for name in (
        "compiler_rt", "system_asl", "system_c", "system_info", "system_kernel", "system_malloc", "system_pthread")),
)
LIBRARIES = (
    "/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit",
    "/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation",
    "/usr/lib/libSystem.B.dylib",
)
NUT_LOCALE_LINKS = {
    "scripts/python/app/locale/" + suffix: target
    for lang, name in (("fr", "fr_FR"), ("it", "it_IT"), ("ru", "ru_RU"))
    for suffix, target in ((f"{lang}/{name}.UTF-8.po", f"{lang}.po"), (f"{name}.UTF-8", lang))
}
PRODUCT = "PRODUCT"
PREFIX = Path("/private/tmp/ups-monitor-prefix-unused")
VERSION_LINES = {
    "aclocal": "aclocal (GNU automake) 1.19",
    "autoconf": "autoconf (GNU Autoconf) 2.73",
    "autoheader": "autoheader (GNU Autoconf) 2.73",
    "autom4te": "autom4te (GNU Autoconf) 2.73",
    "automake": "automake (GNU automake) 1.19",
    "autoreconf": "autoreconf (GNU Autoconf) 2.73",
    "glibtoolize": "glibtoolize (GNU libtool) 2.6.2",
    "m4": "m4 (GNU M4) 1.4.21",
    "make": "GNU Make 3.81",
    "pkgconf": "3.0.11",
}


def require(condition: bool, why: str) -> None:
    if not condition:
        raise ValueError(why)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def path_name(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    require(bool(path.parts) and not path.is_absolute() and path.as_posix() == value and
            ".." not in path.parts and not any(c.isspace() or c in "\\,\0" for c in value),
            "invalid archive or manifest path")
    return path


def directory(path: Path) -> Path:
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_dir(),
            "expected canonical absolute directory: " + str(path))
    return path


def read_file(path: Path, limit: int = ARTIFACT_LIMIT) -> bytes:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and path.resolve(strict=True) == path and info.st_size <= limit,
            "expected bounded regular file: " + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino),
                "file identity changed: " + str(path))
        raw = stream.read(limit + 1)
    require(len(raw) == info.st_size, "file size changed: " + str(path))
    return raw


def write_file(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def write_json(path: Path, value: dict) -> None:
    write_file(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def archive_rows(archive: tarfile.TarFile, maximum: int,
                 links: dict[str, str] | None = None) -> dict[str, tarfile.TarInfo]:
    rows = {}
    size = 0
    for member in archive:
        require(len(rows) < 100_000, "too many archive members")
        name = path_name(member.name).as_posix()
        require(name not in rows and (member.isreg() or member.isdir() or
                (member.issym() and (links or {}).get(name) == member.linkname)),
                "duplicate or unadmitted archive member: " + name)
        require(not member.sparse and 0 <= member.size <= maximum, "archive member size")
        rows[name] = member
        size += member.size
        require(size <= maximum, "archive payload size")
    require(bool(rows), "empty archive")
    for name, member in rows.items():
        path = PurePosixPath(name)
        require(all(parent.as_posix() not in rows or rows[parent.as_posix()].isdir()
                    for parent in path.parents), "file or link used as archive directory")
        if member.issym():
            target = rows.get((path.parent / member.linkname).as_posix())
            require(target is not None and not target.issym(), "missing locale link target")
    require({name for name, row in rows.items() if row.issym()} == set(links or {}), "wrong locale links")
    return rows


def archive_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    require(member.isreg(), "expected regular archive input")
    with archive.extractfile(member) as stream:
        raw = stream.read(member.size + 1)
    require(len(raw) == member.size, "short archive member")
    return raw


def load_module(path: Path, raw: bytes, name: str):
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def kit_inputs(path: Path, expected: str, root: Path, receipt: dict) -> tuple[Path, Path, dict, dict]:
    blob = read_file(path, KIT_LIMIT)
    require(digest(blob) == expected, "developer kit SHA-256 mismatch")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        members = archive_rows(archive, KIT_LIMIT)
        prefix = KIT_ROOT + "/"
        require(KIT_ROOT in members and members[KIT_ROOT].isdir() and
                all(name == KIT_ROOT or name.startswith(prefix) for name in members), "unexpected developer kit root")
        listed = archive_bytes(archive, members[prefix + "SHA256SUMS"])
        require(len(listed) <= 16_384, "SHA256SUMS exceeds limit")
        checksums = {}
        for line in listed.decode("ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            require(match is not None, "invalid SHA256SUMS row")
            pin, name = match.groups()
            path_name(name)
            require(name not in checksums, "duplicate SHA256SUMS row")
            checksums[name] = pin
        files = {name.removeprefix(prefix): member for name, member in members.items() if member.isreg()}
        require(len(checksums) == 23 and files.keys() == checksums.keys() | {"SHA256SUMS"},
                "wrong developer kit file closure")

        def verified_member(name: str) -> bytes:
            value = archive_bytes(archive, files[name])
            require(digest(value) == checksums[name], "kit member SHA-256 mismatch: " + name)
            return value

        for name, pin in checksums.items():
            # Wheel and embedded Python inputs are verified as data and never executed.
            with archive.extractfile(files[name]) as stream:
                require(hashlib.file_digest(stream, "sha256").hexdigest() == pin, "kit member SHA-256 mismatch: " + name)
        project = verified_member("source/project.tar")
        nut = root / "nut.tar"
        require(checksums["native/nut.tar"] == NUT_PIN, "wrong NUT source archive")
        write_file(nut, verified_member("native/nut.tar"))
        checkout = root / "project"
        with tarfile.open(fileobj=io.BytesIO(project), mode="r:") as source_archive:
            rows = archive_rows(source_archive, 32 * MIB)
            roots = {PurePosixPath(name).parts[0] for name in rows}
            require(len(roots) == 1, "project archive must have one root")
            project_root = roots.pop() + "/"
            for name, member in rows.items():
                relative = name.removeprefix(project_root)
                require(member.isdir() or name.startswith(project_root), "regular project root")
                if member.isreg() and (relative.startswith("backend/nut/") or relative == "scripts/export_developer_kit.py"):
                    write_file(checkout / relative, archive_bytes(source_archive, member))
        exporter_path = checkout / "scripts/export_developer_kit.py"
        exporter = load_module(exporter_path, read_file(exporter_path), "_ups_fresh_export_locks")
        recipe = checkout / exporter.NATIVE_RECIPE
        cal = exporter.parse_json(read_file(recipe / "production_source_post_cal.json"), "CAL", unique_keys=True)
        locks = {name: read_file(checkout / name) for name in (*exporter.HIDAPI_016_SUPPORT,
                                                              exporter.NATIVE_RECIPE + "production_source_post_cal.json")}
        pins = exporter.hidapi_016_locks(locks, cal)
        profile = json.loads(locks[exporter.NATIVE_RECIPE + "hidapi-0.16/manifest.json"])
        cancel = json.loads(locks[exporter.NATIVE_RECIPE + "production_source_post_write_cancel.json"])
        require(cal["upstream"]["archive_sha256"] == NUT_PIN, "wrong CAL source archive")
        legacy = {}
        legacy_hashes = cal["hidapi"]["source_sha256"]
        require(legacy_hashes.keys() == set(exporter.HIDAPI_PATHS), "wrong HIDAPI 0.15 source closure")
        for name, pin in legacy_hashes.items():
            raw = verified_member("native/hidapi/" + name)
            require(digest(raw) == pin, "wrong HIDAPI 0.15 source: " + name)
            legacy[Path(name).name] = raw
        licenses = cal["hidapi"]["license_sha256"]
        require(licenses.keys() == set(exporter.HIDAPI_LICENSES), "wrong HIDAPI license closure")
        for name, pin in licenses.items():
            raw = read_file(recipe / "licenses/hidapi" / name)
            require(digest(raw) == pin, "wrong HIDAPI 0.15 notice: " + name)
            legacy["licenses/" + name] = raw
        upgrade = {}
        for name, (size, pin) in pins.items():
            raw = verified_member("native/hidapi-0.16/" + name)
            require(len(raw) == size and digest(raw) == pin, "wrong HIDAPI 0.16 input: " + name)
            upgrade[name] = raw
        receipt["inputs"] = {"kit_sha256": expected, "file_sha256": checksums,
                             "patch_and_manifest_sha256": {name: digest(raw) for name, raw in locks.items()}}
        receipt["hidapi"] = {"tag": profile["hidapi"]["tag"], "commit": profile["hidapi"]["commit"],
                             "files": {name: digest(raw) for name, raw in upgrade.items()}}
        return checkout / "backend/nut", nut, {"cal": cal, "cancel": cancel, "profile": profile}, {
            VENDOR_015: legacy, VENDOR_016: upgrade,
        }


def unpack_nut(path: Path, source: Path) -> dict[str, str]:
    raw = read_file(path, 32 * MIB)
    require(digest(raw) == NUT_PIN, "NUT source archive changed")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        rows = archive_rows(archive, 32 * MIB, NUT_LOCALE_LINKS)
        notices = {name: digest(archive_bytes(archive, rows[name])) for name in NUT_NOTICE_PATHS}
        for name, member in rows.items():
            target = source / name
            if member.isreg():
                write_file(target, archive_bytes(archive, member))
                target.chmod(0o700 if member.mode & 0o111 else 0o600)
            elif member.isdir():
                target.mkdir(parents=True, exist_ok=True)
        for name, target in NUT_LOCALE_LINKS.items():
            (source / name).symlink_to(target)
    return notices


def checked_tree(root: Path, expected: dict[str, str]) -> None:
    require(all(digest(read_file(root / path_name(name))) == pin for name, pin in expected.items()),
            "source checkpoint mismatch")


def probe_audit(path: Path, generated: bool) -> dict:
    raw = read_file(path)
    text = raw.decode("utf-8")
    marker = "whether staged HIDAPI 0.15.0 compiles and links (never run)"
    require(text.count("hid_init()") == 1 and marker in text, "HIDAPI probe shape")
    block = text[text.index(marker):].split('LIBS="$nut_hidapi_save_LIBS"', 1)
    link, run = ("ac_fn_c_try_link", "ac_fn_c_try_run") if generated else ("AC_LINK_IFELSE", "AC_RUN_IFELSE")
    require(len(block) == 2 and "hid_init()" in block[0] and link in block[0] and run not in block[0] and
            not re.search(r"(?m)^\s*(?:\./|\$\{?ac_exeext)", block[0]), "HIDAPI configure probe must link only")
    return {"file_sha256": digest(raw), "link_probe": link, "probe_sha256": digest(block[0].encode())}


def identity(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    require(resolved.is_file(), "expected tool or resource file: " + str(path))
    return {"path": str(path), "resolved": str(resolved), "sha256": sha_file(resolved)}


def resource_tree(root: Path) -> dict:
    resolved = root.resolve(strict=True)
    require(resolved.is_dir(), "missing tool resources: " + str(root))
    rows = {}
    size = 0
    for path in sorted(resolved.rglob("*")):
        info = path.lstat()
        name = path.relative_to(resolved).as_posix()
        require(len(rows) < 10_000, "tool resource count")
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), "redirected tool resource: " + name)
        if path.is_file():
            size += info.st_size
            require(size <= 128 * MIB, "tool resource size")
            rows[name] = sha_file(path)
        else:
            rows[name] = None
    return {"path": str(root), "resolved": str(resolved), "entries": rows}


class Build:
    def __init__(self, root: Path, out: Path, receipt: dict, supervisor, end: float):
        self.root, self.out, self.receipt, self.supervisor, self.end = root, out, receipt, supervisor, end
        self.source, self.build = root / "source", root / "build"
        for name in ("source", "build", "tmp", "home", "cache"):
            (root / name).mkdir(mode=0o700)
        (out / "logs").mkdir(mode=0o700)
        self.cancel, self.stop = Event(), Event()
        self.errors = []
        self.peak = 0
        self.tools = {}
        self.resources = {}
        self.env = {}
        self.owned_clean = True
        self.watcher = Thread(target=self.watch, daemon=True)

    def watch(self) -> None:
        while not self.stop.wait(0.25):
            try:
                self.check_space()
            except (OSError, ValueError) as error:
                self.errors.append(str(error))
                self.cancel.set()
                return

    def check_space(self) -> None:
        allocated = 0
        for root in (self.root, self.out):
            for parent, dirs, files in os.walk(root, followlinks=False):
                for name in dirs + files:
                    try:
                        allocated += (Path(parent) / name).lstat().st_blocks * 512
                    except FileNotFoundError:
                        continue
        self.peak = max(self.peak, allocated)
        require(allocated <= SCRATCH_LIMIT, "2 GiB allocated scratch limit")
        log = self.build / "config.log"
        if log.exists() or log.is_symlink():
            item = log.lstat()
            require(stat.S_ISREG(item.st_mode) and item.st_size <= ARTIFACT_LIMIT, "4 MiB raw config.log limit")
        require(time.monotonic() < self.end, "build campaign deadline")

    def verify_tools(self) -> None:
        require(all(identity(Path(row["path"])) == row for row in self.tools.values()), "tool identity drift")
        require(all(resource_tree(Path(row["path"])) == row for row in self.resources.values()),
                "build resource drift")

    def run(self, label: str, cwd: Path, *command: str | Path) -> str:
        self.check_space()
        require(not self.cancel.is_set(), "campaign cancelled")
        self.verify_tools()
        cmd = ["/usr/bin/env", "-i", *(k + "=" + v for k, v in sorted(self.env.items())),
               "/bin/sh", "-c", 'cd "$1" && shift && exec "$@"', "ups-build", str(cwd), *map(str, command)]
        log = self.out / "logs" / label
        row = {"phase": label, "argv": cmd}
        self.receipt["phases"].append(row)
        try:
            result = self.supervisor.run_bounded(cmd, executable_sha256=self.tools["env"]["sha256"],
                output_directory=log, timeout_seconds=min(PHASE_SECONDS, self.end - time.monotonic()),
                termination_grace_seconds=5 if label == "prepare-sources" else 2, maximum_output_bytes=MIB, cancel_event=self.cancel)
        except self.supervisor.BoundedRunError as error:
            row["error"] = error.code.value
            if error.code == self.supervisor.RunErrorCode.CHILD_UNREAPED:
                self.owned_clean = False
            raise ValueError("bounded phase failed: " + label + " (" + error.code.value + ")") from error
        row["result"] = asdict(result)
        if result.status == self.supervisor.RunStatus.UNREAPED:
            self.owned_clean = False
        require(result.status == self.supervisor.RunStatus.EXITED and result.returncode == 0 and
                result.trigger == self.supervisor.RunTrigger.COMPLETED and result.observation is not None and
                not self.cancel.is_set(), "phase failed: " + label)
        return read_file(log / "stdout.bin", MIB).decode("utf-8")

    def patch(self, label: str, patch: Path, expected: str) -> None:
        require(digest(read_file(patch)) == expected, "patch input changed: " + patch.name)
        self.run(label, self.source, "/usr/bin/patch", "--batch", "--fuzz=0", "-p1",
                 "--no-backup-if-mismatch", "-i", patch)
        require(digest(read_file(patch)) == expected, "patch input changed: " + patch.name)

    def set_up_tools(self, autotools: Path, developer: Path) -> Path:
        apple_bin = developer / "Toolchains/XcodeDefault.xctoolchain/usr/bin"
        sdk = developer / "Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
        brew = Path("/opt/homebrew")
        libusb = brew / "opt/libusb"
        pkgconf = brew / "opt/pkgconf"
        libtool = brew / "opt/libtool"
        system = ("env", "patch", "perl", "xcrun", "ar", "ranlib", "ld", "libtool", "make")
        paths = {name: Path("/usr/bin") / name for name in system}
        paths.update({name: autotools / name for name in
                      ("aclocal", "autoconf", "autoheader", "autom4te", "automake", "autoreconf")})
        paths.update({name: apple_bin / name for name in ("clang", "clang++", "otool", "nm", "strings")})
        paths.update({"sh": Path("/bin/sh"), "python": Path(sys.executable).resolve(strict=True),
            "xcodebuild": developer / "usr/bin/xcodebuild", "m4": brew / "opt/m4/bin/m4",
            "pkgconf": pkgconf / "bin/pkgconf", "pkg.m4": pkgconf / "share/aclocal/pkg.m4",
            "glibtoolize": libtool / "bin/glibtoolize", "libusb.pc": libusb / "lib/pkgconfig/libusb-1.0.pc",
            "libusb.h": libusb / "include/libusb-1.0/libusb.h",
            "libusb.dylib": libusb / "lib/libusb-1.0.0.dylib", "libusb.a": libusb / "lib/libusb-1.0.a",
            "SDKSettings": sdk / "SDKSettings.json",
            "SDKSystemVersion": sdk / "System/Library/CoreServices/SystemVersion.plist"})
        paths.update({"sdk:" + name: sdk / name for name in SDK_INPUTS})
        self.tools.update({name: identity(path) for name, path in paths.items()})
        self.env.update({
            "PATH": f"{autotools}:{brew}/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.root / "home"), "USER": "builder", "LOGNAME": "builder",
            "TMPDIR": str(self.root / "tmp"), "XDG_CACHE_HOME": str(self.root / "cache"), "LC_ALL": "C",
            "CONFIG_SITE": "/dev/null", "DEVELOPER_DIR": str(developer), "SDKROOT": str(sdk),
            "MACOSX_DEPLOYMENT_TARGET": "27.0", "NUT_VERSION_PREFER_GIT": "false",
            "PKG_CONFIG": str(paths["pkgconf"]), "PKG_CONFIG_LIBDIR": str(paths["libusb.pc"].parent),
            "PKG_CONFIG_PATH": "", "PKG_CONFIG_SYSROOT_DIR": "",
            "ACLOCAL_PATH": f"{pkgconf}/share/aclocal:{libtool}/share/aclocal",
            "M4": str(paths["m4"]), "LIBTOOLIZE": str(paths["glibtoolize"]),
        })
        for name in ("ar", "ranlib", "ld", "libtool", "make", "perl", "aclocal", "autoconf",
                     "autoheader", "autom4te", "automake", "autoreconf"):
            require(shutil.which(name, path=self.env["PATH"]) == str(paths[name]), "PATH selects another " + name)
        self.resources.update({str(name): resource_tree(root) for name, root in {
            "autotools": autotools.parent, "glibtoolize-bin": libtool / "bin",
            "glibtoolize-aclocal": libtool / "share/aclocal", "glibtoolize-share": libtool / "share/libtool",
        }.items()})
        self.receipt["tool_sha256"] = self.tools
        self.receipt["tool_resources"] = self.resources
        versions = self.receipt["tool_versions"] = {"python": "3.15.2"}
        for name, version in VERSION_LINES.items():
            output = self.run("version-" + name, self.root, paths[name], "--version").splitlines()
            require(bool(output) and output[0] == version, "wrong " + name + " version")
            versions[name] = version
        xcode = self.run("version-xcode", self.root, paths["xcodebuild"], "-version").splitlines()
        require(xcode == ["Xcode 27.2", "Build version 27B52"], "wrong Xcode version")
        sdk_settings = json.loads(Path(self.tools["SDKSettings"]["resolved"]).read_bytes())
        sdk_build = plistlib.loads(Path(self.tools["SDKSystemVersion"]["resolved"]).read_bytes())
        sdk_version = self.run("version-sdk", self.root, paths["xcrun"], "--sdk", "macosx", "--show-sdk-version")
        require(sdk_settings["CanonicalName"] == "macosx27.2" and sdk_settings["Version"] ==
                sdk_build["ProductVersion"] == sdk_version.strip() == "27.2", "wrong SDK version")
        usb = self.run("version-libusb", self.root, paths["pkgconf"], "--modversion", "libusb-1.0").strip()
        require(usb == "1.0.30", "wrong libusb version")
        versions.update(xcode=xcode, sdk=sdk_version.strip(), sdk_build=sdk_build["ProductBuildVersion"], libusb=usb)
        for name in ("ar", "ranlib", "ld", "libtool", "make"):
            raw = self.run("resolve-" + name, self.root, paths["xcrun"], "--find", name).strip()
            expected = (developer / "usr/bin" if name == "make" else apple_bin) / name
            require(raw == str(expected), "Xcode resolves a different " + name)
            self.tools["xcode-" + name] = identity(expected)
        return sdk

    def configured_archive_tools(self) -> dict[str, str]:
        config = read_file(self.build / "config.log").decode(errors="replace")
        selected = {}
        for name in ("ar", "ranlib", "ld"):
            commands = re.findall(r"(?m)^" + name.upper() + r"='([^'\r\n]*)'$", config)
            require(len(commands) == 1, "configure tool value missing or ambiguous: " + name)
            resolved = commands[0] if commands[0].startswith("/") else (
                shutil.which(commands[0], path=self.env["PATH"]) or "")
            require(resolved in (self.tools[name]["path"], self.tools["xcode-" + name]["path"]),
                    "configure tool differs from reviewed tool: " + name)
            selected[name] = resolved
        return selected

    def archive_trace(self, configured: dict[str, str]) -> dict:
        require(self.configured_archive_tools() == configured, "archive tool selection changed")
        events = []
        covered = set()
        for phase in ("make-common", "make-dummy"):
            text = read_file(self.out / "logs" / phase / "stdout.bin", MIB).decode()
            subdir = phase.split("-")[1].replace("dummy", "drivers")
            for line in text.splitlines():
                if "libtool: link: " not in line:
                    continue
                command = shlex.split(line.split("libtool: link: ", 1)[1])
                if command and Path(command[0]).name in ("ar", "ranlib"):
                    role = Path(command[0]).name
                    path = command[0] if command[0].startswith("/") else (
                        shutil.which(command[0], path=self.env["PATH"]) or "")
                    require(path == configured[role], "archive command changed: " + role)
                    target = subdir + "/" + next((piece for piece in command[1:] if piece.endswith(".a")), "")
                    require(target in ARCHIVES, "unexpected archive target: " + target)
                    events.append({"phase": phase, "command": command})
                    covered.add((role, target))
        require(covered == {(name, path) for path in ARCHIVES for name in ("ar", "ranlib")},
                "incomplete archive production trace")
        return {"configure_tools": configured, "commands": events,
                "generated_gnu_libtool_sha256": digest(read_file(self.build / "libtool"))}


def read_generated(build: Path) -> dict[str, bytes]:
    return {name: read_file(build / name) for name in GENERATED}


def verify_generated(build: Path, pins: dict[str, str]) -> None:
    require(set(pins) == set(GENERATED) and {name: digest(raw) for name, raw in read_generated(build).items()} == pins,
            "fresh generated inputs changed before or during link")


def ar_inventory(raw: bytes, expected: tuple[str, ...]) -> dict:
    require(raw.startswith(b"!<arch>\n"), "bad static archive signature")
    index = None
    objects = {}
    offset = 8
    while offset < len(raw):
        position = offset
        header = raw[offset:offset + 60]
        require(len(header) == 60 and header[-2:] == b"`\n", "invalid archive member header")
        size = int(header[48:58])
        require(0 < size <= len(raw) - offset - 60, "bad archive member size")
        name = header[:16].rstrip(b" ")
        payload = raw[offset + 60:offset + 60 + size]
        if name.startswith(b"#1/"):
            length = int(name[3:])
            require(0 < length < size, "bad BSD archive member name length")
            name, payload = payload[:length].rstrip(b"\0"), payload[length:]
        label = name.removesuffix(b"/").decode("ascii")
        record = {"offset": position, "payload_sha256": digest(payload), "bytes": len(payload),
                  "date": int(header[16:28]), "uid": int(header[28:34]), "gid": int(header[34:40]),
                  "mode": int(header[40:48], 8)}
        if label == "__.SYMDEF SORTED":
            require(position == 8 and index is None, "duplicate or displaced archive index")
            index = (record, payload)
        else:
            require(label in expected and label not in objects and
                    payload[:8] == bytes.fromhex("cffaedfe0c000001") and payload[12:16] == b"\x01\x00\x00\x00",
                    "wrong or non-arm64 archive object: " + label)
            objects[label] = record
        offset += 60 + size
        if size % 2:
            require(raw[offset:offset + 1] == b"\n", "bad archive odd-member padding")
            offset += 1
    require(tuple(objects) == expected and index is not None, "archive member closure")
    record, payload = index
    table_bytes = int.from_bytes(payload[:4], "little")
    require(table_bytes > 0 and table_bytes % 8 == 0 and table_bytes + 8 <= len(payload), "bad archive symbol table")
    string_bytes = int.from_bytes(payload[4 + table_bytes:8 + table_bytes], "little")
    strings = payload[8 + table_bytes:]
    require(0 < string_bytes <= len(strings) and not any(strings[string_bytes:]), "bad archive index strings")
    offsets = {row["offset"] for row in objects.values()}
    indexed = set()
    for i in range(4, 4 + table_bytes, 8):
        string_index = int.from_bytes(payload[i:i + 4], "little")
        slot = int.from_bytes(payload[i + 4:i + 8], "little")
        require(slot in offsets and string_index < string_bytes and
                0 <= strings.find(b"\0", string_index, string_bytes) - string_index,
                "archive index points outside admitted members")
        indexed.add(slot)
    require(indexed == offsets, "archive index omits member")
    return {"members": [{"name": name, **row} for name, row in objects.items()], "bsd_sorted_index": record}


def check_generated(raw: dict[str, bytes], source: Path, build: Path, libusb: str,
                    config_argv: tuple[str, ...]) -> dict:
    require(set(raw) == set(GENERATED), "expected seven generated inputs")
    entries = re.findall(r"(?m)^#define ([A-Z0-9_]+)[ \t]+([^\r\n]+)$", raw["include/config.h"].decode())
    macros = dict(entries)
    require(len(macros) == len(entries), "duplicate generated config macro")
    expected = {"ABS_TOP_SRCDIR": str(source), "ABS_TOP_BUILDDIR": str(build),
                "CONFPATH": str(PREFIX / "etc/nut"), "LIBDIR": str(PREFIX / "lib"),
                "STATEPATH": "/var/state/ups", "ALTPIDPATH": "/var/state/ups", "PIDPATH": "/var/run",
                "SOPATH_LIBUSB1": libusb,
                "CONFIG_FLAGS": " ".join(arg for arg in config_argv if arg != "--disable-inplace-runtime")}
    require(all(macros.get(name) == json.dumps(value) for name, value in expected.items()) and
            all(macros.get(name) == "1" for name in ("HAVE_LIBUSB_H", "WITH_USB", "WITH_LIBUSB_1_0")) and
            macros.get("WITH_LIBUSB_0_1") == "0", "wrong generated configuration")
    versions = re.findall(r"(?m)^#define (NUT_VERSION_\w+) (.+)$", raw["include/nut_version.h"].decode())
    expected_versions = {"NUT_VERSION_MACRO": '"2.8.5.1"', "NUT_VERSION_SEMVER_MACRO": '"2.8.5"',
                         "NUT_VERSION_IS_RELEASE": "0", "NUT_VERSION_IS_PRERELEASE": "0"}
    require(len(versions) == len(expected_versions) and dict(versions) == expected_versions, "wrong NUT version header")
    return {"config_macros": {name: macros[name] for name in expected}, "version_macros": expected_versions,
            "archives": {name: ar_inventory(raw[name], members) for name, members in ARCHIVES.items()}}


def reader_placeholders(build: Path) -> list[str]:
    vendor_placeholders = {f"{VENDOR_015}/.deps/apcmicrolink_hidapi_{name}-hid.Po"
                           for name in ("continuous", "observe")}
    result = []
    for path in sorted(build.rglob("apcmicrolink*")):
        rel = path.relative_to(build).as_posix()
        row = path.lstat()
        require((rel in vendor_placeholders or re.fullmatch(r"drivers/\.deps/apcmicrolink[-A-Za-z0-9_.]*\.(?:Po|Plo)", rel))
                and stat.S_ISREG(row.st_mode) and row.st_size == 0 and row.st_nlink == 1 and row.st_uid == os.getuid()
                and path.resolve(strict=True) == path, "unexpected bootstrap reader output: " + rel)
        result.append(rel)
    return result


def archive_link_members() -> list[str]:
    return [f"{archive}({name})" for archive, names in ARCHIVES.items() for name in names if archive != "common/.libs/libparseconf.a"]


def link_objects(content: str, work: Build, sdk: Path) -> list[str]:
    require("# Arch: arm64\n" in content and content.count("# Object files:\n") == 1, "link map framing")
    listing = content.split("# Object files:\n", 1)[1].split("\n#", 1)[0]
    rows = []
    for line in listing.splitlines():
        row = re.fullmatch(r"\[\s*(\d+)\]\s+(.+)", line)
        require(row is not None and int(row[1]) == len(rows), "link map row order")
        item = row[2]
        if item == "linker synthesized":
            rows.append(item)
            continue
        obj = Path(item)
        if obj.parent == work.root / "tmp":
            unit = re.fullmatch(r"(.+)-[0-9a-f]+\.o", obj.name)
            require(unit is not None, "unadmitted translation unit object")
            rows.append("TU:" + unit[1])
        elif obj.is_relative_to(work.build):
            rows.append("archive:" + str(obj.relative_to(work.build)))
        elif obj.is_relative_to(sdk) and obj.resolve(strict=True).is_relative_to(sdk.resolve(strict=True)):
            rows.append("SDK:" + str(obj.relative_to(sdk)))
        else:
            raise ValueError("unadmitted linker input: " + item)
    require(rows == (["linker synthesized"] + ["TU:" + Path(name).stem for name in UNITS] +
                     ["archive:" + name for name in archive_link_members()] + ["SDK:" + name for name in SDK_INPUTS]),
            "linked object, archive member or SDK closure mismatch")
    return rows


def link_dependencies(content: str, work: Build, sdk: Path, pins: dict[str, str],
                      clang_resources: Path) -> tuple[dict, dict]:
    lines = content.replace("\\\n", " ").splitlines()
    require(len(lines) == len(UNITS), "translation-unit dependency count")
    ring = work.source / VENDOR_016 / "src/core/hidapi_input_ring.h"
    ring_spelling = str(work.source / VENDOR_016 / "mac") + "/../src/core/hidapi_input_ring.h"
    rows, tool_headers = {}, {}
    for unit, line in zip(UNITS, lines, strict=True):
        target, deps = line.split(":", 1)
        require(target == "native_checkpoint", "unexpected dependency target")
        local = set()
        for name in deps.split():
            path = Path(name)
            resolved = path.resolve(strict=True)
            if resolved.is_relative_to(work.root):
                rel = resolved.relative_to(work.root).as_posix()
                require(rel in pins and (name == str(resolved) or
                        (unit == HID_TU and name == ring_spelling and resolved == ring)),
                        "unadmitted local link dependency: " + rel)
                local.add(rel)
            else:
                require(path.is_absolute() and (resolved.is_relative_to(sdk.resolve(strict=True)) or
                        resolved.is_relative_to(clang_resources)), "unadmitted external link header: " + name)
                if name not in tool_headers:
                    tool_headers[name] = identity(path)
        require("source/" + unit in local, "wrong translation-unit origin")
        rows[unit] = sorted(local)
    new_headers = {"source/" + VENDOR_016 + "/" + name for name in ("hidapi/hidapi.h", "mac/hidapi_darwin.h")}
    require(new_headers <= set(rows[NATIVE_ADAPTER]) and new_headers <= set(rows[HID_TU]) and
            [unit for unit, names in rows.items() if ring.relative_to(work.root).as_posix() in names] == [HID_TU] and
            any("build/include/config.h" in names for names in rows.values()), "wrong generated or vendor header selection")
    return rows, tool_headers


def audit_product(work: Build, product: Path) -> dict:
    require(stat.S_IMODE(product.lstat().st_mode) == 0o600, "linked reader must be non-executable")
    raw = read_file(product)
    require(len(raw) >= 32 and raw[:8] == bytes.fromhex("cffaedfe0c000001"), "reader must be thin arm64 Mach-O")
    initial = digest(raw)
    otool = work.tools["otool"]["path"]
    output = work.run("audit-libraries", work.root, otool, "-L", product)
    libs = tuple(line.strip().split(" ", 1)[0] for line in output.splitlines()[1:])
    require(libs == LIBRARIES, "unexpected Mach-O dependencies")
    arch = work.run("audit-architecture", work.root, otool, "-hv", product)
    require(re.search(r"^MH_MAGIC_64\s+ARM64\s+ALL\s+\S+\s+EXECUTE\s+", arch, re.M) is not None,
            "reader must be thin arm64 Mach-O")
    load = work.run("audit-load-commands", work.root, otool, "-l", product)
    versions = re.findall(r"^\s*cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform (\d+)\s+minos (\S+)\s+sdk (\S+)", load, re.M)
    require(versions == [("1", "27.0", "27.2")] and not re.search(r"LC_(?:CODE_SIGNATURE|RPATH|VERSION_MIN_)", load),
            "wrong Mach-O deployment, signature or runpath")
    nm = work.run("audit-symbols", work.root, work.tools["nm"]["path"], product)
    required = {"_main", "_upsdrv_cleanup", "_hid_write", "_hid_read_interrupt", "_IOHIDDeviceSetReport",
                "_apcmicrolink_operational_stream_v2_run", "_mlink_hidapi_native_create", "_native_write_report"}
    require(required <= {line.split()[-1] for line in nm.splitlines() if line.split()} and
            not re.search(r"replay|fake|fixture|libusb_", nm, re.I), "unexpected native reader symbols")
    strings = work.run("audit-strings", work.root, work.tools["strings"]["path"], "-a", product)
    require("/Users/" not in strings and str(work.root) not in strings, "private path embedded in reader")
    require(digest(read_file(product)) == initial and stat.S_IMODE(product.stat().st_mode) == 0o600,
            "reader changed during audit")
    return {"name": PRODUCT, "sha256": initial, "bytes": product.stat().st_size, "mode": "0600",
            "architecture": "arm64", "signature": "ABSENT", "dependencies": libs,
            "minimum_macos": "27.0", "sdk_version": "27.2"}


def stage_vendor(root: Path, files: dict[str, bytes]) -> dict[str, str]:
    root.mkdir()
    for name, raw in files.items():
        write_file(root / path_name(name), raw)
    pins = {name: digest(raw) for name, raw in files.items()}
    checked_tree(root, pins)
    return pins


def apply_first_io_source_overlay(source: Path, selected, vendor_map: dict[str, str]) -> dict[str, str]:
    """Apply authenticated E119 bytes over the exact post-0.16 source map."""
    checked_tree(source, selected.native_base_map)
    require(vendor_map == selected.vendor_map, "first-IO vendor map mismatch")
    require(set(selected.native_overlay) == {
        "drivers/apcmicrolink-hidapi-session.h", "drivers/apcmicrolink-hidapi-shared.c",
        "drivers/apcmicrolink.c"}, "first-IO overlay key set mismatch")
    for name, raw in selected.native_overlay.items():
        target = source / path_name(name)
        target.write_bytes(raw)
        target.chmod(0o600)
    checked_tree(source, selected.native_map)
    return dict(selected.native_map)


def bootstrap(work: Build, backend: Path, nut: Path, locks: dict, vendors: dict) -> dict[str, str]:
    source, build, root = work.source, work.build, work.root
    recipe = backend / "native-build"
    cal = locks["cal"]
    pre = cal["source_checkpoint"]["pre_cal_sha256"]
    post = cal["post_cal_sha256"]
    require(len(pre) == 190 and pre.keys() == post.keys() and
            {name for name in pre if pre[name] != post[name]} ==
            {"drivers/apcmicrolink-maps.c", "drivers/apcmicrolink.c"}, "wrong source checkpoint delta")
    reconstructed = root / "reconstructed"
    python = work.tools["python"]["path"]
    prepare = backend / "prepare_production_source.py"
    work.receipt["inputs"]["source_preparer_sha256"] = digest(read_file(prepare))
    work.run("prepare-sources", root, python, "-I", "-S", "-B", prepare,
             "--backend-dir", backend, "--nut-archive", nut,
             "--deadline-helper", backend / "process_deadline.py", "--output-dir", reconstructed)
    raw = read_file(reconstructed / "SOURCE_RECEIPT.json")
    prepared = json.loads(raw)
    require(prepared["state"] == "SOURCE_ONLY_PASS" and prepared["source_sha256"] == pre, "wrong public source preparation receipt")
    write_file(work.out / "SOURCE_RECEIPT.json", raw)
    work.receipt["nut"] = {"revision": cal["upstream"]["revision"], "archive_sha256": NUT_PIN,
                           "notices": unpack_nut(nut, source)}
    for name, pin in pre.items():
        relative = path_name(name)
        raw = read_file(reconstructed / "source" / relative)
        require(digest(raw) == pin, "reconstructed source changed: " + name)
        target = source / relative
        require(target.resolve() == target and (not target.exists() or target.is_file()),
                "unsafe NUT overlay destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o600)
    checked_tree(source, pre)
    work.patch("apply-cal", recipe / "nut-cal-status-freshness.patch", cal["cal_patch"]["sha256"])
    checked_tree(source, post)
    work.receipt["source_checkpoints"] = {"pre_cal": pre, "post_cal": post}
    work.receipt["legacy_hidapi"] = stage_vendor(source / VENDOR_015, vendors[VENDOR_015])
    work.receipt["configure_probe"] = {"source": probe_audit(source / "configure.ac", False)}
    work.env["PYTHON"] = python + " -I -S -B"
    try:
        work.run("autogen", source, "/bin/sh", "./autogen.sh")
    finally:
        del work.env["PYTHON"]
    checked_tree(source, post)
    checked_tree(source / VENDOR_015, work.receipt["legacy_hidapi"])
    work.receipt["configure_probe"]["generated"] = probe_audit(source / "configure", True)
    work.env["CFLAGS"] = "-O0 -g0 -ffile-prefix-map=" + str(root) + "=/usr/src/ups-monitor"
    cc = work.tools["clang"]["path"]
    cxx = work.tools["clang++"]["path"]
    config = ("--prefix=" + str(PREFIX), "--with-all=no", "--with-drivers=apcmicrolink", "--with-doc=no",
              "--with-ssl=no", "--disable-inplace-runtime", "--disable-shared-private-libs", "--with-usb=libusb-1.0",
              "--with-apcmicrolink-hidapi=yes", "CC=" + cc, "CXX=" + cxx)
    work.run("configure", build, source / "configure", *config)
    configured_tools = work.configured_archive_tools()
    make = work.tools["make"]["path"]
    work.run("make-headers", build, make, "-C", "include", "nut_version.h")
    work.run("make-common", build, make, "-C", "common", "V=1", "libparseconf.la", "libcommon.la", "libcommonversion.la")
    work.run("make-dummy", build, make, "-C", "drivers", "V=1", "libdummy_serial.la", "libdummy_upsdrvquery.la")
    checked_tree(source, post)
    checked_tree(source / VENDOR_015, work.receipt["legacy_hidapi"])
    work.receipt["bootstrap_automake_placeholders"] = reader_placeholders(build)
    work.receipt["bootstrap_archive_tools"] = work.archive_trace(configured_tools)
    raw = read_generated(build)
    work.receipt["bootstrap_generated"] = check_generated(raw, source, build, work.tools["libusb.dylib"]["resolved"], config)
    # The only producer of these pins is the successful bootstrap in this run.
    pins = {name: digest(blob) for name, blob in raw.items()}
    work.receipt["generated_input_sha256"] = pins
    return pins


def compile_and_audit(work: Build, backend: Path, sdk: Path, locks: dict,
                      vendors: dict, generated: dict[str, str], first_io_stage=None) -> None:
    source, build, root = work.source, work.build, work.root
    recipe = backend / "native-build"
    cancel, profile = locks["cancel"]["post_write_cancel_sha256"], locks["profile"]["post_hidapi_016_sha256"]
    work.patch("apply-write-cancel", recipe / "nut-write-cancel-boundary-v2.patch", locks["cancel"]["patch_sha256"])
    checked_tree(source, cancel)
    work.patch("apply-hidapi-version-gate", recipe / "hidapi-0.16/version-gate.patch", locks["profile"]["gate_patch_sha256"])
    checked_tree(source, profile)
    new_vendor = stage_vendor(source / VENDOR_016, vendors[VENDOR_016])
    checked_tree(source / VENDOR_015, work.receipt["legacy_hidapi"])
    shutil.rmtree(source / VENDOR_015)
    if first_io_stage is not None:
        post_first_io = apply_first_io_source_overlay(source, first_io_stage, new_vendor)
        work.receipt["source_checkpoints"]["post_first_io"] = post_first_io
        work.receipt["first_io_source_stage"] = first_io_stage.identity
    work.receipt["source_checkpoints"].update(post_write_cancel=cancel, post_hidapi_016=profile)
    for name, pin in work.receipt["nut"]["notices"].items():
        raw = read_file(source / name)
        require(digest(raw) == pin, "NUT notice changed")
        write_file(work.out / "upstream-notices/nut" / name, raw)
    for name in ("LICENSE.txt", "LICENSE-bsd.txt", "LICENSE-gpl3.txt", "LICENSE-orig.txt"):
        raw = read_file(source / VENDOR_016 / name)
        require(digest(raw) == new_vendor[name], "HIDAPI notice changed")
        write_file(work.out / "upstream-notices/hidapi" / name, raw)
    selected_native_map = work.receipt["source_checkpoints"].get("post_first_io", profile)
    local_pins = {"source/" + name: pin for name, pin in selected_native_map.items()}
    local_pins.update({"source/" + VENDOR_016 + "/" + name: pin for name, pin in new_vendor.items()})
    local_pins.update({"build/" + name: pin for name, pin in generated.items()})
    flags = ["--no-default-config", "-arch", "arm64", "-isysroot", str(sdk), "-mmacosx-version-min=27.0",
             "-std=gnu99", "-O0", "-g0", "-ffile-prefix-map=" + str(root) + "=/usr/src/ups-monitor",
             "-Wall", "-Wextra", "-Wno-unused-parameter", "-DMLINK_HIDAPI_NATIVE_CANDIDATE=1",
             "-DMLINK_HIDAPI_CONTINUOUS_CANDIDATE=1", "-DMLINK_CONTINUOUS_PACING_V2=1", "-DMLINK_HIDAPI_OPERATIONAL_V2=1"]
    for parent in (build / "include", source / "include", source / "drivers",
                   source / VENDOR_016 / "mac", source / VENDOR_016 / "hidapi"):
        flags.extend(("-I", str(parent)))
    clang = work.tools["clang"]["path"]
    resource = Path(work.run("clang-resource-dir", root, clang, "--no-default-config", "-print-resource-dir").strip())
    resource_root = Path(clang).parent.parent / "lib/clang"
    require(resource.is_absolute() and resource.resolve(strict=True).is_relative_to(resource_root.resolve(strict=True)),
            "unadmitted compiler resource directory")
    units = [source / name for name in UNITS]
    deps = work.run("link-dependencies", root, clang, *flags, "-M", "-MT", "native_checkpoint", *units)
    headers, tool_headers = link_dependencies(deps, work, sdk, local_pins, resource.resolve(strict=True))
    work.tools.update({"header:" + name: row for name, row in tool_headers.items()})
    work.receipt["link_headers"] = headers
    verify_generated(build, generated)
    checked_tree(root, local_pins)
    link_map = root / "native.map"
    product = root / PRODUCT
    try:
        work.run("compile-link", root, clang, *flags, *units, *(build / name for name in ARCHIVES),
                 "-framework", "IOKit", "-framework", "CoreFoundation", "-lm",
                 "-Wl,-no_adhoc_codesign", "-Wl,-map," + str(link_map), "-o", product)
    finally:
        if product.is_file() and not product.is_symlink():
            product.chmod(0o600)
    raw_map = read_file(link_map)
    write_file(work.out / "audit/native.map", raw_map)
    work.receipt["link_map_sha256"] = digest(raw_map)
    work.receipt["link_objects"] = link_objects(raw_map.decode(), work, sdk)
    product_record = audit_product(work, product)
    verify_generated(build, generated)
    checked_tree(root, local_pins)
    work.verify_tools()
    require(not work.cancel.is_set(), "campaign cancelled after audit")
    destination = work.out / PRODUCT
    write_file(destination, read_file(product))
    require(stat.S_IMODE(destination.stat().st_mode) == 0o600 and sha_file(destination) == product_record["sha256"],
            "published product changed")
    work.receipt["product"] = product_record


def retain_diagnostics(work: Build) -> None:
    retained = {}
    rejected = {}
    candidates = [(f"generated/{name}", work.build / name) for name in GENERATED]
    candidates.extend((("audit/config.log", work.build / "config.log"), ("audit/native.map", work.root / "native.map")))
    if not (work.out / PRODUCT).exists():
        candidates.append(("audit/partial-product", work.root / PRODUCT))
    for name, src in candidates:
        dest = work.out / name
        if dest.exists():
            continue
        try:
            raw = read_file(src)
            write_file(dest, raw)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            rejected[name] = str(error)
            continue
        if name.startswith("generated/"):
            retained[name.removeprefix("generated/")] = digest(raw)
        if name == "audit/partial-product":
            work.receipt["unaccepted_product"] = {"path": name, "sha256": digest(raw)}
    work.receipt["retained_generated_sha256"] = retained
    if rejected:
        work.receipt["unretained_artifacts"] = rejected
    require(not rejected, "one or more diagnostic outputs could not be retained")
    if "generated_input_sha256" in work.receipt:
        require(retained == work.receipt["generated_input_sha256"], "preserved generated inputs changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--kit-sha256", required=True)
    parser.add_argument("--autotools-bin", type=Path, required=True)
    parser.add_argument("--developer-dir", type=Path, default=Path("/Applications/Xcode.app/Contents/Developer"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--first-io-source-stage", type=Path,
                        help="authenticate and overlay the optional E119 source-only stage")
    args = parser.parse_args()
    try:
        require(sys.platform == "darwin" and os.uname().machine == "arm64" and os.uname().release.split(".")[0] == "27"
                and sys.version_info[:3] == (3, 15, 2) and sys.flags.isolated and sys.flags.no_site
                and sys.dont_write_bytecode and not sys.flags.optimize, "requires macOS 27 arm64 with Python 3.15.2 -I -S -B")
        require(re.fullmatch(r"[0-9a-f]{64}", args.kit_sha256) is not None, "invalid developer kit SHA-256")
        require(args.kit.is_absolute() and args.kit.suffix == ".tar", "provide absolute developer kit tar path")
        autotools = directory(args.autotools_bin)
        developer = directory(args.developer_dir)
        # NUT/Autotools also consume these paths in GNU make and shell variables.
        require(all(re.fullmatch(r"/[A-Za-z0-9_./+@-]+", str(path))
                    for path in (autotools, developer, Path(sys.executable))), "tool paths contain shell-sensitive characters")
        out = args.output_dir
        directory(out.parent)
        require(out.is_absolute() and out.resolve() == out and out != out.parent, "expected canonical absolute output path")
        if args.first_io_source_stage is not None:
            stage_path = args.first_io_source_stage
            require(stage_path.is_absolute() and ".." not in stage_path.parts, "invalid first-IO stage path")
            stage_resolved = stage_path.resolve(strict=True)
            out_resolved = out.parent.resolve(strict=True) / out.name
            require(out_resolved != stage_resolved and out_resolved not in stage_resolved.parents
                    and stage_resolved not in out_resolved.parents, "output overlaps first-IO stage")
        os.umask(0o077)
        out.mkdir(mode=0o700)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    end = time.monotonic() + BUILD_SECONDS
    root = Path(tempfile.mkdtemp(prefix="ups-fresh-hidapi-", dir="/private/tmp"))
    receipt = {"schema": 1, "state": "HOLD", "reader_execution": "NOT_RUN", "phases": [],
               "runner_sha256": sha_file(Path(__file__).resolve()),
               "host": {"os": "macOS", "kernel_release": os.uname().release, "architecture": "arm64"}}
    work = None
    handlers = {}
    compiled = False
    try:
        backend, nut, locks, vendors = kit_inputs(args.kit, args.kit_sha256, root, receipt)
        require(digest(read_file(backend / Path(__file__).name)) == receipt["runner_sha256"],
                "running builder differs from kit project")
        first_io_stage = None
        if args.first_io_source_stage is not None:
            validator_path = backend / "first_io_source_stage.py"
            validator = load_module(validator_path, read_file(validator_path), "_ups_first_io_source_stage")
            first_io_stage = validator.validate_source_stage(args.first_io_source_stage, backend)
            receipt["first_io_source_stage"] = first_io_stage.identity
        helper_path = backend / "process_deadline.py"
        raw = read_file(helper_path)
        require(digest(raw) == SUPERVISOR_PIN, "wrong subprocess supervisor")
        receipt["inputs"]["process_deadline_sha256"] = SUPERVISOR_PIN
        work = Build(root, out, receipt, load_module(helper_path, raw, "_ups_fresh_deadline"), end)
        for number in (signal.SIGINT, signal.SIGTERM):
            handlers[number] = signal.signal(number, lambda *_: work.cancel.set())
        work.watcher.start()
        sdk = work.set_up_tools(autotools, developer)
        generated = bootstrap(work, backend, nut, locks, vendors)
        if first_io_stage is None:
            compile_and_audit(work, backend, sdk, locks, vendors, generated)
        else:
            compile_and_audit(work, backend, sdk, locks, vendors, generated, first_io_stage)
        compiled = True
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        receipt["failure"] = str(error)
    finally:
        if work is not None:
            work.stop.set()
            work.watcher.join()
            receipt["sampled_peak_bytes"] = work.peak
            receipt["guard_errors"] = work.errors
            if work.owned_clean:
                try:
                    retain_diagnostics(work)
                except (OSError, ValueError) as error:
                    receipt["retention_failure"] = str(error)
                    compiled = False
            compiled = compiled and not work.cancel.is_set()
        if work is None or work.owned_clean:
            try:
                shutil.rmtree(root)
            except OSError as error:
                receipt["cleanup_failure"] = str(error)
                compiled = False
        else:
            receipt["unresolved_process_scratch"] = str(root)
            compiled = False
        receipt["scratch_removed"] = not root.exists()
        for number, handler in handlers.items():
            signal.signal(number, handler)
        if compiled:
            receipt["state"] = "COMPILED_STATIC_AUDIT_ONLY"
        write_json(out / "BUILD_RECEIPT.json", receipt)
    if not compiled:
        print(receipt.get("failure") or receipt.get("guard_errors") or "build held; see BUILD_RECEIPT.json", file=sys.stderr)
    return 0 if compiled else 1


if __name__ == "__main__":
    sys.exit(main())
