# Release Gates

This checklist is an acceptance contract, not a record of successful tests.
Attach a dated command result, test artifact or observed behavior to each item.

Preparation evidence: [CI configuration](CI.md), [validation sequence](VALIDATION.md),
[compatibility](COMPATIBILITY.md), [bounded privacy audit](PRIVACY_AUDIT.md),
[data policy](../PRIVACY.md) and [license inventory](../THIRD_PARTY_NOTICES.md).
Their presence does not automatically clear any gate below.

## Foundation

- [ ] Source-only clean checkout builds using the documented toolchain.
- [ ] Exact dependency revisions, licenses and checksums are recorded.
- [ ] CI actions are reviewed and pinned; outside pull requests receive no secrets.
- [ ] Deployment target is supported by APIs and validated separately from SDK version.
- [ ] Signing, App Group and widget registration requirements are documented and tested.

## Correctness

- [ ] Native enumeration includes UPS and excludes the Mac's internal battery.
- [ ] Capacity denominators, sentinel values, minutes and millivolts are normalized correctly.
- [ ] Multiple UPS sources, absent devices and malformed source dictionaries are covered.
- [ ] NUT parsing covers partial lines, escaping, oversized responses, EOF, errors and timeouts.
- [ ] No writable NUT or UPS commands are exposed through UI or transport APIs.
- [ ] Source changes, reconnection and clock changes cannot mix unrelated histories.
- [ ] Stale or unsupported values cannot appear as current zero-valued measurements.
- [ ] Energy tests cover constant/ramping loads, missing intervals, reset and invalid time.
- [ ] Native, upstream-derived and application-estimated quantities remain distinguishable.

## Product

- [ ] Menu and details work with real telemetry, including missing advanced fields.
- [ ] Source selection, settings, export, retention and deletion work end to end.
- [ ] Display handles long values, accessibility sizes, VoiceOver and light/dark appearance.
- [ ] Widget works when installed, shows age, and behaves honestly when the app stops updating.
- [ ] Local notifications are optional and do not imply shutdown protection.
- [ ] No required accounts, network telemetry or cloud service.

## Hardware Qualification

- [ ] Each real test lists device model, firmware, platform, backend and exact version.
- [ ] A separate consent record precedes interface claims or potentially disruptive work.
- [ ] Native service and power settings are compared before/after authorized driver tests.
- [ ] LCD comparisons state observations and tolerances, not unsupported calibration claims.
- [ ] Sleep/wake and disconnect behavior are separated into simulated and observed evidence.
- [ ] No Linux or different-firmware result is presented as local macOS proof.
- [ ] The target UPS's advanced telemetry is either demonstrated or remains an explicit blocker.

## Publication

- [ ] No real serials, UUIDs, addresses, credentials or unredacted dumps in files or Git history.
- [ ] MIT covers original code only; dependency notices and source obligations are satisfied.
- [ ] English README, Italian guide, contribution and security policies are present.
- [ ] Compatibility table distinguishes tested, experimental, unsupported and unknown cases.
- [ ] Public repository and release links exist and match tested revisions.
- [ ] Downloaded release artifact matches the recorded checksum and launches as documented.
- [ ] Signature/notarization status is explicit; users are not told to disable Gatekeeper.

A source preview can be useful before every gate passes, but it must not be
presented as the completed advanced monitor for a target UPS.
