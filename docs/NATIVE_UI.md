# Native Monitor UI

`UPSMonitorUI` contains pure SwiftUI rendering for the menu and details window.
It accepts snapshots and callbacks; it does not read power sources, start
polling, open history storage, or perform exports itself.

`UPSMenuContentView` displays the selected source's generic UPS label, line
state, charge, runtime estimate, freshness, and refresh/details actions. When
multiple sources are present, its native picker reports only an ordinal label
and provider. `UPSDetailsView` groups battery, input, output, UPS, and
Apple-source measurements. Missing metrics read as “Not reported”; reported
zero remains zero. Units, quality, provenance, status quality, charging,
health, internal-failure state, and status flags remain explicit. Source
current and temperature are kept distinct from battery measurements, real
power uses W, apparent power uses VA, and runtime remains an estimate.

The `sourceKey(for:)` helper is intended for internal selection persistence;
the key is never rendered. Freshness is recalculated from the supplied `now`,
`maximumAge` (15 seconds by default), and acquisition-success state. A failed
read or stale capture is labeled separately from an empty source collection.

History is optional. When supplied, the details view offers a metric picker
and plots samples for the selected source using Swift Charts. Missing values,
capture gaps and provenance changes split line segments; valid single samples
have point marks. W, VA and each voltage location remain separate metrics.
The stored-history browser reuses the same pure chart without changing the live
source. Export and clear controls appear only when their corresponding handlers
exist; clearing asks for confirmation. Colors use adaptive system styles and
commands use SF Symbols or native labels. See [plot semantics](HISTORY_PLOT.md).
Actual rendering and accessibility interaction remain unverified.
