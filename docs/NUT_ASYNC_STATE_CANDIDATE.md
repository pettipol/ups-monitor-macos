# Offline USB Async-State Candidate

Date: 2026-10-11. Source-only qualification artifact, not an installed backend.
This fourth incremental patch targets the exact
[lifecycle/write candidate](NUT_LIFECYCLE_WRITE_CANDIDATE.md). Historical patches
and replay source fences are unchanged.

## Identity and Reproduction

NUT upstream revision: `73c4502191d025e35122463986a80c676e734b04`.
Official GitHub API refresh on 2026-10-11 still reports this master revision,
[NUT v2.8.5](https://github.com/networkupstools/nut/releases/tag/v2.8.5) as the
latest release and [libusb v1.0.30](https://github.com/libusb/libusb/releases/tag/v1.0.30).
Microlink continues to use the explicitly experimental master exception.
Apply these patches in order to a separate pristine checkout, without running
the driver:

1. `backend/nut/nut-guarded-monitor-73c4502.patch`
2. `backend/nut/nut-hid-fallback-validation-73c4502.patch`
3. `backend/nut/nut-guarded-lifecycle-write-73c4502.patch`
4. `backend/nut/nut-usb-async-state-73c4502.patch`

The original-base `nut-guarded-monitor.patch` is NOT part of this stack.
Independent application with `git apply --whitespace=error-all` passes.
Only `drivers/apcmicrolink-usb.c` changes in the fourth patch.

| SHA-256 | Value |
|---|---|
| Fourth patch | `61b80e431a9507cd9ee60b608a8c6290bc3ca9706bf40298121fc26f6958a071` |
| Input USB source | `6b81bac1498ce4868a96bca9ee98682155cc1f063eb36c72c4cb29c21bcf01f9` |
| Candidate USB source | `7929a4869cfee9c08734c1b9b5c091c3f7c62496e0981031c2c9ad149ecc33b0` |

## Contract

`usb_device_gone`, `async_xfer_active` and `async_pump_stop` now use six small
getter/setter helpers. All post-initialization accesses to those scalars use
the existing `async_lock` in libusb-1.0/pthread builds; `volatile` is no longer
used as a substitute for synchronization. No mutex is held over a thread join,
libusb event handling or transfer submission. Queue callback code releases its
lock before invoking the state helpers. Non-pthread and libusb-0.1 builds do
not reference the async mutex through the device-gone helpers.

This preserves the continuous async listener and the existing exact 64-byte
write-completion guard. Individual snapshots do not form an atomic lifecycle
transaction and do not prove correct ownership of transfer objects.

## Synthetic Replay Scope

`replay_usb_async_state.py` accepts only the input and candidate USB hashes
above, each on the exact upstream HEAD. It extracts the actual pump, callback,
device-gone getter and candidate helpers; unused lifecycle prototypes are
excluded from the generated fragment. Source copyright/GPL notices are kept.
The C harness supplies file-local inert libusb-shaped functions, not libusb.

Three separate pthread test processes exercise pump-stop, device-gone and
transfer-active. The baseline active reader and stop writer are test-owned
scalar accesses representing the source's unsynchronized accesses, not an
execution of full `get_char` or `async_stop`. Their candidate counterparts use
the extracted helpers. Start/stop/get-char call sites are checked statically;
full lifecycle integration, fallback decoding and real event delivery are not
executed by this harness. The callback test uses synthetic NO_DEVICE events.

To reproduce on macOS with a working compiler/ThreadSanitizer, set `BASELINE`
and `CANDIDATE` to the respective patched source checkouts and `SCRATCH` to
a new external directory for each invocation:

```sh
python3 backend/nut/replay_usb_async_state.py \
  --baseline-root "$BASELINE" --candidate-root "$CANDIDATE" \
  --scratch "$SCRATCH" --mode red
```

Use a different new scratch directory and `--mode green` for the candidate.
`--mode extract` does not compile or run. Compilation and binary symbol/library
inspection precede any synthetic process; unexpected USB/NUT links fail closed.
Each test process has a 15-second bound. RED requires TSan data-race evidence
for the named global and expected frames, with exit 66; GREEN requires clean
success and exact output. Unsupported sanitizer runtime, compiler failures and
generic crashes are not RED evidence. Normal app CI runs Python contracts
only, not these C replays and never a driver.

Recorded result: three baseline RED cases with exit 66 and the exact named
globals, followed by three candidate GREEN cases with exit 0 and empty stderr.
The coordinator independently repeated all six cases. Seventeen Python
contracts pass; six separate in-memory mutations removing one helper lock
each are rejected. These results cover the stated extracted-source scenarios,
not all schedules or the integrated driver.

The initial Luna attempts failed at compilation (unmatched extraction guard,
then unused prototypes). The task escalated narrowly to Sol. macOS sanitizer
configuration required `abort_on_error=0` to obtain exit 66; an initial
same-value active fixture was changed to an initial active state before thread
creation. Failed attempts are not counted as RED evidence. No driver source
change was needed during replay repair.

## Build and Review

Fresh out-of-tree USB and serial `apcmicrolink` target builds pass on macOS.
Generated build templates from the same pinned baseline were reused; no new
dependency was installed. The USB build enables libusb-1.0 and pthreads.
Source, independently applied stack and build source have identical USB hashes.
Neither resulting driver was executed, including with informational options.
Windows, libusb-0.1 and USB-without-pthread builds were not run.

Existing warnings remain: system include path, allocator wrappers and a
platform-constant signal-helper return. No new async-state warning was found.
Luna implemented the scoped source change and independently developed tests;
the coordinator repeated critical checks. A bounded read-only Sol review
found no new concrete defect in this delta. This is not full-driver approval.

## Primary Sources and Remaining Gates

Official [libusb threading documentation](https://libusb.sourceforge.io/api-1.0/libusb_mtasync.html)
was read through BrowserOS on 2026-10-11. Its event wrappers and synchronous
functions handle the library's event locks. Consequently, a live event pump
alongside synchronous I/O is not, by itself, proof of a bug. The driver's own
shared data and lifecycle still require separate reasoning and tests.
The [libusb caveats](https://libusb.sourceforge.io/api-1.0/libusb_caveats.html)
separately require ownership discipline for submitted transfers and buffers.
The open [Microlink PR #3719](https://github.com/networkupstools/nut/pull/3719)
was rechecked: its USB diff adds report-padding handling already present in
this base, not shared-state synchronization. Its control/serial changes were
not adopted. This targeted check is not a claim that no other solution exists.

After a terminal callback or failed resubmission, active may become zero while
the pump remains alive until an explicit stop. The sync fallback transition,
transfer lifetime, callback affinity, queue behavior and cancellation paths
are NOT qualified by this scalar fix. F1 signal delivery/cleanup remains
partial; F3 receive deadlines/resubmission remains open. None of these offline
results demonstrates power continuity, USB coexistence, electrical accuracy
or advanced APC compatibility. No hardware operation is authorized by this
document or its replay tools.
