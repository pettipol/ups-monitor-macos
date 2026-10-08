# Architecture

## Scope

The application is a read-only monitor. Apple power-source APIs and NUT are
independent telemetry providers. The app never replaces the operating system's
shutdown protection and does not send UPS control commands.

## Components

| Component | Responsibility |
|---|---|
| UPSCore | Typed snapshots, units, availability, provenance and data-quality rules |
| ApplePowerSource | Read the documented IOPowerSources service; filter UPS from internal batteries |
| UPSProbe | Sanitized, one-shot capability inspection, without opening USB interfaces |
| UPSEnergy | Pure integration of validated active watts, source binding, monotonic coverage and replay rejection; connected to the app's memory-only session tracker, with live watt qualification open |
| NUTData | Decode native upsc JSON or explicit text fallback into an allowlisted, typed snapshot; no I/O |
| NUTClient | Bounded direct upsc execution on explicit loopback endpoints; requires a separately qualified completion-hardened client |
| UPSModel | Versioned app/storage snapshot, strict units and identity, Apple/NUT adapters, independent freshness evaluation |
| UPSHistory | Actor-serialized SQLite storage, transactional retention, bounded session catalog/keyset pages, exact-page export and explicit deletion |
| UPSMonitorUI | Pure menu/details rendering and selectable metric charts with source, provenance and gap isolation; visual qualification open |
| UPSRuntime | Validated single-flight acquisition, cancellation/drain, stale cache, optional history sink, digest-checked NUT adapter and pure bounded alert evaluation |
| macOS app | Menu, details, opt-in recording/alerts, bounded stored-session browser/export, native acquisition and explicit local NUT settings; isolated synthetic preview |
| UPSWidgetData / UPSWidgetBridge | Validated private atomic snapshot, entitlement-matched group configuration and bounded publication/reload requests |
| UPSWidgetUI / Widget extension | Small/medium capture views with age; read-only cache provider, no USB access or independent sensor polling; installation still unqualified |

Do not join measurements from different sources or different UPS devices by
display name. Device selection and source identity must be explicit. Generic
probe IDs describe one enumeration; they are not permanent hardware identity.
Each provider session is caller-assigned. Native source-offline, output-off
and unknown input mains state are distinct. The storage API requires an
explicit private location; it never scans existing user databases. See the
[model/storage contract](MODEL_STORAGE_CONTRACT.md) for clock, identity,
privacy and export boundaries.

## Measurement Rules

- Keep active power (W), apparent power (VA), battery charge (%) and energy (Wh)
  distinct. A nominal rating is not a current measurement.
- Missing, invalid, unsupported, estimated and stale states are not zero.
- Preserve input/output/battery measurement locations and upstream provenance.
- Derived upstream fields remain derived in the app. Do not invent an accuracy
  specification from the number of decimal places in a raw value.
- Never label the experimental Microlink energy register as kWh without proven
  units, reset behavior and measurement location.
- Integrate power only across valid covered intervals using elapsed time;
  report gaps instead of bridging sleep, disconnections or source changes.
- Estimates describe the data actually sampled, not guaranteed runtime or
  complete household input energy consumption.

The app tracks `inputRealPower` as `Input` and `upsRealPower` as `UPS`, each in
its own application-estimated Wh accumulator. `UPS` is not an output-location
measurement. Coverage, breaks and accepted watt provenance remain attached to
the estimates. Tracking is memory-only, independent of history recording, and
the separate schema-version-1 export does not turn the estimates into history.
The current app wiring has not yet passed full-suite qualification, and no live
UPS/APC watt measurement has been qualified.

## Lifecycle and Security

Native reads go through the existing macOS service. Driver initialization and
polling are a separate qualification activity because they can claim USB
interfaces or send output reports even when the intended operation is a read.

NUT client support must not expose a generic command executor. Start with
loopback-only configuration, not remote endpoints or subnet scanning.
Validate bounds, numeric values, encodings and quoted strings. Restrict logs to
sanitized error categories. Remote transport and authentication must have an
explicit security policy before remote credentials are supported.

Snapshots shared with WidgetKit use a versioned, atomic format. Widget refresh
is system-scheduled; it is never presented as guaranteed real-time monitoring.
App Group and signing behavior must be tested on macOS, not inferred from a
successful compile.

## Upstream Reuse

Keep NUT independently versioned. Prefer upstream fixes for driver issues;
do not fork the protocol just to make a UI. Review maintained client libraries
before implementing even a narrow NUT protocol reader. Audit licensing before
copying, linking or distributing any upstream code.
