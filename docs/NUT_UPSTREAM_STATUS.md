# Experimental NUT Upstream Status

Reviewed on 2026-10-08. This is a source-research snapshot, not hardware
qualification. The app does not bundle or launch a UPS driver, run `upsmon`,
or implement automatic shutdown. The experimental guarded source patch is an
offline qualification artifact, not a production backend.

## Open Findings

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
  interruption. The proposed fix requires recent decoded AC/discharging status;
  its author reports offline replay and tests on that SMX, but no real
  on-battery fallback transition or other-device qualification.

PR #3728 was open at review and stacked on #3714. Do not treat its entire diff
as an isolated, merged, or qualified fix. The reviewed master still matched
[`1a8369f8688443a500527059167d2f66ca27535f`](https://github.com/networkupstools/nut/commit/1a8369f8688443a500527059167d2f66ca27535f).
Our guarded patch does **not** correct this fallback-status defect. Restricting
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

[PR #3714](https://github.com/networkupstools/nut/pull/3714) remained open at
review. It separates calibration result flags from `ups.status` and discards
the remaining tunnel-report bytes after extracting a frame only when that
remainder is all zero. It is not indiscriminate removal of zero bytes before
parsing. Its reported SMX1500/firmware-16/Linux results do not qualify the
target SMC1500I/firmware-10/macOS combination.

## Offline Follow-Up

The exact corrective commit
[`e0bb8ea64f7f8a140ad8908904186a05a324c295`](https://github.com/networkupstools/nut/commit/e0bb8ea64f7f8a140ad8908904186a05a324c295)
was subsequently compared with the pinned base using an
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
results support further upstream review, not hardware testing or release.
The isolated `e0bb8ea` delta changes only `apcmicrolink-usb.c` and `.h`;
differences in other files between its full tree and our base include its
stacked ancestry and must not be attributed to that isolated correction.

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
