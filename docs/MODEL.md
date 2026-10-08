# Shared Monitor Model

`UPSModel` converts the Apple power-source and NUT data snapshots into a small,
versioned record for app, history, and widget consumers. It is a pure mapping
layer: it performs no discovery, polling, storage, or network access.

## Identity and privacy

Every snapshot names one provider and one caller-assigned source ID and session
ID. Both IDs are opaque ASCII tokens of 1 to 64 bytes. Apple ordinal selection
is not hardware identity; callers provide a session explicitly. Configured NUT
IDs may remain stable across sessions when the caller has an explicit
configuration. The model has no device-name, serial-number, or vendor-dictionary
fields.

## Validation

Schema version 1 is the only accepted version. `validate()` checks source IDs,
finite capture time, the 64-metric limit, unique metric IDs, ID/unit pairs, and
value/quality consistency. Decoding a `MonitorSnapshot` performs the same
validation. Available measurements require a finite value; unavailable,
invalid, and calculating measurements require `nil`. Zero is a valid value.
Battery charge is expressed in percent from 0 through 100. UPS load is allowed
to exceed 100 percent. W and VA, measured and nominal values, and reported,
estimated, derived, and driver-derived provenance remain separate.

Apple's charge ratio is converted to percent. Apple time-to-empty and
time-to-full remain distinct estimates. Apple source current and temperature
retain explicit `appleSourceCurrent` and `appleSourceTemperature`
identifiers because they describe the source location, not necessarily the
battery. Apple adaptation requires an available snapshot and a selected present
UPS; internal batteries are rejected. NUT adaptation requires the caller's
source ID to match the decoded NUT source ID. Unknown or unqualified NUT status
is preserved as unknown; the adapter does not infer mains state from metrics.

## Freshness

Freshness is evaluated independently of metric quality with an explicit `now`,
maximum age, and acquisition result. Failed acquisition, an invalid age policy,
a future capture time, or an age beyond the limit yields `stale`. The evaluator
never changes the captured time or measurement values. Consumers must not use
stale samples for time integration.

Apple `internalFailure`, battery health, and charging state are retained as
optional typed status fields. An Apple source reported as offline is represented
with unknown mains state and the `sourceOffline` flag. NUT `OFF` does not prove
that mains are absent; it maps to unknown mains state and preserves the
`outputOff` flag. A status marked unavailable, invalid, or unqualified cannot
claim a qualified line state.
