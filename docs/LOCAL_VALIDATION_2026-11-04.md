# Local Validation — 2026-11-04

## Outcome

**PASS for the configured local synthetic validation and ad-hoc Release build.**
This result does not authorize a release and does not prove live monitoring
continuity, device compatibility, widget operation, GUI behavior, or hosted CI.

The run used Xcode 27.2 build `27B52`, Apple Swift 6.4.2 and Python 3.15.2. It
ran against a frozen working-tree copy of 503 source files (5,776,706 bytes),
verified unchanged before and after the run. Documentation changes recording
this result were made after that frozen source validation and were not part of
the tested snapshot.

## Checks and counts

- Python synthetic suites: 640 tests passed, 0 skipped, 0 failed, across 42
  test commands.
- Swift tests: 449 total, 447 passed, 2 skipped, 0 failed. The two skips were
  optional NUT-client interoperability tests because the separately qualified
  client bundle was absent.
- Swift Release build: passed.
- Xcode app/widget Release build: passed with ad-hoc signing, empty team and
  empty App Group settings.
- Plist, entitlement, version metadata and packaged privacy-manifest checks:
  passed.
- Deep/strict ad-hoc signature verification: passed.

The run did not include a separately packaged Python runtime. It did not launch
the app, widget, native probe, packaged operational helper, UPS driver, or
access USB hardware. No
live device or NUT server was used. The observed process snapshot found no live
owned run processes at completion; process observation is a snapshot and may
miss short-lived or reparented descendants.

## Toolchain and hosted CI

The local pin now matches the observed stable Xcode 27.2 build `27B52` and Apple
Swift 6.4.2; Python 3.15.2 is unchanged. The documented hosted runner image
still maps its Xcode 27.2 alias to RC build `27B48`. The exact preflight rejects
that build, so hosted qualification remains **HOLD** until the runner provides
the stable build. No hosted run was started for this result.

The historical E31/E32 replay pins do not match the current admitted source and
remain unqualified; no automatic repinning is included. This full validation did
not execute the packaging recipe; the separate E61 composition is recorded below.
Repeated-build reproducibility remains unqualified.

## Packaging (2026-11-04, E61)

A separate complete synthetic package composition completed 25 bounded
commands in 57.314 seconds against a frozen source tree of 504 files
(5,787,739 bytes). It assembled the SharedRelease synthetic app and widget,
including the helper/runtime built from the pinned original PBS archive and
six locked wheels plus the public synthetic C producer. The static closure had
25 entries and nine external backend modules bound to the E60 process-deadline
source. Four independent signature verifications passed; 25 notice files were
copied and checked.

No app, helper, producer or widget was launched, and no UPS or hardware was
accessed. This package run did not repeat the test suites above. Archive
read-back verifies the selected retained bytes; it is not runtime qualification.
The result does not establish bit reproducibility, distribution or
notarization, and third-party redistribution review remains **NOT PERFORMED**.
See the [public build recipe](FROZEN_BUILD_RECIPE.md) and
[validation status](VALIDATION.md) for the separate evidence boundaries.

## Managed GUI Session (2026-11-04, E62)

The restored E61 synthetic package, including the E60 process-stop correction,
completed one bounded managed GUI session. The app opened idle; one Start
displayed 90% charge and 3,000 seconds, followed by 91% and 2,995 seconds. One
Stop left the app stopped/stale with the final sample preserved, then normal
Quit completed. The managed receipt reports two samples, `control_reason=stop`,
no adapter error, and confirmed child reap, absent process group, both EOFs,
consumer quiescence and ownership resolution. The outer supervisor completed
with exit 0 in 34.896 seconds. USB and hardware access were not run.

The first GUI attempt timed out at its 180-second supervisor limit while the UI
tool was blocked in app acquisition for about 750 seconds. No Start was sent and
no managed session began; this timeout is not attributed to an app defect. A
second bounded attempt used the existing accessibility binding and completed
the session described above. No new full suite was run; the separate E60 run
remains 640 Python tests passed and 447 Swift tests passed with two skips.

