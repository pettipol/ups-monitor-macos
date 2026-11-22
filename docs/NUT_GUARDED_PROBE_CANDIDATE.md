# NUT guarded probe candidate

Status, 2026-10-12: source review, USB-entry replay and the fixed 23-case
full-main/APC synthetic matrix passed, with an independent repeat. The
two continuation scenarios and two mutation controls below also passed
independent comparison. Two additional data-quality scenarios demonstrate
that exit success, a dump and global DATAOK do not qualify individual metrics;
both passed an independent repeat. The complete ninth-patch driver has now passed four
offline USB/serial A/B compile/link runs. The current-v4 callback-expiry replay
also passed its two synthetic cases, independently repeated by Luna and root
(four child executions with identical per-case records and output). Hardware
remains **HOLD**; no operational command line or device parameters are approved.

## Bounded Policy

`nut-guarded-probe-attempts-73c4502.patch` is an incremental patch over the
eight-patch candidate based on NUT
`73c4502191d025e35122463986a80c676e734b04`. It changes only
`drivers/main.c`, `drivers/apcmicrolink.c` and `drivers/apcmicrolink-usb.c`.

The new opt-in `guard_probe_attempts=N` accepts canonical ASCII values `1`
through `10`. Leading zeroes, signs, whitespace, suffixes and longer values
are rejected. It requires guarded USB mode with `hid_fallback=no`; invalid
combinations must fail before guard setup or opening a transport. A serial-only
build must explicitly reject the option with a failure exit status, rather
than rely on upstream's unknown-option path, which can exit successfully.
Main rejects the option without `guarded_monitor` immediately after parsing,
before any command/peer-driver admission path. The serial-profile replay
covers this early rejection, not APC's separate USB-support diagnostic.

The counter is process-wide and is consumed immediately before the first
STOP of each STOP/INIT attempt. Failed sends consume the attempt too. It is
not reset by initinfo, retry or reconnect. The option disables USB reopen
regardless of remaining attempts, including a defensive gate at the backend
entry point before teardown, reset, allocation/free or reopening.

A valid session may continue NEXT requests, polling, descriptors and
authentication after using its last attempt. A lost session without a remaining
attempt must fail before the retry timer can return a stale dump. An observed
device-gone state must fail at the reviewed decision points, including between
handshake sends and before another attempt. The final best-effort raw cleanup
STOP is separate from this budget and is not removed.

The option is absent by default. Legacy behavior is preserved outside this
opt-in path; that is a design constraint, not yet a demonstrated equivalence
claim for every runtime path.

## Evidence Gates

### Startup Expiry Replay, 2026-10-12

Two additional synthetic cases pass, independently repeated with identical
records and captures. Full pinned main/APC/dstate sources are unchanged.
A fake guard latches expired immediately after the first INIT, independently
of its getter, while a valid page-0 frame remains available. Startup exits 1
with the fallback-disabled diagnostic before any transport read, NEXT,
update, dump or DATAOK; cleanup closes the fake handle before atexit, without
a cleanup STOP. The paired non-expired control reads the same page and sends
NEXT, then exits 0. Both cases keep `data_qualified=false`.

Source, compile/link, static inspection and bounded runtime were reviewed
separately. The linked fixture uses fake transports and libSystem only, not
the USB backend; generic OS imports remain, so it is not a sandbox. Two
scenarios were run twice, not four distinct scenarios. N=1 also limits INIT
attempts: no second INIT must not be attributed solely to expiry. This proves
only the caller's reaction before its first page, not the real USB callback,
clock, OS deadlines, authentication, measurements or hardware behavior.
The product now has optional dependency-pin checks in the supervised spawn
path; their targeted integration tests are reported below. The profile
registry is still empty and hardware qualification remains HOLD.

### Runtime Input Audit, 2026-10-12

