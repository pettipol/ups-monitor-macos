# Changelog

## Unreleased

- Shortened Apple widget titles when a complete recognized firmware/ID suffix
  is present. The full sanitized name remains in accessibility labels, help,
  the app and the widget payload. Other providers and unrecognized names are
  unchanged. Added focused tests and two explicitly synthetic render cases.

- Added a pinned source-extracted USB lifecycle observation: six expected RED
  pending-transfer/close cases and two completion controls with local mocks.
  Runner contracts join normal CI; C observations are separate and offline.
  No driver fix, hardware qualification or installed-app change is implied.
- Published the source-only lifecycle question as NUT #3751 and linked the
  qualification hold; maintainer guidance and process-exit policy remain open.

- Added an optional sanitized Apple presentation name, paired with the current
  source observation and used only as a display label plus an optional local
  widget-envelope field. It does not change source identity or enter history,
  exports or energy records. Names may identify a device/location and are not
  guaranteed model/SKU labels; missing names retain the UPS/provider fallback.
  Synthetic tests, offline builds and named offscreen renders passed; this does
  not qualify an installed widget or new hardware measurements.
- Expanded the medium widget to show battery charge and six distinct metrics:
  runtime estimate, UPS load, active watts, input voltage, output voltage and
  apparent power. Missing readings, provenance and stale status remain explicit;
  the small widget is unchanged. This does not acquire additional hardware data.
- Added three compact synthetic render cases and a labelled offscreen preview.
  The expanded layout is not yet installed or qualified in the WidgetKit host.

- Added an on-demand Widget status sheet using the public WidgetKit
  configuration API. Counts are restricted to the production widget kind;
  unavailable queries are distinct from zero configured widgets. Configuration
  status is not proof of installed rendering or shared-data freshness.

- Documented the remaining experimental USB transfer-ownership and shutdown
  gaps in a focused static review. Driver qualification remains on hold;
  no hardware execution or forced-termination policy was introduced.

- Added a separate offline guarded IN observation-budget candidate: one
  monotonic epoch, finite remaining-time submissions and no guarded sync
  fallback. USB/serial target builds pass without executing drivers. This is
  cooperative, not a hard process deadline or hardware qualification.
- Reproduced continued callback activity on the previous source, passed nine
  candidate helper/callback cases, and added 14 Python runner contracts.
  Startup/read/flush/reopen checks are static, separate from dynamic replay.

- Added a separate offline USB async-state candidate protecting three shared
  scalar flags with the existing mutex. USB/serial builds pass without
  executing drivers; complete async lifecycle and hardware remain unqualified.
- Reproduced three scalar races in pinned source fragments with ThreadSanitizer
  and passed the matching candidate cases. Added 17 Python runner contracts;
  source-fragment replay is separate from app CI and full-driver execution.

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
