# Offline USB Observation-Budget Candidate

Date: 2026-10-11. Source-only experiment, not an installed backend.
This fifth incremental patch extends the frozen
[async-state candidate](NUT_ASYNC_STATE_CANDIDATE.md). Historical patches and
their replay source fences remain unchanged.

## Exact Source

NUT HEAD: `73c4502191d025e35122463986a80c676e734b04`. The same-day official
version refresh is recorded in the preceding candidate document: stable
NUT 2.8.5 and libusb 1.0.30, with an explicit experimental-master exception
for Microlink. No dependency is added or updated here.

Apply these patches, in order, to a separate pristine checkout:

1. `backend/nut/nut-guarded-monitor-73c4502.patch`
2. `backend/nut/nut-hid-fallback-validation-73c4502.patch`
3. `backend/nut/nut-guarded-lifecycle-write-73c4502.patch`
4. `backend/nut/nut-usb-async-state-73c4502.patch`
5. `backend/nut/nut-usb-guard-deadline-73c4502.patch`

The original-base `nut-guarded-monitor.patch` is not part of this stack.
Independent application with `git apply --whitespace=error-all` passes;
source, separately applied stack and build-source hashes match.

| SHA-256 | Candidate |
|---|---|
| Fifth patch | `546bc985bd052eb081475f605d917c72b203410a5c1017259a2314db6da88fe1` |
| `drivers/apcmicrolink-usb.c` | `1b7e3d3b8cdb54910e68f28a8bea4e10b6f4cdef4f5143ffacd64ff2aa6af42a` |
| `drivers/apcmicrolink-usb.h` | `1b0ac143a8c99a161930562b441f1340ca8bd971d4bb2315e46a98e1b8a75ba8` |
| `drivers/apcmicrolink.c` | `3bc7eadc8e2fae657df1b8f0e37f3baf53fd9a6e20a7da3c029d218193d2177d` |

## Contract

The opt-in guarded profile now starts one monotonic observation budget before
the first USB open. Polling, startup, reconnect and retries cannot renew it.
A missing monotonic/async prerequisite rejects guarded initialization before
USB access. Clock failure, invalid timestamps, negative elapsed time and
expiry latch a terminal state under the existing mutex. Time arithmetic uses
validated integer seconds/nanoseconds, not floating-point conversion.

Initial submissions and callback resubmissions use the remaining budget,
rounded up to milliseconds in `1...300000`; zero remains the ordinary-mode
unbounded timeout. Startup rechecks after allocation and immediately before
submission. A callback that observes expiry neither decodes nor queues a
report and does not resubmit. It clears active state and wakes waiters, without
introducing a fatal exit or freeing an owned transfer in that expiry branch.
The pre-existing abandoned-transfer branch is separate and remains unqualified.

Guarded inactive/expired reads and flushes cannot fall back to synchronous IN.
The requested condition wait is capped to remaining budget; guarded failure
to obtain its realtime wait clock also latches terminal state. Reopen checks
the budget at entry and again before opening. Failure to start the listener
invalidates the budget. Initial startup failure returns to NUT main before a
fatal check in `upsdrv_initinfo`, where the existing cleanup hook has already
been registered. This avoids a new early-fatal regression; it does not prove
that the existing cleanup handles every pending transfer safely.

This is an **IN observational/cooperative budget**, not a hard OS or process
deadline. Scheduling can delay the interval between check and submission, and
the condition variable still uses a realtime absolute clock. No claim is made
that OUT/authentication/cleanup STOP traffic is absent after the budget, that
pending I/O is instantly cancelled, or that all resources are released on time.
Normal-mode semantics are intended to remain unchanged; this is not exhaustive
normal-mode runtime qualification.

## Verification Scope

USB/libusb-1.0/pthread and serial target builds pass in separate out-of-tree
directories. The USB configuration was created fresh, then the three changed
files were rebuilt after final review corrections. Serial was built from the
final source. Existing generated templates from the pinned baseline were
reused; no dependency was installed. Neither driver binary was executed, even
with informational arguments. Existing include-path, allocator-wrapper and
platform-constant signal-helper warnings remain. Windows, libusb-0.1 and
USB-without-pthread configurations were not built.

The replay tools distinguish extracted helper/callback execution from static
checks of startup, get-char, flush and reopen call sites. They pin upstream
HEAD and all three changed source files, preserve upstream GPL notices in
generated excerpts, and reject existing scratch paths or overlap with the
source/product checkout. Recording libusb-shaped functions are file-local
test stubs, not the USB library. Compilation uses warnings-as-errors and
UBSan; symbol/library inspection precedes every synthetic test binary. Each
test process has a ten-second bound and must match exact status/stdout/stderr.

Set `BASELINE` to the four-patch input checkout, `CANDIDATE` to the five-patch
checkout, and each scratch variable to a different new external directory:

```sh
python3 backend/nut/replay_usb_guard_deadline.py --mode red \
  --source "$BASELINE" --scratch "$RED_SCRATCH"
python3 backend/nut/replay_usb_guard_deadline.py --mode green \
  --source "$CANDIDATE" --scratch "$GREEN_SCRATCH"
```

`--mode extract` accepts the candidate and generates excerpts without compiling
or executing. The baseline RED executes the actual old callback after the
test-defined observation window and observes decode/queue/resubmit continuing;
it does not invent a deadline API in that baseline. Nine candidate GREEN cases
cover one-nanosecond boundaries, exact/late expiry, nonrenewal, clock failure,
invalid nanoseconds, negative elapsed time, the 300000-ms maximum, explicit
invalidation and ordinary callback statuses including resubmit failure.

Both an independent worker and the coordinator reproduced one expected RED
(exit 1, exact assertion output, empty stderr) and all nine GREEN processes
(exit 0, exact output, empty stderr). The coordinator repeated GREEN against
the independently applied patch stack. Three additional mutations of generated
synthetic C were caught by assertions: premature fractional expiry, renewable
epoch and zero timeout. Compile errors/crashes were not accepted as detection.
Fourteen Python runner contracts pass; normal CI runs these contracts, not the
C replays or NUT driver. Together with existing backend/privacy checks,
93 local Python tests pass. Integrated call paths and concurrent schedules
remain outside this dynamic replay; main's cleanup-registration ordering was
checked manually, not executed.

## Review and Open Gates

Luna implemented the three-file change and began the independent replay.
Root review caught premature expiry during the last fractional second; a
bounded Sol review caught an early fatal before cleanup registration and an
initial timeout sampled before allocation. These were corrected before the
final candidate. Replay repair was escalated narrowly to Sol after Luna's
failed source-selection, extraction and compilation attempts. Failed attempts
are not RED regression evidence.

The relevant primary contracts are the official
[libusb asynchronous API](https://libusb.sourceforge.io/api-1.0/group__libusb__asyncio.html),
[threading documentation](https://libusb.sourceforge.io/api-1.0/libusb_mtasync.html)
and [ownership caveats](https://libusb.sourceforge.io/api-1.0/libusb_caveats.html).
These describe upstream APIs, not proof of this driver on an APC device.

F3 remains partial at the integrated-driver level. Transfer lifetime,
cancellation acknowledgement, pump shutdown, F1 signal routing/cleanup and
real OS scheduling remain open. The previous scalar TSan result does not
automatically qualify this newer callback. No electrical continuity, USB
coexistence, advanced telemetry or local APC compatibility is established.
No hardware operation is authorized by this document or these replay tools.
