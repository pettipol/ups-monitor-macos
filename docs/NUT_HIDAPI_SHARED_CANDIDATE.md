# Shared HID Transport: Offline Candidate

Status: **M1 PARTIAL; P2 build and bounded whole-NUT fake replay pass offline**.
Updated on 2026-10-24. A dated one-shot hardware observation is recorded below;
it does not promote M1 to a qualified operational profile or continuous
service.

### 2026-10-24 one-shot observation

One local APC SMC1500I HIDAPI shared-driver observation completed normally with
`-d 1` in 8.45 seconds. The checked descriptor parser passed and Microlink
variables were exported. The dump contained charge and estimated runtime,
battery voltage/temperature, input/output voltage and frequency, output
current, load, nominal W/VA, and driver-derived W/VA. This establishes field
availability in one dump only; observed values are omitted here and are not
metrologically qualified. The existing app reader imported the archived bundle
as `ArchivedUnqualified`, with W/VA labeled driver-derived. That archive import
is distinct from continuous monitoring or a live widget. The one-shot
admission is consumed; this entry does not grant repeat access or claim the
hardware is fully safe for another operation.

The experimental energy counter has unknown units and is ignored by the
standard decoder. Do not interpret it as Wh or kWh. Firmware, calibration,
continuous operation, and the app's live monitoring path remain unqualified.

The historical reviewed baseline core has SHA-256
`99ad54329466cab13789d4f5d8ac7a98e3922e987c47a9cff3fdacada1364115`.
The retained default-off prepare/finish P1 snapshot has SHA-256
`3753ac1d27f8bee542e4fecc2f901b68023dfc0eeb3bb2872ff655bef289e766`.
P2 adds explicit NUT build selection, not an operational profile or app activation.

H01-DIAG-01 adds an in-memory, closed-vocabulary admission diagnostic to the
shared/native seam. It reports the first refused stage, fixed reason token and
parser status (`not-run` is distinct from `ok`); it stores no path, descriptor,
device identity or platform error string. Host detail is copied before callback
leave can trigger close, and the public getter is a pure value snapshot. A
successful admission reports `none`; later I/O and cleanup do not convert it
into an admission refusal. The NUT patch emits only fixed tokens with an
`unknown` fallback. At the author synthetic checkpoint on 2026-10-24,
independent review was pending; that is a historical status. Later H02 emitted
`stage=layout reason=parser-rejected parser=unsupported`; H03 succeeded, so it
did not exercise a failure diagnostic. This records one observed failure
route; it does not prove every token or qualify the patch across other NUT
revisions. Author synthetic shared/native/session replays, six-scenario
whole-NUT fake replay, 28
replay-contract tests and 8 stager tests passed; these do not prove every
failure token was emitted or qualify continuous operation.

Current diagnostic source hashes: shared core
`a87a7d001b992b7b1cfd1afd96d4432cb5a5d9bfe40550c1877ebd646ba83a21`, native
binding `3a1205741d62e02871d96c4e3091674b8131e8d3d95e58b156f2f95e9de1d2a5`,
host/diagnostic header
`606caa96cef85055c68c3b0d7c999e57e24efeb7bac16427dc8836bfd0631dcd`, and
session header
`50104ad0660fbd3c77fa185b0d8e00269f59775a1e123d3b548cb6c86f77d5ae`.

## Scope

The C candidate implements the existing `apcmicrolink-usb.h` interface. Generic
host-operation injection exists only in tests; a separate compile-time opt-in
exposes a typed, one-shot native session API. It is intended to preserve NUT's Microlink
protocol and decoder in a separate, default-off shared-HID candidate.
The existing libusb implementation and its frozen candidate remain unchanged.

Files:

