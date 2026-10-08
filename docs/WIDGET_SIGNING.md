# Widget Build and Qualification

## Configurations

| Configuration | Signing | App Group | Purpose |
|---|---|---|---|
| Debug / Release | Ad hoc | None | Local source build; widget explicitly unconfigured |
| SharedDebug / SharedRelease | Developer-supplied Apple Development identity | Developer-team-prefixed group by default | Future local shared-container qualification |

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
This command has not been run with a personal identity in this qualification.
It does not perform online group registration or provisioning updates. The
[Apple App Group entitlement documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups)
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

## Evidence as of 2026-10-08

- Release app and embedded widget compile as arm64/x86_64; ad-hoc nested signature
  verifies. The Release widget has sandbox enabled, no App Group and no
  `get-task-allow` entitlement. No personal certificate used.
- Shared-file tests cover validation, subsecond timestamps, atomic replacement,
  bounded reads, unsafe files/directories and failure preservation. Publisher
  tests cover request limits and concurrent out-of-order submissions.
- Controller integration tests publish synthetic captures with history off,
  publish stopped state, and keep preview data out of the shared file.
- Pure view/formatter tests are not screenshots or proof of layout in WidgetKit.

Still required: actual signed group access from both processes; extension
registration; placement and rendering of small/medium widgets; user interaction;
updates while the host runs/stops; light/dark and accessibility; and source
selection/disconnection behavior. No bundle from this widget tranche has been
launched or explicitly installed/registered. Never disable Gatekeeper, change
existing group permissions or use a shared temporary-file workaround to clear
these gates.
