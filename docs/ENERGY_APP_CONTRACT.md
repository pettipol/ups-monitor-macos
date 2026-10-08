# Session Energy Estimates Contract

Reuse `EnergyIntegrator`; do not implement a second numerical integrator.
Calculations are application estimates from upstream active-watt data, not
meter readings, billing totals or complete household input consumption.
No experimental energy register, charge percentage, apparent power, nominal
rating, guessed power factor or watts inferred from generic load percentages.

## Pure Tracker API

In UPSEnergy add `MonitorEnergyChannel: String, CaseIterable, Encodable, Sendable`
with `.input` (inputRealPower) and `.ups` (upsRealPower); do not call ups.realpower
an output-location measurement. Add `MonitorEnergyState: String, Encodable,
Sendable` cases unavailable, collecting, estimated, paused.

`MonitorEnergyEstimate: Equatable, Encodable, Sendable` has public let fields and
initializer: `channel`, `source: MonitorSource?`, `state`, `energyWh: Double?`,
`coveredDurationSeconds: Double`, `gapOrBreakCount: Int`,
`firstCapturedAt: Date?`, `lastCapturedAt: Date?`,
`powerProvenances: [MonitorMetricProvenance]`.
energyWh is nil until at least one interval is covered; zero Wh with positive
coverage is valid zero-load integration, not missing energy. Dates describe
accepted power samples, not a guarantee of continuous coverage between them.
Provenances list observed accepted watt provenance, in deterministic order.
No coverage percentage or unmeasured tail duration is inferred.

`MonitorEnergyTracker` has `init()` with fixed maximum gap/freshness 10 seconds
and wall/monotonic disagreement tolerance 1 second, `reset()`, `pause()`,
`summaries: [MonitorEnergyEstimate]` always input then ups, and mutating
`observe(snapshot: MonitorSnapshot?, acquisitionSucceeded: Bool, now: Date,
monotonicSeconds: TimeInterval)`. One exact source/session, two channels only.
No I/O, persistence, unbounded channel/token history or synthetic telemetry
in normal operation. UPSEnergy may depend on UPSModel; no I/O modules.

Validate snapshot/time/freshness and available status without sourceOffline.
Read only the channel's available finite nonnegative watts with exact unit.
Accept provenance without relabeling it as physically calibrated; derived and
estimated input remains explicitly listed. State includes observed data quality.
An identity change resets totals only after admitting a valid, fresh, available
snapshot from a successful acquisition, never merges them. Rejected foreign
snapshots pause continuity without erasing the current session's totals.
Identical capture times with unchanged content are harmless cached UI refreshes,
not new integration samples; replayed/changed-at-same-time data must not count.
Older timestamps break continuity without replacing the capture high watermark.
Use monotonic receipt time supplied by the runtime; UI time never adds energy.

Fresh missing/invalid watt data, failed/stale reads and pause break continuity
once per outage per started channel, preserve existing totals and mark paused.
No eligible power ever observed => unavailable. First eligible sample or
zero covered intervals => collecting, never zero Wh claimed as measured.
Provenance changes break before reprime so intervals never straddle provenance.
Long gaps, invalid clocks and arithmetic overflow must preserve finite totals
and never bridge missing intervals. Recovery requires an advancing new capture;
a cached sample cannot restart a paused segment. Reset removes all totals and
watermarks. Add `EnergyIntegrator.interrupt()` to expose its existing continuity
break without manufacturing a sample; coalesce calls in tracker, not integrator.
The integrator may gain Sendable conformance for its value-only fields.

## Runtime and App

Coordinator records an injected finite nonnegative monotonic receipt clock
alongside each successful batch, before awaiting any storage sink. Expose
`lastSuccessUptime: TimeInterval?` in state; cached UI reads preserve it.
Invalid receipt clocks fail acquisition without replacing last successful data.
This timestamp is process-local and not written into telemetry/history/widget.

The app updates the tracker from selected, successfully acquired state and
that batch's receipt time. Failed, stale, absent sources interrupt it. Selection
and backend replacement reset totals; sleep and stop pause before awaiting I/O.
No history opt-in is needed for memory-only estimates. Reset is an explicit UI
action with confirmation. Preview remains synthetic and never reads hardware.

JSON export is explicit, bounded to the displayed two estimates, labeled
`schemaVersion: 1` and `quality: applicationEstimated`, with `generatedAt` and
`estimates`. It contains no connection path, serial, hardware name or absolute
system uptime. It is a separate session estimate export, not a migration of
history schema or a historical meter reading. The widget schema is unchanged.

## UI and Evidence

Pure `UPSEnergySummaryView(estimates:onReset:onExport:)` in UPSMonitorUI; both
callbacks optional @MainActor @Sendable () -> Void. Render an unframed section
with input and UPS estimates, Wh (not VA or percent), collecting/unavailable/
paused state, covered seconds, break count, power-data provenance and sample
dates. Missing energy is never shown as 0. Label all values estimated. Native
icon actions with help/accessibility; reset confirmation. No data access.
Root integrates it into DetailsView and app. No marketing or tutorial text.

Synthetic tests cover different input/UPS power, zero vs missing, irregular
sampling, gaps, provenance, duplicate/replayed timestamps, clock disagreements,
reset, source/session switches, overflow, invalid source/metric/time and UI
formatting. Coordinator tests prove receipt time before delayed sinks and no
change during cached reads. Host tests prove lifecycle/selection/history/preview
isolation and export fields. No claim of real APC energy until watts, timing,
measurement location and physical comparison are qualified separately.

## Clock Privacy Review

The default receipt clock uses Foundation `ProcessInfo.systemUptime`, documented
as awake time since restart. Its absolute value stays in process memory and is
not part of history, widget snapshots or energy exports. Coverage exports only
durations derived from accepted intervals. Apple flags this API for privacy
review; there is no fingerprinting or cross-app identity use here.

This is not a completed privacy-manifest or distribution-compliance audit.
Before release, review all used APIs and dependencies against the applicable
platform and distribution requirements. The general required-reason guidance
lists iOS/iPadOS/tvOS/visionOS/watchOS, which alone does not establish a macOS
manifest requirement. No unverified approved-reason code is asserted here.

Primary sources checked on 2026-10-08:
[systemUptime](https://developer.apple.com/documentation/foundation/processinfo/systemuptime),
[required-reason API guidance](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api).
