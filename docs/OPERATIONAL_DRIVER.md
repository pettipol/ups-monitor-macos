# Operational driver v2: experimental, offline qualification

The opt-in driver combines the schema-2 formatter, native health guard and
freshness collector in one session. The existing v1/H07 profile is unchanged.
This is not an enabled product profile or a qualification for daily hardware use.

`nut-operational-driver-v2.patch` applies after the admitted guarded/continuous
NUT baseline, pacing patch, `nut-operational-formatter-v2.patch` and
`nut-operational-health-v2.patch`. Apply the E24
`nut-operational-cleanup-v2.patch` after health-v2 and before this driver patch
in any future build. The operational driver patch changes only
`drivers/apcmicrolink.c` and `drivers/main.c`. Its driver preimage is
`4193f05e286d6fb071ae0aed8aa3363175b55d1a47b265cf08550f917269d015`;
the E25 driver postimage is
`6b197e27e61183b9496aa68c8f59976ba5144add1d52fa9ac5b6c93924e31c75`.
The main preimage is
`40887c15f634ea963204d2e0060623b5729d1c690103204656475e801219ff06`;
the postimage is
`11a8d2470dc326a599cdb28a0a30881b935ce4d831416f659e73d3a27ea3ea75`.
E25 leaves `drivers/main.c` unchanged.
The freshness C/header are additional sources, not replacements for v1 helpers.

## Session behavior

The operational macro and runtime `monitor_stream_v2` selector are both required.
The restricted foreground CLI rejects conflicting stream selection, retry,
fallback, invalid device admission and the old lifetime-deadline profile before
native creation. The session opens once. Fresh successful publications renew a
15-second health lease after the 35-second startup allowance. It does not recycle
the connection at 120 seconds. Stop and terminal failures lead to one cleanup
attempt; there are no electrical controls, resets or automatic reconnects.

Publication freshness is rechecked immediately before output and after successful
flush. An emitted candidate that became stale during the flush terminates the
session without renewing the lease or retrying its sequence. Cleanup failure or
unresolved ownership cannot be presented as clean cancellation. A terminal
timestamp uses the post-cleanup clock; an unavailable clock is not fabricated.

## Whole-driver fake replay, 2026-10-27

Three full 17-unit C builds used ASan/UBSan: operational v2, v1 without the new
macro, and v1 with the macro compiled but its runtime selector unused. Static
dependency, symbol, library and link-map checks excluded a native HID host,
HIDAPI, libusb and IOKit from these test binaries.

The 29 distinct fake child invocations passed: 19 operational scenarios, eight
CLI rejections and two v1 regressions. Healthy v2 emitted 140 refreshed samples
over 700,600 virtual milliseconds, with one open/close, 140 accepted publications,
one cancelled End and maximum NEXT gap 200 ms. Stale and partial input expired the
health lease; Stop at admission/read/write/cleanup, cleanup failures, clock
regression, pre-output staleness and post-flush freshness boundaries were checked.
Both v1 variants retained 24 samples and duration-complete at 120,000 virtual ms.

Two interrupted validation passes were retained. A missing dictionary key and an
inapplicable v2 counter ceiling in the validator were corrected; existing captures
were revalidated without repeating any fake child. Mutations of terminal timing,
fault class and v1 counter/time bounds were rejected. Combined captured output
across the 29 children was 621,836 bytes.

`replay_operational_native.c`, `replay_operational_hooks.h` and
`nut-operational-replay-hooks.patch` are fake-only test support. The separate hook
patch adds four read-only checkpoints. The operational driver translation unit
alone redirects fwrite/fflush to the test host. A hardware build must omit these
hooks and aliases. The host delegates real serialization and flush; it injects
frames and virtual time, not fabricated output records.

`validate_operational_replay.py` is a pure capture validator. Its caller must
explicitly inject the admitted `continuous_protocol` module. It is not a hardware
launcher, a standalone test command or an automatically discovered CI suite.

## Explicit transport read failure, 2026-10-27

An additional fake-host scenario, `read-transport-error`, returns a persistent
read error immediately after the first accepted publication. It is distinct
from a user Stop or a physical device-disconnected notification. The full driver
emits one sample and one `guard_error` End, returns 1, and records IO reason 6
and FINISHED phase 4. It performs one cleanup STOP, close and dispose, with no
ordinary I/O after the injected error and no reconnect. The zero virtual
elapsed time is intentional: the injection occurs before the next clock advance.

Three bounded fake processes passed: this new case, `stop-read`, and
`healthy-700s`. The latter two outputs remained byte-identical to their earlier
captures. All 29 earlier captures passed the extended validator without rerunning
those processes. Only the new scenario accepts the two added summary counters;
historical summaries retain their exact schema. This extends synthetic error
coverage; it does not qualify physical USB loss, reconnect or daily use.

## Stop race fixes, 2026-10-28 (E25 RED → GREEN)

The whole-driver fake replay added two precise Stop checkpoints. At the
post-flush, pre-publication boundary, Stop produced one flushed sample and zero
accepted publications. At the post-update, pre-wait boundary, it produced one
sample and one accepted publication. Both cases now end `cancelled`, return 0,
and perform one cleanup STOP, close and dispose, with no later NEXT request.
The first terminal cause is retained. The RED replay had produced
`guard_error` and return code 1 at both boundaries before the driver change.

The GREEN replay passed 10 operational scenarios. The two new boundary cases
ended cancelled with return code 0. Five error controls remained
`guard_error` with nonzero return: `error-before-stop`, `read-transport-error`,
`cleanup-short`, `cleanup-late` and `clock-regression`. `error-before-stop`
confirms that a later Stop does not replace an earlier transport failure. The
remaining cases covered healthy 700-second virtual operation and Stop during
read and write. All timing in the 700-second case is virtual; it is not physical
duration or hardware qualification.

The 32 historical captures (29 E8 and three E19) were revalidated with the pure
validator; their child processes were not rerun. Replay hooks remain fake-only:
four earlier checkpoints and the two E25 boundary checkpoints. The additional
boundary summary counters are emitted only for those two boundary scenarios;
the transport counters remain limited to `read-transport-error` and
`error-before-stop`.

The earlier H08 GUI run showed readings but its Stop ended
`failed/guard_error`; E25 synthetic results do not change that hardware result
or establish a clean physical Stop. The installed runtime remains unchanged.
A public replay adapter and CI integration for these support files remain
open.

## Limits and remaining integration

The high-clock-origin scenario tests an absolute origin above `2^32`, not a
relative session duration above `2^32`. Standalone wide-integer tests and a full
driver session crossing that duration are separate evidence. The host does not
expose the private freshness watermark; its summary explicitly marks it unmeasured.
Physical disconnect/reconnect behavior, hardware operation beyond the prior
120-second H07 observation, app/widget integration and daily use remain open.

The current complete replay campaign is preserved as local development evidence.
A portable public reconstruction/execution adapter and CI wiring for these new
support files remain to be integrated. Existing v1 pins must not be changed merely
to make that reconstruction pass. Do not treat these sources as a distributable
runtime or enable the consumed H07 profile.
