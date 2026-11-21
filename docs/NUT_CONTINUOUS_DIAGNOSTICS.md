# Experimental bounded continuous diagnostics

This is an **experimental, default-OFF diagnostic candidate** for the existing
continuous NUT stream. It does not fix or identify the real USB failure, qualify
hardware compatibility, or authorize a device run. Existing hardware evidence,
source, executable, wrapper, gate, marker and freeze remain immutable.

## Additive scope and staging

`backend/nut/nut-hidapi-continuous-diag-v1-73c4502.patch` applies only to the
admitted H04 intermediate APC source. The sibling
`stage_hidapi_continuous_diagnostics.py` first uses the unchanged pinned H03
continuous stager, verifies the intermediate APC hash, and applies the additive
patch. It requires a new destination inside the real resolved TMPDIR, rejects
unsafe paths or changed inputs, and records `STAGED_UNBUILT` / build `NOT_RUN`.
No compilation or native execution is performed by staging.

```text
python3.15 stage_hidapi_continuous_diagnostics.py \
  --source <admitted-H03-source> \
  --inventory <pinned-H03-inventory.json> \
  --output <real-resolved-TMPDIR>/<new-absent-directory> \
  --compile-opt-in
```

The flag records the intended `-DMLINK_CONTINUOUS_DIAGNOSTICS_V1` compile
opt-in; it does not activate a runtime profile. Diagnostics also require the
existing continuous mode. No runtime option, transport operation, retry,
reconnect, guard change, command or dependency is added. Public continuous
helper structs, enum ordinals and serializers are unchanged.

The new additive patch subprocess uses the hash-checked sibling supervisor,
an absolute patch executable with its local invocation hash, a fresh owned
process group, a 20-second deadline, two-second termination grace and 1 MiB
combined output cap. The historical base stager remains unchanged: callers
must also bound the entire staging invocation. On failure, directory deletion
requires both proven child completion and the directory identity this call
acquired. UNREAPED results or uncertain exceptions preserve the output; a
JSON-escaped local stderr record identifies the retained path. Do not remove a
retained tree while child completion is unproven.

## Summary semantics

Only on ordinary stream return, after existing cleanup and the stdout end-write
decision, the opt-in code attempts one stderr line with prefix `MLINK_DIAG_V1`
and one JSON object. The full line is bounded to 4096 bytes, using a fixed
buffer and fixed keys/tokens. No raw bytes, field values, descriptor names,
object identifiers, addresses or paths enter this summary. There are no
per-sample diagnostic lines and no new clock reads.

Stdout remains the existing `ups-monitor.continuous.v1` NDJSON. The summary
distinguishes NEXT calls, receive results, scanner candidate checks, cache
admission, blob rebuild, descriptor capture and sample publication. Scanner
rejections count candidate evaluations, including repeated/overlapping checks,
not unique device reports. Ignoring an implausible page0 cache object can still
return a successful receive. A blob rebuild can contain previously cached data;
a published record is not necessarily a new observation.

Counters saturate at uint32 max. `saturated` means an increment was discarded
because the counter was already at max; merely reaching max does not set it.
Partition sums are censored at uint32 max; unsaturated partitions are exact.
Relative time values clamp at uint32 max and flag time saturation. `null` means
undefined, rather than an invented zero timestamp.

`last_poll_success` remains the original wall-clock value, assigned by both
handshake and poll success. It is labeled accordingly and is not monotonic
measurement age. Startup for the admitted fixture includes successful polls;
startup followed by silence therefore ends with source `poll`. The first
terminal branch token is separate from the unchanged final public reason.
Cleanup STOP, native-finish result and clock validity are reported separately:
native `released` is an API result, not electrical safety proof.

A formatting overflow has a fixed bounded marker; failed/partial stderr writes
do not request a retry or change the computed driver result. Dynamic fault
testing of those write paths remains OPEN. Summary absence after fatal startup,
crash, kill or blocked cleanup is missing evidence. It does not imply success.

