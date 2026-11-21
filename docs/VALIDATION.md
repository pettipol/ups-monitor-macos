# Local Validation

The [November 19 candidate check](LOCAL_VALIDATION_2026-11-19.md) records E89
packaging, native-source reconstruction and the H14 controller simulation.
Its scope is separate from the full historical suite results below; real Stop,
widget observation, sustained operation and delivery qualification remain open.

From the repository root, run the validation sequence with:

```sh
bash scripts/test_check_preflight.sh
"${PYTHON_BIN:-python3}" -I -S -B scripts/check_reader_contracts.py
bash scripts/check.sh
```

The middle command exercises six offline reader suites covering source extraction,
configuration, cancellation, staging and simulated replay. It fails when a named
suite is missing, empty, entirely skipped or unsuccessful.

The hosted candidate splits these checks into two jobs. `reader-contracts` runs
only the six suites on `macos-26`, after asserting Python 3.15.2, Darwin and
arm64. It does not select or require Xcode. The existing `macos` build job keeps
its name and `xcode-27` runner, depends on `reader-contracts`, and has a guard
that fails before checkout if the reader job did not succeed. Workflow
cancellation cancels the dependent job. The build job then runs the synthetic
preflight harness and `scripts/check.sh`; the latter performs the real pinned
Xcode/Swift/Python preflight before its test and build sequence. A reader PASS
alone is never build PASS. Runner provisioning and hosted execution are
`NOT RUN`; see [CI status](CI.md).

On 2026-11-05 the 523 source files from the E76 developer kit were checked
locally with the pinned toolchain. The ordinary preflight and 651 Python
tests passed. The process monitor interrupted the first Swift compilation.
The remaining Swift/Xcode steps were resumed in the same workspace. Swift
reported 451 passes and two optional skips. Both skipped NUT client cases
then passed against their own localhost fixtures with the previously qualified
client, for 453 distinct passing Swift cases. Both Release builds, source and
bundle privacy checks, version checks and ad-hoc signature verification passed.
The six separate reader suites contributed 72 more passing Python tests
(723 across the two selections). This was a local, multi-phase check. A hosted
run on the delivery revision, desktop widget refresh, normal USB Stop and
installation from a download still require separate evidence.

The main check script is Bash 3.2 compatible and resolves the repository root from its own
path; from another directory pass the path to `scripts/check.sh`. It accepts
no arguments. The current local preflight expects macOS (Darwin), Xcode
27.2 build 27B52, Apple Swift 6.4.2 and Python 3.15.2. `PYTHON_BIN` may name
the Python 3.15.2 executable; it defaults to `python3`. The script prints the detected versions and stops before tests if they do not match. The complete
configured local check, including Swift and Xcode Release builds, passed on
2026-11-04 on a frozen working-tree copy: 640 Python tests and 447 Swift tests
passed, with two optional NUT-client tests skipped. See the [dated result and
limits](LOCAL_VALIDATION_2026-11-04.md). The 2026-10-29 result remains a separate
historical baseline; see [its dated record](LOCAL_VALIDATION_2026-10-29.md).
Hosted CI for the refreshed baseline is still `HOLD`; see [CI status](CI.md).
The check includes bundled and frozen runtime contracts, but does not execute
the assembled frozen app or qualify its GUI, hardware or distribution. The
script does not install or download tools.

