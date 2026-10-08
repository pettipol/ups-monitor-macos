# UPS Monitor Mac

An open-source, local-first macOS UPS monitor in early development. It reuses
Apple power-source APIs and Network UPS Tools instead of implementing a new UPS
USB protocol. Original code is MIT licensed; upstream software retains its license.

Scope: menu-bar monitoring, detailed measurements, desktop widgets, local history
and export. Implementation and qualification status are listed below. No UPS
control commands, required cloud service, accounts or telemetry.

## Status

**Source-only preview.** No installable release is available, and real advanced
UPS telemetry, interactive app behavior and installed widgets remain unqualified.

The Swift package includes a read-only Apple capability probe, a tested
energy-integration module, an allowlisted NUT JSON decoder, a bounded
loopback client adapter, a shared snapshot schema and local SQLite history
with JSON/CSV export. A native app host now connects Apple session acquisition,
menu/details views and opt-in history. A separate bounded browser selects retained
sessions, plots individual metrics with explicit gaps, and exports the displayed
page. Browsing does not enable recording or change the live selection.
Optional session-only local alerts cover line changes, low battery and loss of
monitoring. They default off and are not a replacement for shutdown protection;
actual macOS permission and banner presentation remain unqualified.
The local app build succeeds;
interactive UI and live-history qualification remain open. Session-only settings
can select one loopback NUT source using an explicitly completion-qualified
client and matching SHA-256; the app never installs or starts a driver/server.
The project now embeds a small/medium WidgetKit extension with a validated shared
snapshot path; signed App Group access and desktop widget installation remain
unqualified. The default local build deliberately has no App Group configured.
There is no released app or qualified
advanced USB backend yet. Native charge reporting does not prove access to AC
voltage, active power or energy. The energy module is tested on synthetic active
power, not on a qualified live watt reading from the target UPS.

The app now connects session energy estimates to the selected source using
separate `inputRealPower` and `upsRealPower` channels. Estimates remain in memory,
retain covered time, breaks and watt provenance, and can be exported separately
from history while history recording is off. Synthetic integration tests cover
the application wiring but do not qualify real watt telemetry or an
APC measurement path. See [energy tracker](docs/ENERGY_TRACKER.md) and
[energy UI](docs/ENERGY_UI.md).

The source preview includes a [compatibility matrix](docs/COMPATIBILITY.md),
[Italian guide](docs/GUIDA_ITALIANA.md), [privacy/data policy](PRIVACY.md),
[third-party notices](THIRD_PARTY_NOTICES.md) and [contribution guide](CONTRIBUTING.md).
The [pinned CI workflow](docs/CI.md) passed its first GitHub-hosted run with
229 Swift tests passed, 2 optional NUT interop tests skipped, and 11 Python tests
passed, plus Release builds and ad-hoc signature checks. There is no public
release or verified distribution artifact yet.

## Build and Inspect

Use Xcode 27 with Swift 6.4 on macOS. The package currently targets macOS 14+, but
the live probe has only been checked on macOS 27.0.1 / Apple Silicon.

For the pinned synthetic tests and build sequence, see
[local validation](docs/VALIDATION.md). It does not launch the app or probe:

```sh
bash scripts/check.sh
```

```sh
swift test
swift run ups-probe
swift run ups-probe --session
```

Build the development app (ad-hoc signed, not a notarized release):

```sh
xcodebuild -project UPSMonitor.xcodeproj -scheme UPSMonitor \
  -configuration Debug -derivedDataPath .build/app build
open '.build/app/Build/Products/Debug/UPS Monitor.app' --args --synthetic-preview
```

The explicit synthetic preview performs no live reads or history writes.
Launching without that flag uses the existing Apple power-source service only,
not a NUT driver. History recording defaults off. No startup service is installed.

The probe enumerates the existing macOS power-source service and emits a
sanitized JSON snapshot. It does not open USB interfaces or launch a driver.
An unavailable metric is not zero. Runtime estimates are suppressed outside the
documented discharge context. Generic source IDs are enumeration-local, not
stable hardware identities for cross-session history.
The explicit `--session` mode exercises the app's sanitized session reader and
shared schema once, using opaque process-local IDs. It still uses only the
existing Apple service, never a USB driver.

See [native observations](docs/NATIVE_BASELINE.md),
[NUT build and safety analysis](docs/NUT_FEASIBILITY.md),
[NUT data semantics](docs/NUT_DATA.md),
[shared application model](docs/MODEL.md),
[history and retention](docs/HISTORY.md),
[history browsing and pagination](docs/HISTORY_BROWSING.md),
[historical metric plots](docs/HISTORY_PLOT.md),
[session energy tracker](docs/ENERGY_TRACKER.md),
[energy estimate UI](docs/ENERGY_UI.md),
[optional alert policy](docs/ALERT_POLICY.md),
[alert delivery and limits](docs/ALERT_DELIVERY.md),
[acquisition lifecycle](docs/RUNTIME.md),
[native UI](docs/NATIVE_UI.md),
[application host and qualification](docs/APP_HOST.md),
[local NUT configuration contract](docs/NUT_APP_CONTRACT.md),
[NUT runtime reader](docs/NUT_RUNTIME.md),
[widget signing and qualification](docs/WIDGET_SIGNING.md),
[client completion qualification](docs/NUT_CLIENT_COMPLETION.md),
[experimental driver guards](docs/NUT_GUARDS.md),
[architecture](docs/ARCHITECTURE.md), and [release gates](docs/RELEASE_CHECKLIST.md).

## Safety

This is a monitor, not a replacement for an operating system's UPS shutdown
protection. Do not disable existing power-management services to use it.
Experimental NUT drivers require model-, firmware- and platform-specific testing.

## Contributions

Use synthetic fixtures when reporting issues. Do not upload hardware serial
numbers, network addresses, credentials or unredacted system dumps.
