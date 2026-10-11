# Native Capability Baseline

One observation was made through the native Apple power-source service. No USB
interface was opened, and no power-management configuration was changed. This
is a qualitative capability record, not a device-specific compatibility test.

## Observation

The Apple service enumerated one present UPS and one internal Mac battery.
Only the UPS was emitted as a monitored source; no unknown or absent UPS entries
were observed. The source reported AC power, present and not charging.

| Field | Native result | Interpretation |
|---|---|---|
| Battery charge | Reported (ratio) | Derived from current/max capacity; exact value omitted |
| Battery voltage | Reported (V) | Power-source voltage; not AC input or output; exact value omitted |
| Time to empty | Unavailable | Apple documents it as valid only on battery and not charging |
| Time to full charge | Unavailable | Not in charging context |
| Source current | Unavailable | Inspected documented key; no valid value returned |
| Source temperature | Unavailable | Inspected documented key; no valid value returned |
| Internal failure | Unavailable | No valid documented boolean returned |
| Battery health | Unavailable | No recognized health enum returned |

This whitelist is not a raw inventory of every possible private/vendor field.
It does not establish that AC voltage or active power is impossible to obtain
through another backend. No live energy measurement is claimed.

## Interpretation Sources

The installed Apple SDK `IOKit/ps/IOPSKeys.h` documents capacity ratios,
time-to-empty validity and minutes, time-to-full charging context, presence,
voltage in mV, current in mA and temperature in Celsius. The probe rejects
non-integral, non-finite, boolean-as-number and out-of-Int32 values.

NUT's [macosx-ups implementation at the pinned revision](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/drivers/macosx-ups.c#L213-L221)
maps the same Apple voltage key to `battery.voltage`. This supports the battery
label, not an AC-voltage interpretation or an accuracy specification.

## Verification Scope

The package's synthetic tests cover filtering, missing and malformed values,
units, provenance and output privacy. Independent energy tests first reproduced
cross-device accumulation and out-of-order double counting; fixes now bind each
integrator to one source and reject replayed intervals/tokens. An analytic linear
load test validates trapezoidal integration on irregular sample spacing.

Live USB driver behavior, a power-loss transition, runtime accuracy, LCD
agreement, multi-device real behavior and long-duration stability remain untested.
Changing or disconnecting hardware is not part of this baseline.

## Production Qualification Observation (2026-10-11)

A production `SharedRelease` build from source revision `0969b6cced759aa5bb80fe7d1e4fd9126d209f31`
was signed locally with the previously authorized Apple Development identity
and dedicated App Group. Both app and widget Info.plists explicitly set
`UPSWidgetFixtureMode` to `NO`; their signed App Group entitlements matched.
Deep/strict code-signature verification and the repository privacy-manifest
checker passed. This records build and packaging evidence, not widget operation.

The app was then opened in production mode. The Apple backend selected one UPS
source, reported online status, and showed a fresh capture. Charge was available
as a derived ratio and battery voltage was reported. The UI reported not
charging. The Mac's internal battery was present in the native power-source
inventory but was excluded from the app's UPS list. Time-to-empty/full, active
power, apparent power, AC input/output voltage, current and temperature were unavailable; energy
was consequently unavailable because no power measurement was available. A
manual refresh left the same values fresh at the time observed. These are field
availability observations only, not accuracy, LCD-agreement or long-duration
stability evidence.

History remained off. The session alert switch was off. No permission prompt
appeared. Process inventory matched no `apcmicrolink`, `usbhid-ups`, `upsd` or
`upsmon` process. This is a point-in-time process observation, not a broader
system state guarantee. This app session used native power services only; this
qualification did not claim USB/HID interfaces or send experimental reports.

## History Export Observation (2026-10-11)

Offline validation of a short native-history export found three records in the
JSON export and SQLite store, with 33 corresponding CSV rows. Decoded JSON
records matched the stored payloads and source/session identities; CSV fields
matched the records, including values, units, quality and provenance. JSON
capture times matched SQLite at microsecond precision; CSV timestamps preserved
millisecond precision. Unavailable metrics remained empty rather than becoming
zero. This validates one short export only; retention and deletion behavior and
long-duration recording were not tested.

The empty-history view, recording on/off, both save-panel exports and the
three-sample charge chart were exercised in the app. Choosing unavailable
runtime data displayed no valid samples, not zero points. The stored session
remained readable after a normal app quit and reopening a new signed build;
recording defaulted to off. A range-picker title that wrapped in the compact
controls row was hidden visually while preserving the accessible `Range`
group; the corrected row was inspected in the running app. This does not
qualify VoiceOver, all text sizes or appearance modes. The focused history
test selection passed 29 XCTest tests and eight Swift Testing tests.
