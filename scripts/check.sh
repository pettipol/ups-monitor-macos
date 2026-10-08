#!/bin/bash
set -euo pipefail

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

[ "$#" -eq 0 ] || fail "This script accepts no arguments. Configure only the documented environment variables."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

require_command uname
SYSTEM_NAME="$(uname -s)"
printf 'Host: %s\n' "$SYSTEM_NAME"
[ "$SYSTEM_NAME" = "Darwin" ] || fail "This validation entry point requires macOS (Darwin)."

require_command xcodebuild
require_command sed
XCODE_OUTPUT="$(xcodebuild -version 2>&1)" || fail "Could not query Xcode version."
XCODE_NAME="$(printf '%s\n' "$XCODE_OUTPUT" | sed -n '1p')"
XCODE_BUILD="$(printf '%s\n' "$XCODE_OUTPUT" | sed -n '2p')"
printf 'Xcode: %s (%s)\n' "$XCODE_NAME" "$XCODE_BUILD"
[ "$XCODE_NAME" = "Xcode 27.0" ] || fail "Expected Xcode 27.0."
[ "$XCODE_BUILD" = "Build version 27A266a" ] || fail "Expected Xcode build 27A266a."

require_command swift
SWIFT_OUTPUT="$(swift --version 2>&1)" || fail "Could not query Swift version."
SWIFT_LINE="$(printf '%s\n' "$SWIFT_OUTPUT" | sed -n '1p')"
printf 'Swift: %s\n' "$SWIFT_LINE"
case "$SWIFT_LINE" in
    "Apple Swift version "*) ;;
    "swift-driver version: "*)
        case "$SWIFT_LINE" in
            *" Apple Swift version "*) ;;
            *) fail "Expected Apple Swift 6.4." ;;
        esac
        ;;
    *) fail "Expected Apple Swift 6.4." ;;
esac
SWIFT_VERSION_TOKEN="$(printf '%s\n' "$SWIFT_LINE" | sed -n 's/.*Apple Swift version \([^[:space:]]*\).*/\1/p')"
[ "$SWIFT_VERSION_TOKEN" = "6.4" ] || fail "Expected Apple Swift 6.4."

PYTHON_BIN="${PYTHON_BIN:-python3}"
require_command "$PYTHON_BIN"
PYTHON_OUTPUT="$("$PYTHON_BIN" --version 2>&1)" || fail "Could not query Python version."
printf 'Python: %s\n' "$PYTHON_OUTPUT"
[ "$PYTHON_OUTPUT" = "Python 3.14.8" ] || fail "Expected Python 3.14.8 (set PYTHON_BIN to its executable if needed)."

require_command plutil
require_command codesign

optional_count=0
if [ "${UPS_TEST_UPSC+x}" = "x" ]; then optional_count=$((optional_count + 1)); fi
if [ "${UPS_TEST_UPSC_SHA256+x}" = "x" ]; then optional_count=$((optional_count + 1)); fi
if [ "${UPS_TEST_PYTHON+x}" = "x" ]; then optional_count=$((optional_count + 1)); fi
if [ "$optional_count" -ne 0 ] && [ "$optional_count" -ne 3 ]; then
    fail "Set UPS_TEST_UPSC, UPS_TEST_UPSC_SHA256 and UPS_TEST_PYTHON together, or unset all three."
fi

if [ "$optional_count" -eq 3 ]; then
    case "$UPS_TEST_UPSC" in /*) ;; *) fail "UPS_TEST_UPSC must be an absolute path." ;; esac
    [ -f "$UPS_TEST_UPSC" ] && [ -x "$UPS_TEST_UPSC" ] && [ ! -L "$UPS_TEST_UPSC" ] \
        || fail "UPS_TEST_UPSC must be an executable regular file, not a symlink."
    [[ "$UPS_TEST_UPSC_SHA256" =~ ^[[:xdigit:]]{64}$ ]] \
        || fail "UPS_TEST_UPSC_SHA256 must contain exactly 64 hexadecimal characters."
    require_command shasum
    require_command tr
    HASH_OUTPUT="$(shasum -a 256 "$UPS_TEST_UPSC" 2>/dev/null)" \
        || fail "Could not hash UPS_TEST_UPSC."
    ACTUAL_SHA256="$(printf '%s\n' "$HASH_OUTPUT" | sed -n '1s/^\([[:xdigit:]]\{64\}\)[[:space:]].*/\1/p' | tr '[:upper:]' '[:lower:]')"
    EXPECTED_SHA256="$(printf '%s' "$UPS_TEST_UPSC_SHA256" | tr '[:upper:]' '[:lower:]')"
    [ -n "$ACTUAL_SHA256" ] && [ "$ACTUAL_SHA256" = "$EXPECTED_SHA256" ] \
        || fail "UPS_TEST_UPSC SHA-256 does not match the supplied executable."
    case "$UPS_TEST_PYTHON" in /*) ;; *) fail "UPS_TEST_PYTHON must be an absolute path." ;; esac
    [ -f "$UPS_TEST_PYTHON" ] && [ -x "$UPS_TEST_PYTHON" ] \
        || fail "UPS_TEST_PYTHON must be an executable regular file."
    printf 'Optional synthetic NUT client interop: enabled\n'
else
    printf 'Optional synthetic NUT client interop: skipped (UPS_TEST_UPSC, UPS_TEST_UPSC_SHA256 and UPS_TEST_PYTHON are unset)\n'
fi

printf '\n== Python synthetic process tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_process_deadline*.py' -v

printf '\n== Offline replay source-fence tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_hid_fallback.py' -v

printf '\n== Swift package tests ==\n'
swift test

printf '\n== Swift release build ==\n'
swift build -c release

printf '\n== Plist and entitlement syntax ==\n'
plutil -lint \
    UPSMonitor.xcodeproj/project.pbxproj \
    App/Info.plist App/Shared.entitlements \
    Widget/Info.plist Widget/Local.entitlements Widget/Shared.entitlements
bash "$SCRIPT_DIR/check-version.sh"
printf '\n== Version metadata regression tests ==\n'
bash "$SCRIPT_DIR/test-versioning.sh"

printf '\n== Ad-hoc Xcode Release build ==\n'
DERIVED_DATA="$ROOT/.build/validation-app"
xcodebuild \
    -project UPSMonitor.xcodeproj \
    -scheme UPSMonitor \
    -configuration Release \
    -destination 'generic/platform=macOS' \
    -derivedDataPath "$DERIVED_DATA" \
    build \
    CODE_SIGN_IDENTITY=- \
    CODE_SIGN_STYLE=Manual \
    CODE_SIGNING_REQUIRED=YES \
    DEVELOPMENT_TEAM= \
    UPS_APP_GROUP_ID=

APP_BUNDLE="$DERIVED_DATA/Build/Products/Release/UPS Monitor.app"
[ -d "$APP_BUNDLE" ] || fail "Xcode Release app bundle was not produced."
printf '\n== Ad-hoc signature verification ==\n'
codesign --verify --deep --strict "$APP_BUNDLE"
printf 'Ad-hoc app signature verified.\n'

printf '\nValidation completed. No app, widget, native probe or UPS driver was launched by this script.\n'
