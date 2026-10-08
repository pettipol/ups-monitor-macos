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
