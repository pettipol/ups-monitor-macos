# NUT Qualification Artifacts

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
| `test_process_deadline*.py` | Synthetic subprocess and lifecycle regressions; never execute a UPS driver |

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
All eight patch artifacts follow
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
repository contains eight patch artifacts and synthetic C tests, not the
complete NUT source tree or NUT/libusb binaries. The standalone HID fragment
replay is not a full-driver build; the separate combined build evidence does
not establish driver runtime or hardware behavior.

The original Python synthetic qualification helpers and tests are identified
as application/MIT material. They do not include NUT source and do not
authorize or perform hardware testing.

See [process supervision limits](../../docs/PROCESS_DEADLINE.md); these helpers
are not part of the app's read-only NUT transport and do not authorize hardware
tests or qualify a caller's argument list.
