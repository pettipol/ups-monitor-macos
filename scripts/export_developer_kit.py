#!/usr/bin/env python3
"""Create a deterministic, offline USTAR containing only locked build inputs."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
from typing import BinaryIO
from urllib.parse import urlparse

ROOT_NAME = "UPS-Monitor-Developer-Inputs"
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_SOURCE_MEMBERS = 100_000
MAX_LOCK_BYTES = 5 * 1024 * 1024
HIDAPI_PATHS = ("mac/hid.c", "hidapi/hidapi.h", "mac/hidapi_darwin.h")
HIDAPI_LICENSES = ("LICENSE.txt", "LICENSE-bsd.txt", "LICENSE-gpl3.txt", "LICENSE-orig.txt")
HIDAPI_016_PATHS = (*HIDAPI_PATHS, "src/core/hidapi_input_ring.h", *HIDAPI_LICENSES)
HIDAPI_016_COMMIT = "750c87abb03282a237297052b84522e6bb3c0616"
NUT_BASELINE_COMMIT = "73c4502191d025e35122463986a80c676e734b04"
NATIVE_PROFILES = ("hidapi-0.15", "hidapi-0.16")
NATIVE_RECIPE = "backend/nut/native-build/"
HIDAPI_016_SUPPORT = tuple(NATIVE_RECIPE + name for name in (
    "hidapi-0.16/manifest.json", "hidapi-0.16/README.md", "hidapi-0.16/version-gate.patch",
    "production_source_post_write_cancel.json", "WRITE_CANCEL_BOUNDARY.md", "nut-write-cancel-boundary-v2.patch",
    "nut-cal-status-freshness.patch",
))
WRITE_CANCEL_FILES = {"drivers/apcmicrolink-hidapi-native.c", "drivers/apcmicrolink-hidapi-shared.c",
                      "drivers/apcmicrolink-hidapi-shared-host.h"}
GENERATED_FILES = {"include/config.h", "include/nut_version.h", "drivers/.libs/libdummy_serial.a",
                   "drivers/.libs/libdummy_upsdrvquery.a", "common/.libs/libcommon.a",
                   "common/.libs/libcommonversion.a", "common/.libs/libparseconf.a"}
PROJECT_SUPPORT_FILES = (
    "Package.swift", "backend/nut/prepare_production_source.py",
    "backend/nut/stage_hidapi_candidate.py", "backend/nut/stage_bundled_python_runtime.py",
    "backend/nut/native-build/README.md", "docs/FROZEN_BUILD_RECIPE.md", "docs/SOURCE_RELEASE.md",
)


class ExportError(ValueError):
    """Raised when a supplied input does not match the reviewed locks."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExportError(message)


def regular_file(path: Path, label: str) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ExportError(f"{label}: cannot stat input") from exc
    require(stat.S_ISREG(info.st_mode), f"{label}: must be a regular non-symlink file")
    return path


def directory(path: Path, label: str) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ExportError(f"{label}: cannot stat input directory") from exc
    require(stat.S_ISDIR(info.st_mode), f"{label}: must be a real directory, not a symlink")
    return path


def checked_digest(value: object, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value), f"{label}: invalid SHA-256")
    return value


