# Runtime Coordination

`UPSRuntime` coordinates caller-supplied readers. It does not discover NUT
servers, launch drivers, poll hardware by itself, or own history storage.
Applications configure each backend reader and opt into a history sink
explicitly.

## Coordinator API

`MonitorCoordinator` accepts an asynchronous `read` closure returning a complete
`[MonitorSnapshot]`, an injectable `clock`, and an optional asynchronous sink.
The sink receives each validated snapshot and the explicit acquisition time.
Polling intervals must be finite and between 1 and 300 seconds. `refresh()` is
single-flight; an overlapping request returns the current immutable state
without starting another read. `start()` begins with an immediate refresh and
then waits one full interval after each attempt, so a slow read does not cause
catch-up bursts.

`stop()` cancels the scheduled task and active read task, advances a generation
fence, and marks cached samples stale immediately. A cancelled or non-cooperative
reader cannot commit a late result. A new read is not started while the previous
read is still unwinding. Cancelling the caller of `refresh()` is propagated to
the read task; a cancellation observed before commit preserves the previous
cache and does not invoke the sink. A sink operation that has already begun is
an external side effect and cannot be rolled back; later sink calls are skipped
after cancellation.

`MonitorCoordinatorState` contains immutable source snapshots, per-source
freshness, `maximumAge`, acquisition state, `lastAttemptAt`, `lastSuccessAt`,
`lastSuccessUptime`, polling/refreshing flags, and a separate storage-failure
flag. On a successful read the coordinator captures the injected finite,
nonnegative monotonic receipt time before replacing state or awaiting the first
sink operation. Cached state reads do not advance it. Acquisition
states distinguish idle, refreshing, success, successful no-sources, redacted
failure categories and stopped. Failure preserves last-known values and their
capture times but makes them stale; the coordinator never retimes cached data.
Freshness is evaluated against the injected wall clock whenever state is read.
Successful empty reads clear current sources and report `noSources`; they do
not fabricate a zero-valued sample. A sink failure does not invalidate a good
live acquisition. `lastSuccessUptime` is process-local receipt metadata; it is
not persisted to history or included in widget snapshots or energy export.

The app passes this receipt time to its memory-only `MonitorEnergyTracker` for
the selected source. Cached UI refreshes do not add energy; a failed/stale read
or invalid receipt time interrupts continuity. See the
[session energy tracker](ENERGY_TRACKER.md) and [energy UI](ENERGY_UI.md).

Before replacing state or invoking the sink, the coordinator validates every
snapshot, requires unique complete `MonitorSource` identities, rejects future
captures, and rejects a collection if any member is invalid. Errors and
upstream error text are not exposed in state.

## Apple Session Identity

`AppleSessionReader` is an actor with a random process-session ID. It uses
`kIOPSPowerSourceIDKey` only as an in-memory lookup key, maps it to random opaque
source IDs, and returns an `AppleSessionSnapshot` containing sanitized
`PowerSourceSnapshot` data. Native IDs and raw descriptions are not present in
the result. The existing ordinal one-shot probe is unchanged.

The mapping preserves opaque IDs when a uniquely identified UPS is reordered.
Missing, malformed, duplicate or absent identities retire their tokens; an
unavailable discovery resets all mappings. No ordinal fallback is used for
identity. Internal batteries remain excluded by `PowerSourceNormalizer`.
`AppleSnapshotRuntimeAdapter` turns a complete session result into model
snapshots with explicit session-local identity. It fails closed on unavailable
discovery or any present UPS whose identity could not be established.

The SDK describes `kIOPSPowerSourceIDKey` as a `CFNumber` of
`kCFNumberIntType` that uniquely identifies a power source. The value is not
treated as a serial number or durable identity across app launches, daemon
restarts or unobserved reconnects. Identity tests use synthetic dictionaries;
they do not call native readers.

## Probe Modes

`ups-probe` without arguments retains the original ordinal `PowerSourceSnapshot`
output. The explicit `ups-probe --session` mode performs one Apple session read,
adapts and validates the resulting `MonitorSnapshot` collection, then emits a
JSON array. Its opaque source IDs and session ID are process-local diagnostic
identifiers, not durable device identity. Native IDs and raw descriptions are
never emitted. Unknown arguments print a short usage message to stderr and exit
with status 2 without reading a provider; read, identity or validation errors
print only a redacted message to stderr and exit with status 1, leaving stdout
empty. Neither mode loops or launches a USB driver.

No runtime test proves physical-device compatibility. Native reads, storage
durability, app lifecycle behavior and WidgetKit integration remain separate
verification gates.
