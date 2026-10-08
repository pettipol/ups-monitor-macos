# Optional Local Alerts Contract

Alerts are opt-in for the running app session and disabled at every launch.
No permission prompt, notification-center access or submission occurs in preview,
unit-test defaults, or before explicit enable. No hardware/control, startup item,
remote notification, sound, badge or critical/time-sensitive entitlement is added.
Alerts are informational, not shutdown protection or a guaranteed alarm service.

## Pure Policy

Add `UPSAlertPolicy` (Equatable, Sendable) with public initializer and mutable
`lineChanges`, `lowBattery`, `monitoringLoss` booleans (default true) and
`lowChargeThreshold: Int` (default 20, valid 5...50). Add `UPSAlertKind` cases
`onBattery`, `powerRestored`, `lowBattery`, `monitoringUnavailable`, and
`UPSAlertEvent(kind:capturedAt:)` (Equatable, Sendable). Events contain no source
IDs, paths, device names, serials, server names or arbitrary upstream text.

`UPSAlertEvaluator` is a bounded value type with `init()`, `reset()`,
`resetObservations()` (preserving per-kind cooldowns) and mutating
`evaluate(snapshot: MonitorSnapshot?, acquisitionSucceeded: Bool, now: Date,
uptime: TimeInterval, maximumAge: TimeInterval, policy: UPSAlertPolicy)` returning
at most four events. It performs no I/O. Reject invalid policy/time/age or
backwards monotonic time and reset continuity. Validate the full snapshot and
freshness. Only successful, fresh, status-available samples without sourceOffline
qualify as usable. Unknown line state cannot prove a line transition.

Keep only one exact source/session baseline. A different source resets condition
state, not the global per-kind cooldown. Identical/replayed capture times do not
retrigger or overwrite observations; timestamps must increase for that source.
Capture gaps exceeding maximumAge, failed/stale/unavailable data clear line-transition continuity and
must never imply restored power. A first usable on-battery sample can notify
the current condition; powerRestored requires a prior continuously usable
on-battery observation from the same source. First on-line data is silent.

Low battery is supported by an explicit lowBattery flag or available charge
at/below threshold. Clear the latch only when the flag is absent and available
charge is at least threshold+5; missing charge cannot imply recovery. Do not
rearm merely because a read failed. Source changes reset the latch.

Monitoring loss notifies once after 30 continuous monotonic seconds of unusable
data, only after a usable observation. A single bad observation does not notify.
Recovery cancels the pending loss and rearms it. Do not call missing data a power
outage; its event capture time is the last usable observation. All other events
carry the supporting sample's capture time. Never manufacture an observed state.

Each kind has a 60-second monotonic cooldown, shared across source changes.
Consume a condition transition even when suppressed by cooldown so an old
transition is not delivered later as a new event. No unbounded event history.

## Delivery Controller

App-level `UPSAlertController` is @MainActor @Observable, with private(set)
`isEnabled`, `isBusy`, `message: String?`, `policy` and terminal stop. Public-to-app
methods: `setEnabled(_:) async`, `setPolicy(_:)`, `observe(snapshot:... same clocks
and freshness...) async`, `suspend() async`, `stop() async`. Suspend resets
observations and removes this app's alert requests, without changing opt-in or
per-kind cooldowns; stop disables permanently. Policy changes reset condition
observations but preserve cooldowns.

Inject an `UPSAlertDelivery` protocol (@MainActor, class-bound) with async
`requestAuthorization() throws -> Bool`, `isAuthorized() async -> Bool`,
`submit(_ event: UPSAlertEvent) async throws`, `clear() async`. Authorization is
requested only by explicit enable, never by observe. Real delivery checks current
settings again before submission. Unsupported/denied permission disables alerts
with a redacted message. Failed submission is reported, not retried on every
poll. No raw OS errors in UI. On enable/disable/suspend/stop, generation fences
prevent late authorization from re-enabling or stale events from submitting.
An admitted submission may complete after cancellation: await/drain owned work
then clear only the fixed identifiers owned by this feature. Never remove other
features' notifications. Serialize delivery so async observations cannot queue an
unbounded backlog. Preserve the latest observation or conservatively skip while
busy, with subsequent polling ensuring reevaluation.

`SystemUPSAlertDelivery` must initialize UNUserNotificationCenter lazily, only
after explicit use. Request only `.alert`. Four fixed opaque identifiers, nil
trigger for immediate scheduling, generic constant title/body, no userInfo,
attachments, sound, badge, actions or hardware IDs. Include a formatted capture
time in the body, distinguishing last observation for monitoring loss. Delivery
acceptance is not proof of a banner being shown. User/System Settings determine
actual presentation. Retained OS notification history is not covered by local
SQLite deletion or a physical-erasure guarantee.

## Integration and Evidence

The app owns the controller, passes only the selected source, acquisition result,
freshness and clocks, suspends on backend replacement/sleep and stops on quit.
Changing selection suspends the previous observations before processing the next.
UI: a bell settings action, session toggle, three event toggles and a bounded
threshold stepper. Preview cannot enable alerts. No real permission request or
notification is run during implementation; tests inject a fake delivery.

Test initial/transition behavior, stale/future/invalid/replay data, exact source,
low-battery latch/hysteresis, monotonic loss delay, cooldown, backwards clock,
default-off/preview, denied/revoked permission, delivery failure, duplicate polls,
delayed authorization/submission and disable/stop races. UI and actual macOS
notification delivery remain separately unverified until explicitly exercised.

Apple API reference checked on 2026-10-08:
[Asking permission to use notifications](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications).
The local Xcode 27 SDK headers additionally document replacement by request ID
and targeted removal. No external dependency is introduced.