The E61 widget itself was not observed. The prior stopped/stale WidgetKit
observation remains from E57/E58 and is separate from this app session; no
WidgetKit image was exported and existing desktop duplicates were not removed.
This result qualifies only the bounded synthetic app/session path. It does not
qualify real UPS communication, hardware compatibility, daily use, widget
rendering, full accessibility, release or distribution.

## Process-stop correction context

A prior 2026-11-04 E59 full check stopped with one failure in
`test_user_stop_preserves_term_terminal_record_and_real_eofs` (observed child
return code `-15`, expected `0`). E60 changed the public process-deadline helper
to avoid a duplicate direct termination when group signaling succeeds and the
leader remains in the saved process group. The helper revision tested here has
SHA-256 `81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e`.
The E60 check passed after this change, but the evidence does not establish a
causal or temporal relationship between the E59 failure and the E60 correction.

The stop-path checks establish synthetic process-control behavior under their
fixtures. They do not prove uninterrupted real UPS sampling or safety of an
operational device path.

## Historical results

The 2026-10-29 Xcode 27.1 / Apple Swift 6.4 result remains historical and is
preserved in [its dated record](LOCAL_VALIDATION_2026-10-29.md). Earlier E54
and E31/E32 replay evidence also remains historical; this result does not
retroactively qualify those replay pins or change their evidence boundaries.

## Historical producer source reconstruction (E63)

All 200 retained native-build inputs were checked against their recorded
hashes: 190 source files, three HIDAPI files and seven generated/library inputs.
The three vendor files also match the official HIDAPI 0.15.0 tag by Git blob
identity and size; this establishes provenance, not redistribution compliance.

The source-only reconstruction utility matched all 190 production source
hashes against the independent retained archive. Its 18 patch commands
completed normally. Two altered private inputs (one patch and one baseline
source, one byte each) were rejected before creating output. Four synthetic
cancellation tests passed. The first unit gate had stopped before reconstruction
because two tests missed the expected second cancellation exception at context
exit; the failed evidence was preserved and the expectations corrected.

The [experimental source procedure](PRODUCTION_SOURCE_RECONSTRUCTION.md)
does not compile or launch a native driver. The generated headers/static
libraries still need a complete public source recipe, and the later upstream
CAL status mapping must be considered with its freshness dependencies.
No new USB, app or widget session was run. Real Stop, continuous operation,
widget refresh and release remain separate open qualifications.

## E64: native build from source and offline status tests

See the [native build guide and source manifest](../backend/nut/native-build/README.md).

The native SMC1500I candidate was compiled without using the generated headers
or static libraries from earlier private builds. The upstream NUT bootstrap,
out-of-tree configure, two generated headers, five static archives, final link
and static audits completed locally. The 403,760-byte arm64 product declared
macOS 27.0 as its minimum and SDK 27.2. It linked IOKit, CoreFoundation and
libSystem; no libusb library appeared in the linked dependency or object list.
Two unused-code warnings were retained. The product was stored with mode 0600
and was never launched.

The status patch changed two of the 190 admitted source files. Ten offline
groups passed, covering the three CAL register paths, their on/off transitions
and the age of all present status contributors. Reading this bit does not
initiate calibration. No device, live status change or electrical operation
was involved. Packaging this specific producer, clean Stop on hardware,
continuity and real widget rendering remain unqualified.

## E65 — assembled local real preview

The source-built arm64 producer and previously verified arm64 frozen helper
were packaged with the real app and widget. Both received local development
signatures with the dedicated App Group. Nine backend module hashes, the
compiled pin, separate widget store selection and 83 archived bundle entries
were checked. The outer app contains arm64 and x86_64, while the managed
runtime is restricted to arm64. This checkpoint did not launch the package.
Real Stop, real widget updates, sustained runtime and distribution remain open.
See the [packaging steps](REAL_PREVIEW_PACKAGE.md).