- `backend/nut/apcmicrolink-hidapi-shared.c`: guarded adapter and byte stream.
- `backend/nut/apcmicrolink-hidapi-shared-host.h`: fake host interface and layout.
- `backend/nut/test_hidapi_shared_transport.c`: deterministic synthetic fixtures.
- `backend/nut/replay_hidapi_shared_transport.py`: bounded build/test runner.
- `backend/nut/apcmicrolink-hid-descriptor-checked.c` and `.h`: pure NUT-derived,
  namespaced descriptor admission for a bounded subset; no legacy ABI change.
- `backend/nut/test_hid_descriptor_checked.c` and its replay runner: synthetic
  descriptor cases with explicit rejection and zero usable data on errors.
- `backend/nut/apcmicrolink-hidapi-native.c` and `.h`: explicit, unregistered
  native host factory, single caller/owner, exact USB identity and shared open.
- `backend/nut/test_hidapi_native.c` and `replay_hidapi_native.py`: fake HIDAPI
  tests of the combined core/binding/parser and optional native link-only check.
- `backend/nut/apcmicrolink-hidapi-session.h`, `test_hidapi_session.c` and
  `replay_hidapi_session.py`: default-off one-shot API and isolated fake scenarios.
- `backend/nut/nut-hidapi-observe-73c4502.patch`: separate default-off NUT target
  on the exact ninth guarded source stack, not directly on the base commit.
- `backend/nut/stage_hidapi_candidate.py` and `test_stage_hidapi_candidate.py`:
  pinned offline source/license staging, without patching, building or executing.
- `backend/nut/extract_hidapi_nut.py`, `test_extract_hidapi_nut.py`,
  `test_hidapi_nut.c`, `replay_hidapi_nut.py` and `test_hidapi_nut_supervisor.py`:
  pinned protocol extraction, coupled fake-HID replay and owned-child cancellation.
- `backend/nut/test_hidapi_nut_config.h` and `test_replay_hidapi_nut_config.py`:
  portable test-only branch selection and closed configuration-pin checks.
- `backend/nut/test_hidapi_full_driver.c`, `test_hidapi_full_os.h`,
  `test_hidapi_full_frames.c`, `.h` and `test_hidapi_full_frames_test.c`:
  whole-NUT fake-HID wrapper, explicit test-only OS guards and artificial frames.
- `backend/nut/replay_hidapi_full_driver.py` and `test_replay_hidapi_full_driver.py`:
  separate local build/audit/replay tool and Python mocks; not a live profile.

Only `MLINK_HIDAPI_SHARED_TEST` exposes generic host injection. The separate
`MLINK_HIDAPI_NATIVE_CANDIDATE` exposes prepare/finish; defining both is a
compile error. With neither macro, no host is registered and opening fails
closed. P2 connects the native session API to a separately compiled NUT main;
no app entrypoint or operational profile activates it. No HIDAPI library is
bundled in this repository.
Synthetic layout IDs are not claims about any actual UPS.

## P2 Build Boundary

Patch SHA-256: `5665093a972b760ea460863cdfefc4f8943065af34da606eeca49cad2bd945d0`.
It changes only `configure.ac`, `drivers/Makefile.am`, `drivers/main.c` and
`drivers/apcmicrolink.c` on the ninth guarded stack. It does not alter the
historical libusb driver, the seven pinned adapter modules, or the empty live
profile registry.

The `noinst` target is `apcmicrolink-hidapi-observe`. Configuration requires
explicit `--with-apcmicrolink-hidapi=yes`, Darwin, real USB1 configuration for
NUT headers, and `--disable-shared-private-libs`. The candidate itself does not
link libusb. Default is `no`, independent of `--with-all`; the HIDAPI probe is
compile/link only. Fourteen pinned inputs include seven adapter files, three
HIDAPI 0.15.0 sources/headers and all four upstream license files.

The candidate main is compiled with its own macro. It requires `hidapi_shared`
and `guarded_monitor` before sibling-driver signaling; existing guarded mode
also rejects command, kill-power and PID-target options. Driver initialization
requires explicit one-probe, deadline, exact identity and no-fallback settings.
Private cleanup registration precedes resource allocation. Protocol output is
restricted to STOP, INIT, NEXT and four-byte authentication-descriptor writes;
control entrypoints reject requests. These source-level restrictions still
require integration qualification; they do not establish electrical safety.

