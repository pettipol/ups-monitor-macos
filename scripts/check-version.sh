#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${UPS_VERSION_CHECK_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

fail() {
    printf 'Version check failed: %s\n' "$*" >&2
    exit 1
}

[ -f "$ROOT/VERSION" ] || fail "VERSION is missing."
[ -f "$ROOT/CHANGELOG.md" ] || fail "CHANGELOG.md is missing."
[ -f "$ROOT/App/Info.plist" ] || fail "App/Info.plist is missing."
[ -f "$ROOT/Widget/Info.plist" ] || fail "Widget/Info.plist is missing."
command -v plutil >/dev/null 2>&1 || fail "plutil is required."

version="$(cat "$ROOT/VERSION")"
semver_pattern='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)$'
[[ "$version" =~ $semver_pattern ]] || fail "VERSION must be SemVer with a prerelease identifier."

prerelease="${version#*-}"
IFS='.' read -r -a identifiers <<< "$prerelease"
for identifier in "${identifiers[@]}"; do
    if [[ "$identifier" =~ ^[0-9]+$ && ${#identifier} -gt 1 && "$identifier" == 0* ]]; then
        fail "Numeric prerelease identifiers must not have leading zeroes."
    fi
done

release_version="${version%%-*}"
bundle_build=""
for plist in "$ROOT/App/Info.plist" "$ROOT/Widget/Info.plist"; do
    short_version="$(plutil -extract CFBundleShortVersionString raw -o - "$plist")" \
        || fail "Could not read CFBundleShortVersionString from $plist."
    build_version="$(plutil -extract CFBundleVersion raw -o - "$plist")" \
        || fail "Could not read CFBundleVersion from $plist."
    semver_version="$(plutil -extract UPSMonitorSemVer raw -o - "$plist")" \
        || fail "Could not read UPSMonitorSemVer from $plist."

    [ "$short_version" = "$release_version" ] \
        || fail "$plist CFBundleShortVersionString must match $release_version."
    [[ "$build_version" =~ ^[0-9]+([.][0-9]+){0,2}$ ]] \
        || fail "$plist CFBundleVersion must be numeric."
    [ "$semver_version" = "$version" ] \
        || fail "$plist UPSMonitorSemVer must match VERSION ($version)."

    if [ -z "$bundle_build" ]; then
        bundle_build="$build_version"
    elif [ "$bundle_build" != "$build_version" ]; then
        fail "App and widget CFBundleVersion values differ."
    fi
done

heading="## [$version] - Source preview"
grep -Fqx "$heading" "$ROOT/CHANGELOG.md" \
    || fail "CHANGELOG.md must contain: $heading"

printf 'Version metadata consistent: %s (bundle %s, build %s).\n' \
    "$version" "$release_version" "$bundle_build"
