# Native App Host

The Xcode project builds the native SwiftUI menu and details application using
local Swift package products. The shared `UPSMonitor` scheme has no remote
package dependencies. SwiftPM additionally compiles the same controller source
in `UPSAppHost` for synthetic unit tests; it does not launch a GUI.

## Acquisition and Storage

Normal launch configures `AppleSessionReader` with one coordinator, a five-second
poll interval and ten-second freshness limit. UI state is refreshed once per
second. A session-only settings sheet can switch to one explicit local NUT
source after executable/digest preflight. The expected digest and a separate
completion-qualification acknowledgment are required; neither a version string
nor the acknowledgment alone qualifies a client. No driver launcher, login item,
daemon, remote notification registration or UPS control is included.

Selecting a file does not execute it. Failed preflight keeps the current backend;
a failed NUT read never silently falls back to Apple. Switching cancels and waits
for the previous owned read, clears selection/displayed history, and fences its
late callbacks. Each new NUT reader receives random opaque source/session IDs.
Connection drafts are not persisted or exported. The settings UI and file-picker
interaction are not yet visually qualified. See [the application contract](NUT_APP_CONTRACT.md)
and [reader checks and limits](NUT_RUNTIME.md).

History is off at each launch. Enabling it opens the private SQLite store under
the user's application support directory, `UPSMonitorMac`. Disabling recording
does not delete data. The live details view and its exports query the selected
source's current session over the past hour. A separate stored-history browser
opens the same private store without enabling recording or changing live source
selection. It lists up to 100 recent sessions with an explicit truncation label,
offers hour/day/week/session ranges anchored to the selected session's final
capture, and pages through at most 2,000 samples at a time.

The browser's JSON/CSV export uses exactly the displayed page, including all
typed metrics, rather than rerunning a query. Save-panel actions are explicit.
Session deletion and all-history clearing have separate confirmation dialogs;
database clearing is not a claim about SSD blocks, filesystem snapshots or
backups. The catalog and pages are not a transactionally frozen view across
concurrent appends or retention. See [history browsing](HISTORY_BROWSING.md).

## Session Energy Estimates

The app connects the selected source to the in-memory `MonitorEnergyTracker`.
It keeps `inputRealPower` (`Input`) and `upsRealPower` (`UPS`) in separate Wh
estimates; `UPS` is not an output-location measurement. Estimates retain only
covered seconds, break count, accepted sample dates and upstream watt provenance.
Missing values remain unavailable, and the values are application estimates,
not meter readings, billing totals or complete household consumption. The
coordinator's monotonic receipt time is supplied before any history sink wait;
cached state reads do not add intervals.

An explicit, confirmed reset clears both estimates for the selected source and
session. Changing the selected source or replacing the backend resets estimates;
sleep and app stop pause continuity. Tracking is memory-only and independent of
history recording, so history may remain off. The separate JSON export contains
the two current estimates with `schemaVersion: 1`, `quality: applicationEstimated`
and a generation time; it is not a history export. Synthetic host tests cover
selection, backend reset, failed reads, explicit reset, stop, preview isolation
and export fields with history off. These do not qualify a live watt reading,
APC behavior or the rendered energy UI. See [tracker rules](ENERGY_TRACKER.md)
and [energy presentation](ENERGY_UI.md).

Successful appends invalidate the relevant history view, and request generations
prevent an older query from overwriting newer results. Stop is terminal for an
app-controller instance: it rejects new operations and late state updates,
waits for the owned read to unwind, removes workspace observers and closes the store. An already
admitted database transaction may finish before close; it is not rolled back by
task cancellation. Sleep stops the coordinator; wake retires native identity
before starting a fresh Apple observation; the configured NUT session is not a
claim of physical identity across sleep. Normal application termination is
routed through the same stop path by an AppKit delegate, including the menu quit
command. Forced process termination is not intercepted. Physical sleep/wake and
the delegate's actual GUI termination path are not yet tested.

## Synthetic Preview

`--synthetic-preview` is explicitly labeled in the menu and details. It uses
fixed synthetic measurements and history, does not call native readers and
does not create persistent history. It is a static rendering preview, not an
emulation of elapsed-time behavior or evidence for real power/voltage readings.

## Optional Local Alerts

Local alerts default off at every launch. Explicit enable requests only alert
permission; the app does not access Notification Center before opt-in. Preview
cannot enable alerts. Session settings choose line changes, low battery with a
5...50% threshold, and monitoring loss. Only the selected source is considered.
Stale or invalid data never proves mains restoration, and monitoring loss is
distinct from a power outage. See [policy semantics](ALERT_POLICY.md).

One owned asynchronous task sends observations to the delivery controller, so
OS notification delivery cannot freeze the live freshness clock or accumulate
a backlog. Explicit source selection, backend replacement and sleep suspend observations;
normal quit drains admitted delivery before clearing this feature's identifiers.
Policy changes and suspension preserve per-kind cooldowns. Already admitted OS
requests may finish before cleanup; cleanup is not guaranteed physical erasure.
Revoked permission is checked before submission and disables the feature when
detected. No background alert guarantee exists after the app exits or sleeps.

The native delivery requests foreground banner/list presentation for its own
identifiers, with no sound, badge, action, attachment or userInfo. Payloads use
generic text and capture time, without hardware identities. These informational
alerts are not shutdown protection. Focus, System Settings and macOS determine
actual presentation. Test doubles qualify policy and lifecycle, not real
permission prompts or banners; see [delivery limits](ALERT_DELIVERY.md).

## Current Qualification

The source builds with Xcode 27 / Swift 6.4. The local Release bundle contains
arm64 and x86_64 slices. Its ad-hoc signature verifies and includes the runtime
flag, but has no Developer ID identity, notarization or qualified distribution
path. Cross-compiling x86_64 does not prove execution on an Intel Mac.

Controller tests use injected readers and clocks, isolated temporary stores,
and no workspace observers. They cover charge-conversion bounds, terminal stop,
queued refresh, preview isolation, opt-in storage/reopen, failed preflight,
delayed-reader replacement, history isolation and no automatic backend fallback.
Browser tests cover old-session pagination, exact-page exports, deletion,
terminal close, and separation from live selection/recording. Library tests
cover indexed pagination and plot gaps/provenance. Save-panel actions, visual layout, accessibility,
menu interaction and live app history still require interactive verification.
The first app process launched, but the UI inspection tool timed out. On
2026-10-08, an explicitly authorized restart into the latest synthetic preview
allowed a partial interactive check: details scrolling, the history-metric
picker and missing-data state, static Refresh, and normal application-menu
Quit/reopen. Genuine window captures and remaining limits are recorded in
[visual evidence](SCREENSHOTS.md). This does not qualify live acquisition,
backend/source selection, exports, the menu-bar popover or VoiceOver.

The native session probe has produced one qualitative observation from a real
Apple UPS source: status, battery charge (ratio) and battery voltage (V) were
reported, while AC input/output voltages and power were unavailable through
this path. This does not qualify a specific model, app UI, sustained
acquisition, sleep/wake, display accuracy or advanced USB compatibility.

The host now publishes selected-source snapshots when its explicit App Group
configuration matches its signed entitlements. Sharing is independent of history
and disabled in synthetic preview; sharing failures have a separate status.
The embedded WidgetKit extension builds, while actual App Group access, widget
installation and real NUT/UPS telemetry qualification remain open work.
See [widget qualification](WIDGET_SIGNING.md). The release checklist is not
cleared by this source preview.
