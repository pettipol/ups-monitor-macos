# Local Validation

From the repository root, run the validation sequence with:

```sh
bash scripts/check.sh
```

The script is Bash 3.2 compatible and resolves the repository root from its own
path; from another directory pass the path to `scripts/check.sh`. It accepts
no arguments. It requires macOS (Darwin), Xcode 27.0 build 27A266a, Apple Swift 6.4 and
Python 3.14.8. `PYTHON_BIN` may name the Python 3.14.8 executable; it defaults
to `python3`. The script prints the detected versions and stops before tests if
the pinned baseline does not match. It does not install or download tools.

`bash scripts/test_check_preflight.sh` separately exercises version parsing and
early rejection with synthetic command stubs. It covers both supported Swift
version-line formats, rejects nearby/prerelease versions, checks optional
client digest matching (including uppercase hex), and checks incomplete or
invalid optional environment variables and unknown arguments before test
execution. The parser and early-rejection harness can be run separately with
`bash scripts/test_check_preflight.sh`; it uses synthetic command stubs and
stops at a fake test marker, without starting the full validation sequence.

## Sequence

The script runs, in order:

1. Python standard-library tests under `backend/nut` matching
   `test_process_deadline*.py`.
2. The complete Swift package test suite with `swift test`.
3. A Swift release build with `swift build -c release`.
4. `plutil -lint` over the Xcode project, app/widget plists and entitlements.
5. An Xcode Release build in `.build/validation-app`, with ad-hoc identity and
   empty `DEVELOPMENT_TEAM` and `UPS_APP_GROUP_ID`.
6. Deep/strict signature verification of the resulting local app bundle.

The Xcode step does not use the Shared signing configurations or an App Group.
It does not launch the app, widget, native probe, or UPS driver. Build output is
kept under `.build/validation-app`; the script never runs a clean or recursively
deletes build data.

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

This command sequence is local source, synthetic-test, build, plist and
ad-hoc-signature validation. Hosted CI has not been run by this script and must
be recorded separately. Passing tests and a successful build do not prove
physical UPS compatibility, real NUT/driver safety, sustained telemetry,
permissions, user-interface quality, widget installation/rendering, App Group
runtime access, or notification presentation. Those remain separate gates in
the release checklist. The script does not perform a native power-source probe
or launch the application.
