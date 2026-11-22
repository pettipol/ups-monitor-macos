# NUT Qualification Artifacts

**2026-11-04 historical source reconstruction:** the
[source-only procedure](../../docs/PRODUCTION_SOURCE_RECONSTRUCTION.md)
reconstructs the 190-file production checkpoint with the corrected supervisor,
without adding operational replay hooks, compiling or opening hardware.
Four cancellation tests and two altered-input rejection cases passed, and all
190 output hashes matched the retained reference. Generated headers and static
libraries remain outside this procedure; it is not a complete native build or
qualification of the latest upstream driver.

**2026-10-28 native cleanup:** the isolated operational cleanup patch permits
only the guard-authorized, owner-bound final F7 report after Stop, consuming
one attempt before HIDAPI. The true adapter passes synthetic regression and
negative cases; legacy inputs remain unchanged. Authentic macOS HIDAPI was
compiled/linked only, never executed in this offline qualification. Driver
Stop races and real hardware qualification remain open. See
[the reproducible cleanup test](../../docs/NATIVE_CLEANUP_TESTS.md).

**App-session offline components:** the private workspace and app-controlled
capture adapter are documented in [APP_CONTROLLED_CAPTURE](../../docs/APP_CONTROLLED_CAPTURE.md).
These components are not an end-to-end application or hardware qualification.

**2026-10-26 pacing:** one bounded H07 session on an SMC1500I completed
120 seconds with 24 samples and renewed field timestamps. Separately, the
public adapter's bounded synthetic OFF/ON replay passed. Neither result
qualifies daily use or widget refresh. See
[the pacing recipe](../../docs/NUT_CONTINUOUS_PACING.md). Historical entries
below are retained as written.

**2026-10-26 experimental continuous diagnostics:** a separate default-off
[diagnostic patch and synthetic host](../../docs/NUT_CONTINUOUS_DIAGNOSTICS.md)
distinguish protocol reception, cache admission, field provenance and cleanup.
Local validation passed 10 diagnostic tests covering 24 fake executions,
7 staging tests and OFF/ON plus non-continuous compilation checks. These are
offline results; the real H05 session still lost communication after about
35 seconds without renewing its initial measurements. Private C formatter
fault cases and continuous hardware qualification remain open. The dedicated
`replay_continuous_diagnostics.c` does not replace the historical replay host.
No installed driver, service or new hardware-test profile is created.

**2026-10-24 one-shot milestone:** one local APC SMC1500I HIDAPI shared-driver
observation completed normally with `-d 1` in 8.45 s; the checked descriptor
parser passed and Microlink variables were exported. The dump included charge
and estimated runtime, battery voltage/temperature, input/output voltage and
frequency, output current, load, nominal W/VA, and driver-derived W/VA. This
records field availability only; observed values are not reproduced here and
none are metrologically qualified. The existing app reader imported the
archived bundle as `ArchivedUnqualified`, with W/VA marked driver-derived.
That import is separate from continuous monitoring or a live widget. The
one-shot admission is consumed; this milestone does not establish a reusable
permission or a continuously qualified profile. The experimental energy
counter has unknown units and is ignored by the standard decoder; do not label
it Wh or kWh. No firmware, calibration, continuous operation, or app live path
is qualified.