Coordinator checks: autoreconf, opt-in configure, native target link and
default-off configure PASS. Static `nm`/`otool` inspection found IOKit,
CoreFoundation and libSystem only, with no libusb or test-injection symbols.
At the pre-observation build-only checkpoint the native executable was
NOT_RUN and lacked execute permission. H02 later launched it and stopped at
the parser; H03 later passed the parser and exported Microlink variables, as
recorded above. Builds emitted warnings; this is not a warning-free release
build.
Staging has eight synthetic tests PASS, independently repeated by the
coordinator. A separate reviewer passed 47 exact-source boundary cases and
caught six executable mutations plus a late-main-gate static mutation; the
coordinator repeated that suite. Another 26 cases exercised exact generated
configure blocks with synthetic inputs and a recorded link stub, not a full
configure run for every case. Both completed full configure runs and the
native link above are distinct evidence.

The historical 47-case fixture replaces prepare/open/finish and transport with
callbacks. A subsequent 32-case replay connects extracted NUT functions to
the real core/session, native binding and checked descriptor parser, replacing
only HIDAPI and surrounding NUT services. Two additional scenarios exercise
the existing process supervisor. The subsequent whole-NUT fake replay below
also exercises main, receive decoder and one real signal-handler path.
Operational profile and hardware qualification remain open. H02 reached the
real descriptor parser and returned `UNSUPPORTED`; H03 passed parser admission
and exported one Microlink dump. Neither observation establishes repeatability
or continuous operation.

The staging command only creates a new external source bundle:

```sh
python3 -I -B backend/nut/stage_hidapi_candidate.py \
  --hidapi-source /path/to/hidapi-hidapi-0.15.0 \
  --output-dir /path/to/new-external-bundle
```

It does not apply the patch, configure, build, install, launch or grant consent.

### Extracted Coupled Replay

The extractor checks seven source pins and preserves fourteen function bodies,
the forbidden-option list, three control-byte definitions and the upstream GPL
notice verbatim. Thirteen extractor tests pass, including case-insensitive
filesystem aliases and symlink rejection. Source/output overlap is checked by
existing ancestor identity, not by path spelling alone.

The replay uses the real pinned NUT headers (frame size 256, payload size 253),
production prepare/finish and no generic test-binding API. It checks exact
64-byte reports, zero padding, STOP/INIT/NEXT, authentication checksum, one
probe, admission failures, partial writes, stop/deadline, reentrant finish and
no fallback. Thirty-two isolated process scenarios pass with ASan/UBSan and
reachability counters; the coordinator repeated them. Symbol/dependency audit
precedes execution, and all HIDAPI entrypoints are fake. Authentic macOS
HIDAPI is neither linked nor run by this replay.

The two supervisor cases wait until the admitted fake read is active. Both
finish as CANCELLED: cooperative return code 0 with close/exit/finish recorded
once, or blocked return code -9 with no cleanup observed. A private fake-only
sidecar records callbacks because the existing supervisor drains, but does not
capture, output after TERM. Reaping a killed child does not prove hardware
cleanup or electrical safety; neither case qualifies measurements.

```sh
python3 -I -B backend/nut/replay_hidapi_nut.py \
  --nut-source /path/to/pinned-patched-source \
  --hidapi-source /path/to/hidapi-hidapi-0.15.0 \
  --output-dir /path/to/new-private-replay
```

The default now uses the repository's pinned test-only configuration header,
not a private generated NUT config. It selects the USB1 branches and Darwin
declarations for this fake executable; it is not a production configuration
or platform-capability probe. Five configuration-selection tests pass.
Author and independent review compared the portable and historical private
config runs: all 32 stdout/stderr pairs and both supervisor results match.
The coordinator also passed 32+2 with freshly reconstructed public NUT sources.

