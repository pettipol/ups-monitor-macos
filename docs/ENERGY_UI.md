# Energy Estimate UI

`UPSEnergySummaryView` is a pure presentation of the two in-memory
`MonitorEnergyEstimate` values supplied by its caller. It performs no reads,
integration, persistence, or export itself. The channel names are `Input` and
`UPS`; the latter is not described as a physical output-location measurement.

Energy appears in Wh only when a finite nonnegative estimate and positive finite
covered duration exist. Missing or invalid energy is shown as unavailable, never
as zero. Zero Wh remains visible when the tracker reports covered time. Extreme
finite values use compact scientific notation. Each row keeps tracker state, covered
seconds, break count, watt provenance, and accepted sample dates visible, and
labels the value as estimated. It does not infer coverage percentages or claim
continuous measurement between dates.

Rows expose a combined VoiceOver label containing channel, state, Wh, coverage,
provenance, and sample dates. Nonfinite or reversed sample dates are shown as
unavailable. Export and reset controls have explicit accessible labels; reset
opens a confirmation dialog before invoking its callback.

Reset requires confirmation. Export and reset are optional `@MainActor`
callbacks; the parent owns their effects and the view does not construct or
write an export payload. Tests exercise formatting and stored view inputs only;
they do not constitute visual-layout verification.
