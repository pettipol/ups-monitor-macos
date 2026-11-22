# Opt-in operational capture candidate

This opt-in component adds `capture_operational` in its own module. It does
not change a v1 interface, app entrypoint, profile, native source or runtime
manifest. Synthetic validation and real hardware qualification are distinct.
The focused validation set passed 37 tests: 18 capture tests, four publisher
admission tests, seven publisher/framer regressions and eight v1 protocol tests.
These use fake runners and clocks, temporary files and finite worker threads.
Full CI, app/native integration and hardware qualification remain **NOT_RUN**.

A separate opt-in real-OS synthetic probe also passed with the pinned default
runner and atomic publisher, without mocks: two active file snapshots, Stop,
validated cancelled End, zero child exit, real pipe EOF, group absence, reaping,
consumer/finalizer quiescence and a closed publisher. The final envelope was
stopped with sample sequence 2. Its finite producer emitted two samples and one
End; this proves the short software bridge, not long UPS operation or a GUI.

## One session and bounded state

`capture_operational` calls `run_streaming` exactly once, with the supplied
shared cancellation Event and the fixed 35/15/2-second startup, progress and
termination policies. It supplies no lifetime timeout and performs no retry.
The runner retains responsibility for executable/dependency admission, one
process group, bounded dispatch, rate limits, real pipe EOF and reaping.

The sink uses `OperationalFramer` and `OperationalStreamValidator`. It retains
one bounded pending line, the last sample, count and end, one minimum observation
timestamp, an observed-field set bounded by the fixed field allowlist and fixed
metadata. It does not tail or reread files, retain sample lists or persist raw
stream bytes. The runner's admitted empty capture files are not feed logs.

A nonempty chunk returns `True` only after at least one eligible sample has
successfully completed atomic publication and cancellation has not been
requested by its completion. `ups.status` must be observed within 10 seconds of
current monotonic elapsed time. The minimum timestamp of all currently observed
non-static fields must strictly exceed the last successfully published minimum.
The observed-field baseline is a union, including ineligible samples: an old
new field prevents progress until refreshed, and later removing it cannot renew
health. Cached repeats, missing status, stale status, static-only samples and
shrinking observed-field sets return `False`. Parser or clock failure latches
`protocol_error` and sets cancellation. Native failure End reasons are retained
before a later runner failure can replace them.

## Stop and publication order

The caller requests Stop with `cancel_event.set()`. That operation takes no
capture lock, waits for no callback and does not promise to interrupt file I/O.
Under a short state lock the sink checks cancellation and reserves an eligible
active operation. This reservation is the operation's start. A Stop racing after
that reservation can leave that single already-admitted write in flight, even
before its publisher call executes. Its return cannot renew progress after Stop.
No active operation is admitted after cancellation is observed at reservation.
Publisher and injected clock calls execute outside state locks.

Capture admits, constructs and starts its sole daemon finalizer once, before
invoking the runner. Construction and start failures are latched in a retained
result and never retried; the runner is not invoked after such an admission
failure. This prestarted worker waits on one Event. Terminal publication requires
the independent runner consumer-quiesced fact and no active in-flight
reservation. Capture or observation can then notify that worker to attempt
terminal publication once and close the publisher once. Capture may join a
notified finalizer for a finite 0–2-second budget. Observation never constructs,
starts or joins a thread, calls publisher I/O, signals a process, restarts a
worker or retries I/O. Its runner observer retains its existing bounded
nonblocking drain for late EOF facts. An arbitrary publisher can block;
that leaves the owner retained and terminal publication unattested. A successful
terminal call is separately recorded from publisher closure and finalizer
termination. No new session is admitted until all ownership is resolved.

`stopped/cancelled` requires requested cancellation, runner trigger `cancelled`,
return code zero, validated native End `cancelled`, all five independent runner
cleanup facts and no prior failure. Native End `cancelled` is interpreted under
the v2 contract as emitted after native cleanup; this module neither manufactures
that End nor proves the unimplemented native lifecycle. Native qualification is
**OPEN**. Missing End, spontaneous zero exit, native failure End or nonzero exit
cannot produce clean Stop.

