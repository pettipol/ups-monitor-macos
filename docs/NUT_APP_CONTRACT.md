# Local NUT Application Contract

The app can select Apple power-source monitoring or one explicitly configured
local NUT source. Apple remains the default on every launch. No automatic
service discovery, installation, driver launch or fallback is introduced.
Switching backends does not assert that their sources describe the same device.

## Reader

`NUTSnapshotReader` in UPSRuntime wraps the existing bounded UPSCClient and
MonitorSnapshotAdapter. It accepts UPSCClientConfiguration, an expected SHA-256
for an independently completion-qualified executable, and an opaque session ID.
The configured source ID must not contain the UPS name or a hardware identifier.
Each reader instance represents one monitoring session. Identity is configured,
not a verified physical identity across server/driver restarts.

Validate the expected digest and source/session at construction. Before every
read, hash a bounded regular executable file through a no-follow descriptor,
reject unsafe type/permissions, non-owner or group/world-writable files, multiple
links, changes during hashing, digest mismatch and cancellation. An explicit
validation method supports preflight without executing the binary. A digest
binds the caller's qualification to bytes, not to a version string, but does not
independently prove the qualification or resist a malicious same-user path swap.
Do not hash libraries or imply that executable integrity proves their integrity.

The only process execution remains UPSCClient's fixed read-only loopback query.
Return a fully validated MonitorSnapshot collection, preserving the decoder's
measurement timestamp, provenance and missing values. No energy integration,
USB access, raw output logging or credential loading is added.

## App Switching

Settings are in memory only in this tranche. Selecting a file or editing a draft
does not launch anything. Connecting requires explicit completion-qualification
acknowledgment, a valid digest, UPS name and local port. A failed preflight keeps
the old backend running. No arbitrary host field is offered.

After preflight, cancel the old coordinator and invalidate all its outstanding
UI/history completions before starting the replacement. Its admitted history
transaction may finish, but must not be attributed to the new source. Clear
selection and displayed history on a switch; never reuse a previous session ID.
Late old read/state completions may not update the UI, widget or history sink.
Stop remains terminal. Sleep stops the active reader; wake resumes without
catch-up. The preview cannot connect to NUT or switch to live Apple reads.

Show a compact backend picker and a settings sheet, separate redacted connection
errors from history errors. Local paths, UPS names, ports and digests stay only
in the settings/controller memory, never telemetry/history/widget/export.
NUT unavailability stays an error, not an automatic Apple fallback.

## Qualification

Use synthetic payloads and self-owned local fixture processes only. Prove
digest rejection before execution, bounded hashing/cancellation, source/session
validation, successful adaptation, error propagation, failed preflight keeping
Apple active, switching during a delayed read, history isolation and preview
isolation. The real qualified client may be exercised only against a new
ephemeral loopback synthetic server, never an existing local UPS server.

Build and unit/integration tests do not qualify real USB telemetry or settings
interaction. The existing separate consent gates remain unchanged.
