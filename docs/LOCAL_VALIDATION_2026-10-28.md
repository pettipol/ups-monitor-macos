# Complete local validation — 2026-10-28

**PASS for the configured local check, with two expected optional-client skips.**
One run of `scripts/check.sh` completed on a frozen copy of 439 regular source
files, including tracked and uncommitted working-tree changes. This is not a
clean release commit, a published artifact, or hosted CI evidence. Subsequent
documentation updates record this result; the tested copy remains unchanged.

## Results

| Stage | Observed result |
|---|---|
| Python unittest | 545 tests in 34 invocations, all passed |
| XCTest | 271 declared tests: 269 passed, two expected skips |
| Swift Testing | 151 declared tests passed; parameterized cases are not counted again |
| Swift package | Test build and Release build succeeded |
| Xcode macOS Release | App and widget build succeeded |
| Metadata | Plists, source/bundle version and packaged privacy manifests passed |
| Local signature | Deep/strict verification of the ad-hoc app signature passed |

The two Swift frameworks total 422 declared tests: 420 passed and two skipped.
The skipped tests are the optional `UPSCInteropTests` cases: the qualified
client/interpreter/digest environment was deliberately absent. No additional
skip was introduced. The E31 32-contract and E32 57-contract suites passed
within the Python total; do not add them again.

The recorded toolchain was Xcode 27.1 build `27A9275`, Apple Swift 6.4 and
Python 3.15.2. Version metadata remained `0.1.0-preview.1`, bundle 0.1.0/build 1.
The supervised child completed in about 115 seconds, with 2,657,416 bytes of
captured output. Source and toolchain pins matched before and after the run.
An independent review checked the complete logs and artifact digests.

## Boundaries

This is the full configured entrypoint, not every specialized runner in the
repository. It does not execute the separately admitted native replay builds,
qualify an actual NUT client, or replace their evidence. Synthetic test helpers
and test binaries did run; the app, widget, native probe and UPS driver were
not launched. No USB or electrical test was performed.

The postflight observed no remaining owned process or open scratch/capture
handle. Process sampling is bounded evidence, not an audit of all processes.
Peak recorded scratch allocation was about 1.39 GiB; cumulative writes and
external Apple metadata/cache writes were not measured or fully confined.
Xcode can perform local LaunchServices/execution-policy registration during
build. Ad-hoc signing does not qualify distribution signing or notarization.

The CoreSimulator-version warning did not prevent the macOS build. This run
does not establish simulator or UI compatibility. Privacy-manifest validation
checks the declarations and packaging, not all runtime privacy behavior.

Hosted CI on the intended release commit, real clean Stop, live widget/App
Group behavior, sustained monitoring, portable runtime packaging, and release
acceptance remain separate open gates. See [CI status](CI.md),
[validation procedure](VALIDATION.md), and [release checklist](RELEASE_CHECKLIST.md).