An optional `--nut-config` retains the exact historical private pin
`2efcc93b54fc93fc77f8e160f8639253b7746a2fd47a6cfc57a3030657a5c04b`
or accepts the exact public fixture pin; it cannot select arbitrary config.
The private file is not needed or distributed. Source/config/header pin drift
rejects before compilation; no inputs are downloaded automatically. Output
contains local provenance paths and remains private, not a publishable artifact.
The full receive decoder is explicitly stubbed, and the real NUT main/signal
handler is not executed. Independent review repeated all 32+2 cases and caught
three private mutations: altered report ID, bypassed probe budget and missing
cleanup sidecar marker. These results are not an end-to-end driver qualification.

#### Preparing Public Source Inputs

Use a new, external, clean NUT checkout at commit
`73c4502191d025e35122463986a80c676e734b04` and the external HIDAPI 0.15.0
source release. Do not use a working tree containing other changes. Apply
these files from `backend/nut/` in order, checking each before application:

1. `nut-guarded-monitor-73c4502.patch`
2. `nut-hid-fallback-validation-73c4502.patch`
3. `nut-guarded-lifecycle-write-73c4502.patch`
4. `nut-usb-async-state-73c4502.patch`
5. `nut-usb-guard-deadline-73c4502.patch`
6. `nut-usb-owner-retention-73c4502.patch`
7. `nut-guarded-startup-stop-73c4502.patch`
8. `nut-guarded-reopen-stop-73c4502.patch`
9. `nut-guarded-probe-attempts-73c4502.patch`
10. `nut-hidapi-observe-73c4502.patch`

Use `git -C /path/to/new-nut-checkout apply --check /absolute/path/to/patch`
and then the same command without `--check`, stopping on any failure. The
original-base `nut-guarded-monitor.patch` is not part of this stack. No
autoreconf, NUT configure/build, staged authentic HIDAPI implementation or
private config is needed for the extracted replay above. Its seven source
pins reject an incorrect stack. A local reconstruction from the base Git
object plus these ten public patches matched all seven pins before replay.
This verifies the local recipe, not a fresh network download or CI execution.

### Whole-NUT Fake Replay

The separate `replay_hidapi_full_driver.py` compiles whole pinned main, APC,
maps, dstate and common translation units with the production core, native
binding and checked parser. HIDAPI entrypoints and input reports are synthetic;
authentic HIDAPI, libusb and Apple device frameworks are not linked. It does
not replace NUT's receive decoder, field mapper, data tree or signal handler.
Observers delegate to real update, dump, dataok and cleanup bodies.

Historical result on the earlier private-input setup: coordinator and
independent reviewer each passed these six process scenarios (6+6). This is
separate from the later public-input replay result below.

| Synthetic scenario | Observed result |
|---|---|
| Updated metrics | Real decoder publishes charge 76 and runtime 590, replacing artificial initial values 75 and 600; three updates and one dump, exit 0 |
| Metadata only | Exit 0, three DATAOK calls and one dump, but neither charge nor runtime exists; success is not a qualified measurement |
| Corrupted checksum | Exit 1, no metric or dump; one close and HID exit |
| SIGTERM during admitted fake read | Real NUT signal flag set; no STOP/INIT/NEXT after READY, no dump, ordered cleanup once; exit 1 |
| Invalid HID descriptor | Exit 1 before protocol reads/writes; early cleanup hook closes/exits once without ordinary driver cleanup |
| Guard expires after INIT | Synthetic native clock reaches the 20-second budget with a page queued; zero reads, NEXT, dump or cleanup STOP; close/exit once |

The fake clock is confined to the native binding; NUT's other clocks are real.
The positive case reads 49 reports and sends 48 NEXT requests. Timeout read
counts in negative cases can vary with scheduling and are not exact oracles.
SIGTERM is raised by the owned fake child itself; this covers the real NUT
handler, not an operator's keyboard action. Existing supervisor cancellation
tests remain separate. All results retain `data_qualified=false`.

