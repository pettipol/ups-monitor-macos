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
[ "$XCODE_NAME" = "Xcode 27.2" ] || fail "Expected Xcode 27.2."
[ "$XCODE_BUILD" = "Build version 27B52" ] || fail "Expected Xcode build 27B52."

require_command swift
SWIFT_OUTPUT="$(swift --version 2>&1)" || fail "Could not query Swift version."
SWIFT_LINE="$(printf '%s\n' "$SWIFT_OUTPUT" | sed -n '1p')"
printf 'Swift: %s\n' "$SWIFT_LINE"
case "$SWIFT_LINE" in
    "Apple Swift version "*) ;;
    "swift-driver version: "*)
        case "$SWIFT_LINE" in
            *" Apple Swift version "*) ;;
            *) fail "Expected Apple Swift 6.4.2." ;;
        esac
        ;;
    *) fail "Expected Apple Swift 6.4.2." ;;
esac
SWIFT_VERSION_TOKEN="$(printf '%s\n' "$SWIFT_LINE" | sed -n 's/.*Apple Swift version \([^[:space:]]*\).*/\1/p')"
[ "$SWIFT_VERSION_TOKEN" = "6.4.2" ] || fail "Expected Apple Swift 6.4.2."

PYTHON_BIN="${PYTHON_BIN:-python3}"
require_command "$PYTHON_BIN"
PYTHON_OUTPUT="$("$PYTHON_BIN" --version 2>&1)" || fail "Could not query Python version."
printf 'Python: %s\n' "$PYTHON_OUTPUT"
[ "$PYTHON_OUTPUT" = "Python 3.15.2" ] || fail "Expected Python 3.15.2 (set PYTHON_BIN to its executable if needed)."

require_command plutil
require_command codesign
require_command mktemp

# Keep SwiftPM, compiler, Xcode, and temporary user state inside one owned
# directory. Do not remove it automatically: callers can inspect or clean it
# after confirming every child process has exited.
VALIDATION_TMP="$(mktemp -d "${TMPDIR:-/tmp}/ups-validation.XXXXXX")"
mkdir -p \
    "$VALIDATION_TMP/tmp" \
    "$VALIDATION_TMP/cache" \
    "$VALIDATION_TMP/config" \
    "$VALIDATION_TMP/security" \
    "$VALIDATION_TMP/swiftpm-scratch" \
    "$VALIDATION_TMP/module-cache/clang" \
    "$VALIDATION_TMP/module-cache/swift" \
    "$VALIDATION_TMP/module-cache/swiftpm"
export TMPDIR="$VALIDATION_TMP/tmp"
export PYTHONDONTWRITEBYTECODE=1
export CLANG_MODULE_CACHE_PATH="$VALIDATION_TMP/module-cache/clang"
export SWIFT_MODULE_CACHE_PATH="$VALIDATION_TMP/module-cache/swift"
export SWIFTPM_MODULECACHE_OVERRIDE="$VALIDATION_TMP/module-cache/swiftpm"
SWIFT_SCRATCH_PATH="$VALIDATION_TMP/swiftpm-scratch"
printf 'Validation scratch directory (caller cleanup after child exit): %s\n' "$VALIDATION_TMP"

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
printf '\n== Operational streaming policy tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_process_streaming_policy.py' -v
printf '\n== Operational streaming real-child lifecycle tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_process_streaming_lifecycle.py' -v
printf '\n== Cleanup diagnostic parser and synthetic streaming tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_cleanup*.py' -v
printf '\n== Closed operator CLI synthetic tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_operator_session.py' -v
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_observation_receipt.py' -v