## Retention and late observation

There is one module-global retained owner, protected by nonblocking admission.
Concurrent starts fail with `capture_active`; starts after an unresolved return
fail with `capture_ownership_unresolved`, before publisher construction or runner
invocation. Retention includes a blocked active callback, runner ownership,
publisher descriptors and a blocked finalizer.

`observe_operational_ownership()` uses the runner's bounded, nonwaiting ownership
observer only for a runner that this capture actually invoked. A late consumer
quiescence receipt may notify the already-started finalizer. Another observation sees its
completion and returns the updated fixed-size result, releasing the global slot
only when runner ownership, actual finalizer termination and publisher close all
resolve. The next observation returns `None`. If failure was already published
while other process cleanup remained unresolved, late cleanup does not rewrite
it as success or publish another terminal envelope.

No cleanup receipt after a runner exception means unresolved ownership, not an
inferred clean process. Both the idle prestarted finalizer and publisher remain
explicitly retained; no finalization command or close is permitted without a
quiescent receipt. A failed close is ambiguous: the descriptor number may
already have been consumed. Numbers are detached before each single close and
are never retried. An ambiguity retains an owner with failure information and
does not claim resolution. There is intentionally no automatic recovery path
for that case.

The receipt vocabulary includes the real runner's `output_incomplete` trigger.
Its eventual EOF receipt keeps that trigger and remains a failure; late cleanup
can release ownership without rewriting the failure or duplicating publication.
Diagnostic-only `runner_error` remains visible in `first_error`, while envelope
and result terminal reasons map to the publisher's existing `io_error` reason.

The terminal publisher samples a wall/monotonic pair after End. It requires
bounded timestamps, no monotonic regression, wall time at least start and last
successful publication, and the same one-second wall/monotonic consistency guard
as stream validation. An inconsistent pair fails without publishing a stopped
envelope or manufacturing a replacement timestamp. Publisher close still runs
after the independently proved consumer quiescence.

## Publisher admission correction

The v2 publisher retains the base class's directory admission, identity/ACL
rechecks, atomic replacement and 16,384-byte envelope cap. Its constructor now
tracks the two owned directory descriptors from `-1`, closes partial admission
once, and leaves no number available for a second close after identity failure.
`OperationalPublicationAdmissionError` carries the partial publisher only if a
close failed. Capture retains that object without invoking or observing a runner.
The v1 writer and v1 constructor remain unchanged.

## Caller seam

A future separately admitted v2 app adapter can keep the existing sole
control-pipe owner, turn STOP/EOF/signal into the shared Event, call this API once
and poll `observe_operational_ownership` after an unresolved result. It must keep
the module/owner alive and deny another session while retained. It must not
interpret runner quiescence alone, an attempted terminal write or a zero exit as
cleanup success. The existing v1 adapter and native/Swift profiles are not wired
to this candidate.

## Synthetic acceptance cases included

`test_operational_capture.py` supplies fake runner, publisher and clocks only.
It covers 700 virtual seconds, one runner call, constant retained structure,
cached/stale/shrinking and expanded fields, invalid records, Stop before and
during active publication, missing/failure End, nonzero/spontaneous exit, each
process ownership fact, late blocked-worker resolution, second-start rejection,
blocked final publication, first-error retention and terminal/close failure.
Blocked test workers are released and joined by their own test teardown.
Fake OS tests cover second-open failure, identity failure, idempotent close and
ambiguous close without descriptor retry. No test invokes Popen or native code.
Targeted revision tests preserve `output_incomplete` through late EOF, deny
constructor retry, spy against observer thread creation/start/join and caller
publisher I/O, validate the real terminal-reason vocabulary after late runner
and observer errors, and reject an inconsistent final clock pair. Fake unknown
receipt tests release their owned idle finalizer in teardown only after supplying
a test-only fake quiescence receipt; no such receipt is synthesized in production.