Four Python mock tests cover forwarding the previously audited binary digest
unchanged, rejecting a post-signal write, duplicate cleanup and wrong event
order. Luna authored the artificial frames and these tests; Sol wired the
whole-driver replay, with independent Sol review and coordinator execution.
The review corrected digest auto-admission and strengthened the signal oracle.
The first full run correctly decoded both values but failed an incorrect
two-update expectation: main also calls update during initialization before
the two dump-loop updates. Only the test expectation changed; NUT did not.

The default whole-driver replay now uses public, synthetic pinned config and
version headers and compiles 16 translation units, including `state.c`,
`str.c`, `upsconf.c` and `parseconf.c` under the same explicit test OS guards
and ASan/UBSan. It uses no private NUT archives. The four new translation
units replace only the archive members identified by the prior link map; the
original six scenario oracles and production NUT sources are unchanged. Header
dependency files attest that the staged config header was selected, and the
link map is audited. Input paths containing whitespace, `$`, backslash, `#`
or `:`, and symlinked inputs are rejected. This closes portability for the
local macOS arm64 recipe only; it is not CI, release, Windows or Linux
qualification.

The default command builds and audits the full fake, then executes pure frames;
it does not execute the six whole-NUT scenarios. `--compile-only` compiles and
audits without executing any C code. Use `--run-fake` explicitly for the six
synthetic scenarios:

```sh
python3 -I -S -B backend/nut/replay_hidapi_full_driver.py \
  --nut-source /path/to/pinned-patched-source \
  --hidapi-source /path/to/hidapi-hidapi-0.15.0 \
  --output-dir /path/to/new-private-full-replay \
  --run-fake
```

Omit `--run-fake` for the default pure-frames-only execution. Replace it with
`--compile-only` for compile-and-audit with no C execution. The explicit legacy
`--nut-build` path remains available with strict pins and no public-input
fallback; it was not rerun for this result.

This is a local test harness, **not an OS sandbox**. Closed argv and a minimal
environment exclude configuration-file, background and socket paths; explicit
test seams suppress privilege lookup/change and deny process, network and
other side effects. The local review also confirmed `/proc` absent. General
open/fopen are not globally interposed. Symbol/dependency and link-map audits
precede execution; Darwin symbol suffixes are normalized, and both common and
common-version are rebuilt with the guards instead of using their unguarded
archive members. ASan/UBSan instrument the rebuilt translation units. The
synthetic config needed corrections for `EXEEXT` and `va_copy`; regressions
were added without changing NUT, the six scenario oracles or the deadline
helper. Symbolizer warnings occurred; this is not a warning-free release
build. Bounded supervision uses one owned child at a time, 30-second timeout,
2-second grace and a 1 MiB output cap. Test binaries are mode 0600, including
after failure. The runner has 28 Python contract tests; the local backend
Python suite passed 232/232. Latest local replay passed pure frames and all six
scenarios. An independent reviewer audited the resulting artifacts but did
not perform a second C replay. CI and release execution remain NOT_RUN. Local
manifests contain private provenance paths and must not be published unchanged.

The fixture's authentication-required bit is zero: the full authenticated
firmware exchange is **not covered**. Results retain `data_qualified=false`;
voltage, W, VA, load and energy are not qualified by these artificial fields.
SIGINT/SIGQUIT runtime, real shared access, routing, queue behavior and
electrical effects remain open. No app, widget or live-profile activation
follows from this replay.

## Behavior Under Test

The adapter uses one owner and one report of staging, not another reader thread.
It enforces a nonrenewable monotonic guard, one opening attempt, exact 64-byte
output, no automatic write retry, and checks after host calls and before byte
delivery. Input uses 65 bytes of capacity to detect an oversized tunnel report;
unrelated report IDs are filtered without publishing fallback measurements.
Flush is bounded. Reset/reopen and standard-HID fallback are unavailable.
An unconfirmed close retains its owner and prevents reuse rather than retrying.