printf '\n== Offline replay source-fence tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_hid_fallback.py' -v
printf '\n== Merged-pin HID candidate runner contract tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_hid_validation.py' -v
printf '\n== Offline lifecycle and write replay contract tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_guarded_dump_signals.py' -v
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_usb_write_completion.py' -v
printf '\n== Offline USB async-state runner contracts ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_usb_async_state.py' -v
printf '\n== Offline USB observation-budget runner contracts ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_usb_guard_deadline.py' -v
printf '\n== Offline USB lifecycle observation runner contracts ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_usb_lifecycle_observation.py' -v
printf '\n== Synthetic continuous protocol tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_continuous_protocol.py' -v
printf '\n== Synthetic operational protocol v2 tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_operational_protocol.py' -v
printf '\n== E31 public operational replay contract tests (synthetic only) ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_replay_operational_portable_e31.py' -v
printf '\n== E32 public cleanup replay contract tests (synthetic only) ==\n'
"$PYTHON_BIN" -I -S -B backend/nut/test_replay_operational_portable_e32.py -v
printf '\n== Synthetic continuous capture tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_continuous_capture.py' -v
printf '\n== Synthetic operational publication and framing tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_operational_publication.py' -v
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_operational_framing.py' -v
printf '\n== Synthetic operational capture lifecycle tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_operational_capture.py' -v
printf '\n== App-controlled capture adapter v2 tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_app_controlled_capture.py' -v
printf '\n== Managed synthetic entrypoint tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_managed_synthetic_entrypoint.py' -v
printf '\n== Managed native runtime tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_managed_native_runtime.py' -v
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_app_controlled_operational.py' -v
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_managed_operational_entrypoint.py' -v
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_stage_managed_operational_runtime.py' -v
"$PYTHON_BIN" -I -S -B backend/nut/test_stage_bundled_python_runtime.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_normalize_bundled_python.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_managed_bundled_operational_entrypoint.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_managed_frozen_operational_entrypoint.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_prepare_bundled_operational_candidate.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_stage_frozen_operational_runtime.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_assemble_frozen_operational_runtime.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_build_fresh_hidapi_candidate.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_first_io_source_stage.py -v
"$PYTHON_BIN" -I -S -B backend/nut/test_first_io_package_recipe.py -v
"$PYTHON_BIN" -I -S -B -m unittest discover -s scripts -p 'test_prepare_synthetic_source.py' -v
"$PYTHON_BIN" -I -S -B -m unittest discover -s scripts -p 'test_export_developer_kit.py' -v
printf '\n== Bounded stream dispatch tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_bounded_stream_dispatch*.py' -v
printf '\n== Synthetic continuous stream tests ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_synthetic_continuous_stream.py' -v
printf '\n== Synthetic continuous diagnostics staging tests ==\n'
"$PYTHON_BIN" backend/nut/test_stage_hidapi_continuous_diagnostics.py \
    --stager-sha256 1e4730c8e237232302ec26f3cff07c5ce838cb0b7b98c1d96ff3d00c226b74a8
printf '\n== Offline USB ownership extraction contracts ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_extract_usb_owner_retention.py' -v
printf '\n== Offline guarded startup/stop extraction contracts ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_extract_guarded_startup_stop.py' -v
printf '\n== Offline guarded reopen/stop extraction contracts ==\n'
"$PYTHON_BIN" -m unittest discover -s backend/nut -p 'test_extract_guarded_reopen_stop.py' -v

printf '\n== Privacy declaration and packaging regressions ==\n'
"$PYTHON_BIN" -m unittest discover -s scripts -p 'test_privacy_manifest.py' -v
"$PYTHON_BIN" "$SCRIPT_DIR/check_privacy_manifest.py" --source-root "$ROOT"

printf '\n== Swift package tests ==\n'
DisableExecutionPolicyExceptionRegistration=YES swift test --verbose --build-system swiftbuild \
    --scratch-path "$SWIFT_SCRATCH_PATH" \
    --cache-path "$VALIDATION_TMP/cache" \
    --config-path "$VALIDATION_TMP/config" \
    --security-path "$VALIDATION_TMP/security" \
    --manifest-cache none --disable-dependency-cache

printf '\n== Swift release build ==\n'
DisableExecutionPolicyExceptionRegistration=YES swift build -c release --verbose --build-system swiftbuild \
    --scratch-path "$SWIFT_SCRATCH_PATH" \
    --cache-path "$VALIDATION_TMP/cache" \
    --config-path "$VALIDATION_TMP/config" \
    --security-path "$VALIDATION_TMP/security" \
    --manifest-cache none --disable-dependency-cache

printf '\n== Plist and entitlement syntax ==\n'
plutil -lint \
    UPSMonitor.xcodeproj/project.pbxproj \
    App/Info.plist App/Shared.entitlements App/PrivacyInfo.xcprivacy \
    Widget/Info.plist Widget/Local.entitlements Widget/Shared.entitlements Widget/PrivacyInfo.xcprivacy
bash "$SCRIPT_DIR/check-version.sh"
printf '\n== Version metadata regression tests ==\n'
bash "$SCRIPT_DIR/test-versioning.sh"

printf '\n== Ad-hoc Xcode Release build ==\n'
DERIVED_DATA="$VALIDATION_TMP/xcode-derived-data"
printf 'Fresh Xcode validation directory: %s\n' "$DERIVED_DATA"
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
printf '\n== Built app and widget privacy manifests ==\n'
"$PYTHON_BIN" "$SCRIPT_DIR/check_privacy_manifest.py" \
    --source-root "$ROOT" --app-bundle "$APP_BUNDLE"
printf '\n== Ad-hoc signature verification ==\n'
codesign --verify --deep --strict "$APP_BUNDLE"
printf 'Ad-hoc app signature verified.\n'

printf '\nValidation completed. No app, widget, native probe or UPS driver was launched by this script.\n'
printf 'Caller-owned scratch remains at %s; remove it only after all child processes have exited.\n' "$VALIDATION_TMP"
