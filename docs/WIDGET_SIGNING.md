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

### On-Demand Configuration Status

The production app exposes **View > Widget status**. Opening that sheet or
using its refresh button calls Apple's public
[`WidgetCenter.getCurrentConfigurations`](https://developer.apple.com/documentation/widgetkit/widgetcenter/getcurrentconfigurations(_:))
API. It counts only the production widget kind and distinguishes small,
medium and other families. Synthetic and unrelated kinds are excluded.
No widgets are added, removed, registered or reloaded by this query, and it
does not access an UPS or launch NUT. Synthetic app modes do not expose the
command.

A successful empty result means that no matching configured widgets were
returned. An error is shown as unavailable, never as zero widgets; raw system
error details are not displayed. The query does not prove actual rendering,
shared-container access or fresh readings. Those remain separate checks even
when the configured count is nonzero. It is not a replacement for inspecting
the installed widget.

To open the system gallery, use the desktop's **Edit Widgets** context-menu
item, or click the menu-bar date/time and then **Edit Widgets** at the bottom
of Notification Center. These are system UI actions, not an application named
"Edit Widgets". See [Apple's widget guide](https://support.apple.com/or-in/guide/mac-help/mchl52be5da5/mac).

### Snapshot Publication

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

## Production Qualification Evidence (2026-10-11)

A production `SharedRelease` build was made from source revision
`0969b6cced759aa5bb80fe7d1e4fd9126d209f31` in a private qualification directory.
It reused the previously authorized local Apple Development identity and
dedicated App Group, with manual signing, no provisioning update request, and
`UPS_WIDGET_FIXTURE_MODE=NO` explicitly set. Both built Info.plists contain
`NO`; the app and extension carry the same team-prefixed App Group entitlement.
Deep/strict signature verification and the repository privacy-manifest checker
passed. No signing material or personal identifiers are recorded here.

The production host was opened and observed using the Apple backend. It showed
one UPS source with fresh online data and no sharing error; history was off and
the session alert switch was off. This does not prove the extension
can read the shared container. Widget gallery automation could not inspect the
gallery because accessibility attempts returned `illegalArgument` and
`noWindowsAvailable`. No installed widget placement, extension selection,
rendering, interaction, refresh behavior, appearance or accessibility result was
verified. No claim that the widget was running or that the product release gates
passed follows from this observation.

### Registry Selection Follow-Up

A later read-only check on 2026-10-11 compared the default `pluginkit` match
with `-A` (all versions) and `-D` (all physical instances), using the installed
manual's definitions. The default query returned one older ad-hoc Release
copy. `-A` returned the current signed SharedRelease copy. `-D` returned 15
development instances, including a synthetic fixture and other builds. Their
visible short-version/build fields were the same; the reason for the differing
selection was not established.

The initial inference that one `-A` result meant there were no competing copies
was incorrect. Neither that query nor valid signatures prove which extension
the widget gallery or host will select. No registration was changed and no
shared container was directly inspected during this check. Registry correction
and an actual gallery/rendering check remain open. The running production host
still showed fresh Apple data, history off, and no visible sharing-error message;
this is not proof of a successful widget read.

### Authorized Registry Correction

After explicit consent on 2026-10-11, the coordinator verified all 15 bundle
identifiers, the running production app path, its `NO` fixture setting and its
deep/strict signature. Only the 14 older copies of this project's widget were
removed from the plug-in registry with `pluginkit -r`; the currently running
signed app's embedded extension was registered with `pluginkit -a`.
No files, app data, other widgets or system-process lifecycles were changed.

The default, `-A` and `-D` queries then each returned exactly the same single
current signed extension. This is point-in-time registry evidence, not a
guarantee against automatic rediscovery of development copies that still exist
on disk. The installed manual explicitly warns that discovery may add removed
registrations back. No installed widget rendering or shared-container read was
established; the gallery remains a separate qualification gate.

### Configuration Status Follow-Up

On 2026-10-11, after the user's restart, the production Apple host was reopened
and showed fresh native readings with history recording off. A new
SharedRelease build containing the configuration-status sheet passed deep/strict
signature checks, matching App Group checks, fixture `NO` checks on both
bundles, and privacy-manifest validation. It reused the authorized local
identity/group without provisioning updates. No signing values are published.

The coordinator quit only the previous host normally and opened the new build.
**View > Widget status** returned **No widgets added** from the real WidgetKit
API. Refresh, close and reopening the sheet were exercised; each query
returned the same empty production-kind result. The sheet was visually
inspected without overlapping text. This establishes the on-demand query UI,
not rendering of a system-hosted UPS widget or a successful extension read.
VoiceOver, alternate appearance and nonzero real configuration counts were
not qualified by this check.

The builds had created three registry entries for this project's extension.
After checking their bundle IDs and the current signed app, the previously
authorized project-only registration correction removed the two older entries
and registered the new signed extension. The all-versions/all-instances query
then returned one copy. No app files, other widgets, system services or USB
connections were changed. Automatic rediscovery remains possible.

Seven synthetic controller tests cover empty/count/error results, production
kind filtering, retry, overlapping checks and close/reopen with delayed success
or failure. A single pending recheck is coalesced until the previous query
returns; closing again clears it. Cancellation invalidates the result, not
Apple's underlying callback operation. A system callback that never arrives
has no guaranteed deadline; the sheet can still be closed. The full local
Swift suite passed 246 tests, with two optional synthetic-client interop tests
skipped. These tests never invoke WidgetKit's real configuration query.

### User-Added Medium Widget

Later on 2026-10-11, the user reported adding the production widget to the
desktop. A new real **View > Widget status** query returned **Small: 0,
Medium: 1, Other sizes: 0**. The configuration sheet was visually inspected
and closed normally; the Apple host remained active with history recording off.
No registry correction, new build, driver launch or USB operation was needed.

This establishes one matching configured medium widget, not its rendered
contents. The UI capture tool exposed a different desktop widget, so direct
inspection of the UPS widget and successful extension-side shared-data reading
remain **OPEN**. A cropped screenshot or a transcription from the user was
requested. There is no claim of observed live widget values or update timing.

### Reported Values and Expanded Layout

The user subsequently described a visible `UPS · Apple` widget with most
advanced readings absent. This is a user-reported observation, not an
independently inspected screenshot or a timed end-to-end freshness check.
`Apple` names the data provider, not the UPS manufacturer. At the time of that
report, the schema did not acquire or publish a presentation name. Opaque source
identity remained unchanged.

The Unreleased medium view now shows charge separately from a six-cell grid:
runtime estimate, load percentage, active W, input V, output V and apparent VA.
The earlier medium view omitted load and both AC voltage fields even when a
snapshot contained them. This presentation gap is fixed in source. Six view
tests and three compact synthetic canvases cover the expanded presentation;
see [render evidence and limits](RENDER_PROBE.md). The installed signed app and
its configured widget have not been replaced in this tranche.

This does not remove the acquisition gap. The Apple adapter has no input/output
AC voltage, load or active/apparent power mapping. Its battery voltage is not
mains voltage, and its runtime estimate is suppressed on AC or while charging
in accordance with the native field's documented context. Missing fields remain
`Not reported`, never invented zeros or estimates from nominal VA. Advanced
readings on the target UPS remain unqualified; experimental NUT driver work is
still on [lifecycle hold](NUT_LIFECYCLE_REVIEW.md). No driver, USB operation,
power-loss test or hardware configuration change was performed for this update.

### Native Presentation Name Source Update (2026-10-11)

The current source can carry a sanitized name from `kIOPSNameKey` beside the
Apple source observation. It is matched through the current opaque session
token, not used as source identity, and is not added to `MonitorSnapshot`,
history, JSON/CSV exports or energy records. If present, it may be stored in the
optional `presentationName` field of the local widget envelope; configured
App Group cache persistence therefore includes this potentially identifying
display value. It is not guaranteed to be a model or SKU, and no persistent
user alias is introduced. Missing or rejected names fall back to UPS/provider
labels.

The render probe source matrix now contains three named cases with a visible
synthetic-fixture banner. They exercise the production name-label path in an
offscreen view; they are not installed-app or WidgetKit evidence. Offline
validation passed 273 Swift tests (two optional interop tests skipped), 93 Python
tests, package Release and ad-hoc app/widget builds, plus privacy and signature
checks. The strengthened late-cancellation test passed in a subsequent 25-test
name selection. A fresh render produced fourteen images; the three named cases
were visually inspected with the limits in [the render notes](RENDER_PROBE.md).

### Signed Native-Name Host Check (2026-10-11)

A new production SharedRelease app and embedded widget were built with the
already-authorized local identity and dedicated group. Both fixture-mode values
were `NO`; their group entitlements matched. Deep/strict signature verification
and packaged privacy checks passed. The old host was quit normally, its exit
confirmed, and the new host opened. Its details window visibly displayed the
native UPS name, online status, full battery charge and the reported battery
voltage. Runtime, load, W, VA and AC input/output voltage remained unavailable;
no new measurement is claimed. History remained off.

The new host's WidgetKit query reported small 0, medium 1, other 0. Default and
`-A` registry queries selected the new signed extension; `-D` also listed the
older signed build and the new ad-hoc validation copy. No registry entries were
changed. These queries do not establish the extension selected by the running
widget host. The UI tool did not expose the UPS widget surface. A scoped cache
check could read file metadata, but macOS denied content access; no alternative
access method or permission change was attempted. Thus actual extension reads,
the named medium widget's desktop appearance and refresh timing remain open.
No driver, HID interface, power setting or system process was touched.

### User Confirmation And Compact Title (2026-10-11)

The user subsequently confirmed that the desktop widget displays the correct
native UPS name, but found the technical suffix too long. This is user-reported
evidence of name delivery, not a new screenshot, refresh-timing test or advanced
telemetry qualification. It supersedes only the earlier uncertainty about
whether the native name appeared on the desktop.

The widget now removes a complete recognized `FW:UPS <version> / ID=<number>`
suffix from the visible title for Apple sources only. The full sanitized value
is unchanged in the payload, app, accessibility label and help text. Incomplete
or unrecognized suffixes and other providers retain their original labels.
The new compact title still requires confirmation in the system-hosted widget;
source tests and synthetic renders are separate evidence.

The compact-title update passed 275 Swift tests and 108 Python tests, with two
optional NUT client interop tests skipped. Package Release, ad-hoc app/widget and
locally signed SharedRelease builds, signature and privacy-packaging checks
passed. Both signed bundles have fixture mode disabled and the previously
authorized group. The host was replaced through normal Quit/open operations;
its full native label, Apple backend and history-off state were preserved.

A registry check selected an older development widget. Under the existing
scoped consent, five stale registrations for this widget identifier alone were
removed and the current signed extension registered. Default and all-copy
queries then showed only the new copy; no bundle/data deletion or system
process restart occurred. WidgetKit still reported one medium widget. These
checks do not establish that the visible desktop widget has reloaded the new
compact title or prove real-time freshness.
