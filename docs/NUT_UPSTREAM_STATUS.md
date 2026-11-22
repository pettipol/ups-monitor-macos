# Experimental NUT Upstream Status

Full source-research snapshot: 2026-10-11. The targeted discussion refresh
below is dated separately. This is source research, not hardware
qualification. The default app does not run `upsmon` or implement automatic
shutdown. Separately opted-in developer bundles can package and launch a
hash-pinned, bounded experimental driver. This developer path is not a
qualified continuous production backend.

## Targeted lifecycle recheck, 2026-10-27

The official GitHub connector still reports [issue #3751](https://github.com/networkupstools/nut/issues/3751)
closed with one contributor reply and [PR #3778](https://github.com/networkupstools/nut/pull/3778)
merged as `59c77828298b4ff4e1a5c752123227647a8e906e`. The PR explicitly reports
no hardware testing. Its bounded abandoned-transfer reap follows a USB reset
in the upstream libusb path; the local shared-HIDAPI candidate does not adopt
that reset/recovery path. This recheck does not change dependency pins or
establish continuous-session compatibility. Release versions were not
refreshed in this check; the dated stable-version observations below retain
their original scope.

## Targeted metadata refresh, 2026-10-26

The official GitHub API still identifies [NUT v2.8.5](https://github.com/networkupstools/nut/releases/tag/v2.8.5)
and [libusb v1.0.30](https://github.com/libusb/libusb/releases/tag/v1.0.30)
as the latest stable releases. Issue #3751 remains closed, with one contributor
reply; PR #3778 remains merged. Its description still explicitly excludes
hardware testing. The discussion and PR describe the upstream libusb transport,
not the separately guarded HIDAPI path used by the local candidate. This check
read release, issue, comment and PR metadata only. It did not audit current master,
change dependency pins or qualify any hardware behavior.

## Targeted Lifecycle Discussion Refresh, 2026-10-24

[Issue #3751](https://github.com/networkupstools/nut/issues/3751) received a
contributor response on October 18 and was closed on October 21 by merged
[PR #3778](https://github.com/networkupstools/nut/pull/3778). The earlier
"no replies" observation below is historical. The PR describes two changes
to the upstream asynchronous libusb transport:

- Start the event-pump thread before submitting the first transfer, so thread
  creation failure leaves no submitted transfer outstanding.
- After reset and before closing the handle, allow a bounded event-loop reap
  of abandoned transfers; report those still pending as leaked.

The PR explicitly reports no hardware test. Its reset/reopen path is not our
guarded HIDAPI transport, and the merge is not an endorsement of SMC1500I
firmware 10 on macOS. This source refresh does not adopt the PR, change any
dependency pin, authorize reset/reopen, or qualify the local candidate. It
also does not explain a local HIDAPI admission failure.

The remaining sections preserve their dated research snapshots; unqualified
"remains open" and version statements there refer to those earlier checks.

## Historical Targeted Discussion Refresh, 2026-10-12

The three official discussions and official NUT/libusb release pages were
read in BrowserOS neo without posting or changing anything. This check did
not fetch or audit current master or change dependency pins. The release
pages still label NUT v2.8.5 and libusb v1.0.30 as latest stable; this is a
release-page observation, not adoption or qualification of a new build.

- [Issue #3751](https://github.com/networkupstools/nut/issues/3751), the
  source-only lifecycle question, remained open with no replies visible. It
  does not report a reproduced hardware failure or an executed driver test.
- [Issue #3587](https://github.com/networkupstools/nut/issues/3587) remained
  open. A visible October 10 user report describes a run as apparently working;
  it is an attributed report, not independently verified compatibility. Later
  timeline references include serial and control-command changes, not a
  demonstrated asynchronous USB ownership/stop/reopen/exit solution.
- [PR #3719](https://github.com/networkupstools/nut/pull/3719) remained open
  with serial and control-command scope, observed head `c36aa01`. The listed
  seven changed files do not include `apcmicrolink-usb.c` or `libusb1.c`.
  No bounded USB cancellation or reopen
  solution was established from its discussion and listed scope. This is not
  a source-diff or commit-ancestry audit, and the PR is not adopted here.

The official [NUT releases](https://github.com/networkupstools/nut/releases)
and [libusb releases](https://github.com/libusb/libusb/releases) pages show
no newer stable release than those already recorded. None of the discussion
activity establishes SMC1500I firmware 10 on macOS compatibility. Transient PR
CI counts are not treated as USB lifecycle or hardware evidence.

No upstream resolution of the local probe-policy gap was established by this
limited check. This does not imply absence of other upstream work. A count of
session attempts and a no-reopen policy still require local source review;
neither property proves data completeness, electrical safety or real firmware
compatibility. Any future device session still requires separate consent.

## Merged Upstream, Not Hardware Qualified

The official GitHub PR records now confirm these merges on 2026-10-10:

| Change | Merge time (UTC) | Merge commit |
|---|---|---|
| [PR #3714](https://github.com/networkupstools/nut/pull/3714): calibration-status mapping and USB tunnel padding | 14:15:47 | `d460f7b5829f15569914077fd3e5fcb64d087465` |
| [PR #3728](https://github.com/networkupstools/nut/pull/3728): HID fallback status freshness | 14:22:29 | `b3ca797a274d85103f7cb78d5da445c309911f78` |

The observed master is
[`73c4502191d025e35122463986a80c676e734b04`](https://github.com/networkupstools/nut/commit/73c4502191d025e35122463986a80c676e734b04).
Local Git ancestry confirms both merges are included. The three-revision
[offline fallback replay](NUT_HID_REPLAY.md) now covers this exact master;
the two synthetic residuals below remain. This is not a full-driver test.
NUT stable remains 2.8.5 and libusb stable remains 1.0.30 at this check.

The original guarded patch and its qualification baseline remain on `1a8369f`.
A non-mutating `git apply --check` of that original patch against the new master fails
at the frame-parser context changed by #3714. Do not force-apply it or reuse
the old guard evidence for the new source. A reviewed offline rebase and
renewed guard tests were required before considering a new candidate.
The upstream changes do not remove USB opening/claim, STOP/INIT/NEXT tunnel
messages, or cleanup traffic. No new driver was built or run during that
research refresh. The subsequent same-day [guarded rebase](NUT_GUARDS_MERGED.md)
provides a separately named patch, renewed static/policy checks and USB/serial
build evidence. Neither resulting driver binary was run. This does not promote
the candidate to a production backend or qualify live hardware.

[PR #3719](https://github.com/networkupstools/nut/pull/3719) remains open and
unmerged. Its serial and control-command changes must not be attributed to
the tested master or added to this monitor's read-only v1. Issue #3587 also
remains open; the maintainer's
[2026-10-10 comment](https://github.com/networkupstools/nut/issues/3587#issuecomment-6098513076)
requests testing of the integrated master, not a compatibility endorsement.

## Unresolved Hardware Findings

- [NUT issue #3587](https://github.com/networkupstools/nut/issues/3587) describes
  startup timeouts and an unresponsive USB Microlink session on other Smart-UPS
  hardware under Linux. A participant reports needing to reconnect the USB
  cable to recover communication. This is not evidence for the same behavior
  on SMC1500I firmware 10 under macOS, nor a measurement of electrical risk.
- [NUT PR #3728](https://github.com/networkupstools/nut/pull/3728) describes a
  false `OB` status on SMX1500RM2UC firmware 16.0: charge/runtime reports made
  the HID fallback appear fresh before AC status had been decoded. Later stale
  data caused a configured `upsmon` to shut down a host that still had mains
  power. That is a reported software shutdown, not a demonstrated UPS output
  interruption. The merged fix requires recent decoded AC/discharging status;
  its author reports offline replay and tests on that SMX, but no real
  on-battery fallback transition or other-device qualification.

At the original 2026-10-08 review, PR #3728 was open and stacked on #3714.
Its entire diff was not an isolated fix. The then-reviewed master matched
[`1a8369f8688443a500527059167d2f66ca27535f`](https://github.com/networkupstools/nut/commit/1a8369f8688443a500527059167d2f66ca27535f).
Our unchanged guarded patch does **not** correct this fallback-status defect.
Its baseline has not been promoted to the newly merged master. Restricting
USB/process side effects does not make upstream measurements trustworthy.

## Already Available Parser Fixes

[PR #3586](https://github.com/networkupstools/nut/pull/3586), merged on
2026-08-27, bounds the HID descriptor parser's usage/path stacks. Its merge
commit `ab82520df91714649f41326e9080d2d10fc3709a` is an ancestor of our pinned
base. The base also includes these subsequent parser changes:

- [`18acb37599657198b9382b32d17e7cac55243190`](https://github.com/networkupstools/nut/commit/18acb37599657198b9382b32d17e7cac55243190)
  rejects truncated descriptor items before reading their declared bytes.
- [`5cbff890de092204c2bec1001932378da6c9a26c`](https://github.com/networkupstools/nut/commit/5cbff890de092204c2bec1001932378da6c9a26c)
  sizes the usage stack from the descriptor length while retaining bounds
  checks. The current pin is not accurately described as a fixed 50-usage cap.

These existing fixes should be reused, not reimplemented. They concern HID
**descriptors**, not the runtime fallback report decoder exercised below.
Their inclusion does not resolve the replay's truncated-report residual.

[PR #3714](https://github.com/networkupstools/nut/pull/3714), open on October 8
and merged on October 10, separates calibration result flags from `ups.status`
and discards the remaining tunnel-report bytes after extracting a frame only when that
remainder is all zero. It is not indiscriminate removal of zero bytes before
parsing. Its reported SMX1500/firmware-16/Linux results do not qualify the
target SMC1500I/firmware-10/macOS combination.

## Offline Follow-Up

The exact corrective commit
[`e0bb8ea64f7f8a140ad8908904186a05a324c295`](https://github.com/networkupstools/nut/commit/e0bb8ea64f7f8a140ad8908904186a05a324c295)
was compared with the original pinned base using an
[offline replay of the actual decoder/getter and publisher](NUT_HID_REPLAY.md). The base
published incomplete or stale status in the synthetic scenarios; the proposed
correction withheld those snapshots. Two residual behaviors reproduced in
both revisions: a matching report ID with no status payload can refresh zero
values, and a backward wall-clock step can make old values appear fresh.
No claim is made that either input occurs on a particular UPS. The expanded
replay now checks the publisher's `OL`/`OB` calls and ordering using recording
stubs, plus the exact callback reset statements in a test-only wrapper. It
does not run the callback itself, reopen USB, emulate real dstate inference,
or include the full driver, descriptor parser, threading, server or `upsmon`.

The isolated correction also passed a textual `git apply --check` against the
pinned base. Its stacked ancestry alone does not establish a code dependency
on #3714; conversely, textual applicability and a fragment replay do not
qualify an integrated backport. The guarded patch remains unchanged. These
results supported further upstream review, not hardware testing or release.
The isolated `e0bb8ea` delta changes only `apcmicrolink-usb.c` and `.h`;
differences in other files between its full tree and our base include its
stacked ancestry and must not be attributed to that isolated correction.

On October 11 the same extracted functions from merged master were replayed
with the same assertions. Their generated translation unit differs from the
corrective revision only in its revision comment. This confirms continuity
of the bounded fallback fix; the replay does not exercise #3714's padding
scanner hook, calibration map, full startup, concurrency, or USB lifecycle.

A separate [merged-pin HID candidate replay](NUT_HID_VALIDATION.md) then
passed its exact-pristine RED and exact-candidate GREEN contracts. It covers
only extracted fallback/getter/publisher fragments with synthetic reports,
clock and recording stubs. This does not build the complete NUT driver or
qualify hardware, USB coexistence, measurement accuracy, or shutdown behavior.

## Qualification Boundary

An existing [SMC1500I USB report in #1426](https://github.com/networkupstools/nut/issues/1426)
uses a different firmware and Linux. No exact firmware-10/macOS compatibility
or coexistence proof was established by this review. Absence of a found report
is not proof that no report exists.

A client cannot detect every plausible but incorrect status reported by its
server. Rejecting stale/incomplete lists does not validate the underlying
measurement. Do not attach the experimental driver to a shutdown supervisor
or use this monitor as an electrical safety mechanism. Any future hardware
test needs independent upstream/source review, a bounded agreed protocol,
appropriate load isolation and separate informed consent. No such test was
performed here. See [guard limitations](NUT_GUARDS.md).
