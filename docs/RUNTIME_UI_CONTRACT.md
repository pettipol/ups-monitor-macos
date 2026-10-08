# Runtime and Native UI Contract

P2/P3 work contract. Native monitoring may use the existing IOPowerSources
service. No experimental USB driver, daemon or hardware control is launched.

## Apple Session Identity

The installed Apple SDK documents `kIOPSPowerSourceIDKey` as a CFNumber of
`kCFNumberIntType`, uniquely identifying a power source (`IOPSKeys.h`). This
is not a serial number or a documented permanent identity across restarts.
The existing one-shot probe keeps its ordinal schema unchanged.

A new actor-based session reader maps valid native IDs to random opaque
source IDs in memory only. It emits normalized, sanitized telemetry, never
native IDs, names, serials or raw dictionaries. Reordered enumerations keep
the same opaque IDs. Missing, malformed or duplicate native UPS IDs fail
closed for the affected observation; no ordinal fallback for history.
Mappings are retired on absence, unavailable discovery or identity ambiguity;
a later reappearance receives a fresh opaque ID. App launch also starts a new
session. This qualifies source identity only within the observed session,
not hardware persistence across daemon restarts or unobserved reconnections.
Do not select/merge UPS devices by name, charge or voltage similarity.

## Acquisition

Use a testable actor-based coordinator with injected async read, wall clock and
optional history sink. It operates on a validated collection of MonitorSnapshot
values. Callers configure backend readers separately; the coordinator does not
find servers or start drivers. Each backend has its own coordinator.

- At most one read in flight, including manual refresh and scheduled polling.
- Polling interval bounded to 1...300 seconds, no catch-up bursts after wake.
- Stop cancels the polling and read tasks, invalidates late completions and
  immediately marks cached data stale. No new read until the old read unwinds.
- Validate complete collections before replacing state or writing history:
  valid schema, exact source uniqueness, finite non-future capture times.
- Failed, cancelled and malformed reads preserve the last good capture time
  and values but mark them stale immediately. Never retime the cache.
- A successful empty collection is no-sources, not a fabricated zero sample.
  Disappearance retires native identity and leaves a history gap.
- History receives only validated successful acquisitions, with explicit `now`.
  A storage error is separately visible and does not turn a good live read into
  a failed measurement. History is opt-in at the application layer.
- Immutable Sendable state exposes last attempt, last success, acquisition
  state, last-known samples and redacted read/storage error categories.
- Deterministic injected tests cover concurrency, cancellation, stale state,
  malformed collections, absence, persistence errors and session changes.

This is not yet permission to integrate driver-derived power. The energy
module remains disconnected until a power field's semantics are qualified.

## Native UI

Use system SwiftUI/AppKit and SF Symbols, without web assets or new packages.
Keep rendering separate from acquisition. The menu shows selected-source
charge/status/age and refresh/open-details commands. The details window offers
source selection, grouped measurements, their units/quality/provenance, and
history rendering/export commands only when a functional handler is supplied.

Every absent field reads as not reported, never zero. Current source, cached
stale data and no-source/error states must be visually distinct. Preserve
battery/input/output location, W versus VA, runtime as an estimate, and
driver-derived labels. Provider/session labels must not expose native IDs.
No control for shutdown, battery test, calibration, reset, firmware or USB claim.

Use a compact, scan-friendly native layout, light/dark adaptive system colors,
stable columns, wrapping labels, keyboard navigation, VoiceOver labels and
tooltips for icon commands. No marketing page or feature-explanation copy.
Synthetic preview mode must be visibly labeled and must perform no live reads
or persistent history writes. It is not evidence of physical compatibility.

The containing app will use a small Xcode project and local Swift package
products, leaving room for a real WidgetKit extension and App Group later.
Source compilation, app launch, visible behavior, signing and widget
registration remain separate evidence gates.
