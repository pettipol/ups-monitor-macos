# Upstream Reuse Review

Checked on 2026-10-08. This is a bounded review, not a claim that no other useful
project exists. No third-party application code has been copied so far.

## NUT

NUT remains the intended advanced telemetry backend. Its driver and server
support are the substantial reusable protocol implementation. Keep them separate
from this application's UI, data-quality rules and native Apple adapter.
See [the feasibility record](NUT_FEASIBILITY.md).

## APCUPSMonitor

[eliliu911/APCUPSMonitor](https://github.com/eliliu911/APCUPSMonitor), MIT,
was created on 2026-10-02. Reviewed commit:
[`e4cd78ce54198437a3e6a6fd896183192f9caec4`](https://github.com/eliliu911/APCUPSMonitor/commit/e4cd78ce54198437a3e6a6fd896183192f9caec4).
It is a small native menu application for Back-UPS, with a reported BE600M1 test,
not a general Swift NUT library or a demonstrated Smart-UPS C Microlink solution.

The README and `SystemUPSReader.swift`, `SnapshotProcess.swift` and
`MenuContentView.swift` were inspected. Useful ideas include independent readers,
bounded worker lifetimes and separation of native and HID refresh cycles.
These are candidates for future focused reuse, not qualifications of behavior.

Adopting the application unchanged would not meet this project's contract:

- Its system reader accepts name-based UPS matches and exposes a raw dictionary.
  This project requires explicit UPS type filtering and a sanitized public schema.
- Its menu presents estimated watts from a user-configured nominal rating and
  load percentage. This is not proof of active power for a target UPS.
- Its direct shared HID path is different from Microlink; shared-open flags
  alone do not prove non-interference with every macOS UPS service or firmware.
- NUT, local energy coverage and WidgetKit are not established by this review.

Decision: retain the minimal tested Apple adapter and NUT-centered architecture.
Reconsider individual upstream modules before adding analogous infrastructure;
preserve the original MIT notice if code is adopted. Do not run the upstream HID
reader on real hardware as part of this source review.
