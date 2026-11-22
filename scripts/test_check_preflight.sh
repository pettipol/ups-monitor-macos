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
                printf '%s\n%s\n' "${XCODE_NAME_VALUE:-}" "${XCODE_BUILD_VALUE:-}"
            elif [ "${PREFLIGHT_SCENARIO:-}" = "swiftpm-contract" ]; then
                : > "$XCODE_BUILD_MARKER"
                exit 92
            fi
            ;;
        swift)
            reject_swift_call() {
                printf '%s\n' "$*" >&2
                : > "$SWIFT_REJECT_MARKER"
                exit 91
            }
            if [ "${1:-}" = "--version" ]; then
                printf '%s\n' "${SWIFT_LINE:-}"
            elif [ "${PREFLIGHT_SCENARIO:-}" = "swiftpm-contract" ]; then
                VALIDATION_BASE="${TMPDIR%/tmp}"
                if [ "$#" -eq 15 ] && [ "$1" = "test" ] && [ "$2" = "--verbose" ] \
                    && [ "$3" = "--build-system" ] && [ "$4" = "swiftbuild" ] \
                    && [ "$5" = "--scratch-path" ] && [ "$7" = "--cache-path" ] \
                    && [ "$9" = "--config-path" ] && [ "${11}" = "--security-path" ] \
                    && [ "${13}" = "--manifest-cache" ] && [ "${14}" = "none" ] \
                    && [ "${15}" = "--disable-dependency-cache" ]; then
                    case "$6:$8:${10}:${12}" in
                        "$VALIDATION_BASE/swiftpm-scratch:$VALIDATION_BASE/cache:$VALIDATION_BASE/config:$VALIDATION_BASE/security")
                            [ -d "$6" ] && [ -d "$8" ] && [ -d "${10}" ] && [ -d "${12}" ] || reject_swift_call 'Missing Swift temporary path.' ;;
                        *) reject_swift_call 'Swift scratch/cache/config/security paths are outside validation TMP.' ;;
                    esac
                    case "$6" in "$CHECKOUT_ROOT"/*) reject_swift_call 'Swift scratch path is inside the checkout.' ;; esac
                    printf 'test|%s\n' "$6" >> "$SWIFT_CALL_LOG"
                elif [ "$#" -eq 17 ] && [ "$1" = "build" ] && [ "$2" = "-c" ] \
                    && [ "$3" = "release" ] && [ "$4" = "--verbose" ] \
                    && [ "$5" = "--build-system" ] && [ "$6" = "swiftbuild" ] \
                    && [ "$7" = "--scratch-path" ] && [ "$9" = "--cache-path" ] \
                    && [ "${11}" = "--config-path" ] && [ "${13}" = "--security-path" ] \
                    && [ "${15}" = "--manifest-cache" ] && [ "${16}" = "none" ] \
                    && [ "${17}" = "--disable-dependency-cache" ]; then
                    case "$8:${10}:${12}:${14}" in
                        "$VALIDATION_BASE/swiftpm-scratch:$VALIDATION_BASE/cache:$VALIDATION_BASE/config:$VALIDATION_BASE/security")
                            [ -d "$8" ] && [ -d "${10}" ] && [ -d "${12}" ] && [ -d "${14}" ] || reject_swift_call 'Missing Swift temporary path.' ;;
                        *) reject_swift_call 'Swift scratch/cache/config/security paths are outside validation TMP.' ;;
                    esac
                    case "$8" in "$CHECKOUT_ROOT"/*) reject_swift_call 'Swift scratch path is inside the checkout.' ;; esac
                    printf 'build|%s\n' "$8" >> "$SWIFT_CALL_LOG"
                else
                    printf 'Unexpected SwiftPM argv (%s tokens): %s\n' "$#" "$*" >&2
                    : > "$SWIFT_REJECT_MARKER"
                    exit 91
                fi
                if [ "${DisableExecutionPolicyExceptionRegistration:-}" != "YES" ]; then
                    printf 'Unexpected execution-policy flag value: %s\n' "${DisableExecutionPolicyExceptionRegistration:-<unset>}" >&2
                    : > "$SWIFT_REJECT_MARKER"
                    exit 91
                fi
                printf '%s|%s|%s\n' "$DisableExecutionPolicyExceptionRegistration" "$#" "$*" >> "$SWIFT_CALL_LOG"
            fi
            ;;
        python3)
            if [ "${1:-}" = "--version" ]; then
                printf '%s\n' "${PYTHON_VERSION_OUTPUT:-}"
            elif [ "${PREFLIGHT_SCENARIO:-}" = "swiftpm-contract" ]; then
                exit 0
            else
                : > "$PYTHON_TEST_MARKER"
                exit 97
            fi
            ;;
        shasum)
            [ "${1:-}" = "-a" ] && [ "${2:-}" = "256" ] && [ -n "${3:-}" ] || exit 98
            printf '%s  %s\n' "${UPS_TEST_ACTUAL_SHA256:-}" "$3"
            ;;
        plutil)
            if [ "${PREFLIGHT_SCENARIO:-}" = "swiftpm-contract" ]; then
                : > "$PLUTIL_MARKER"
                exit 86
            fi
            ;;
        codesign)
            if [ "${PREFLIGHT_SCENARIO:-}" = "swiftpm-contract" ]; then
                : > "$CODESIGN_MARKER"
                exit 93
            fi
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
CHECKOUT_ROOT="$(cd "$(dirname "$CHECK_SCRIPT")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ups-check-preflight.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT HUP INT TERM

run_case() {
    CASE_NAME="$1"
    SWIFT_LINE_VALUE="$2"
    SCENARIO="$3"
    CASE_CHECK_SCRIPT="${4:-$CHECK_SCRIPT}"
    CASE_DIR="$TEST_ROOT/$CASE_NAME"
    mkdir -p "$CASE_DIR/bin"
    for command_name in uname xcodebuild swift python3 shasum plutil codesign; do
        ln -s "$TEST_SCRIPT" "$CASE_DIR/bin/$command_name"
    done
    printf '#!/bin/sh\nexit 99\n' > "$CASE_DIR/fake-upsc"
    chmod 700 "$CASE_DIR/fake-upsc"
    CASE_MARKER="$CASE_DIR/python-tests-reached"
    CASE_OUTPUT="$CASE_DIR/output.txt"
    SWIFT_CALL_LOG="$CASE_DIR/swift-calls.txt"
    SWIFT_REJECT_MARKER="$CASE_DIR/swift-rejected.txt"
    PLUTIL_MARKER="$CASE_DIR/plutil-reached.txt"
    CODESIGN_MARKER="$CASE_DIR/codesign-reached.txt"
    XCODE_BUILD_MARKER="$CASE_DIR/xcode-build-reached.txt"
    CASE_STATUS=0

    if (
        unset PYTHON_BIN UPS_TEST_UPSC UPS_TEST_UPSC_SHA256 UPS_TEST_PYTHON DisableExecutionPolicyExceptionRegistration
        export PATH="$CASE_DIR/bin:/usr/bin:/bin"
        export SWIFT_LINE="$SWIFT_LINE_VALUE"
        export XCODE_NAME_VALUE="Xcode 27.2"
        export XCODE_BUILD_VALUE="Build version 27B52"
        export PYTHON_VERSION_OUTPUT="Python 3.15.2"
        export PYTHON_TEST_MARKER="$CASE_MARKER"
        export PREFLIGHT_SCENARIO="$SCENARIO"
        export SWIFT_CALL_LOG SWIFT_REJECT_MARKER PLUTIL_MARKER CODESIGN_MARKER XCODE_BUILD_MARKER
        export CHECKOUT_ROOT
        mkdir -p "$CASE_DIR/tmp"
        export TMPDIR="$CASE_DIR/tmp"
        case "$SCENARIO" in
            xcode-27.1)
                export XCODE_NAME_VALUE="Xcode 27.1"
                export XCODE_BUILD_VALUE="Build version 27A9275"
                ;;
            xcode-27.2-rc-build)
                export XCODE_BUILD_VALUE="Build version 27B48"
                ;;
            xcode-rc)
                export XCODE_NAME_VALUE="Xcode 27.2 RC"
                export XCODE_BUILD_VALUE="Build version 27B48"
                ;;
            python-3.15.0) export PYTHON_VERSION_OUTPUT="Python 3.15.0" ;;
            python-3.15.1) export PYTHON_VERSION_OUTPUT="Python 3.15.1" ;;
            python-3.14.9) export PYTHON_VERSION_OUTPUT="Python 3.14.9" ;;
            python-prerelease) export PYTHON_VERSION_OUTPUT="Python 3.15.2rc1" ;;
        esac
        if [ "$SCENARIO" = "swiftpm-contract" ]; then
            export DisableExecutionPolicyExceptionRegistration=NO
        fi
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
            bash "$CASE_CHECK_SCRIPT" --unexpected
        else
            bash "$CASE_CHECK_SCRIPT"
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

assert_swiftpm_contract() {
    run_case "$1" "$APPLE_LINE" swiftpm-contract "$2"
    [ "$CASE_STATUS" -eq 86 ] || {
        printf 'FAIL: %s expected stop at fake plutil (86); got %s\n' "$1" "$CASE_STATUS" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
    VALIDATION_TMP_VALUE="$(sed -n 's/^Validation scratch directory (caller cleanup after child exit): //p' "$CASE_OUTPUT")"
    [ -n "$VALIDATION_TMP_VALUE" ] && [ -d "$VALIDATION_TMP_VALUE/swiftpm-scratch" ] \
        && [ -d "$VALIDATION_TMP_VALUE/cache" ] && [ -d "$VALIDATION_TMP_VALUE/config" ] \
        && [ -d "$VALIDATION_TMP_VALUE/security" ] || {
        printf 'FAIL: %s did not create bounded validation scratch outside the checkout.\n' "$1" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
    case "$VALIDATION_TMP_VALUE" in
        "$CASE_DIR/tmp"/ups-validation.*) ;;
        *) printf 'FAIL: validation scratch is not under the supplied TMPDIR.\n' >&2; exit 1 ;;
    esac
    grep -Fq 'DERIVED_DATA="$VALIDATION_TMP/xcode-derived-data"' "$CASE_CHECK_SCRIPT" || {
        printf 'FAIL: %s does not keep Xcode DerivedData under validation TMP.\n' "$1" >&2
        exit 1
    }
    case "$VALIDATION_TMP_VALUE" in "$CHECKOUT_ROOT"/*) printf 'FAIL: validation scratch is inside checkout.\n' >&2; exit 1 ;; esac
    printf '%s\n' \
        "test|$VALIDATION_TMP_VALUE/swiftpm-scratch" \
        "YES|15|test --verbose --build-system swiftbuild --scratch-path $VALIDATION_TMP_VALUE/swiftpm-scratch --cache-path $VALIDATION_TMP_VALUE/cache --config-path $VALIDATION_TMP_VALUE/config --security-path $VALIDATION_TMP_VALUE/security --manifest-cache none --disable-dependency-cache" \
        "build|$VALIDATION_TMP_VALUE/swiftpm-scratch" \
        "YES|17|build -c release --verbose --build-system swiftbuild --scratch-path $VALIDATION_TMP_VALUE/swiftpm-scratch --cache-path $VALIDATION_TMP_VALUE/cache --config-path $VALIDATION_TMP_VALUE/config --security-path $VALIDATION_TMP_VALUE/security --manifest-cache none --disable-dependency-cache" > "$CASE_DIR/expected-swift-calls.txt"
    cmp -s "$CASE_DIR/expected-swift-calls.txt" "$SWIFT_CALL_LOG" || {
        printf 'FAIL: %s did not make both audited SwiftPM calls with the expected flag and argv.\n' "$1" >&2
        cat "$CASE_OUTPUT" "$SWIFT_CALL_LOG" >&2
        exit 1
    }
    [ -f "$PLUTIL_MARKER" ] && [ ! -f "$CODESIGN_MARKER" ] && [ ! -f "$XCODE_BUILD_MARKER" ] \
        && ! grep -Fq 'Version metadata consistent' "$CASE_OUTPUT" || {
        printf 'FAIL: %s passed the fake plutil stop or reached a later command.\n' "$1" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
}

assert_swiftpm_mutant_rejected() {
    run_case "$1" "$APPLE_LINE" swiftpm-contract "$2"
    [ "$CASE_STATUS" -eq 91 ] && [ -f "$SWIFT_REJECT_MARKER" ] && [ ! -f "$PLUTIL_MARKER" ] || {
        printf 'FAIL: %s mutant was not rejected by the fake Swift contract.\n' "$1" >&2
        cat "$CASE_OUTPUT" >&2
        exit 1
    }
}

make_check_mutant() {
    MUTANT_NAME="$1"
    shift
    MUTANT_DIR="$TEST_ROOT/$MUTANT_NAME/scripts"
    mkdir -p "$MUTANT_DIR"
    sed "$@" "$CHECK_SCRIPT" > "$MUTANT_DIR/check.sh"
    chmod 700 "$MUTANT_DIR/check.sh"
}

DRIVER_LINE='swift-driver version: 1.168.6 Apple Swift version 6.4.2 (swiftlang-6.4.2.1.9 clang-2100.4.1.1)'
APPLE_LINE='Apple Swift version 6.4.2 (swiftlang-6.4.2.1.9 clang-2100.4.1.1)'
TEST_SHA_LOWER="$(printf '%64s' '' | tr ' ' 'a')"
TEST_SHA_UPPER="$(printf '%s' "$TEST_SHA_LOWER" | tr '[:lower:]' '[:upper:]')"
TEST_SHA_OTHER="$(printf '%64s' '' | tr ' ' 'b')"
assert_reaches_tests "driver-version" "$DRIVER_LINE"
assert_reaches_tests "apple-version" "$APPLE_LINE"
assert_reaches_tests "optional-digest-match" "$APPLE_LINE" optional-match
assert_reaches_tests "optional-digest-uppercase" "$APPLE_LINE" optional-uppercase

assert_rejected_before_tests "version-6.40" 'Apple Swift version 6.40 (swiftlang)' normal
assert_rejected_before_tests "version-6.4" 'Apple Swift version 6.4 (swiftlang)' normal
assert_rejected_before_tests "version-6.4.1" 'Apple Swift version 6.4.1 (swiftlang)' normal
assert_rejected_before_tests "version-6.4.3" 'Apple Swift version 6.4.3 (swiftlang)' normal
assert_rejected_before_tests "version-prerelease" 'Apple Swift version 6.4.2-rc1 (swiftlang)' normal
assert_rejected_before_tests "xcode-27.1" "$APPLE_LINE" xcode-27.1
assert_rejected_before_tests "xcode-27.2-rc-build" "$APPLE_LINE" xcode-27.2-rc-build
assert_rejected_before_tests "xcode-rc" "$APPLE_LINE" xcode-rc
assert_rejected_before_tests "python-3.15.0" "$APPLE_LINE" python-3.15.0
assert_rejected_before_tests "python-3.15.1" "$APPLE_LINE" python-3.15.1
assert_rejected_before_tests "python-3.14.9" "$APPLE_LINE" python-3.14.9
assert_rejected_before_tests "python-prerelease" "$APPLE_LINE" python-prerelease
assert_rejected_before_tests "partial-optional-environment" "$APPLE_LINE" partial
assert_rejected_before_tests "optional-digest-mismatch" "$APPLE_LINE" digest-mismatch
assert_rejected_before_tests "optional-invalid-digest" "$APPLE_LINE" invalid-digest
assert_rejected_before_tests "optional-empty-executable" "$APPLE_LINE" empty-executable
assert_rejected_before_tests "optional-empty-digest" "$APPLE_LINE" empty-digest
assert_rejected_before_tests "optional-empty-python" "$APPLE_LINE" empty-python
assert_rejected_before_tests "unknown-argument" "$APPLE_LINE" unknown-argument

assert_swiftpm_contract "swiftpm-contract" "$CHECK_SCRIPT"
make_check_mutant "missing-ep-flag" 's/DisableExecutionPolicyExceptionRegistration=YES //g'
assert_swiftpm_mutant_rejected "missing-ep-flag" "$TEST_ROOT/missing-ep-flag/scripts/check.sh"
make_check_mutant "ep-flag-no" 's/DisableExecutionPolicyExceptionRegistration=YES/DisableExecutionPolicyExceptionRegistration=NO/g'
assert_swiftpm_mutant_rejected "ep-flag-no" "$TEST_ROOT/ep-flag-no/scripts/check.sh"
make_check_mutant "missing-build-system" 's/ --build-system swiftbuild//g'
assert_swiftpm_mutant_rejected "missing-build-system" "$TEST_ROOT/missing-build-system/scripts/check.sh"
make_check_mutant "collapsed-swift-argv" -e 's/swift test --verbose --build-system swiftbuild/swift "test --verbose --build-system swiftbuild"/' -e 's/swift build -c release --verbose --build-system swiftbuild/swift "build -c release --verbose --build-system swiftbuild"/'
assert_swiftpm_mutant_rejected "collapsed-swift-argv" "$TEST_ROOT/collapsed-swift-argv/scripts/check.sh"
make_check_mutant "missing-scratch-path" 's/--scratch-path "$SWIFT_SCRATCH_PATH"//g'
assert_swiftpm_mutant_rejected "missing-scratch-path" "$TEST_ROOT/missing-scratch-path/scripts/check.sh"
make_check_mutant "missing-manifest-cache-policy" 's/--manifest-cache none//g'
assert_swiftpm_mutant_rejected "missing-manifest-cache-policy" "$TEST_ROOT/missing-manifest-cache-policy/scripts/check.sh"
make_check_mutant "scratch-inside-checkout" 's|--scratch-path "$SWIFT_SCRATCH_PATH"|--scratch-path "$CHECKOUT_ROOT/.build"|g'
assert_swiftpm_mutant_rejected "scratch-inside-checkout" "$TEST_ROOT/scratch-inside-checkout/scripts/check.sh"

printf 'Swift preflight parser and early-rejection tests passed.\n'