A private read-only audit now checks the proposed USB9 executable and its
specific libusb loader path, literal symlink target, canonical library path
and hash. Nine synthetic file tests pass, independently repeated, including
same-byte symlink retargeting during the read. At the preceding filesystem
audit, the real files matched the build pins; they were not re-audited in the
dependency-pin integration tranche. No executable was launched and no library
was loaded by that audit. The auditor
does not infer the Mach-O load path: that was inspected separately on the
hash-pinned executable. It does not eliminate TOCTOU or constitute admission.
Before an operational profile is enabled, the same specific checks must be
part of its reviewed pre-spawn path. The distributed profile registry remains
empty; hardware remains HOLD.

The existing [guard deadline replay](NUT_GUARD_DEADLINE_CANDIDATE.md) already
tests the core clock/budget logic. The ownership R5 receipt also remains
reusable for selected body-identical functions: `async_pending_get_locked`,
owner/pending queries, guard helpers, `async_xfer_active_get`, the async
callback and pump, reap/wait, stop, close/open/reset-handle, flush, reads and
libusb context cleanup/hold/release. In particular, the callback body SHA-256
is `d91a35a5003be05e543f39328b6c7c3d506a2514a76df3ecf0d644c82f938166` in
both ownership candidate d6 and current v4. The R5 synthetic ownership cases
did exercise that d6 callback. Correction: the callback differs from the
older deadline replay source, not from ownership R5; its body is reusable for
v4. `async_start` and `reset_and_reopen` are not body-identical, and the R5
receipt does not qualify callback expiry or the complete v4 module. The
startup replay above covers one main/APC consequence only.
No C replay or compilation was performed during this audit.

### Current Callback Expiry Replay

The current-v4 source-exact USB callback now has a separate two-case
synthetic replay. With the same completed payload, the expired-guard case
proves no decode, queue insertion or resubmit; it marks the callback terminal
and retains ownership until the event pump returns, after which stop/reap/close
complete. The non-expired control decodes, queues and resubmits, then exercises
stop, cancellation acknowledgement and close. Both cases passed under UBSan.
Luna and root each ran the same two cases: four child executions across two
scenarios, with byte-identical per-case records and captured output.

This replay uses real fixture pthreads and event-pump synchronization, but
mocked libusb calls, a fake monotonic clock and fake decoder. It does not
qualify real libusb callbacks or cancellation, an OS clock/deadline, kernel
URB behavior, platform scheduling, an UPS, the NUT operational path, USB,
IOKit or hardware timing. The old R5 receipt remains a historical result for
its pinned source; this separate replay does not revise its hashes or imply
that the entire current-v4 module has been qualified.

The offline C01 evidence is sufficient to propose a separately reviewed,
bounded first observational session, not to qualify or authorize hardware.
The current operator-profile proposal lists a 20-second guard, 30-second
process timeout, 2-second termination grace and 1 MiB output cap as policy
candidates only. The distributed profile registry remains empty and no
profile is activated.

### Operator Dependency-Pin Integration, 2026-10-12

`DependencyPin` is optional and defaults to `()`, preserving the legacy path.
The closed `OperatorProfile` accepts only an immutable tuple of pins and passes
the same tuple object through `run_operator_controlled` to `run_bounded`. The
registry remains empty; no profile, executable path, private loader path or
hash is registered in the product.

With pins, the runner checks the executable and each exact dependency before
output creation, then repeats the hashes after private output preparation and
performs a final executable-identity and loader-link/target-resolution scan
before the final cancellation check and `Popen`. A late rejection closes but
does not delete output already created; rejection errors are fixed
(`hash_mismatch`, `executable_rejected` or `dependency_rejected`). Cancellation keeps its
existing checks and outcome. The child deadline begins after the audit. There
is no Mach-O parser or atomic binding: the closed profile must attest the
loader-path and symlink relationship to the precise Mach-O SHA, and a residual
TOCTOU window remains after the final scan. No generic dependency discovery
or new parser is introduced.

