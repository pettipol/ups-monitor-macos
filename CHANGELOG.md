# Changelog

## Unreleased

- Added a separate offline lifecycle/write NUT candidate: reject incomplete
  interrupt-OUT completions and add guarded dump cancellation checkpoints.
  Exact extracted-source write tests and synthetic signal-helper tests pass;
  cooperative termination remains partial and hardware remains on hold.
- Added 17 synthetic Python contracts for those replay tools to app validation.
  USB/serial driver builds passed offline; neither driver binary was executed.

- Qualified the exact merged guarded/HID patch combination offline: both
  application orders produce identical sources; synthetic harnesses and
  USB/serial builds pass. Existing patches and source fences remain unchanged;
  no NUT binary or hardware was run.

- Added a separately pinned guarded NUT patch for merged master `73c4502`,
  preserving upstream padding, calibration and HID fallback corrections.
  Offline source/policy checks and USB/serial builds pass; no driver execution
  or hardware qualification. The original patch remains unchanged.
- Added a static merged-rebase preservation checker with six mutation checks,
  separate from normal app CI and real protocol testing.
- Added a third exact source pin to the offline NUT HID fallback replay after
  upstream PRs #3714 and #3728 merged. Source-fence coverage now includes all
  three pins. Hardware compatibility and the full-driver baseline are unchanged.
- Added a separately pinned merged-master HID fallback validation candidate.
  Exact RED on pristine source and GREEN on the candidate passed the bounded
  extracted-source replay; 13 synthetic Python runner-contract tests are wired
  into local validation. No full-driver build, hosted-CI result, or hardware
  qualification is claimed.
- Prevented the stored-history range picker's visible title from wrapping in
  the compact controls row; its accessibility group label remains available.
- Recorded bounded production Apple-reader and history-export observations.
  Installed-widget operation and advanced APC telemetry remain unqualified.

## [0.1.0-preview.1] - Source preview

Date: 2026-10-08

- Documented a source-only archive workflow with an explicit commit, checksums
  and clean extracted-source validation, separate from binary distribution.
- Added minimal macOS app/widget privacy declarations and checks of source and
  built-bundle placement. The platform-specific review distinguishes local
  storage from developer data collection and does not invent required-reason
  API declarations for native macOS or claim Apple distribution approval.
- Extended the offline NUT fallback replay to the exact publisher and a
  test-only wrapper around callback reset statements, with two-file source
  hashes and seven source-fence tests. It checks synthetic status emissions
  and ordering, not real dstate, USB reopen, or hardware behavior. Recorded
  already-included upstream HID descriptor parser fixes separately from the
  remaining runtime-report and clock-rollback residuals.
- Added opt-in `UPS_WIDGET_FIXTURE_MODE=YES` for a synthetic widget fixture,
  with `NO` as the default, fail-closed invalid plist values, separate fixture
  storage and WidgetKit kind, and an explicit synthetic badge. The fixture does
  not use the real reader, history recording, or alert delivery; preview mode
  takes precedence without publishing shared widget data.
- Added a widget timeline transition at capture time plus maximum age plus one
  second for fresh valid payloads. This lets the UI reflect stale status after
  the inclusive freshness boundary, but does not guarantee WidgetKit scheduling
  at that time.
- Added an offline, source-hash-fenced replay of the upstream HID fallback
  decoder/getter, comparing the pinned base and proposed correction. Synthetic
  source-fence tests run in normal validation; the C replay is a separate local
  qualification, not a driver execution or an integrated upstream fix.
- Hardened the offline guarded NUT source prototype: effective foreground dump
  mode only, no sibling-driver stop/signaling path, and no interrupt PIPE
  clear-halt recovery. Added policy and static call-site regressions; no driver
  or hardware execution.
- Documented open upstream USB recovery and HID fallback-status issues. The
  guarded patch does not fix the fallback defect or qualify UPS measurements.
- Recorded an authorized local Apple Development app/widget build and verified
  matching signed group entitlements. Runtime shared access and installed
  widget behavior remain open; no personal signing identifiers are included.

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
  this source version is not an installable app or hardware qualification.
- Updated public compatibility, build, contribution and third-party licensing
  guidance. Live watt qualification remains open.
- Added pinned hosted CI and local synthetic validation. The first hosted run
  passed source, test and ad-hoc build checks; these do not qualify widget
  installation, VoiceOver or real hardware.