## Dedicated fake-only host and harness

`backend/nut/replay_continuous_diagnostics.c` is a dedicated synthetic host,
separate from the existing legacy native replay file. Never link this host into
a real candidate. The fake-only build excludes native.c, real HIDAPI, IOKit and
CoreFoundation; local linkage inspection found only libSystem and no undefined
HID/IOKit/libusb symbols.

The fake supplies post-finish clock, startup/page cycles, cleanup failure and
cancellation cases. Its translation unit alone overrides time() and the
admitted NUT timestamp implementation's CLOCK_MONOTONIC clock to one scripted
clock. Empty reads consume the requested synthetic timeout. Complete page 1/2
cycles distinguish equal values with renewed provenance from cache-only and
unrelated-page refresh. Cancellation signals only the current fake process
after stream startup. There is no production session_ready injection.

Host events use reversible TOKEN*count encoding for consecutive equal events.
No events are filtered: decoded clock/read/wait/transport totals must match host
counters, the fixed trace must not truncate, and complete OFF/ON trace bytes
must match. No stderr normalization is used.

`test_continuous_diagnostics.py` takes already built OFF/ON fake paths and their
hashes. It explicitly loads hash-pinned sibling `process_deadline.py` and
`continuous_protocol.py`, including under Python `-I`; callers supply the
local env/supervisor/protocol hashes through required CLI arguments. Each fake
run is capped at 20 seconds, two-second grace and 1 MiB combined output, with
a fresh Event and owned group. Successful EXITED/completed is required before
parsing. At most 24 fake subprocesses are admitted; 24 * (20 + 2 + 1) = 552
seconds leaves 48 seconds under the required outer 600-second suite bound.
Captured output has a separate 32 MiB aggregate ceiling and remains in the
owned temporary tree for collection.

## Local validation and limits

The recorded local cycle passed:

- Fake-only diagnostics OFF and ON compilation, plus no-continuous syntax.
- Ten diagnostic tests with 24 fake executions: strict stdout-v1 parsing,
  OFF/ON stdout/return/complete-trace identity, fresh equal-payload cycles,
  cache-versus-rebuild provenance, corruption versus the healthy schedule,
  ignored-cache receive semantics, idle/cancellation/clock terminal branches,
  cleanup outcomes and strict summary schema mutations.
- Seven stager mock-test methods (eight subcases), with no child process
  launched by the mocks: completion-gated deletion, unreaped/uncertain retention
  and directory ownership/replacement boundaries.
- One real offline staging invocation, producing the same APC source hash as
  the locally compiled diagnostic candidate.

These are local recorded results on the admitted macOS/Xcode inputs and private
Python 3.15.2 interpreter. Hosted CI has **NOT_RUN**, and portable reproduction
on another toolchain/OS is **NOT_DEMONSTRATED**. The existing legacy replay path
was not repaired or requalified by this dedicated-host addition.

Actual C formatter maximum-state/null-state, counter/time saturation boundaries,
partial/failed stderr writes and forced overflow-marker execution remain
**OPEN**. Python schema mutations are not C formatter execution evidence.
The pinned backend's device-lost stub and source-bound session-not-ready branch
are not established by these fixtures; pre-stream missing handshake correctly
has no summary. No branch is made reachable by changing production state.

No real candidate, USB/HID device, UPS control, GUI, firmware or electrical
behavior was exercised. Hardware qualification, a later separately approved
campaign, and release readiness remain separate work.

## Qualification update, 2026-10-26

The C formatter helper checks and the public-source OFF/ON fake replay have
passed the scoped local checks. See [the detailed evidence boundaries](CONTINUOUS_OFFLINE_QUALIFICATION.md).
The formatter overflow fallback and physical SIGPIPE were not exercised; a
source-width bound and append-buffer test are recorded separately. No new UPS
execution or live-continuous qualification follows from these results.
