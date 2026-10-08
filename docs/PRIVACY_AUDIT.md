# Static Privacy and Security Audit

Audit date: 2026-10-08

## Findings

### Material: User-selected NUT executable remains a code-execution trust boundary

Connecting a NUT source launches the executable selected by the user as a child
process (`Sources/NUTClient/BoundedProcessRunner.swift:79-88`). The application
requires a path, expected SHA-256 and completion-qualification acknowledgment,
but the digest is supplied by the caller and does not attest to a trusted
publisher or safe behavior. The configuration fixes the client's query target
to `127.0.0.1` and constructs read-only `upsc` arguments
(`Sources/NUTClient/UPSCClientConfiguration.swift:44-64,87-98`). This constrains
the arguments created by this application; it cannot constrain arbitrary code
inside a user-selected executable. The reader hashes the file before each read,
but then launches it by path (`Sources/UPSRuntime/NUTSnapshotReader.swift:66-82`),
so a same-user path replacement between hashing and launch is not ruled out.
The repository's NUT contract documents this limit. Treat NUT mode as an
explicit local executable trust decision, not as a sandboxed or publisher-
verified integration. No executable was launched during this audit.

### Moderate: Local history and exports contain identifiable source-session data

History is opt-in and stored under the user's Application Support directory;
the database directory and file are restricted to owner-only permissions
(`App/MonitorAppModel.swift:210-225,248-260`,
`Sources/UPSHistory/UPSHistoryStore.swift:340-379`). Stored snapshots include
provider, source ID, session ID, capture time, status and metrics. JSON and CSV
exports retain those typed fields (`Sources/UPSHistory/UPSHistoryStore.swift:253-265,458-490`)
and are written only after a user invokes a save panel
(`App/MonitorAppModel.swift:279-300`, `App/HistoryBrowserModel.swift:100-110`).
The current Apple reader maps native power-source IDs to opaque session-local
tokens; the app's NUT source/session IDs are generated opaque values. The
exported IDs and timestamps can still correlate samples from one local session.
NUT paths, UPS names, ports and expected digests are held in the connection
draft and are not included in telemetry/history/export by the app contract.

Disabling recording stops new appends; it does not delete existing history.
The configured retention is 90 days and 100,000 rows, applied on appends or an
explicit prune, rather than as a background deletion schedule. Session delete
and clear remove database rows, but neither SQLite secure-delete nor these
operations establish physical erasure from storage, filesystem snapshots,
backups, or user-created exports. See
`Sources/UPSHistory/HistoryTypes.swift:4-12`,
`Sources/UPSHistory/UPSHistoryStore.swift:290-302,440-455`, and
`App/MonitorAppModel.swift:210-225,263-276`.

### Moderate: Configured widget sharing publishes a selected snapshot independently of history

When signed App Group configuration is available, app startup creates a shared
publisher. It writes the selected `WidgetSnapshot` regardless of whether
history recording is enabled (`App/MonitorAppModel.swift:114-123,418-432,435-442`).
The payload contains the complete selected `MonitorSnapshot`, including source
identity fields, status and metrics (`Sources/UPSWidgetData/WidgetSnapshot.swift:19-37`).
The widget reads that shared payload read-only. The dedicated child directory
and file are checked as owner-only (0700/0600), and payloads are size-bounded
(`Sources/UPSWidgetData/WidgetSnapshotStore.swift:42-68,98-145`). This is still
intentional cross-process persistence in the configured App Group, not merely
an in-memory widget handoff.

The checked-in Debug/Release configuration has an empty App Group setting;
Shared configurations use developer-supplied signing and group values
(`UPSMonitor.xcodeproj/project.pbxproj:33-36,68-73`). This audit did not sign,
launch, install, or verify either process's App Group access. Actual shared
container access and widget rendering remain **NOT RUN / NOT VERIFIED**.

### Note: Optional OS alerts have retention outside app history controls

Alerts default off and authorization is requested only after the user enables
them (`App/UPSAlertController.swift:54-83`). The app requests alert permission,
uses generic text plus capture time, and clears only its four fixed identifiers
(`App/SystemUPSAlertDelivery.swift:12-24,48-80`). Notification delivery and its
history are managed by macOS, so app history deletion does not clear every OS
notification surface or establish physical erasure. No permission prompt or
notification was exercised in this audit.

## Bounded Positive Evidence

- The source fixes the NUT client's host to loopback; this audit found no direct
  `URLSession`, Network.framework client, remote notification registration,
  analytics, or telemetry API in the inspected app/runtime/widget source. This
  is a source scan, not proof of runtime egress. The child executable and local
  NUT service are outside that conclusion.
- Child process arguments are assembled as an argument array, not a shell
  command. Its environment is a small explicit allowlist, standard input is
  null, standard error is counted and discarded, standard output is bounded,
  and execution has a deadline (`Sources/NUTClient/UPSCClientConfiguration.swift:87-98`,
  `Sources/NUTClient/BoundedProcessRunner.swift:79-88,171-189`). Errors exposed
  to the app are typed/redacted rather than including child output.
- The live Apple app path uses `AppleSessionReader`; native power-source IDs
  are used only by its identity mapper and are replaced by opaque generated
  tokens before snapshots leave that actor
  (`Sources/ApplePowerSource/AppleSessionReader.swift:12-15,111-135`,
  `Sources/UPSRuntime/AppleSnapshotAdapter.swift:10-24`).
- A scoped text scan of `README.md`, `docs/`, `App/`, `Sources/` and `Widget/`
  found no literal user-home or volume paths, UUID-shaped values, MAC addresses,
  or obvious private network addresses. This did not inspect Git history,
  generated products, binaries, or external build artifacts.
- The app target's local Debug/Release configurations do not name an app
  entitlement file; the widget's local entitlement enables App Sandbox, while
  Shared configurations add App Group entitlements
  (`UPSMonitor.xcodeproj/project.pbxproj:33-36,66-73`,
  `Widget/Local.entitlements`, `App/Shared.entitlements`,
  `Widget/Shared.entitlements`). This is configuration evidence only, not a
  claim about the entitlements of a built or running process.

## Not Established

This review was static and limited to the repository's app, runtime, widget,
bridge, storage and relevant configuration/docs. No build, test, launch,
permission prompt, process execution, hardware access, network capture, egress
test, signing, or App Group runtime verification was performed. Source review
cannot establish operating-system privacy behavior, backup state, third-party
executable behavior, full dependency behavior, or absence of all data flows.
At the original audit snapshot no `PrivacyInfo.xcprivacy` file was present.
A subsequent same-day [platform-specific review](PRIVACY_MANIFEST.md) adds
local-data declarations to the app and widget and source/bundle checks. It does
not turn this earlier static audit into runtime evidence or establish Apple
distribution acceptance. This report is not a legal assessment, comprehensive
security review, or publication approval.
