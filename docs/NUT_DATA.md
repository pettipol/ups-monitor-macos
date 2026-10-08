# NUT Data Adapter

`NUTData` is a pure parser and normalizer. It does not launch `upsc`, open a
socket, start a driver, or communicate with a UPS. The caller supplies both a
caller-assigned `sourceID` and the capture timestamp; neither is inferred from
UPS output. The timestamp records when the caller says it captured the command
output. It does not establish that the server or transport was current.

## Input

Use `UPSCJSONDecoder` for native `upsc -j <ups>` output. Upstream documents this
mode as a JSON object mapping variable names to string values; it is available
in NUT 2.8.5 and the inspected current source. A future command adapter should
select the text fallback only after verifying that the installed `upsc` lacks
the JSON option, rather than masking a parse or UPS error. The decoder rejects
malformed JSON, arrays, empty objects, the JSON error-object form, non-string
values, and bounded-size violations. Foundation's
`JSONSerialization` does not reliably report duplicate object keys; JSON input
therefore has no duplicate-key rejection guarantee. Do not use JSON duplicate
keys as a trusted override mechanism.

`UPSCTextDecoder` handles the documented `upsc <ups>` listing form
(`variable: value`) as a fallback. It accepts CRLF, rejects malformed lines and
duplicate whitelisted metrics, status, or driver-profile fields, and applies
the same normalization.
It is not a parser for NUT's quoted TCP wire protocol.

Both decoders enforce a 64 KiB input limit, 512 entries/lines, a 1 KiB text
line limit, and a 512-byte value limit. Unknown variables are discarded. The
output contains only the fixed `NUTMetricID` whitelist and normalized status;
it never contains raw output, UPS identity strings, host names, serial numbers,
alarms, descriptions, arbitrary driver names, or experimental fields. A
caller-provided source ID is limited to ASCII letters, digits, `.`, `_`, and
`-` (64 bytes maximum).

## Measurement mapping

The standard NUT variable names and units below follow upstream
`docs/nut-names.txt`. The adapter keeps each nominal measurement as its own
metric instead of merging it into a live reading.

| NUT variable | Snapshot metric | Unit |
| --- | --- | --- |
| `battery.charge` | `batteryCharge` | percent, constrained to 0...100 |
| `battery.runtime` | `batteryRuntime` | seconds, nonnegative; provenance `estimated` |
| `battery.voltage`, `battery.voltage.nominal` | `batteryVoltage`, `batteryVoltageNominal` | volts |
| `battery.current`, `battery.temperature` | `batteryCurrent`, `batteryTemperature` | amps, Celsius |
| `input.voltage`, `input.voltage.nominal` | `inputVoltage`, `inputVoltageNominal` | volts |
| `input.current`, `input.current.nominal` | `inputCurrent`, `inputCurrentNominal` | amps |
| `input.frequency`, `input.frequency.nominal` | corresponding input metrics | hertz |
| `input.realpower`, `input.realpower.nominal`, `input.power` | `inputRealPower`, `inputRealPowerNominal`, `inputApparentPower` | watts, volt-amperes |
| `output.voltage`, `output.voltage.nominal` | `outputVoltage`, `outputVoltageNominal` | volts |
| `output.current`, `output.current.nominal` | `outputCurrent`, `outputCurrentNominal` | amps |
| `output.frequency`, `output.frequency.nominal` | `outputFrequency`, `outputFrequencyNominal` | hertz |
| `ups.load` | `upsLoad` | percent, nonnegative; values above 100 remain valid during overload |
| `ups.realpower`, `ups.realpower.nominal` | `upsRealPower`, `upsRealPowerNominal` | watts |
| `ups.power`, `ups.power.nominal` | `upsApparentPower`, `upsApparentPowerNominal` | volt-amperes |
| `ups.temperature` | `upsTemperature` | Celsius |

NUT describes `ups.realpower` and `ups.power` as UPS-scope real and apparent
power. They are not renamed as input power. `ups.load` is never converted to
watts by this adapter. `battery.runtime` is labeled estimated because it is a
remaining-runtime estimate, not a directly measured duration. This parser
accepts the documented finite decimal syntax; scientific notation, `NaN`, and
infinities are invalid. This is an explicit decoder limitation, not a claim
that every NUT driver's exported output has been audited against that grammar.
A present but invalid reading has `quality = invalid`; an absent whitelisted
reading has `quality = unavailable` and no value.

NUT describes `ups.status` as an opaque space-separated token string. Only
recognized status flags are retained. `OL` and `OB` describe mains presence;
`OFF` independently marks output off and is retained as the `outputOff` flag.
Thus `OL OFF` has line state `.onLine` plus output-off, while `OFF` alone maps
to `.off`. The documented `HB` token is retained as `highBattery`. Conflicting
`OL OB` yields line state `.unknown` and quality `.invalid`. Unknown future
tokens conservatively yield line state `.unknown` and quality `.unqualified`.
A missing status is unavailable. A decode with no valid metric and no supplied
status (including empty or metadata-only output) throws
`noUsableTelemetry`, so it cannot be mistaken for a fresh all-missing snapshot.

For `driver.name == apcmicrolink`, the decoder tags `ups.realpower` and
`ups.power` with `derivedByDriver`. That driver documents these outputs as
derived from real/apparent load percentages and their respective nominal
ratings. The adapter does not retain or export the arbitrary driver name. All
other NUT values have `reported` provenance, which means only that the server
reported them; it does not independently verify measurement accuracy.

`experimental.output.energy` is intentionally not mapped to watt-hours. Its
unit is not established here. The adapter also does not infer power factor,
power from current and voltage, or any load-to-power conversion.

## Upstream basis

The NUT references below are from the inspected `networkupstools/nut` checkout
at revision `1a8369f8688443a500527059167d2f66ca27535f` (recorded in
`NUT_FEASIBILITY.md`):

- [`upsc` JSON output mode](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/man/upsc.txt#L28-L38)
- [`upsc -j` support in stable NUT 2.8.5](https://github.com/networkupstools/nut/blob/v2.8.5/docs/man/upsc.txt#L28-L38)
- [Standard NUT names, status opacity, UPS real/apparent power and temperature](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/nut-names.txt#L204-L229)
- [Standard input voltage/current/frequency fields](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/nut-names.txt#L354-L404), [input real/apparent power fields](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/nut-names.txt#L450-L455)
- [Standard output and battery fields](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/nut-names.txt#L505-L519), [battery units](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/nut-names.txt#L682-L724)
- [NUT numeric value format (decimal only; no scientific notation)](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/nut-names.txt#L96-L112)
- [Microlink derived power publication](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/guarded-source/drivers/apcmicrolink.c#L3321-L3359)
- [Standard UPS status flag meanings](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/source/docs/new-drivers.txt#L343-L360)

No NUT code is copied into this MIT-licensed repository. Decoder tests use
synthetic strings only; they do not qualify a NUT installation, driver,
transport, UPS, or real measurement.
