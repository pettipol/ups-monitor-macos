# Widget Sharing Contract

This is the implementation contract for P4, not proof of registration or signing.
The extension reads only a sanitized shared snapshot. No Apple power-source
enumeration, network client, database, driver or hardware access in the widget.

## Shared Data API

New Swift package `UPSWidgetData` depends only on Foundation, Darwin and UPSModel.
Public types:

```swift
enum WidgetAcquisition: String, Codable, Sendable {
    case active, noSources, readFailed, stopped
}
struct WidgetSnapshot: Codable, Equatable, Sendable {
    let schemaVersion: Int // exactly 1
    let publishedAt: Date
    let acquisition: WidgetAcquisition
    let maximumAge: TimeInterval // finite, 1...600 seconds
    let snapshot: MonitorSnapshot?
    init(schemaVersion: Int = 1, publishedAt: Date, acquisition: WidgetAcquisition,
         maximumAge: TimeInterval, snapshot: MonitorSnapshot?)
    func validate() throws
    func isStale(at: Date) -> Bool
}
enum WidgetStoreMode: Sendable { case readOnly, readWrite }
actor WidgetSnapshotStore {
    init(directoryURL: URL, mode: WidgetStoreMode) throws
    func read(now: Date) throws -> WidgetSnapshot? // nil only when file is absent
    func write(_ value: WidgetSnapshot, now: Date) throws
}
```

`active` requires a snapshot; `noSources` requires nil. Failure/stop may carry the
last good snapshot, never retimed. All dates must be finite; sample capture must
not exceed publication. Reader/writer reject publication later than explicit
`now`. A sample becomes stale at age strictly greater than maximumAge or whenever
acquisition is not active. Invalid clocks fail closed. Validate nested snapshots
using UPSModel. Codable decoding must validate, not just public API writes.

One selected source/session only; no names, serials, native IDs, network endpoint,
history or arbitrary metadata. Unknown values are not converted to zero. No
retained sample when a successful read reports no sources. No preview payload is
ever written into the real shared location.

The store uses one fixed JSON filename, at most 64 KiB including encoding.
Injected directory is a dedicated private child of the App Group, not its root.
Read-only mode never creates or repairs files/directories. Writer may create this
child with 0700 and atomic replacement using a same-directory exclusive 0600
temporary file. Refuse symlink directories/files, nonregular or hard-linked
files, foreign ownership and nonprivate modes. Bound reads before allocation
and while reading. Validate before touching the previous valid file; refuse
unsafe existing targets rather than following or silently replacing them.
Directory-relative descriptor operations are preferred to repeated path checks.
Keep errors typed and redacted. No claim of protection from a malicious same-user
process, power-loss durability or rollback attacks.

## Extension UI

`UPSWidgetUI` depends on UPSWidgetData, UPSModel and UPSMonitorUI. It supplies a
pure `UPSWidgetView(payload: WidgetSnapshot?, date: Date, isMedium: Bool,
unavailableReason: String? = nil)` without filesystem, WidgetCenter or hardware
calls. The entry date is the time of rendering, never substituted for capture.

Small: provider, charge, captured line status, captured timestamp/relative age,
explicit stale/unavailable/no-source/stopped states. Medium also shows runtime
estimate and active/apparent power with W/VA and provenance. Missing fields stay
not reported. Never suggest a nominal power is a live measurement. Compact native
SwiftUI/SF Symbols, wrapping/adaptive text, light/dark, no unsupported controls.

Always frame numbers and state as a last capture, not current live measurements.
Use a system-updating date view for age; do not promise exactly timed state changes.
No green current/live badge that can freeze after the app stops. The provider
may schedule a conservative stale entry five minutes later and request another
timeline after 15 minutes. Refresh requests remain system-controlled. Pure
formatters/planning tests are separate from actual WidgetKit presentation.

## App and Signing Integration (Coordinator Ownership)

The app writes validated state independent of optional history, only when an
explicit App Group configuration and entitlement match are present. It requests
WidgetCenter reloads sparingly, never once per native poll. Failure to share data
is visible and does not invalidate native acquisition. No fallback to a global
temporary file, guessed group directory, user history DB or network service.

Default local builds remain usable without an App Group and show unconfigured
widget state. Separate SharedDebug/SharedRelease configurations use developer-
supplied signing/team/group values; no personal identity in source. The widget
extension is sandboxed; the host retains its existing sandbox policy. Building
with entitlements is not evidence that the group exists or that access works.
Do not register groups online, alter permissions, bypass security, sign with a
personal identity or install/register the extension without the appropriate gate.

## Primary Sources Checked 2026-10-08

- [Widget refresh scheduling](https://developer.apple.com/documentation/widgetkit/keeping-a-widget-up-to-date):
  updates have a system-controlled budget; timeline spacing around five minutes
  is recommended and exact reload timing is not guaranteed.
- [App Group setup](https://developer.apple.com/documentation/xcode/configuring-app-groups)
  and [entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups):
  macOS supports a developer-team-prefixed group as well as registered group IDs.
- Installed SDK 27 `NSFileManager.h`, lines 989-996: macOS can return a container
  URL even for an invalid group; real directory access still needs verification.
- SDK 27 WidgetKit Swift interface: TimelineProvider, StaticConfiguration,
  TimelineReloadPolicy and supported systemSmall/systemMedium families.