Targeted synthetic tests for this integration passed. Luna reports all 15 new
dependency-pin tests passing. Root independently ran all 168 backend tests
(rc=0), including 54 process tests and 12 CLI tests; 14 privacy tests passed
separately (rc=0). The 15 new cases are included in the 54 process tests. These
tests do not exercise an operational NUT executable, actual dynamic loading,
USB, IOKit or hardware. No real compiler or TSan run was performed in this
tranche; compiler-like strings in logs are mock test data. Final Sol source,
evidence and document review found no blocker in this synthetic scope.

Current frozen Python source/test SHA-256 values are recorded in
[the process-runner evidence](PROCESS_DEADLINE.md#dependency-pin-synthetic-evidence).
Historical 141/153 backend-suite counts and earlier module/receipt hashes are
not current verification. No operational profile has been added; hardware
remains HOLD.

The first observational attempt does not require app/widget integration or
a service. Those remain product requirements, not reasons to broaden the
first CLI-based trial. A closed profile, input checks, reviewed bounds,
protected preparation and separate user consent remain prerequisites.

### Source And Runtime Separation

The offline plan separates a full NUT main/APC fixture with fake transports
from an extracted USB-entry fixture with recording mocks. Common NUT static
support libraries may be used by the former; neither fixture may link the real
USB backend, libusb, HID or IOKit. Source extraction, compile/link, executable
inspection and bounded execution are separate review gates.

Static review found and source-corrected the serial-only successful-exit issue
and device-gone transitions during handshake operations. Full-main replay then
found a separate late-admission defect, corrected and retested below.
No source-only inspection is a runtime PASS.

### Main/APC Replay

The first matrix stopped after 12 passing cases: the non-guarded configuration
reached a peer-driver query before APC option validation. A fake sentinel
returned 125 without sending the query. Root reproduced the same failure;
the remaining ten cases were not run. The new early main rejection fixes the
source path, without removing or weakening that sentinel.

Three revised fixtures compile whole pinned main/APC/dstate sources with
mock transports. Candidate and baseline main/APC files are kept separate.
A declared read-only accessor appended to the candidate APC translation unit
observes its attempt counter; it is not part of the product patch. All 369
generated inputs are hash-checked before compilation. Link maps, imports and
binary hashes were reviewed before execution: common NUT static support
archives and libSystem, no real USB/serial backend, libusb, HID or IOKit.
Generic OS imports remain; this is not a general sandbox. Unlike the entry
fixture below, this full-main matrix is not UBSan-instrumented.

The revised **23-case matrix passed**, then passed root's independent repeat:
two valid values with exact attempt counts; ten invalid values; three invalid
mode combinations; failed STOP consumption; first NEXT at an exhausted quota;
three device-gone schedules; separate cleanup STOP; and the no-option control
on both candidate and baseline. These are 23 matrix cases, not 46 distinct
scenarios. Each child exited with the expected code 1; the deliberately
terminated cases are not successful acquisitions.

Each child used private NUT paths, a 10-second timeout, 1-second termination
grace and 1 MiB capture cap. No timeout or output cap fired. Root checked all
46 records and captured bytes: paired statuses, exits, stdout/stderr hashes
and markers agree. Normalized result digest:
`052aaca225a7621cb3ce944c8f33285d1b60b8bd2420b5af0902f278393d7c8a`.

Earlier source-verifier errors, a Bash 3.2 empty-array build failure and a
malformed intermediate patch were preserved and repaired before the admitted
build. The current patch passes independent dry-run/application and source
hash comparison. Failed preparations are not counted as successful tests.

### Continuation Replay

Two additional full-main scenarios use a valid synthetic page 0 followed by
silence. A mocked clock advances only in the APC translation unit after the
first NEXT; no candidate state is assigned by the fixture. With `N=2`, the
real startup and initial update/reconnect consume counters 1 then 2. With
`N=1`, reconnect sends no additional handshake. Both fail before datastale
publication, with one separately observed raw cleanup STOP.

Two single-change controls establish test sensitivity. Resetting the counter
at session entry produces an extra handshake with counters 1,1,2; removing
only the post-reconnect quota check permits datastale and a second update
before a later failure. Both controls are rejected by the actual candidate
assertions, not merely classified by exit status.

Luna ran the four children and root repeated them: four pairs of records,
markers and captured bytes agree. Every child exited with expected code 1;
the matrix runner exited 0. Each child had private NUT paths, a 10-second
timeout, 1-second grace and 1 MiB cap; no bound fired. Three inspected binaries
use mock transport, common static NUT support and libSystem only, without
real USB/serial backend, libusb, HID or IOKit. They are not UBSan-instrumented.
Normalized result digest:
`f16d074755c4f50b6c65bb75177e5c8f61d2b32ac8a6f87a70dcee0199b5d409`.

Preparation failures and a first launch rejected by an incompatible Python
interpreter before spawning any child were preserved, not counted as passes.
This evidence covers two deterministic schedules, not every retry/backoff,
sustained healthy polling, full authentication or physical communication loss.

### Data-Quality Replay

Two fixed traces use the unchanged whole main/APC/dstate candidate with a
fake transport and observers delegating to the real DATAOK, DATASTALE, dump
and cleanup functions. One provides only the startup page 0; the other adds
exactly one page 0 at the first update. Both pages contain protocol metadata,
not advanced measurements. The APC clock is fixed below the session timeout;
the USB guard is mocked. This does not test expiry or full authentication.

Each trace exits 0 after three real update entries and a dump, with three
DATAOK calls setting/keeping stale=0 and no DATASTALE. The first receives no
frame after startup. The second receives one extra frame, but its dump is
identical: only metadata and an empty `ups.status`, without battery charge,
runtime, battery/input/output voltage, load, W or VA. Both execute the observed
cleanup in order, including its separate final STOP and fake-handle close.

Luna ran both traces and root repeated them. The two pairs of records,
markers and captures agree: each child completed with 700 stdout bytes and
53 stderr bytes, within a 10-second timeout, 1-second grace and 1 MiB cap.
No bound fired. Sol reviewed the source, build, runtime gate and final results.
Normalized two-record digest:
`6632149b0867a401e064d95a5259194d57066774194b1af6b73131fca51b9ba7`.

The first build failed because the fixture input list omitted two required
headers. That failure and its inputs are preserved; the repaired source pack
passed eight compilation steps and one link without warnings. All 54 generated
payload files were checked against the manifest and original inputs. Binary
imports/link map contain fake transports, static NUT support and libSystem,
not real USB/serial backends, libusb, HID or IOKit. Generic OS imports remain;
this is neither a general sandbox nor a UBSan run.

This is a counterexample to treating global process/driver status as a
per-metric quality certificate, not evidence that existing measurements are
stale or that NUT has a universal defect. No production C change was made
to force a different outcome. Future acquisition criteria must distinguish
process completion, field presence/validity, provenance and observable recency.
Missing fields or unproved freshness remain explicit and must not trigger an
automatic retry. No real profile or device parameter is approved by this replay.

### USB Entry Replay

The exact `microlink_usb_reset_and_reopen()` body was extracted from baseline8
and candidate9 into recording-mock fixtures. Three scenarios, six child runs
per pass: the baseline probe test produced its specific RED assertion; the
candidate probe test returned before any modeled side effect. Guarded and
unguarded no-option controls passed on both variants. Root repeated the six
runs independently with identical result records, SHA-256
`c9a785294c0e19d90801a104846e74fa3b2f2ab421af56d0edd03bdddb22028b`.

The fixtures were compiled with undefined-behavior sanitization, then their
imports/dependencies were inspected before execution: libc and UBSan only.
Each child was bounded to 5 seconds plus 1-second termination grace, with a
64 KiB output cap. All six exited normally; no timeout signal was needed.

The first pass in each run stopped on its first child because compiler-rt
added a missing-symbolizer warning. Those attempts are preserved, not counted
as valid RED/PASS evidence. This isolated fixture needs no NUT configuration;
using the supervisor's existing clean PATH/LANG/LC_ALL environment corrected
the test setup. The C, binaries, sanitizer checks and exact output assertions
were unchanged. This environment choice does not apply to the full-main fixture,
which still requires isolated NUT configuration/state directories.

This proves only the modeled entry gate and controls, not actual cancellation,
ownership, the caller's handshake budget or real USB behavior.
The subsequent main-only admission correction leaves the tested USB source
bytes unchanged; it does not turn this entry replay into whole-driver proof.

| Artifact | SHA-256 |
| --- | --- |
| Patch 9, current | `e0f2f1c7cb04e59c1ea55ca14f0db0ba59decd6ee6e098f50bcf89b4678ab5c2` |
| Main source 9 | `8cc88c24c6b719b65dc00d74082217d07de3313d813ac382b844a1d847a346e2` |
| APC source 9 | `a181e17e882ddac83e06b86c92866593f4872e2eacb2e12ab6943d8a8df97324` |
| USB source 9 | `cc315c05ed27c7e4ec6705e113a7091170a0f08b54aa9823ba0b69dd85af2f36` |
| Entry baseline binary | `e861b59e1b471575b4220f0e560e06920601244a9abce687bcbc23f5c13f5e04` |
| Entry candidate binary | `8d8d6d7531d1a3ce53cd3b96d3bca2d44fcd32b5808b070764d36a0428340b09` |

### Complete Offline Build

The pinned ninth-patch tree passed USB A/B and serial-only A/B configure,
compile and link with the existing pinned toolchain. A clean environment and
`--disable-inplace-runtime` excluded deployed NUT version queries; compiler
feature conftests were allowed. Only the driver build target and required
common libraries were built. No generated or installed NUT executable was run.

Independent verification recalculated 1,357 source files and six symlink
targets per pass, plus 518 artifacts/294 prerequisites for USB and 508/273
for serial. Both binary pairs are byte-identical; only `config.log` differs
within each artifact set. This is observed local repeatability, not general
reproducibility. Compiler warnings remain recorded in the private build logs.

| Built artifact, not executed | SHA-256 |
| --- | --- |
| USB A/B | `9c5e2ca50e4c36179dcb26691d569c9d97d30f652d4aef336fbc33002637a2c8` |
| Serial A/B | `2395293b09fd527648dd0f3e27c8b7c810442675c8895a1e31397a73c5a7f988` |

These operational build artifacts are distinct from the synthetic fixtures
above and have not received runtime or hardware approval.

## Remaining Limits

- Counter persistence and failure before datastale are demonstrated only for
  the two continuation schedules above. General retry/backoff coverage,
  sustained healthy polling and full authentication remain **NOT_DEMONSTRATED**.
  The gone-update case injects at update entry, not the internal retry branch.
  No main-matrix proof is inferred for real USB ownership.
- The attempt limit is not a total USB-message limit. Reads, NEXT requests,
  descriptor/authentication traffic and the final cleanup STOP are distinct.
- A checkpoint cannot cancel a write already in flight or make checking a flag
  atomic with an asynchronous callback. There is no hard kernel deadline or
  guarantee of electrical continuity.
- Successful handshake, exit zero or `ups.status=OL` does not establish complete,
  fresh advanced measurements. The future acquisition/output acceptance policy
  remains separate.
- Neither `N=1` nor any particular guard duration is approved for the target UPS.
  Timing comments for other hardware are not evidence for this device.
- The operator adapter, exact supervised command line and selection of the
  current build artifact must be qualified together before a device session.
- No app/widget integration, service installation, package update, hardware
  access or upstream patch publication is part of this source candidate.

The patch is NUT-derived **GPL-2.0-or-later**, not relicensed by the application
MIT license. See [notices](../THIRD_PARTY_NOTICES.md), the
[eight-patch baseline](NUT_GUARDED_REOPEN_STOP_CANDIDATE.md) and
[upstream discussion refresh](NUT_UPSTREAM_STATUS.md).
