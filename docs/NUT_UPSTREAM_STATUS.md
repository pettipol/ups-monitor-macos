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
