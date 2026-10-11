# Offline USB Lifecycle Observation

Date: 2026-10-11. **Expected RED observations, not a driver fix.** No real
NUT executable, libusb library, USB interface or UPS is used by this replay.
The experimental driver remains on hold. The source-only lifecycle question
is published as [NUT #3751](https://github.com/networkupstools/nut/issues/3751);
publication is not maintainer endorsement or a resolved shutdown contract.

## Frozen Input

Use exactly the five-patch stack and three SHA-256 values in
[the observation-budget candidate](NUT_GUARD_DEADLINE_CANDIDATE.md), based on
NUT `73c4502191d025e35122463986a80c676e734b04`. The runner rejects a different
HEAD or changed USB source, header or main-driver source. It neither updates
the dependencies nor modifies the candidate. This is a historical pinned
experiment, not a claim about every upstream revision or supported UPS.

The generated translation unit preserves full function bodies for the pump,
callback, start, stop and close, plus their state/guard/device helpers. It
retains the upstream GPL notice. Libusb-shaped functions, the close operation,
clock, allocator and thread creation/join are local test doubles. Generated
excerpts stay outside the product and source checkout; the output directory
must be new and must not traverse symlinks. `--mode extract` writes source and
a manifest without compiling or running it.

## Observed Paths

Each scenario runs in a fresh process for both ordinary and guarded profiles.
The synthetic guarded clock stays inside its budget; expiry is not tested here.

| Scenario | Expected observation |
|---|---|
| Thread creation fails after initial submission | RED: close occurs with a pending transfer, cleared owner/active state and changed pending `user_data` |
| Cancel returns success, no completion in 50 event-dispatch calls | Same RED observation; a cancel request does not complete the fake transfer |
| Cancel returns `LIBUSB_ERROR_NOT_FOUND`, no completion | Same RED observation; the error does not clear the independent pending ledger |
| Cancel completion callback delivered during stop | CONTROL: callback, buffer free and transfer free precede close; no pending transfer remains |

For RED cases, the fake dispatcher later invokes the unchanged callback and
checks exactly one logical buffer/transfer release and no resubmission. This
late callback is a test input, **not evidence that dispatch after a real close
is supported or safe**. Pending state is tracked independently of the driver's
pointer/active flag. Event counts and ordering are asserted, including initial
submit before thread creation, join before cancel when applicable, and close
before the deliberately late callback. Mock deallocation is deferred until
these checks pass; this ledger is not AddressSanitizer or actual allocator
lifetime proof.

The thread facade captures the real pump function and invokes it synchronously
after its stop flag is set. Its immediate return does not test active pump
iterations, real concurrency, scheduling, blocking join or teardown deadlines.
Other exclusions are whole NUT startup, fallback reads, reset/reopen, protocol
STOP, exit hooks and context destruction. Those remain in the
[lifecycle qualification hold](NUT_LIFECYCLE_REVIEW.md).

## Reproduce

Set `CANDIDATE` to the separately prepared five-patch source checkout and
`SCRATCH` to a new external directory:

```sh
python3 backend/nut/replay_usb_lifecycle_observation.py --mode observe \
  --source "$CANDIDATE" --scratch "$SCRATCH"
```

On macOS, the runner compiles with C99, warnings-as-errors and UBSan, then
checks undefined symbols and linked libraries with `nm` and `otool` before
execution. No USB/NUT/IOKit linkage is accepted. Compilation has a 30-second
limit; each synthetic process has a 10-second limit. These runner timeouts
are not driver shutdown guarantees. A RED is accepted only with exit 1,
the exact expected output and empty stderr. Controls require exit 0 with
their own exact output. A crash, compiler error, timeout or unrelated failure
is a harness failure, never a successful RED observation.

The manifest records input, generated-source and C-fixture hashes, compiler
arguments and scope; per-case files retain status/stdout/stderr. These local
logs may contain filesystem paths and are not automatically published.

## Results And Boundaries

The Luna worker and coordinator independently reproduced six expected RED
observations and two controls against the frozen candidate. Both compilations
and all processes had empty stderr, and both binaries passed the linkage
inspection. No candidate or installed app was changed by this work.

Three mutations in separate generated-source copies were compiled successfully
and rejected by assertion status 2 with empty stdout/stderr: omitted device
close, omitted cancellation and omitted abandoned-buffer release. The
coordinator reviewed each diff, rechecked binary hashes/linkage and repeated
the targeted cases. Compile errors or crashes were not counted as detection.
Fifteen Python lifecycle-runner contracts pass; the local replay/process/privacy
suite totals 108 passing tests. Swift and local Xcode builds were not repeated
for this test/documentation-only change.

Normal app CI runs only the synthetic Python runner-contract tests. It does
not fetch/build NUT or run this C observation. App build success, runner
success and reproducing a contract gap are three different results; none
qualifies real advanced telemetry, safe USB coexistence or electrical safety.
