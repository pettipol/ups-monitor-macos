# Complete local validation — 2026-10-29

**PASS for the configured local check, with two expected optional-client skips.**
One complete run of `scripts/check.sh` finished on a frozen copy of 493 source
files (5,677,511 bytes), including uncommitted changes. An independent review
checked the raw logs, source/tool bindings and built app/widget artifacts.
This is local source/build evidence, not a release commit or hosted CI result.
Documentation recording the result was updated after the tested freeze.

## Results

| Stage | Observed result |
|---|---|
| Python unittest | 617 tests in 40 invocations, all passed |
| XCTest | 298 declared tests: 296 passed, two expected skips |
| Swift Testing | 151 declared tests passed; expanded parameter cases are not added again |
| Swift package | Test build and Release build succeeded |
| Xcode macOS Release | App and widget build succeeded |
| Metadata | Source/bundle versions and source/bundled privacy manifests passed |
| Local signature | Deep/strict verification of the ad-hoc app signature passed |

The Swift frameworks total 449 declared tests: **447 passed and two skipped**.
The skipped tests are the optional `UPSCInteropTests` cases; the qualified
client/interpreter/digest environment was deliberately absent. There were no
additional skips or unexpected failures. The bundled/frozen packager and notice
assembly contracts are included in the Python total, not additional counts.

Toolchain: Xcode 27.1 build `27A9275`, Apple Swift 6.4 and Python 3.15.2.
Version metadata remains `0.1.0-preview.1`, bundle 0.1.0/build 1. The supervised
child completed in about 110 seconds and captured 2,779,844 bytes of output.
The earlier successful stub preflight was reused because its scripts and
selected tool binaries were unchanged.

## Defects resolved before this run

Two earlier attempts stopped in Python tests and remain recorded separately.
First, a staging test incorrectly assumed that the source checkout was outside
the allowed temporary roots. Its replacement tests a deliberately writable
temporary parent, and separately checks the root boundary without opening an
external destination. The old failure was reproduced and the corrected test
passed with both `077` and `022` umasks; removing the permission check was caught.

Next, runtime fixtures inherited restrictive directory modes, and the packager
also created its backend directory without restoring the declared `0755` mode
after `mkdir`. Fixtures now set their intended modes explicitly. The packager
sets and checks the new directory's mode through a file descriptor and writes
modules relative to that same directory. Regression coverage checks bundled
and frozen profiles under both umasks, including identical manifests per
profile. The old packager with corrected fixtures fails with `file_mode` under
`077`; the corrected suites and all remaining configured Python checks passed
before the final complete run. Consumer validation was not relaxed.

## Boundaries

This is the full configured entrypoint, not every specialized native replay in
the repository. Synthetic subprocesses and test binaries ran. No app, widget,
frozen helper, actual NUT client, UPS driver or USB session was launched.

All 493 declared source inputs and selected tool pins matched before and after
the run. The copied checkout also contained three generated `.pyc` files from
test children; these are derived outputs, not source inputs. Input integrity
does not mean the entire copied directory remained unchanged.

The postflight found no observed owned process/group or open scratch, capture
or deleted-file handle. Observation is bounded and does not audit all system
processes. The limits were 600 seconds, five seconds of termination grace,
16 MiB combined captured output and 10 GiB allocated scratch/capture storage,
with a 370 GiB free-space floor. Cumulative writes and external Apple metadata
or cache writes were not measured. Xcode may register build products locally.

The ordinary ad-hoc Release app has no configured shared App Group and does
not contain the separately assembled frozen backend. Its successful build
does not qualify the signed synthetic bundle, main GUI, installed WidgetKit
rendering, real clean Stop or continuous monitoring. Hosted CI on the intended
release revision, complete payload obligations, distribution signing and
download/install behavior remain open. See [CI](CI.md),
[validation](VALIDATION.md) and [release gates](RELEASE_CHECKLIST.md).
