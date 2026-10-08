# Session Energy Tracker

`MonitorEnergyTracker` integrates only validated active real-power metrics:
`inputRealPower` for the input channel and `upsRealPower` for the UPS channel.
The latter is not labeled as an output-location measurement. The tracker uses
the existing trapezoidal `EnergyIntegrator` with a 10-second maximum interval
and 1-second wall/monotonic disagreement tolerance. These values are application
estimates, not meter readings or billing totals.

The tracker has two fixed accumulators and one exact source/session identity.
A source change resets both totals before accepting new data. The integrator
receives a stable source/session token; gaps and provenance changes interrupt
continuity without growing token history. Each channel is independent: missing
input power pauses only input, while valid UPS power can continue.

No eligible power means `unavailable`. A first eligible sample is
`collecting`; `energyWh` remains absent until an interval is covered. Covered
zero-load intervals produce a valid `0` Wh estimate. Coverage seconds count
only accepted intervals, and first/last dates describe accepted power samples,
not guaranteed continuous coverage between them. Provenance is retained in a
deterministic order without relabeling derived or estimated values.

Fresh missing/invalid data, failed or stale acquisition, offline status, clock
disagreement, long gaps, explicit pause, and old captures break continuity.
Repeated interruption during the same outage increments the break count only
once per channel. Totals remain finite and are preserved across pauses; a new
advancing eligible capture reprimes a segment, and only a subsequent valid
sample can add coverage. An unchanged cached snapshot is a no-op, not an
integration sample; a regressing receipt clock still breaks even for a cached
capture. Conflicting payloads at the same capture time break continuity and
are not counted. Future captures break continuity without advancing the
capture high-water mark, and invalid or unadmitted foreign snapshots do not
change the bound source or its watermark; they do pause the active continuity.
A foreign source change is admitted only from a valid, fresh, available and
non-offline snapshot with a successful acquisition. Older timestamps do not
lower the capture high-water mark. A
provenance change breaks before reprime so an interval never spans provenance.

The tracker is in-memory and performs no I/O. It does not infer a coverage
percentage, unmeasured tail energy, household consumption, or physical
calibration. Tests use synthetic snapshots only; no real UPS power source has
been qualified here.
