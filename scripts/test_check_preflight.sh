#!/bin/bash
set -euo pipefail

PROGRAM_NAME="${0##*/}"
if [ "$PROGRAM_NAME" != "test_check_preflight.sh" ]; then
    case "$PROGRAM_NAME" in
        uname)
            printf 'Darwin\n'
            ;;
        xcodebuild)
            if [ "${1:-}" = "-version" ]; then
                printf 'Xcode 27.0\nBuild version 27A266a\n'
            fi
            ;;
        swift)
            if [ "${1:-}" = "--version" ]; then
                printf '%s\n' "${SWIFT_LINE:-}"
            fi
            ;;
        python3)
            if [ "${1:-}" = "--version" ]; then
                printf '%s\n' "${PYTHON_VERSION_OUTPUT:-}"
            else
                : > "$PYTHON_TEST_MARKER"
                exit 97
            fi
            ;;
        shasum)
            [ "${1:-}" = "-a" ] && [ "${2:-}" = "256" ] && [ -n "${3:-}" ] || exit 98
            printf '%s  %s\n' "${UPS_TEST_ACTUAL_SHA256:-}" "$3"
            ;;
        plutil|codesign)
            ;;
        *)
            printf 'Unexpected stub command: %s\n' "$PROGRAM_NAME" >&2
            exit 98
            ;;
    esac
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_SCRIPT="$SCRIPT_DIR/test_check_preflight.sh"
CHECK_SCRIPT="$SCRIPT_DIR/check.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ups-check-preflight.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT HUP INT TERM

run_case() {
    CASE_NAME="$1"
    SWIFT_LINE_VALUE="$2"
    SCENARIO="$3"
    CASE_DIR="$TEST_ROOT/$CASE_NAME"
    mkdir -p "$CASE_DIR/bin"
    for command_name in uname xcodebuild swift python3 shasum plutil codesign; do
        ln -s "$TEST_SCRIPT" "$CASE_DIR/bin/$command_name"
    done
    printf '#!/bin/sh\nexit 99\n' > "$CASE_DIR/fake-upsc"
    chmod 700 "$CASE_DIR/fake-upsc"
    CASE_MARKER="$CASE_DIR/python-tests-reached"
    CASE_OUTPUT="$CASE_DIR/output.txt"
    CASE_STATUS=0

    if (
        unset PYTHON_BIN UPS_TEST_UPSC UPS_TEST_UPSC_SHA256 UPS_TEST_PYTHON
        export PATH="$CASE_DIR/bin:/usr/bin:/bin"
        export SWIFT_LINE="$SWIFT_LINE_VALUE"
        export PYTHON_VERSION_OUTPUT="Python 3.14.8"
        export PYTHON_TEST_MARKER="$CASE_MARKER"
        if [ "$SCENARIO" = "partial" ]; then
            export UPS_TEST_UPSC="$CASE_DIR/fake-upsc"
        elif [ "$SCENARIO" = "optional-match" ] || [ "$SCENARIO" = "optional-uppercase" ] || \
             [ "$SCENARIO" = "digest-mismatch" ] || [ "$SCENARIO" = "invalid-digest" ] || \
             [ "$SCENARIO" = "empty-executable" ] || [ "$SCENARIO" = "empty-digest" ] || \
             [ "$SCENARIO" = "empty-python" ]; then
            export UPS_TEST_UPSC="$CASE_DIR/fake-upsc"
            export UPS_TEST_UPSC_SHA256="$TEST_SHA_LOWER"
            export UPS_TEST_PYTHON=/bin/sh
            export UPS_TEST_ACTUAL_SHA256="$TEST_SHA_LOWER"
            case "$SCENARIO" in
                optional-uppercase) export UPS_TEST_UPSC_SHA256="$TEST_SHA_UPPER" ;;
                digest-mismatch) export UPS_TEST_UPSC_SHA256="$TEST_SHA_OTHER" ;;
                invalid-digest) export UPS_TEST_UPSC_SHA256="not-a-digest" ;;
                empty-executable) export UPS_TEST_UPSC="" ;;
                empty-digest) export UPS_TEST_UPSC_SHA256="" ;;
                empty-python) export UPS_TEST_PYTHON="" ;;
            esac
        fi
        if [ "$SCENARIO" = "unknown-argument" ]; then
            bash "$CHECK_SCRIPT" --unexpected
        else
            bash "$CHECK_SCRIPT"
        fi
    ) > "$CASE_OUTPUT" 2>&1; then
        CASE_STATUS=0
    else
        CASE_STATUS=$?
    fi
}

assert_reaches_tests() {
    run_case "$1" "$2" "${3:-normal}"
    [ "$CASE_STATUS" -eq 97 ] || {
        printf 'FAIL: %s expected test marker exit 97; got %s\n' "$1" "$CASE_STATUS" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
    [ -f "$CASE_MARKER" ] || {
        printf 'FAIL: %s did not reach the fake Python test marker\n' "$1" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
}

assert_rejected_before_tests() {
    run_case "$1" "$2" "$3"
    [ "$CASE_STATUS" -ne 0 ] && [ "$CASE_STATUS" -ne 97 ] || {
        printf 'FAIL: %s expected preflight rejection; got %s\n' "$1" "$CASE_STATUS" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
    [ ! -e "$CASE_MARKER" ] || {
        printf 'FAIL: %s reached the fake Python test marker\n' "$1" >&2
        exit 1
    }
}

DRIVER_LINE='swift-driver version: 1.168.6 Apple Swift version 6.4 (swiftlang-6.4.0.34.1 clang-2100.3.34.1)'
APPLE_LINE='Apple Swift version 6.4 (swiftlang-6.4.0.34.1 clang-2100.3.34.1)'
TEST_SHA_LOWER="$(printf '%64s' '' | tr ' ' 'a')"
TEST_SHA_UPPER="$(printf '%s' "$TEST_SHA_LOWER" | tr '[:lower:]' '[:upper:]')"
TEST_SHA_OTHER="$(printf '%64s' '' | tr ' ' 'b')"
assert_reaches_tests "driver-version" "$DRIVER_LINE"
assert_reaches_tests "apple-version" "$APPLE_LINE"
assert_reaches_tests "optional-digest-match" "$APPLE_LINE" optional-match
assert_reaches_tests "optional-digest-uppercase" "$APPLE_LINE" optional-uppercase

assert_rejected_before_tests "version-6.40" 'Apple Swift version 6.40 (swiftlang)' normal
assert_rejected_before_tests "version-6.4.1" 'Apple Swift version 6.4.1 (swiftlang)' normal
assert_rejected_before_tests "version-prerelease" 'Apple Swift version 6.4-dev (swiftlang)' normal
assert_rejected_before_tests "partial-optional-environment" "$APPLE_LINE" partial
assert_rejected_before_tests "optional-digest-mismatch" "$APPLE_LINE" digest-mismatch
assert_rejected_before_tests "optional-invalid-digest" "$APPLE_LINE" invalid-digest
assert_rejected_before_tests "optional-empty-executable" "$APPLE_LINE" empty-executable
assert_rejected_before_tests "optional-empty-digest" "$APPLE_LINE" empty-digest
assert_rejected_before_tests "optional-empty-python" "$APPLE_LINE" empty-python
assert_rejected_before_tests "unknown-argument" "$APPLE_LINE" unknown-argument

printf 'Swift preflight parser and early-rejection tests passed.\n'