def safe_relative(value: str, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    require(path.parts and "\\" not in value and "\0" not in value and not path.is_absolute()
            and path.as_posix() == value
            and all(part not in ("", ".", "..") for part in path.parts),
            f"{label}: unsafe or non-canonical archive path")
    return path


def read_source_members(source: Path, expected_sha256: str, *, additional_required: tuple[str, ...] = (),
                        ) -> tuple[str, dict[str, tarfile.TarInfo], dict[str, bytes], bytes]:
    regular_file(source, "source archive")
    require(source.suffix == ".tar", "source must be one uncompressed .tar archive")
    checked_digest(expected_sha256, "source pin")
    source_size = source.stat().st_size
    require(source_size <= MAX_TOTAL_BYTES, "source archive exceeds 100 MiB input limit")
    source_blob = source.read_bytes()
    require(len(source_blob) == source_size and hashlib.sha256(source_blob).hexdigest() == expected_sha256,
            "source archive SHA-256 mismatch")

    members: dict[str, tarfile.TarInfo] = {}
    root_name: str | None = None
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(source_blob), mode="r:") as archive:
            rows = archive.getmembers()
            require(0 < len(rows) <= MAX_SOURCE_MEMBERS, "source archive member count outside limit")
            for member in rows:
                path = safe_relative(member.name.rstrip("/") if member.isdir() else member.name, "source member")
                name = path.as_posix()
                if root_name is None:
                    root_name = path.parts[0]
                require(path.parts[0] == root_name, "source archive must have one top-level directory")
                require(name not in members, "duplicate source archive member")
                require(member.isdir() or member.isfile(), "source archive may contain only regular files and directories")
                require(len(path.parts) >= 2 or member.isdir(),
                        "source regular files must be below the single top-level directory")
                require(member.uid == 0 and member.gid == 0, "source archive ownership metadata must be normalized")
                if member.isfile():
                    require(member.size >= 0 and member.size <= MAX_TOTAL_BYTES, "source member exceeds size limit")
                    total += member.size
                members[name] = member
    except (tarfile.TarError, OSError) as exc:
        raise ExportError("source is not a readable uncompressed tar") from exc
    require(root_name is not None, "source archive is empty")
    for name, member in members.items():
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            parent_name = PurePosixPath(*parts[:index]).as_posix()
            explicit_parent = members.get(parent_name)
            require(explicit_parent is None or explicit_parent.isdir(),
                    f"source archive has a regular file as parent: {name}")
        if len(parts) == 1:
            require(member.isdir(), "source top-level entry must be a directory")
    require(total <= MAX_TOTAL_BYTES, "source archive payload exceeds size limit")

    required = (
        "LICENSE", "THIRD_PARTY_NOTICES.md", "docs/OFFLINE_DEVELOPER_KIT.md",
        "backend/nut/bundled_python_runtime_inputs.json",
        "backend/nut/frozen_build_inputs.json",
        "backend/nut/native-build/production_source_post_cal.json",
        *("backend/nut/native-build/licenses/hidapi/" + name for name in HIDAPI_LICENSES),
        *PROJECT_SUPPORT_FILES,
        *additional_required,
    )
    prefix = root_name + "/"
    data: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(source_blob), mode="r:") as archive:
            for relative in required:
                archive_name = prefix + relative
                member = members.get(archive_name)
                require(member is not None and member.isfile(), f"source lacks required file: {relative}")
                require(member.size <= MAX_LOCK_BYTES, f"required source file too large: {relative}")
                stream = archive.extractfile(member)
                require(stream is not None, f"cannot read required source file: {relative}")
                blob = stream.read(MAX_LOCK_BYTES + 1)
                require(len(blob) == member.size and len(blob) <= MAX_LOCK_BYTES,
                        f"required source file size mismatch: {relative}")
                data[relative] = blob
    except (tarfile.TarError, OSError) as exc:
        raise ExportError("cannot read required source members") from exc
    return root_name, members, data, source_blob


def parse_json(blob: bytes, label: str, *, unique_keys: bool = False) -> dict:
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        value = dict(pairs)
        require(len(value) == len(pairs), f"duplicate JSON key in lock: {label}")
        return value

    try:
        value = json.loads(blob, object_pairs_hook=unique_object if unique_keys else None)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExportError(f"invalid JSON lock: {label}") from exc
    require(isinstance(value, dict), f"invalid JSON lock object: {label}")
    return value


class VerifyingReader:
    """Stream a file to tar while proving the bytes match its preflight pin."""

    def __init__(self, stream: BinaryIO, expected_size: int, expected_sha256: str):
        self.stream = stream
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        block = self.stream.read(size)
        self.count += len(block)
        self.digest.update(block)
        if self.count > self.expected_size:
            raise ExportError("input grew while being archived")
        return block

    def verify(self) -> None:
        require(self.count == self.expected_size and self.digest.hexdigest() == self.expected_sha256,
                "input changed while being archived")
        require(not self.stream.read(1), "input grew while being archived")