The [shared HID adapter candidate](../../docs/NUT_HIDAPI_SHARED_CANDIDATE.md)
now includes a guarded adapter, a bounded checked descriptor parser, and an
unregistered HIDAPI 0.15.0 host binding. Synthetic tests exercise the combined
path.
P2 adds a separate default-off NUT observation target. The pre-observation
build checkpoint was link-only; H02 later launched and stopped at the parser,
and the H03 one-shot observation is recorded above.
There is no operational profile, installed backend, or hardware qualification.
Independent static/fake review is closed for the baseline modules and the
separate default-off prepare/finish increment P1; M1 remains PARTIAL.
P1 passed 16 isolated author scenarios and 32 independent scenarios; the
coordinator repeated the 16 and core/native regressions. Retained core P1 pin:
`3753ac1d27f8bee542e4fecc2f901b68023dfc0eeb3bb2872ff655bef289e766`.
Permanent RETAINED ownership is possible after reentrant stop/clock cleanup;
no I/O or rearm follows, but guaranteed release is not qualified.
Core baseline: nine groups plus ten independent lifecycle counterexamples.
Checked parser: nine current synthetic groups pass. Three coordinator
counterexamples, 18,172 bounded property calls, 48 independent checks, 117
out-of-mask flag cases and a mixed report-ID case are retained baseline evidence;
they were not rerun with this parser revision. The retained native-binding baseline had eight groups plus 16 independent
scenarios. The checked-parser C pin is
`7db55b980569f8385196d10c30a966b0e78f1f9266c624f05a3c2459d13ebc85`.
Its local subset requires nonzero Report IDs on every Main item. For tunnel
Input, the attribute mask remains `0x17F`; for unrelated Input only, reserved
bit 7 is tolerated and preserved for compatibility, while other unsupported
bits are rejected. Output/Feature retain mask `0x1FF`. HID 1.11 reserves Input
bit 7 (USB-IF §§ 6.2.2.4, 6.2.2.5 and 6.2.2.8:
https://www.usb.org/sites/default/files/hid1_11.pdf); this is a compatibility
exception for a nonzero reserved Input bit, not a general HID conformance claim
or qualification of any real UPS descriptor. String
Index local items are accepted as descriptive metadata only; no string lookup
or state is retained. This parser is not a general HID conformance validator.
In the earlier native-binding baseline, authentic macOS HIDAPI was compiled
and linked only; that baseline artifact was NOT_RUN. This historical result
does not describe later observation sessions. Primary USB-IF HID 1.11 reference verified;
the local archive is retained separately from the repository ([USB-IF HID 1.11](https://www.usb.org/sites/default/files/hid1_11.pdf)). P2 build passes with no libusb dependency; independent exact-source
boundary review passes 47 cases and catches six executable mutations plus a
late-gate static mutation. Those boundary tests use callback mocks.
A subsequent extracted-protocol replay uses the real core/session, native
binding and checked parser with fake HIDAPI: 32 isolated cases and two owned
child cancellation cases pass, repeated by the coordinator. The extractor has
13 tests, including case-insensitive path aliases. The extracted replay now
defaults to a pinned public test-only config:
five selection tests pass, and portable/private-config results match32+2.
A fresh reconstruction from the public base and ten patches also passes32+2
without configure or private build inputs. The existing libusb candidate is
unchanged. See the linked scope document for the recipe and limits.

A separate whole-NUT replay now has a portable local recipe: its default uses
public synthetic config/version headers and recompiles four additional NUT
translation units under the same test guards, without private archives. The
explicit `--run-fake` mode has six synthetic scenarios; the default executes
pure frames only, while `--compile-only` executes no C code. The runner has 28
Python contract tests. The latest local replay passed all six scenarios and
pure frames; this remains synthetic evidence, not an installed backend or
application integration. HIDAPI symbols are fake, native hardware is NOT_RUN,
and no measurements are qualified. The harness is not an OS sandbox and does
not cover the full authenticated exchange. Operational profile, application
integration and real hardware qualification remain pending; see the linked
candidate document for exact commands and limitations.

The H01-DIAG-01 delta adds a closed stage/reason/parser-status snapshot to the
shared admission seam. The parser status distinguishes `not-run` from `ok` and
preserves the parser's existing rejection class. A first refusal is copied
before cleanup can release the native binding; successful admission stays
`none`, and later I/O or cleanup does not create an admission error. The patch
prints only fixed tokens. At the author synthetic checkpoint on 2026-10-24,
independent review was pending; that is a historical status. Later H02 emitted
`stage=layout reason=parser-rejected parser=unsupported`; H03 succeeded, so it
did not exercise a failure diagnostic. This records one observed failure
route; it does not prove every token or qualify the patch across other NUT
revisions. Author synthetic checks on 2026-10-24 passed: shared
transport 11 cases, native binding 9 groups, session 16 scenarios, whole-NUT
fake replay 6 scenarios plus pure frames, replay contract 28 tests and stager
8 tests. These synthetic results do not establish that every failure token was
emitted or qualify continuous operation.

Original base revision: `1a8369f8688443a500527059167d2f66ca27535f` of
[Network UPS Tools](https://github.com/networkupstools/nut). These are source
qualification artifacts, not an installed service or a production backend.
The separately named guarded rebase targets only
`73c4502191d025e35122463986a80c676e734b04`. Choose the artifact for its exact
base; the two guarded patches are alternatives, not a stack. The separate HID
validation patch targets that same merged pin and overlaps the USB driver
source. Its [combined source/build qualification](../../docs/NUT_COMBINED_CANDIDATE.md)
with the merged guarded patch is offline only; neither live execution nor a
stack with the original-base guarded patch is qualified.
The separate [lifecycle/write candidate](../../docs/NUT_LIFECYCLE_WRITE_CANDIDATE.md)
adds a third, incremental patch to that combined baseline. It is still offline
only, with cooperative termination partially qualified and concurrency open.
The fourth incremental [async-state patch](../../docs/NUT_ASYNC_STATE_CANDIDATE.md)
synchronizes three shared scalar flags. It does not qualify the complete
listener lifecycle, cancellation, or real hardware.
The fifth incremental [observation-budget patch](../../docs/NUT_GUARD_DEADLINE_CANDIDATE.md)
adds one nonrenewable guarded IN budget. It is cooperative, not a hard process
deadline or hardware qualification.
The separate [lifecycle observation](../../docs/NUT_LIFECYCLE_OBSERVATION.md)
executes selected unchanged candidate functions with deterministic local mocks.
It observes pending-transfer teardown gaps; it does not patch or qualify them.
The sixth incremental [ownership candidate](../../docs/NUT_OWNER_RETENTION_CANDIDATE.md)
retains unresolved transfer generations and gates close/reopen and synchronous
fallback. Its public integration tool only extracts source and a synthetic
fixture; it never compiles or runs them. Real USB and process exit remain open.
The seventh incremental [startup/stop candidate](../../docs/NUT_GUARDED_STARTUP_STOP_CANDIDATE.md)
adds cooperative transmission checkpoints and checks guarded open admission.
Its separate synthetic replay is not NUT main, real libusb or electrical
qualification. Historical patch and replay pins remain unchanged.
The eighth incremental [reopen/stop candidate](../../docs/NUT_GUARDED_REOPEN_STOP_CANDIDATE.md)
adds cooperative stop checkpoints around reopening and async startup, preserving
pending ownership. Its extract-only tool reuses the ownership fixture with
explicit test interpositions. Consult its separate evidence and remaining gates;
it does not qualify a hardware session or the driver's retry policy.
The ninth incremental [probe candidate](../../docs/NUT_GUARDED_PROBE_CANDIDATE.md)
adds an opt-in process-wide STOP/INIT attempt budget and disables reopen.
It is under offline review; no operational profile or hardware session is
approved by this patch.

| File | Scope |
|---|---|
| `nut-upsc-completion.patch` | Reject interrupted or mismatched client variable lists |
| `nut-guarded-monitor.patch` | Experimental opt-in apcmicrolink USB restrictions; hardware untested |
| `nut-guarded-monitor-73c4502.patch` | The same restrictions rebased onto merged upstream fixes; hardware untested |
| `nut-hid-fallback-validation-73c4502.patch` | Offline candidate for truncated HID fields and wall-clock rollback; combined merged-guard builds checked separately; hardware untested |
| `nut-guarded-lifecycle-write-73c4502.patch` | Incremental patch over merged guard/HID: exact write completion and partial cooperative cancellation; not hardware-qualified |
| `nut-usb-async-state-73c4502.patch` | Incremental patch over lifecycle/write: three mutex-protected scalar flags; broader lifecycle remains open |
| `nut-usb-guard-deadline-73c4502.patch` | Fifth incremental patch: one monotonic guarded IN budget; lifecycle and real hardware remain open |
| `nut-usb-owner-retention-73c4502.patch` | Sixth incremental patch over the five-patch stack: generation ownership and backend context hold; not hardware-qualified |
| `nut-guarded-startup-stop-73c4502.patch` | Seventh incremental patch over ownership: cooperative stop checkpoints and guarded open admission; not hardware-qualified |
| `extract_guarded_startup_stop.py`, `test_guarded_startup_stop.c`, `test_extract_guarded_startup_stop.py` | Pinned source extraction, synthetic replay and extraction contracts; no UPS driver or hardware execution |
| `nut-guarded-reopen-stop-73c4502.patch` | Eighth incremental patch over startup/stop: cooperative reopen and async-start checkpoints; not hardware-qualified |
| `nut-guarded-probe-attempts-73c4502.patch` | Ninth incremental patch over reopen/stop: opt-in process-wide handshake budget and no reopen; offline candidate, not hardware-qualified |
| `extract_guarded_reopen_stop.py`, `test_guarded_reopen_stop.c`, `test_extract_guarded_reopen_stop.py` | Pinned extract-only tool, ownership-fixture wrapper and synthetic contracts; extraction never compiles or runs C |
| `extract_usb_owner_retention.py`, `test_usb_owner_retention.c`, `test_extract_usb_owner_retention.py` | Pinned extract-only integration fixture and synthetic Python contracts; no driver, compiler or C execution by the extractor |
| `replay_usb_guard_deadline.py`, `test_usb_guard_deadline.c`, `test_replay_usb_guard_deadline.py` | Pinned helper/callback experiment and separate static call-site checks; no driver or hardware execution |
| `replay_usb_lifecycle_observation.py`, `test_usb_lifecycle_observation.c`, `test_replay_usb_lifecycle_observation.py` | Source-extracted start/stop/callback/close observation with local mocks and separate Python runner contracts; not real thread scheduling or driver execution |
| `replay_usb_async_state.py`, `test_usb_async_state.c`, `test_replay_usb_async_state.py` | Pinned extracted-source concurrency experiment and synthetic runner contracts; no driver or hardware execution |
| `check_upsc_completion.py` | Actual client test with an ephemeral synthetic loopback server |
| `test_guarded_policy.c` | Compiled policy-header tests with fake callbacks, no libusb |
| `test_guarded_source_paths.py` | Static regression checks on selected patched NUT call sites; never runs a driver |
| `check_guarded_merged_rebase.py` | Pinned-source preservation checks and in-memory mutations for the merged rebase; no driver execution |
| `replay_hid_fallback.py` and `test_hid_fallback_replay.c` | Offline extraction of hash-pinned fallback and publication mapper, plus a test-only reset wrapper; recording stubs, not a full driver |
| `test_replay_hid_fallback.py` | Seven synthetic source-fence checks; no compiler or hardware |
| `replay_hid_validation.py` and `test_hid_fallback_validation.c` | Exact-pin pristine/candidate extraction and synthetic fallback checks; generated excerpts and recording stubs, not a driver |
| `test_replay_hid_validation.py` | Python source, candidate-hash and output-fence checks; no driver or hardware |
| `replay_usb_write_completion.py`, `test_usb_write_completion.c` | Pinned send function and actual wrapper, static fake transfer; no libusb or driver execution |
| `replay_guarded_dump_signals.py`, `test_guarded_dump_signals.c` | Pinned candidate helpers, baseline POSIX model and owned synthetic children; not NUT main/cleanup execution |
| `test_replay_usb_write_completion.py`, `test_replay_guarded_dump_signals.py` | Seventeen Python source/path/output/linkage-fence contracts, without C execution |
| `process_deadline.py` | Offline qualification helper: bounded child process, private output, no automatic driver launch |
| `observation_receipt.py` | Pure, metadata-only JSON bridge from original supervisor capture hashes/times; no file I/O or live activation |
| `test_observation_receipt.py` | Synthetic schema, type, timestamp and qualification-boundary tests |
| `operator_stop.py` | Main-thread SIGINT adapter for the bounded helper; cooperative local cancellation, no CLI, app integration or driver profile |
| `test_process_deadline*.py` | Synthetic subprocess and lifecycle regressions; never execute a UPS driver |
| `operator_session.py` | One-shot operator CLI with an empty immutable profile registry; no operational driver profile or app integration |
| `test_operator_session.py` | Closed CLI contract and owned Python-child cancellation tests; no UPS access |

The original completion and guarded patches affect disjoint files and apply
to the original pristine base revision. Completion-client evidence is not
transferred to the rebased driver or a new client revision. The separate HID
validation patch overlaps the USB driver source; only the exact merged-guard
combination linked above has separate offline source/build evidence.
Read [client evidence](../../docs/NUT_CLIENT_COMPLETION.md) and
[driver limitations](../../docs/NUT_GUARDS.md) before interpreting test results.
The [merged rebase evidence](../../docs/NUT_GUARDS_MERGED.md) is separate from
the original guard qualification. Also review the
[upstream status](../../docs/NUT_UPSTREAM_STATUS.md): the original base lacks
the merged fallback correction; the new base includes it, but retains two
known synthetic residuals and is not hardware-qualified.
The separate [HID fallback replay](../../docs/NUT_HID_REPLAY.md) compares the
original base, corrective commit and merged master using exact source pins.
Those three historical C replays passed their expected comparisons; known
residuals remain. The new [HID fallback validation candidate](../../docs/NUT_HID_VALIDATION.md)
is a separate extracted-source experiment. The later combined build is not
integrated into the application backend. Recorded status calls do not emulate final NUT
dstate inference.
No test here demonstrates physical UPS compatibility, USB coexistence, or
correct electrical measurements.

Patch context lines intentionally contain their unified-diff leading spaces.
Check source whitespace in the patched NUT checkout with `git diff --check`;
do not strip whitespace from the exported patch data. In this application
checkout use `git diff --check -- . ':(exclude)backend/nut/*.patch'` in addition
to `git apply --check` against the pinned NUT source.

## License Boundary

The original completion and guarded patches are derived from NUT source at
`1a8369f8688443a500527059167d2f66ca27535f`; the guarded rebase and separate HID
fallback validation patch target
`73c4502191d025e35122463986a80c676e734b04`. The lifecycle/write patch layers
on that merged guard/HID combination; the async-state patch layers on the
lifecycle/write candidate and changes only `drivers/apcmicrolink-usb.c`.
The observation-budget patch adds changes to `drivers/apcmicrolink-usb.c`,
`drivers/apcmicrolink-usb.h` and `drivers/apcmicrolink.c` over that exact stack.
The ownership-retention patch adds changes to `drivers/apcmicrolink-usb.c`,
`drivers/apcmicrolink-usb.h`, `drivers/libusb1.c` and `drivers/nut_libusb.h`.
The startup/stop patch extends the six-patch ownership candidate to a
seven-patch stack without replacing historical evidence; its exact changes
and limits are documented separately. The reopen/stop patch changes only
`drivers/apcmicrolink-usb.c` over that seven-patch stack. The probe-attempts
patch changes `drivers/main.c`, `drivers/apcmicrolink.c` and
`drivers/apcmicrolink-usb.c` over the eight-patch stack; main rejects a missing
guard flag before attempting any peer-driver query.
All eleven patch artifacts follow
**GPL-2.0-or-later** according to the affected upstream source headers. The
guarded policy C test and HID fallback validation C test carry their own GPL
SPDX identifiers. The HID fallback replay C test is also GPL-2.0-or-later.
The new signal and USB write C harnesses likewise carry GPL-2.0-or-later SPDX.
The async-state C harness also carries GPL-2.0-or-later SPDX; its Python runner
and synthetic runner tests are original MIT material.
The observation-budget C harness also carries GPL-2.0-or-later SPDX; its
Python runner and runner-contract tests are original MIT material.
The lifecycle-observation C harness is GPL-2.0-or-later; its Python runner and
synthetic runner tests are original MIT material.
The ownership-retention C fixture is GPL-2.0-or-later; its Python extractor
and synthetic contract tests are original MIT material.
The startup/stop C fixture is GPL-2.0-or-later; its Python tool for extraction
and replay, and its synthetic contracts, are original MIT material.
The reopen/stop C wrapper is GPL-2.0-or-later and reuses the existing ownership
fixture; its Python extract-only tool and synthetic contracts are original MIT.
Generated excerpts preserve upstream copyright/GPL notices and are not checked
in. None of these artifacts is relicensed by the application's MIT license.
The Python replay runners, source-fence tests and merged-rebase checker are MIT
licensed. No generated NUT fragments are stored in these Python files.

The completion patch changes `clients/upsc.c` and `clients/upsclient.c`.
Their upstream headers list Russell Kroll (1999 in `upsc.c`; 2002 in
`upsclient.c`), Arnaud Quette (2012), Arjen de Korte (2008), and Jim Klimov
(2020-2026), and state GPL version 2 or (at the recipient's option) any later
version. The guarded patch changes the experimental `drivers/apcmicrolink.c`,
whose upstream header lists Lukas Schmid and Nicolai Brogaard, each copyright
2026, and states the same GPL terms. The guarded rebase also records the
pinned source revision and provenance. The HID validation patch changes
`drivers/apcmicrolink-usb.c`, whose upstream header lists Lukas Schmid and
Nicolai Brogaard (2026) and states the same GPL terms; its patch header records
the merged pin and NUT provenance. The completion patch itself has no
standalone SPDX/provenance header; this adjacent notice records its source
files, observed attribution and license basis. The absence of that header
alone is not a finding of legal noncompliance.

`LICENSE-GPL2` is the complete GPL version 2 text copied from the pinned NUT
source checkout. Its SHA-256 is recorded in `THIRD_PARTY_NOTICES.md`.
`COPYING.NUT` is NUT's licensing overview: it describes license families in
the full upstream tree and is not itself the complete GPL text. This
repository contains eleven patch artifacts and synthetic C tests, not the
complete NUT source tree or NUT/libusb binaries. The standalone HID fragment
replay is not a full-driver build; the separate combined build evidence does
not establish driver runtime or hardware behavior.

The original Python synthetic qualification helpers and tests are identified
as application/MIT material. They do not include NUT source and do not
authorize or perform hardware testing.

See [process supervision limits](../../docs/PROCESS_DEADLINE.md); these helpers
are not part of the app's read-only NUT transport and do not authorize hardware
tests or qualify a caller's argument list.

## Public-source continuous replay (2026-10-26)

The fake-only continuous diagnostic replay now has an explicit public reconstruction
recipe. See [the recipe](../../docs/CONTINUOUS_PORTABLE_REPLAY.md) and
[offline qualification and limits](../../docs/CONTINUOUS_OFFLINE_QUALIFICATION.md).
Default mode compiles and audits only; genuine device execution is not available
through this runner. The legacy continuous replay remains a separate target.
