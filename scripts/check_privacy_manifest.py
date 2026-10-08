"""Validate the project's deliberately minimal macOS privacy manifest profile.

This checks project packaging shape only. It does not validate Apple's policy,
application egress, or whether a declaration is true for a running build.
"""

from __future__ import annotations

import argparse
import plistlib
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.parsers.expat import ExpatError


DEFAULT_SOURCE_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_KEYS = {"NSPrivacyTracking", "NSPrivacyCollectedDataTypes"}


@dataclass(frozen=True)
class ManifestCheckError(Exception):
    """A failure tied to a logical manifest location, without payload details."""

    logical_path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.logical_path}: {self.reason}"


def validate_privacy_manifest(path: Path, logical_path: str) -> None:
    """Require the exact two-key, no-tracking, no-collected-data profile."""
    try:
        with path.open("rb") as manifest_file:
            manifest = plistlib.load(manifest_file)
    except FileNotFoundError as error:
        raise ManifestCheckError(logical_path, "manifest is missing") from error
    except (OSError, plistlib.InvalidFileException, ExpatError, ValueError, TypeError) as error:
        raise ManifestCheckError(logical_path, "manifest is unreadable or malformed") from error

    if type(manifest) is not dict:
        raise ManifestCheckError(logical_path, "root value must be a dictionary")
    if set(manifest) != EXPECTED_KEYS:
        raise ManifestCheckError(logical_path, "manifest keys do not match the required profile")
    if type(manifest["NSPrivacyTracking"]) is not bool or manifest["NSPrivacyTracking"] is not False:
        raise ManifestCheckError(logical_path, "NSPrivacyTracking must be boolean false")
    if type(manifest["NSPrivacyCollectedDataTypes"]) is not list or manifest["NSPrivacyCollectedDataTypes"]:
        raise ManifestCheckError(logical_path, "NSPrivacyCollectedDataTypes must be an empty array")


def check_privacy_manifests(source_root: Path, app_bundle: Path | None = None) -> None:
    """Validate source manifests and, optionally, their packaged app copies."""
    targets = (
        (source_root / "App/PrivacyInfo.xcprivacy", "App/PrivacyInfo.xcprivacy"),
        (source_root / "Widget/PrivacyInfo.xcprivacy", "Widget/PrivacyInfo.xcprivacy"),
    )
    for path, logical_path in targets:
        validate_privacy_manifest(path, logical_path)

    if app_bundle is not None:
        packaged_targets = (
            (
                app_bundle / "Contents/Resources/PrivacyInfo.xcprivacy",
                "app/Contents/Resources/PrivacyInfo.xcprivacy",
            ),
            (
                app_bundle / "Contents/PlugIns/UPSMonitorWidget.appex/Contents/Resources/PrivacyInfo.xcprivacy",
                "app/Contents/PlugIns/UPSMonitorWidget.appex/Contents/Resources/PrivacyInfo.xcprivacy",
            ),
        )
        for path, logical_path in packaged_targets:
            validate_privacy_manifest(path, logical_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--app-bundle", type=Path)
    arguments = parser.parse_args(argv)
    try:
        check_privacy_manifests(arguments.source_root, arguments.app_bundle)
    except ManifestCheckError as error:
        print(f"Privacy manifest check failed: {error}", file=sys.stderr)
        return 1
    print("Privacy manifest profile and requested packaging copies are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