A separate 2026-11-04 synthetic SharedRelease package composition completed
25 bounded commands in 57.314 seconds on 504 frozen source files
(5,787,739 bytes). It passed static closure and signature checks without
launching a product or repeating these tests. See the [dated packaging record](LOCAL_VALIDATION_2026-11-04.md#packaging-2026-11-04-e61);
this does not change hosted CI's **HOLD** status or establish runtime,
reproducibility or distribution qualification.

`bash scripts/test_check_preflight.sh` separately exercises version parsing and
early rejection with synthetic command stubs. It covers both supported Swift
version-line formats, rejects nearby/prerelease versions, checks optional
client digest matching (including uppercase hex), and checks incomplete or
invalid optional environment variables and unknown arguments before test
execution. The parser and early-rejection harness can be run separately with
`bash scripts/test_check_preflight.sh`; it uses synthetic command stubs and
stops at a fake test marker, without starting the full validation sequence. It
also rejects Xcode 27.1, Xcode build 27B48 and an Xcode RC, plus Swift 6.4,
6.4.1, 6.4.3 and a prerelease before the Python test marker. The prior 29-case
mock passed on 2026-10-26; the refreshed matrix passed separately on 2026-11-04
using synthetic command stubs. This is distinct from the full check and does not
prove filesystem confinement by a real toolchain. It checks the two SwiftPM
command argument lists, temporary scratch/cache/config/security paths and the
one-command
`DisableExecutionPolicyExceptionRegistration=YES` override, then stops at a
fake `plutil` after toolchain preflight but before source-version checks,
signing, or an Xcode build. Scratch mutants
confirm rejection when paths are missing or point into the checkout, when the
flag is absent or `NO`, when the build-system option is absent, or when the
full argv is collapsed into one token. These stub checks validate the fake
command contract; they do not prove filesystem confinement by a real toolchain.

## Sequence

With the matching toolchain, the script runs, in order:

1. Python standard-library process, offline replay source-fence, merged-pin
   HID candidate-runner contract, continuous-diagnostics staging, continuous
   protocol, continuous-capture, and privacy-declaration tests, followed by
   source privacy-manifest checks.
2. The complete Swift package test suite with dedicated scratch, cache,
   configuration and security paths, no manifest cache and disabled dependency
   cache, using
   `swift test --verbose --build-system swiftbuild`.
3. A Swift release build with the same path and cache settings, using
   `swift build -c release --verbose --build-system swiftbuild`.
4. `plutil -lint` over the Xcode project, app/widget plists, privacy manifests
   and entitlements, then source-version metadata checks and regressions.
5. An Xcode Release build in a fresh DerivedData directory inside the dedicated
   validation scratch area,
   with ad-hoc identity and
   empty `DEVELOPMENT_TEAM` and `UPS_APP_GROUP_ID`.
6. Verification of both packaged privacy manifests, then deep/strict signature
   verification of the resulting local app bundle.

The two SwiftPM invocations set the Swift Build feature flag
`DisableExecutionPolicyExceptionRegistration=YES` for that command only. The
flag is declared in Swift Build's [`SWBFeatureFlag.swift`](https://github.com/swiftlang/swift-build/blob/main/Sources/SWBCore/SWBFeatureFlag.swift)
and checked by [`RegisterExecutionPolicyExceptionTaskAction.swift`](https://github.com/swiftlang/swift-build/blob/main/Sources/SWBTaskExecution/TaskActions/RegisterExecutionPolicyExceptionTaskAction.swift).
Verbose output is retained for audit; when the flag is honored, the
execution-policy task may still appear, but it should report that registration
was skipped. That skip note was dynamically observed in a bounded run using
Xcode 27.1 and Apple Swift 6.4. The observation predates the current Xcode 27.2
and Swift 6.4.2 baseline and does not qualify it. This observation does not
apply retroactively
to the historical Xcode 27.0 build 27A266a baseline and does not qualify release or
CI runs. The flag addresses execution-policy exception registration only.

The validation script creates a unique scratch directory under
`${TMPDIR:-/tmp}`. SwiftPM scratch, cache, configuration and security paths,
compiler module caches, and Xcode DerivedData are directed into that directory.
It prints the directory and leaves it for the caller to clean only after all
owned child processes have exited; it does not automatically remove it while a
child may still be running.

The Xcode step does not use the Shared signing configurations or an App Group,
and the SwiftPM flag does not qualify or isolate it. Xcode may register the app
with LaunchServices and may perform execution-policy registration. No claim of
zero such side effects is made for this phase. It does not launch the app,
widget, native probe, or UPS driver. Build output stays in the printed
validation scratch directory; the script never runs a clean or recursively
deletes earlier build data. Fresh Xcode output and explicit embedded manifest
checks avoid accepting a stale packaged extension as release evidence.

## Optional NUT Client Interop

The two synthetic client interop tests are skipped only when all three are
unset: `UPS_TEST_UPSC`, `UPS_TEST_UPSC_SHA256` and `UPS_TEST_PYTHON`. A partial
set, an empty value, an invalid digest, or invalid path fails before a fixture
or client process is launched. The script checks that `UPS_TEST_UPSC` is an
absolute executable regular file without a final-component symlink,
`UPS_TEST_PYTHON` is an absolute executable file, and the SHA-256 is 64
hexadecimal characters. It also computes SHA-256 over the supplied executable
file bytes and requires a case-insensitive match before entering the test
sequence. Set all three or leave all three unset. When unset, the script prints
an explicit skip notice; the base suite is not full NUT client qualification.

When enabled, tests validate the executable digest again through
`NUTSnapshotReader.validateExecutable()` before each direct client launch; the
runtime reader also performs its own preflight. Tests launch only the
explicitly supplied completion-qualified `upsc` client and Python fixture
process against a synthetic server bound to an ephemeral loopback port. They do
not connect to an existing NUT server or UPS. The digest check identifies file
bytes, but does not establish publisher trust, verify linked libraries, or
prevent a same-user time-of-check/time-of-use replacement. The executable is
actually run by these optional tests; do not pass an unreviewed binary or a real
hardware target. The script itself does not run a driver or hardware probe.

## Evidence Boundaries

On 2026-10-26, selected synthetic suites under the private source-built Python
3.15.2 runtime passed separately: diagnostic staging 7/7, continuous protocol
8/8, and continuous capture 14/14. The 29-case preflight mock also passed.
These targeted results were not a run of the full `check.sh`. The later
2026-10-28 [complete local check](LOCAL_VALIDATION_2026-10-28.md) covers its
configured Swift suite, Swift release build and Xcode app/widget build; hosted
CI on this candidate still remains `NOT RUN`. The separate public-source portable replay passed its 14 contract checks and
10 diagnostic checks across 24 fake executions. It is not wired into hosted CI.
See [the offline qualification record](CONTINUOUS_OFFLINE_QUALIFICATION.md). The Xcode build is not qualified as avoiding LaunchServices
or execution-policy registration.

Earlier, under Astral CPython 3.15.1 arm64, the separate local discoveries
completed with 209 `backend/nut` tests and 14 `scripts` tests passing (223
total). Those results, and earlier Xcode 27.0/Python 3.14.8 results, are
historical and do not qualify this candidate. Passing tests and a successful
build do not prove
physical UPS compatibility, real NUT/driver safety, sustained telemetry,
permissions, user-interface quality, widget installation/rendering, App Group
runtime access, or notification presentation. Those remain separate gates in
the release checklist. The script does not perform a native power-source probe
or launch the application.

## Bundled Runtime: Public Contracts and Local Qualification

The candidate source tree contains synthetic contracts for bundled staging,
normalization, entrypoint admission and runtime configuration. `check.sh` runs
the Python contracts with isolated mode and the Swift package suite; the local
copy can be run with the command above. These tests check bounded inputs,
manifest and pin handling, path validation and refusal cases. They do not sign
the full runtime/app bundle or reproduce a Foundation/AppModel session.

A separate local qualification completed ad hoc signing and verification for
the bundled CPython runtime, synthetic producer and assembled app/widget
bundle. A bounded Foundation/AppModel host—not the main app—then received two
synthetic samples, completed Stop/Quit and cleanup, and passed with the bundle
at its original location and after copies to paths containing spaces and
Unicode. This result is summarized in
[`BUNDLED_OPERATIONAL_RUNTIME.md`](BUNDLED_OPERATIONAL_RUNTIME.md); signing,
assembly and the session recipe are not part of the public check script. The
bundled configuration suite passed 15/15 in a staged copy before its two
source files were integrated byte-for-byte. The complete local script was
subsequently run on 2026-10-29, including the current bundled/frozen contracts
and notice assembler. That run does not reproduce the separate signed bundle
or its session; hosted CI has not qualified this packaging/session path.

The runtime poll cadence is five seconds. `MonitorAppModel` projects the
coordinator's cached state about once per second; the qualification host
observes it in a bounded approximately 50-millisecond polling loop. Neither
cadence is a latency guarantee. At the historical eight-second checkpoint,
the cached model still showed the prior sample, and the second sample was
validated later. The eight-second target is not qualified.

The source release pin remains `nil`, so the bundled profile is disabled by
default. The E62 result below is a bounded synthetic GUI session on the separately
assembled E61 package; it does not qualify the complete main app GUI, live
widget, notarization, Gatekeeper on a clean host, Intel, daily monitoring, or
real hardware/USB. These require separate evidence and release review.

## Managed GUI Session: E62 (2026-11-04)

The restored E61 synthetic package, containing the E60 process-deadline
correction, completed one bounded managed GUI session. The app opened idle. One
Start showed 90% charge and 3,000 seconds; the next sample showed 91% and 2,995
seconds. One Stop produced stopped/stale state while preserving the final sample,
followed by normal Quit. The managed receipt records two samples, Stop as the
control reason, no adapter error, and successful reap, process-group absence,
both EOFs, consumer quiescence and resolved ownership. The outer supervisor
completed with exit 0 in 34.896 seconds. No USB or hardware access occurred.

GUI-01 timed out at the 180-second supervisor limit while the UI tool remained
blocked in app acquisition for about 750 seconds. It sent no Start and produced
no managed session; the timeout is not attributed to an app defect. GUI-02 used
the existing accessibility binding and completed the cycle above. No new full
suite was run; E60 remains the separate run with 640 Python tests passed and 447
Swift tests passed, two skipped.

The E61 widget extension was not observed. The earlier stopped/stale WidgetKit
observation belongs to E57/E58 and is not evidence for this package. No new
WidgetKit image was exported and desktop duplicates were not removed. This
session does not qualify real UPS communication, hardware compatibility,
continuous or daily use, full GUI accessibility, live widget rendering, release
or distribution.

The merged-pin HID candidate-runner contract tests use synthetic temporary
checkouts and mocked subprocess results. They cover candidate/source fences,
scratch-path refusal, extract-only behavior, and exact RED/GREEN output
contracts; they do not compile or execute the C harness, inspect a NUT build,
or contact hardware. Current test totals must come from the corresponding run
log, not earlier qualification records.