def verify_input(path: Path, expected_sha256: str, expected_size: int | None, label: str) -> tuple[int, str]:
    regular_file(path, label)
    digest = checked_digest(expected_sha256, label)
    size = path.stat().st_size
    require(size <= MAX_TOTAL_BYTES, f"{label}: exceeds per-file size limit")
    if expected_size is not None:
        require(isinstance(expected_size, int) and expected_size >= 0 and size == expected_size,
                f"{label}: size mismatch")
    require(sha256_file(path) == digest, f"{label}: SHA-256 mismatch")
    return size, digest


def regular_file_below(root: Path, relative: str, label: str) -> Path:
    parts = safe_relative(relative, label).parts
    current = root
    for part in parts[:-1]:
        current = current / part
        directory(current, f"{label} parent")
    return regular_file(current / parts[-1], label)


def file_row(path: Path, size: int, digest: str) -> tuple[Path, int, str]:
    return path, size, digest


def hidapi_016_locks(source_data: dict[str, bytes], native_lock: dict) -> dict[str, tuple[int, str]]:
    cal_manifest = source_data[NATIVE_RECIPE + "production_source_post_cal.json"]
    cancel_manifest = source_data[NATIVE_RECIPE + "production_source_post_write_cancel.json"]
    cancel = parse_json(cancel_manifest, "production_source_post_write_cancel.json", unique_keys=True)
    profile = parse_json(source_data[NATIVE_RECIPE + "hidapi-0.16/manifest.json"], "HIDAPI 0.16 manifest.json",
                         unique_keys=True)
    try:
        cal_patch = native_lock["cal_patch"]
        upstream = native_lock["upstream"]
        vendor = profile["hidapi"]
        require(cal_patch["file"] == "nut-cal-status-freshness.patch", "wrong CAL patch filename")
        require(cancel["base_manifest_sha256"] == hashlib.sha256(cal_manifest).hexdigest(),
                "write-cancel base manifest pin mismatch")
        require(profile["base_manifest_sha256"] == hashlib.sha256(cancel_manifest).hexdigest(),
                "HIDAPI 0.16 base manifest pin mismatch")
        for path, pin in ((cal_patch["file"], cal_patch["sha256"]),
                          ("nut-write-cancel-boundary-v2.patch", cancel["patch_sha256"]),
                          ("hidapi-0.16/version-gate.patch", profile["gate_patch_sha256"])):
            require(hashlib.sha256(source_data[NATIVE_RECIPE + path]).hexdigest() == pin,
                    f"patch SHA-256 mismatch: {path}")
        require(profile["nut_commit"] == upstream["revision"] == NUT_BASELINE_COMMIT and
                profile["nut_git_archive_sha256"] == upstream["archive_sha256"],
                "HIDAPI 0.16 NUT baseline mismatch")
        require(native_lock["hidapi"]["tag"] == "hidapi-0.15.0", "wrong HIDAPI base tag")
        before = native_lock["post_cal_sha256"]
        middle = cancel["post_write_cancel_sha256"]
        after = profile["post_hidapi_016_sha256"]
        generated = native_lock["build"]["generated_input_sha256"]
        require(all(isinstance(rows, dict) and len(rows) == 190 for rows in (before, middle, after)) and
                before.keys() == middle.keys() == after.keys(), "HIDAPI 0.16 project source inventories differ")
        for rows in (before, middle, after):
            for name, digest in rows.items():
                safe_relative(name, "project source pin")
                checked_digest(digest, "project source pin")
        require({name for name in before if before[name] != middle[name]} == WRITE_CANCEL_FILES,
                "wrong write-cancel source delta")
        require({name for name in middle if middle[name] != after[name]} == {"drivers/apcmicrolink-hidapi-native.c"},
                "wrong HIDAPI 0.16 source delta")
        require(isinstance(generated, dict) and set(generated) == GENERATED_FILES and
                profile["reused_generated_input_sha256"] == generated, "HIDAPI 0.16 generated inputs differ from CAL")
        for digest in generated.values():
            checked_digest(digest, "generated build input pin")
        require(vendor["tag"] == "hidapi-0.16.0" and vendor["commit"] == HIDAPI_016_COMMIT,
                "wrong HIDAPI 0.16 tag or commit")
        rows = vendor["files"]
    except (KeyError, TypeError) as exc:
        raise ExportError("source lacks required HIDAPI 0.16 lock fields") from exc

    require(isinstance(rows, list) and len(rows) == len(HIDAPI_016_PATHS), "wrong HIDAPI 0.16 vendor inventory")
    pins: dict[str, tuple[int, str]] = {}
    for row in rows:
        require(isinstance(row, dict), "invalid HIDAPI 0.16 vendor row")
        name, size = row.get("path"), row.get("bytes")
        require(isinstance(name, str) and name in HIDAPI_016_PATHS and name not in pins,
                "duplicate or unsafe HIDAPI 0.16 vendor path")
        require(type(size) is int and size > 0, f"HIDAPI 0.16 {name}: invalid size")
        pins[name] = (size, checked_digest(row.get("sha256"), f"HIDAPI 0.16 {name}"))
    return pins


