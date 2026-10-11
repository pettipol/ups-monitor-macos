# USB Lifecycle Qualification Hold

Date: 2026-10-11. Static review only; no NUT executable, USB operation or
hardware test was run for this review. The five-patch source and exact hashes
are frozen in [the observation-budget candidate](NUT_GUARD_DEADLINE_CANDIDATE.md).
Line numbers below refer to that patched NUT source, not pristine upstream.

**The local experimental driver remains unqualified.** Its observation budget
does not establish safe transfer ownership through startup failure, reconnect
and process shutdown. This does not prevent separate Apple-reader/app/widget
qualification. It is not evidence of a particular crash or an electrical
failure, nor evidence that electrical risk has been eliminated.

## Findings

| Source | Observed contract gap |
|---|---|
| `drivers/apcmicrolink-usb.c:1343` | After a successful submit, pump creation failure requests cancellation, changes `user_data`, then clears the owning pointer and active flag without observing a terminal callback. Ordinary-mode synchronous fallback may follow. |
| `drivers/apcmicrolink-usb.c:1383` | Stop joins the pump before the nominal cancellation-wait loop. The join has no deadline; fifty requested 20 ms event waits do not bound the complete teardown. |
| `drivers/apcmicrolink-usb.c:1400` | Cancellation timeout abandons the transfer and clears the outstanding state. The close and reset/reopen callers subsequently proceed with the same device handle. |
| `drivers/libusb1.c:158` | The later backend exit hook still calls `libusb_exit`. Its two-second alarm covers that phase, not an earlier blocked join, and does not establish transfer completion. |
| `drivers/apcmicrolink.c:4189` | Cleanup first attempts protocol STOP when the protocol object has been observed, then closes USB. This traffic and ordering also belong to the unqualified lifecycle. |

The coordinator rechecked the candidate hashes, pump-creation failure, stop
and backend exit-hook code after the independent review. No dynamic crash or
specific concurrent `user_data` race was reproduced. In ordinary stop the
pump is joined before the abandoned marker is written; raw pointer access
alone is not proof of a race there.

### Startup Ordering

`upsdrv_initups` ignores the `microlink_usb_open` return at
`drivers/apcmicrolink.c:3822`. In the specific guarded async-start failure,
open invalidates the observation budget and returns. `drivers/main.c:3270`
then registers driver cleanup before `upsdrv_initinfo` terminates at
`drivers/apcmicrolink.c:3899`. It would be incorrect to describe that failure
as bypassing driver cleanup. Other fatal paths during initups precede that
registration and require their own analysis.

## Required Contract

1. A submitted transfer retains an owner, buffer, handle and context until a
   terminal callback is observed. Cancellation requested is not cancellation
   completed, including `LIBUSB_ERROR_NOT_FOUND` or another cancel error.
2. Startup failure cannot fall back to synchronous reads while the asynchronous
   transfer remains unresolved. Moving thread creation earlier also requires
   explicit publication/start ordering; reordering two calls is insufficient.
3. Stop distinguishes stop requested, pump exited and transfer completed.
   A bounded observation timeout retains pending ownership, not a false idle
   state. Repeated stop attempts must be idempotent.
4. Reset, close and reopen are allowed only after verified quiescence. The
   existing integer-returning reconnect path can defer a retry, but that alone
   does not solve process shutdown.
5. Process shutdown must also gate close/free/context exit on outstanding I/O.
   Returning from a void cleanup function cannot veto subsequent exit hooks.

There is no demonstrated local API that both safely aborts/reaps all transfers
and guarantees teardown within a hard deadline. An unbounded wait is not an
approved replacement. Forced process termination would be a separate policy
decision and review, not proof of cooperative cleanup or UPS safety. Neither
policy is introduced by this review.

## Next Offline Work

A complete fix needs coordinated pump/callback/cleanup ownership, not merely
a reconnect patch. Before modifying the candidate, prepare a focused upstream
discussion and agree on the process-exit contract. No issue has been submitted
by this review. Preserve the existing source pins and qualification limits.

Required synthetic cases include submit failure, thread-creation failure,
callback delayed beyond the observation budget, cancel success without an
immediate callback, cancel error/NOT_FOUND, blocked pump, NO_DEVICE, repeated
stop, retry while cancellation is pending and exit with an outstanding transfer.
Assertions must cover resource ownership and exact reset/close/free/exit order,
as well as ordinary-mode behavior. A stub that always returns promptly cannot
qualify the blocked case. Existing scalar and observation-budget replays do
not cover this integrated contract.