The standalone adapter tests do not exercise NUT main or protocol policy.
The extracted coupled replay adds protocol allowlist, one-probe and synthetic
supervisor checks. The separate whole-NUT replay adds the six bounded paths
above, not general firmware or hardware coverage. The adapter alone is not a
safety qualification.

## Reproduction

Use the ABI header from the documented ninth guarded NUT candidate, based on
`73c4502191d025e35122463986a80c676e734b04`. The runner requires its exact SHA-256:
`b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29`.
No header or NUT source is downloaded automatically.

```sh
python3 -I -B backend/nut/replay_hidapi_shared_transport.py \
  --abi-header /path/to/candidate/drivers/apcmicrolink-usb.h
```

The macOS runner uses `/usr/bin/clang`, strict warnings, ASan and UBSan; compiler
and test execution have separate timeouts. It checks compiler header inclusion,
runs nine synthetic test groups and an unbound build without the test macro,
then checks that unbound binary with `nm` and `otool`. No test runs an UPS
driver or accesses a device. Header mismatch stops before compilation.

Coordinator reproduction: nine groups and unbound build PASS; the earlier
header-mismatch check rejected before compilation. Independent core review
passed ten lifecycle counterexamples, including stop/deadline after open,
reentrant close during layout acquisition, and report I/O before admission.
This is PASS_STATIC_FAKE only, not a hardware GO.

### Checked Parser And Native Module

```sh
python3 -I -B backend/nut/replay_hid_descriptor_checked.py \
  --nut-source /path/to/candidate/drivers
python3 -I -B backend/nut/replay_hidapi_native.py \
  --hidapi-source /path/to/hidapi-hidapi-0.15.0 \
  --abi-header /path/to/candidate/drivers/apcmicrolink-usb.h \
  --link-native-only
```

Parser: nine current synthetic groups pass. Three coordinator counterexamples
and 18,172 bounded property calls, plus 48 independent checks, 117 out-of-mask
flag cases and a mixed report-ID case, are retained baseline evidence and were
not rerun with this parser revision.
Retained native-binding baseline: eight groups and 16 independent
scenarios pass with synthetic HIDAPI symbols and the checked parser/core.
In that earlier native-binding baseline, the authentic Darwin backend was
compiled and linked only; that artifact was NOT_RUN. This historical result
does not describe later observation sessions. Independent static/fake review
is closed for the baseline scope.

