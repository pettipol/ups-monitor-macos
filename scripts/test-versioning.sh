#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ups-versioning.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT HUP INT TERM

copy_fixture() {
    mkdir -p "$TEST_ROOT/App" "$TEST_ROOT/Widget"
    cp "$SOURCE_ROOT/VERSION" "$SOURCE_ROOT/CHANGELOG.md" "$TEST_ROOT/"
    cp "$SOURCE_ROOT/App/Info.plist" "$TEST_ROOT/App/Info.plist"
    cp "$SOURCE_ROOT/Widget/Info.plist" "$TEST_ROOT/Widget/Info.plist"
}

expect_failure() {
    if UPS_VERSION_CHECK_ROOT="$TEST_ROOT" bash "$SCRIPT_DIR/check-version.sh" >/dev/null 2>&1; then
        printf 'Expected version checker failure for %s.\n' "$1" >&2
        exit 1
    fi
}

copy_fixture
UPS_VERSION_CHECK_ROOT="$TEST_ROOT" bash "$SCRIPT_DIR/check-version.sh"

plutil -replace UPSMonitorSemVer -string 0.1.0-preview.2 "$TEST_ROOT/App/Info.plist"
expect_failure "app version drift"

copy_fixture
plutil -replace CFBundleShortVersionString -string 0.2.0 "$TEST_ROOT/Widget/Info.plist"
expect_failure "widget bundle version drift"

copy_fixture
plutil -replace CFBundleVersion -string 2 "$TEST_ROOT/Widget/Info.plist"
expect_failure "bundle build drift"

copy_fixture
sed 's/0\.1\.0-preview\.1/0.1.0-preview.2/' "$TEST_ROOT/CHANGELOG.md" > "$TEST_ROOT/CHANGELOG.tmp"
mv "$TEST_ROOT/CHANGELOG.tmp" "$TEST_ROOT/CHANGELOG.md"
expect_failure "changelog heading drift"

copy_fixture
printf '0.1.0-preview.01\n' > "$TEST_ROOT/VERSION"
expect_failure "leading-zero prerelease"

copy_fixture
printf '1.0.0\n' > "$TEST_ROOT/VERSION"
expect_failure "release without prerelease status"

printf 'Version metadata consistency tests passed.\n'
