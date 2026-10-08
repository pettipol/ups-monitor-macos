# Widget Build and Qualification

## Configurations

| Configuration | Signing | App Group | Purpose |
|---|---|---|---|
| Debug / Release | Ad hoc | None | Local source build; widget explicitly unconfigured |
| SharedDebug / SharedRelease | Developer-supplied Apple Development identity | Developer-team-prefixed group by default | Local signed build; end-to-end widget qualification remains open |

The Xcode app target embeds `UPSMonitorWidget.appex`. Both use the same explicit
`UPS_APP_GROUP_ID` build setting in their Info.plist. Only Shared configurations
include this value in both signing entitlements. The extension is sandboxed in
all configurations; no network client or USB entitlement is added. The host's
existing nonsandboxed policy is unchanged. Release configurations do not inject
debugger entitlements. This is not a notarized distribution configuration.

Local build, without a signing account or App Group:

```sh
xcodebuild -project UPSMonitor.xcodeproj -scheme UPSMonitor \
  -configuration Release -derivedDataPath .build/widget-app build
codesign --verify --deep --strict '.build/widget-app/Build/Products/Release/UPS Monitor.app'
```

Shared configurations require a valid local signing identity and the developer's
team identifier. After reviewing the new container and authorizing the local
qualification, the builder may provide their own values, for example:

```sh
xcodebuild -project UPSMonitor.xcodeproj -scheme UPSMonitor \
  -configuration SharedRelease -derivedDataPath .build/shared-app \
  DEVELOPMENT_TEAM="$UPS_DEVELOPMENT_TEAM" \
  UPS_APP_GROUP_ID="$UPS_DEVELOPMENT_TEAM.org.openupsmonitor.shared" build
```

Do not copy another developer's team identifier. Do not check personal signing
identities, provisioning profiles, credentials or container paths into Git.
A SharedRelease build was performed with an explicitly authorized existing local
Apple Development identity and dedicated team-prefixed group on 2026-10-08.
The build used manual signing, an explicit local identity and no provisioning
update flag. No keys were exported and no online group registration was performed.
The [Apple App Group entitlement documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups)
describes the team-prefixed macOS format; it does not establish that a particular
local identity or container will work.

## Data and Reloading

The app verifies the configured identifier against its own signed entitlements
before asking Foundation for a container URL. The dedicated child directory and
file must also pass ownership, type, size and permission checks. Invalid
configuration or failed access produces an explicit unavailable state, without
fallback paths. The widget only opens the store read-only.

Publishing is independent of opt-in history. It includes the selected source's
last capture and acquisition status; synthetic preview never publishes. Stop
publishes stale status without changing the measurement time. A bounded latest-
pending publisher prevents an earlier queued state from replacing a later one.

Ordinary reload requests are at least five minutes apart. A changed source or
status can request an earlier reload after at least 30 seconds. These are request
limits, not an update guarantee. The provider plans entries at five-minute
intervals and requests another timeline after 15 minutes. The UI always describes
a capture and shows a system-relative age. A stale label can be delayed by system
scheduling; the widget must never be used as a real-time alarm or shutdown guard.
See [Apple's refresh guidance](https://developer.apple.com/documentation/widgetkit/keeping-a-widget-up-to-date).

## Synthetic Widget Fixture

The Xcode build setting `UPS_WIDGET_FIXTURE_MODE` is `NO` by default and is
expanded into `UPSWidgetFixtureMode` in both app and widget Info.plists. Only
the exact values `YES` and `NO` are accepted. Missing configuration disables
the fixture; any other value is invalid and fails closed: the app disables live
monitoring, while the widget reports invalid configuration without reading a
store or falling back to production data.

With `YES`, the app supplies a synthetic-only reader and publishes to
`UPSWidgetSyntheticFixture`, never the production `UPSWidgetSnapshot` child
directory. WidgetKit uses `UPSMonitorSyntheticFixture`, separate from the
production `UPSMonitorSnapshot` kind, and the widget
shows a `Synthetic UPS` badge. This mode does not use the real UPS reader,
record history, or activate alerts. The `--synthetic-preview` app argument takes
precedence over the fixture setting and does not publish shared widget data.
Fixture mode is not a signing or App Group entitlement; the existing build and
signing configuration still determines whether shared storage is available.
Append `UPS_WIDGET_FIXTURE_MODE=YES` to the shared-build command above and use
a fresh derived-data directory. Verify that both built Info.plists contain
`UPSWidgetFixtureMode` set to `YES` before launching without arguments. Never
distribute that qualification build as a production monitoring release.

For a fresh, valid payload, the provider schedules an entry at
`capturedAt + maximumAge + 1 second` so that the UI can cross the payload's
inclusive freshness boundary, in addition to the standard timeline dates.
Invalid, missing, stopped, or already-stale payloads receive only the standard
dates. This is a requested timeline schedule, not a WidgetKit execution-time
guarantee; stale-state presentation may be delayed by system scheduling.

## Evidence as of 2026-10-08

- Release app and embedded widget compile as arm64/x86_64; ad-hoc nested signature
  verifies. The Release widget has sandbox enabled, no App Group and no
  `get-task-allow` entitlement. This ad-hoc configuration uses no personal certificate.
- A separate SharedRelease app and embedded widget passed deep/strict signature
  verification using the authorized local Apple Development identity. The host
  and extension carry the same dedicated App Group entitlement; the extension
  also carries its sandbox entitlement, without USB, network-client or debugger
  entitlements. Personal identity and group values are not repository content.
- The signed extension path appears in the local plug-in registry alongside
  earlier build copies with the same bundle identifier. This proves a registry
  entry, not which copy WidgetKit chooses or that its container is accessible.
- Shared-file tests cover validation, subsecond timestamps, atomic replacement,
  bounded reads, unsafe files/directories and failure preservation. Publisher
  tests cover request limits and concurrent out-of-order submissions.
- Controller integration tests publish synthetic captures with history off,
  publish stopped state, and keep preview data out of the shared file.
- A separately built, personally signed fixture app was launched without
  arguments on 2026-10-08. Its synthetic label and built-in values were observed
  in the native interface; both compiled Info.plists contain `YES`. The earlier
  preview process was quit normally before this launch. No real reader was used.
- The host displayed no sharing error, but direct inspection of the group
  directory by the verification process was denied by macOS. No permissions
  were changed and no alternate access path was attempted. Absence of a host
  error is not independent proof of file contents or extension access.
- Pure view/formatter tests are not screenshots or proof of layout in WidgetKit.

Still required: actual signed group access from both processes; selection of the
intended registered extension; placement and rendering of small/medium widgets;
user interaction; updates while the host runs/stops; light/dark and accessibility; and source
selection/disconnection behavior. The signed fixture host was launched, but
gallery placement and installed widget rendering were not verified. No explicit
plug-in registration command was used. Never disable
Gatekeeper, change existing group permissions or use a shared temporary-file
workaround to clear these gates.
