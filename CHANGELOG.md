# Changelog

## Unreleased

- Hardened the offline guarded NUT source prototype: effective foreground dump
  mode only, no sibling-driver stop/signaling path, and no interrupt PIPE
  clear-halt recovery. Added policy and static call-site regressions; no driver
  or hardware execution.
- Documented open upstream USB recovery and HID fallback-status issues. The
  guarded patch does not fix the fallback defect or qualify UPS measurements.
- Recorded an authorized local Apple Development app/widget build and verified
  matching signed group entitlements. Runtime shared access and installed
  widget behavior remain open; no personal signing identifiers are included.

## [0.1.0-preview.1] - Source preview

Date: 2026-10-08

- Established the macOS menu-bar app, details window, opt-in SQLite history,
  stored-session browser, local alert policy and small/medium widget source.
  Synthetic tests cover these boundaries; signed App Group access and installed
  widget behavior remain unqualified.
- Added synthetic-preview screenshots and project presentation notes. Basic
  GUI checks covered scrolling, history-metric selection, refresh and quit/relaunch;
  VoiceOver, broader accessibility, widget rendering and hardware remain open.
- Added a bounded offscreen SwiftUI render probe with eight synthetic cases;
  complex-control placeholders and non-system-hosted output are documented.
- Connected the in-memory session energy tracker to the app's selected source,
  with separate input and UPS active-watt channels, covered Wh, breaks and
  provenance.
- Added an explicit confirmed reset and a separate schema-version-1 JSON export
  that does not depend on history recording.
- Exposed the coordinator's monotonic successful-receipt time before sink work
  so energy intervals use acquisition receipt timing rather than UI refreshes.
- Added the canonical `0.1.0-preview.1` SemVer, checked bundle metadata and
  synthetic version-drift tests. Apple bundle version fields remain numeric;
  this source version is not a release or hardware qualification.
- Updated public compatibility, build, contribution and third-party licensing
  guidance. Live watt qualification remains open.
- Added pinned hosted CI and local synthetic validation. The first hosted run
  passed source, test and ad-hoc build checks; these do not qualify widget
  installation, VoiceOver or real hardware.
