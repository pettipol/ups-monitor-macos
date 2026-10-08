# Local Alert Policy

`UPSAlertEvaluator` is a deterministic value type. It performs no I/O and
returns only an alert kind plus the capture time supporting that event. No
source identity, device name, path, server name, or upstream text is copied to
an event.

Only validated, successful, fresh snapshots with available status and no
`sourceOffline` flag are usable. One exact source/session observation baseline
is retained. Source changes reset condition continuity but preserve per-kind
cooldowns. Failed, stale, unavailable, invalid, or offline observations clear
line-transition continuity; unknown line state also cannot establish a
transition. Replayed capture times are ignored and do not replace the last
observation.

The first known on-battery observation can report that current condition.
`powerRestored` requires a continuously usable on-battery observation followed
by usable on-line data from the same source. A gap or unknown line state breaks
that evidence. Low battery is asserted by an explicit flag or an available
charge at or below the configurable threshold. It rearms only after the flag
clears and available charge reaches threshold plus five points; missing charge
and failed reads do not imply recovery.

Monitoring loss requires a prior usable observation and 30 continuous
monotonic seconds of unusable input. Its event uses the last usable capture
time. Recovery before the deadline cancels the pending loss and rearms the
timer. Each kind has a shared 60-second monotonic cooldown across source
changes; transitions remain consumed when cooldown suppresses delivery.

Invalid policy, dates, age, or backwards monotonic time produce no event and
reset condition continuity. `resetObservations()` clears observations and
clock continuity while preserving global cooldowns; app lifecycle, source
selection, and policy changes should use this operation. `reset()` clears both
observations and cooldowns. A direct capture-time gap greater than the supplied
maximum age also clears only line-transition continuity, not the low-battery
latch. The evaluator is policy logic only: authorization, notifications, opt-in
lifecycle, preview behavior, and delivery remain responsibilities of the
separate app-level controller and delivery implementation. Synthetic tests do
not qualify actual macOS notification presentation.
