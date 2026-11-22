# Managed operational runtime: experimental, disabled by default

The app accepts the sole argument `--managed-operational-session` to select an
explicit operational v2 mode. It stays idle until Start. Mixed, duplicate and
unknown accompanying arguments are rejected. This mode never falls back to
Apple or another NUT backend and never automatically retries or reconnects.

This is a host-local development candidate, not a portable release or a claim
that daily hardware monitoring has been qualified. The currently pinned native
artifact is arm64 with minimum macOS 27.0. Its SHA-256 is
`d754eaa71ef19dad5532ddabfd507f084ec6848ef2642718b1cb575657f43cfc`.
It uses IOKit, CoreFoundation and libSystem directly. It is not a libusb binary.

## Runtime admission

`ManagedOperationalRuntime/runtime.json` has exactly nine keys:
`schema_version` (integer 2), `profile` (`apc-smc1500i-operational-v2`),
`python_path`, `python_sha256`, `module_sha256`, `native_name`
(`apcmicrolink-hidapi-operational`), `native_sha256`, `architecture` (`arm64`),
and `minimum_macos` (`27.0`). Python and all nine modules are pinned by hash.

The module closure is `managed_operational_entrypoint.py`,
`app_controlled_operational.py`, `operational_capture.py`,
`operational_publication.py`, `continuous_capture.py`, `continuous_protocol.py`,
`process_deadline.py`, `bounded_stream_dispatch.py`, and `cleanup_diagnostics.py`.
The entrypoint runs with `-I -S -B` and validates the complete closure before
importing the backend. Files are bounded regular files opened without following
leaf symlinks; the Python validator also rejects aliased runtime/interpreter
directories. No UI command, duration, identity or native path override exists.

`stage_managed_operational_runtime.py` copies into a new destination, rejects
source/destination aliases and preserves a non-executable native copy (0600).
It neither enables nor executes that copy. Runtime launch requires the pinned
native file to be executable, so staged output deliberately fails admission
until a separately reviewed activation step. The original artifact is unchanged.
Partial staging failures retain evidence rather than deleting unknown files.

The fixed driver options select shared HID, guarded monitoring, one probe,
VID/PID 051d/0003, no HID fallback, startup guard 35 seconds and stream v2.
There is no overall 120-second limit in this operational profile. Existing
health/progress and output-rate guards still apply; no electrical control,
reset, self-test, firmware command or automatic reconnect is introduced.

## App lifecycle and data

The app explicitly selects `NUTOperationalSampleReader`. Its startup window is
40 seconds, covering the backend's 35-second startup guard; existing v1 modes
retain 10 seconds. Stop and Quit use the owned process controller. The final
envelope uses `ups-monitor.managed-operational.v2`, schema 2, the exact launch
UUID and the complete nested adapter/capture/runner receipt.

Unknown or unresolved ownership retains the Python supervisor and the app's
ownership marker. A receipt alone cannot release ownership: completion, pipe
EOFs, output limits and the validated receipt are separate checks. Measurement
failure can coexist with successful resource cleanup; it remains failed in the
app, including after Quit. This retention can be indefinite and does not cause
another acquisition attempt.

Titles identify the operational mode as unqualified. History, energy estimates,
alerts and exports stay restricted until hardware qualification. Component
tests use inert files, mocked adapters and fake process handles. They do not
qualify the real producer-to-app path, GUI controls or WidgetKit rendering.

## Remaining qualification

The final component test results belong to the private development evidence;
the public repository includes reproducible test sources and CI discovery.
Still required: a complete synthetic process session through the new entrypoint
and app, bounded native qualification, visible app/widget verification, portable
packaging, license/privacy review, and release checks. No new hardware test is
implied by adding or building these sources.