def build_file_set(source: Path, source_sha256: str, nut_archive: Path, hidapi_source: Path,
                   pbs_archive: Path, wheels_dir: Path, *, native_profile: str = "hidapi-0.15",
                   hidapi_016_source: Path | None = None) -> dict[str, tuple[Path | bytes, int, str]]:
    require(native_profile in NATIVE_PROFILES, "unknown native profile")
    if native_profile == "hidapi-0.16":
        require(hidapi_016_source is not None, "--native-profile hidapi-0.16 requires --hidapi-016-source")
    else:
        require(hidapi_016_source is None, "--hidapi-016-source requires --native-profile hidapi-0.16")
    _, _, source_data, source_blob = read_source_members(
        source, source_sha256, additional_required=HIDAPI_016_SUPPORT if hidapi_016_source is not None else ())
    runtime_lock = parse_json(source_data["backend/nut/bundled_python_runtime_inputs.json"], "bundled_python_runtime_inputs.json")
    frozen_lock = parse_json(source_data["backend/nut/frozen_build_inputs.json"], "frozen_build_inputs.json")
    native_lock = parse_json(source_data["backend/nut/native-build/production_source_post_cal.json"],
                             "production_source_post_cal.json", unique_keys=hidapi_016_source is not None)

    try:
        pbs_pin = checked_digest(runtime_lock["archive"]["sha256"], "PBS archive pin")
        pbs_size = runtime_lock["archive"]["bytes"]
        pbs_name = Path(urlparse(runtime_lock["provenance"]["url"]).path).name
        nut_pin = checked_digest(native_lock["upstream"]["archive_sha256"], "NUT archive pin")
        hidapi_pins = native_lock["hidapi"]["source_sha256"]
        hidapi_license_pins = native_lock["hidapi"]["license_sha256"]
        packages = frozen_lock["packages"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ExportError("source locks lack required pinned input fields") from exc
    require(isinstance(pbs_size, int) and pbs_size >= 0, "PBS archive size pin invalid")
    require(isinstance(pbs_name, str) and pbs_name and Path(pbs_name).name == pbs_name
            and pbs_name.endswith(".tar.zst"), "PBS provenance URL has unsafe archive filename")
    require(isinstance(hidapi_pins, dict) and set(hidapi_pins) == set(HIDAPI_PATHS),
            "HIDAPI lock must pin exactly the three selected source files")
    require(isinstance(hidapi_license_pins, dict) and len(hidapi_license_pins) == 4
            and set(hidapi_license_pins) == set(HIDAPI_LICENSES),
            "HIDAPI lock must pin exactly the four included license files")
    require(isinstance(packages, list) and len(packages) == 6, "frozen build lock must name six wheels")
    directory(hidapi_source, "HIDAPI source")
    directory(wheels_dir, "wheel directory")

    files: dict[str, tuple[Path | bytes, int, str]] = {}

    def add_bytes(destination: str, blob: bytes) -> None:
        files[destination] = (blob, len(blob), hashlib.sha256(blob).hexdigest())

    for relative in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        add_bytes(relative, source_data[relative])
    add_bytes("README.md", source_data["docs/OFFLINE_DEVELOPER_KIT.md"])

    files["source/project.tar"] = (source_blob, len(source_blob), source_sha256)
    nut_size, nut_digest = verify_input(nut_archive, nut_pin, None, "NUT archive")
    files["native/nut.tar"] = file_row(nut_archive, nut_size, nut_digest)

    for relative in HIDAPI_PATHS:
        pin = checked_digest(hidapi_pins[relative], f"HIDAPI pin {relative}")
        path = regular_file_below(hidapi_source, relative, f"HIDAPI {relative}")
        size, digest = verify_input(path, pin, None, f"HIDAPI {relative}")
        files["native/hidapi/" + relative] = file_row(path, size, digest)

    for name, pin_value in sorted(hidapi_license_pins.items()):
        pin = checked_digest(pin_value, f"HIDAPI license pin {name}")
        relative = "backend/nut/native-build/licenses/hidapi/" + name
        require(hashlib.sha256(source_data[relative]).hexdigest() == pin,
                f"included HIDAPI license hash mismatch: {name}")

    if hidapi_016_source is not None:
        pins_016 = hidapi_016_locks(source_data, native_lock)
        for parent in reversed(hidapi_016_source.absolute().parents):
            directory(parent, "HIDAPI 0.16 source ancestor")
        directory(hidapi_016_source, "HIDAPI 0.16 source")
        for relative, (expected_size, pin) in pins_016.items():
            label = f"HIDAPI 0.16 {relative}"
            path = regular_file_below(hidapi_016_source, relative, label)
            size, digest = verify_input(path, pin, expected_size, label)
            files["native/hidapi-0.16/" + relative] = file_row(path, size, digest)

    pbs_size_actual, pbs_digest = verify_input(pbs_archive, pbs_pin, pbs_size, "PBS archive")
    files["python/" + pbs_name] = file_row(pbs_archive, pbs_size_actual, pbs_digest)

    expected_wheels: set[str] = set()
    for package in packages:
        try:
            name = package["filename"]
            pin = checked_digest(package["sha256"], f"wheel pin {package.get('filename')}")
            size = package["bytes"]
        except (KeyError, TypeError) as exc:
            raise ExportError("frozen build lock has an incomplete wheel entry") from exc
        require(isinstance(name, str) and name and Path(name).name == name and name.endswith(".whl"),
                "wheel lock has an unsafe filename")
        require(name not in expected_wheels and isinstance(size, int) and size >= 0,
                "wheel lock has a duplicate filename or invalid size")
        expected_wheels.add(name)
        path = regular_file(wheels_dir / name, f"wheel {name}")
        wheel_size, digest = verify_input(path, pin, size, f"wheel {name}")
        files["python/wheels/" + name] = file_row(path, wheel_size, digest)
    actual_wheels = {entry.name for entry in wheels_dir.iterdir()}
    require(actual_wheels == expected_wheels, "wheel directory must contain exactly the six locked wheels")

    total = sum(size for _, size, _ in files.values())
    require(total <= MAX_TOTAL_BYTES, "developer kit exceeds 100 MiB total payload limit")
    return files


def tar_info(name: str, *, is_directory: bool = False, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    info.mode = 0o755 if is_directory else 0o644
    info.type = tarfile.DIRTYPE if is_directory else tarfile.REGTYPE
    info.size = 0 if is_directory else size
    try:
        info.tobuf(format=tarfile.USTAR_FORMAT)
    except (ValueError, UnicodeError) as exc:
        raise ExportError(f"path cannot be represented by USTAR: {name}") from exc
    return info


def publish_tar(output: Path, files: dict[str, tuple[Path | bytes, int, str]]) -> str:
    require(output.suffix == ".tar", "output must use the .tar suffix")
    parent = directory(output.parent, "output parent")
    require(not output.exists() and not output.is_symlink(), "output already exists")
    names = set(files)
    sums = "".join(f"{digest}  {name}\n" for name, (_, _, digest) in sorted(files.items()))
    sums_bytes = sums.encode("ascii")
    require(sum(size for _, size, _ in files.values()) + len(sums_bytes) <= MAX_TOTAL_BYTES,
            "developer kit including checksum manifest exceeds 100 MiB limit")
    files["SHA256SUMS"] = (sums_bytes, len(sums_bytes), hashlib.sha256(sums_bytes).hexdigest())
    all_files = {ROOT_NAME + "/" + name: value for name, value in files.items()}
    directory_names = {ROOT_NAME}
    for name in all_files:
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            directory_names.add(PurePosixPath(*parts[:index]).as_posix())
    temporary_path: Path | None = None
    published_identity: tuple[int, int] | None = None
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as raw:
            fd = -1
            with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(directory_names, key=lambda item: (item.count("/"), item)):
                    archive.addfile(tar_info(name, is_directory=True))
                for name, (source, size, digest) in sorted(all_files.items()):
                    if isinstance(source, bytes):
                        stream: BinaryIO = io.BytesIO(source)
                    else:
                        stream = source.open("rb")
                    verifier = VerifyingReader(stream, size, digest)
                    try:
                        archive.addfile(tar_info(name, size=size), verifier)
                        verifier.verify()
                    finally:
                        stream.close()
            raw.flush()
            os.fsync(raw.fileno())
        result = sha256_file(temporary_path)
        # link() publishes atomically without replacing a path created in a race.
        os.link(temporary_path, output, follow_symlinks=False)
        output_stat = output.lstat()
        published_identity = (output_stat.st_dev, output_stat.st_ino)
        os.unlink(temporary_path)
        temporary_path = None
        parent_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        published_identity = None
        return result
    finally:
        if published_identity is not None:
            try:
                current = output.lstat()
                if (current.st_dev, current.st_ino) == published_identity:
                    output.unlink()
            except FileNotFoundError:
                pass
        if fd >= 0:
            os.close(fd)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def export_kit(args: argparse.Namespace) -> str:
    files = build_file_set(args.source, args.source_sha256, args.nut_archive,
                           args.hidapi_source, args.pbs_archive, args.wheels,
                           native_profile=getattr(args, "native_profile", "hidapi-0.15"),
                           hidapi_016_source=getattr(args, "hidapi_016_source", None))
    return publish_tar(args.output, files)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source", type=Path, required=True, help="reviewed single-root uncompressed project .tar")
    result.add_argument("--source-sha256", required=True, help="trusted SHA-256 pin for --source")
    result.add_argument("--nut-archive", type=Path, required=True)
    result.add_argument("--hidapi-source", type=Path, required=True, help="HIDAPI source tree with the three locked paths")
    result.add_argument("--native-profile", choices=NATIVE_PROFILES, default="hidapi-0.15",
                        help="native source profile (default: hidapi-0.15)")
    result.add_argument("--hidapi-016-source", type=Path, help="HIDAPI 0.16 upstream tree for the hidapi-0.16 profile")
    result.add_argument("--pbs-archive", type=Path, required=True)
    result.add_argument("--wheels", type=Path, required=True, help="directory containing exactly the six locked wheels")
    result.add_argument("--output", type=Path, required=True, help="new output .tar path")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        digest = export_kit(args)
    except (ExportError, OSError) as exc:
        parser().error(str(exc))
    print(f"WROTE {args.output} SHA256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