The parser requires one unambiguous FF86:FD Input Main and FF86:FC Output Main,
each with 63 eight-bit elements, offset zero, Data attributes, a nonzero ID and
504 total payload bits for that ID/direction. Same ID across directions is
allowed. Every Main item must have a nonzero Report ID. Tunnel Input attributes
remain restricted by local mask `0x17F`; Output and Feature by `0x1FF`. For an
unrelated Input Main only, reserved bit 7 is tolerated and its raw value is
retained, provided that Main's local Usage list contains neither FF86:FD nor
FF86:FC. HID 1.11 reserves Input bit 7 (USB-IF §§ 6.2.2.4, 6.2.2.5 and 6.2.2.8,
<https://www.usb.org/sites/default/files/hid1_11.pdf>). String Index local
items with 1, 2 or 4 data bytes are ignored as descriptive metadata; they do not
trigger string lookup or alter Usage state. String ranges and other unsupported
constructs remain rejected, including in unrelated reports. This is a
compatibility exception for a nonzero reserved Input bit, not a general HID
conformance claim or qualification of any real UPS descriptor. The parser is
not a general HID conformance validator.
Long items, Push/Pop, usage ranges and other unsupported constructs
are rejected, including in unrelated reports. Limits are explicit: 6,144
descriptor bytes, depth 10, 500 Main items, 64 local usages and 65,536 bits per
report/direction. This is not a general HID conformance validator. The actual
UPS descriptor may not belong to the supported subset.

The native descriptor read has one extra byte of capacity and rejects lengths
above the parser limit, because HIDAPI can silently truncate to the buffer.
Close and disposal are separate; disposal cannot close an owned handle.

### P1 One-Shot Session

```sh
python3 -I -B backend/nut/replay_hidapi_session.py \
  --hidapi-source /path/to/hidapi-hidapi-0.15.0 \
  --abi-header /path/to/candidate/drivers/apcmicrolink-usb.h
```

Prepare consumes the process's sole attempt even on failure, allocates the
native binding and starts the guard without HID initialization or device I/O.
Opening remains a separate explicit call. Finish marks terminal, closes only
after host calls return, and disposes only after ownership can be released.
No reset, rebind or retry of a failed disposal is exposed in production.

Sixteen isolated author scenarios and 32 independent scenarios pass, including
default OFF, incompatible macros, invalid configuration, reentrant stop/finish,
no rearm and no I/O after termination. The coordinator repeated the sixteen
scenarios and existing core/native groups (nine/eight) on the final pin.
A counterexample found a write after reentrant finish during a callback;
the core now rechecks terminal state after stop and clock callbacks. Regression
cases cover both boundaries. All executions used synthetic HIDAPI symbols.

RETAINED may be permanent when finish reenters an active native stop/clock
callback: the owner/handle is deliberately kept, with no later protocol I/O,
rearm or forced cleanup. Passing these cases proves retention, not guaranteed
release. External process supervision and NUT integration remain unqualified.

## Remaining Gates

HIDAPI [0.15.0](https://github.com/libusb/hidapi/releases/tag/hidapi-0.15.0)
was checked as the current stable release for this investigation. Its sources
and notices are pinned external build inputs, not bundled or deployed.
Its [Darwin backend](https://github.com/libusb/hidapi/blob/hidapi-0.15.0/mac/hid.c)
requires explicit nonexclusive opening after initialization, truncates reads to
the supplied capacity, and can discard old queued reports without an exposed
loss counter. Its blocking calls are not hard operating-system deadlines.

The local macOS arm64 recipe is portable across the public-source reconstruction
described above; CI/release reproduction and other operating systems remain
NOT_RUN. Remaining gates include the operational profile and
application/supervisor integration, full authenticated-exchange coverage, and
any live qualification. Offline evidence above is bounded to its listed paths
and must not be treated as a general integration qualification.
The adapter now selects a unique preliminary identity, opens once, obtains the
layout through a separate post-open host operation, and only then admits
protocol I/O. `opened` and `admitted` are separate states, with terminal cleanup
on validation failure. In the synthetic baseline, the native layout operation
was exercised against synthetic HIDAPI symbols. H02 later reached the parser
on the local device and returned `UNSUPPORTED`; H03 passed it in one
observation. This does not qualify repeatability or continuous operation.
Enumeration information must not be treated as if it contained report IDs.

An isolated reproduction of the pinned NUT parser found that its 8-bit offsets
misreport a 63-byte payload as 32 bytes, and that an incomplete descriptor can
retain a partial non-null result. Its report-length array also merges directions.
The existing parser and its unchanged callback are therefore not an admission
gate. A checked, namespaced derivative for a deliberately bounded descriptor
subset is now implemented separately; the legacy ABI remains unchanged.
Output routing, real framing, shared access, internal queue loss and physical
behavior remain OPEN. The single supervised communication observation above
does not qualify repeatability or continuous operation. `data_qualified` is
never promoted by this adapter or replay. No UPS control commands are enabled
by this increment.

The primary USB-IF HID 1.11 reference is verified; a local archive is retained
separately from the repository ([USB-IF HID 1.11](https://www.usb.org/sites/default/files/hid1_11.pdf)).

The C implementations, headers and C fixtures are GPL-2.0-or-later; the Python
runners are original MIT material. The pinned NUT header is supplied externally
with its original notices. See [third-party notices](../THIRD_PARTY_NOTICES.md).
