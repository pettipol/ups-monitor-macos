# UPS Monitor Mac

## Scope

Build a free, open-source macOS UPS monitor by reusing Apple IOPowerSources and
Network UPS Tools. SwiftUI/AppKit menu app, WidgetKit snapshots, local history.
Read-only monitoring only. Missing values are not zero; W, VA, Wh and battery
charge are different quantities. Label derived values, estimates and stale data.

## Work Rules

- Prefer Luna for bounded implementation tasks. Escalate a specific unresolved
  task to Terra when available or Sol after two focused attempts, or earlier for
  protocol/security complexity. The coordinating agent reviews critical changes.
- Workers own explicit files/modules and share this checkout. Never revert or
  overwrite another worker's changes. No commits or publication from workers.
- Use apply_patch for manual edits. Keep code and public documentation in English;
  user-facing progress is Italian. Add tests for changed behavior.
- Prefer maintained upstream components and Apple APIs. Verify current stable
  versions before adding dependencies, pin exact revisions, and record sources.
- Private hardware evidence and the surrounding SistemaHardware workspace are
  not repository content. Public fixtures must be synthetic. Never include real
  serials, UUIDs, network addresses, account data or local absolute user paths.

## Hardware Safety

- Native power-source enumeration is allowed. Do not open or claim USB interfaces,
  send HID feature reports, launch UPS drivers, install/activate daemons, change
  power settings, interrupt processes, restart, disconnect hardware or update
  firmware without separate explicit user consent through the coordinator.
- Offline builds and synthetic tests do not qualify real hardware compatibility.
- No shutdown, self-test, calibration, buzzer or configuration commands in v1.
- Do not interrupt backups or other tasks. Never disable Gatekeeper or other
  security controls to obtain a successful build or widget installation.

## Release

Original code is MIT licensed. Dependencies keep their own licenses; NUT is not
relicensed by this project. Review privacy, source licenses and reproducibility
before publishing. No binary signing identity or certificate data in the repo.
