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

### Offline Driver Observations

`NUTDriverDumpDecoder` and `NUTObservationAdapter` provide a separate,
in-memory import path. They do not launch a process, read a file, enumerate a
device, activate an app backend, or enable an operator profile. The `upsc`
reader remains unchanged. The explicit archive detail described below uses
this path without making it a live monitoring source.

The decoder accepts only the pinned NUT 2.8.5.1 Microlink 0.05 stdout preamble,
one supported driver identity, a bounded variable listing and a final LF.
This is a format-specific contract, not compatibility with all NUT versions.
It reuses the existing numeric, unit, status and duplicate validation. Only this
driver-dump path treats an empty `ups.status` as unavailable; it never infers
`OL`. A dump containing metadata but no usable telemetry is rejected, even when
the process exited successfully. Status-only output may be decoded but does
not demonstrate a numeric measurement. The snapshot provider is
`driverDumpOutput`, distinct from `upscOutput`.

The caller must supply an immutable `SupervisedNUTObservation` containing the
original stdout/stderr bytes, process outcome, exact byte counts, combined
output limit, digests and original start/end times. Import requires
`exited/completed/0`, no error, matching counts and hashes, a matching externally
supplied executable pin, valid caller-assigned NUT source identity and finite,
ordered, non-future dates. The combined limit is at most 1 MiB; stdout additionally
obeys the decoder's 64 KiB, 512-line and 1024-byte-per-line limits, including the
preamble. Diagnostics remain separate from telemetry and errors are sanitized.

The executable pin comparison is an attestation check, not a fresh executable
or dependency hash, receipt authentication, or proof of hardware accuracy. The
supervisor now supplies original capture metadata as described below. Its
legacy seven-field CLI response is not a complete observation receipt. Neither
receipt persistence nor a live app route is automatically activated.

`ImportedNUTObservation` retains the declared synthetic/archive origin and
original times, exposes `unqualifiedSnapshot`, and always has
`dataQualified == false`. Its conservative `capturedAt` is the process start,
not import time. The existing model adapter preserves runtime estimates,
Microlink-derived W/VA, missing values and stale captures. The origin wrapper is
not retained automatically by downstream UI/history APIs: do not pass synthetic
or unqualified imports into production polling or persistence.

Qualification tests inject reads into `MonitorCoordinator` without a sink,
polling loop, process or device. These prove only the offline parsing/model
boundary; they do not qualify the driver, live telemetry, app or widget.

### Supervisor Receipt Bridge

`BoundedRunResult.observation` is optional immutable metadata from the original
capture. The supervisor updates each stream's SHA-256 only after successfully
writing the same bytes counted as captured output. Normal post-exit draining is
included; overflow bytes and termination-time discarded output are excluded.
The wall-clock start is sampled immediately before process creation and the
finish after supervision, draining and any reap attempt. Timeouts still use the
existing monotonic clock. Invalid or inverted wall-clock samples leave the
metadata absent without replacing the process outcome; pre-spawn cancellation
has no metadata. See [process contract](PROCESS_DEADLINE.md).

`encode_observation_receipt(result)` in `backend/nut/observation_receipt.py` is a
pure serializer. It emits compact UTF-8 JSON with exactly these decoded keys:

```text
schema_version, status, trigger, returncode, stdout_bytes, stderr_bytes,
maximum_output_bytes, executable_sha256, stdout_sha256, stderr_sha256,
started_at_unix_seconds, finished_at_unix_seconds, data_qualified, error
```

Version is 1, `data_qualified` is false and `error` is null. Missing metadata,
invalid types, non-finite/inverted dates, bad digest syntax or a limit outside
1...1048576 reject serialization with a fixed error. The caller retains the
original process result. Negative outcomes with valid metadata remain negative
outcomes in a receipt; serialization does not admit them for telemetry.
No output bodies, paths, hardware names, argv or origin are included.

`NUTObservationReceiptDecoder` takes receipt bytes (at most 8192), the separately
supplied stdout/stderr bytes, and caller-assigned origin/source/expected pin/time.
It requires UTF-8 without raw NUL bytes, the exact decoded key set, version and
strict field types, then delegates to `NUTObservationAdapter`. Thus replaced or
truncated capture bytes do not gain a new matching reference digest at import.
Python original-capture metadata and the Swift decoder are exercised together
with owned synthetic processes, not a UPS driver.

This is an unsigned local interchange format. Foundation's behavior for
duplicate textual JSON keys is not a duplicate-key rejection guarantee; the
producer does not emit duplicates. Metadata and its bytes can both be forged by
an untrusted caller. No cryptographic receipt authentication, durable/atomic
archive writer or live app route is supplied by this bridge.
The existing operator CLI remains unchanged with its empty profile registry.

### Explicit Archive Detail

`NUTObservationBundleReader` reads only `receipt.json`, `stdout.bin` and
`stderr.bin` from an explicitly selected existing session directory. It uses
no-follow directory/file descriptors and bounded reads, requires a trusted
current-user parent, a mode-0700 session and mode-0600 regular single-link
current-user files, and checks metadata and file-name identity around reading.
Parent, session and files must have no extended ACL entries; the reader rejects
all nonempty ACLs, including otherwise harmless read-only or deny entries, and
fails closed when ACL inspection is unavailable. It does not remove ACLs.
Receipt is limited to 8192 bytes, stdout to 65536, and combined captures to
1048576. It neither creates nor repairs input files. These checks do not resist
all hostile same-user changes or reject symlinks in every path ancestor.

The app's archive model and sheet are separate from its live monitoring model.
Import requires an explicit declared origin and an independently supplied
expected executable SHA-256; the app never obtains that pin from the receipt.
The source identity is an app-assigned archive session, not hardware identity.
Changing inputs, a failed import or closing the sheet clears the previous
result; late completions cannot restore it. No import occurs on startup.

The detail always identifies the observation as archived and unqualified. It
preserves original timestamps, missing values, estimates and provenance, and
may show valid status-only output without claiming numeric measurements.
It does not feed the coordinator, live source list, widget, history, energy
integration or alerts. Opening the archive sheet does not stop or replace the
separate, normally running monitoring backend.

Successful import proves local byte/metadata consistency with the unsigned
receipt and supplied pin, not that the process really ran, hardware origin,
measurement accuracy, consent, current executable integrity or qualification.
The three files do not contain the wrapper's final response or exit status;
they cannot attest wrapper delivery or durability. In particular a result
file written before a final directory fsync cannot prove that fsync succeeded.
Live acquisition and app/widget qualification remain separate release gates.

### Existing Local Client Path

Use synthetic payloads and self-owned local fixture processes only. Prove
digest rejection before execution, bounded hashing/cancellation, source/session
validation, successful adaptation, error propagation, failed preflight keeping
Apple active, switching during a delayed read, history isolation and preview
isolation. The real qualified client may be exercised only against a new
ephemeral loopback synthetic server, never an existing local UPS server.

Build and unit/integration tests do not qualify real USB telemetry or settings
interaction. The existing separate consent gates remain unchanged.
