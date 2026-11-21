# Continuous backend: offline qualification, 2026-10-26

Status: **experimental, hardware qualification incomplete**. These results apply
to the diagnostic source and the local tests described below. They are not a new
public release, hosted CI result, daily-use qualification or a fix for the live
loss of fresh data. The diagnostic feature remains OFF unless explicitly built.

| Check | Observed result | Boundary |
| --- | --- | --- |
| Diagnostic C formatter | PASS: counters, saturation, null metadata, maximum finite values, append bounds, short/failed writes | Helper-only inclusion harness; no driver lifecycle or physical SIGPIPE test |
| Formatter JSON | Two strict-parser summaries, 1632 and 2319 bytes | Conservative fixed-schema bound 2344 bytes; the full-summary overflow fallback was not reached |
| Public replay contracts | 14 tests PASS | Includes patch ordering, pins, path guards, import rejection, selected toolchain and mocked cancellation ownership |
| Public source reconstruction | Twelve complete patches and seven public baseline modules; all final pins match | No private generated headers or prebuilt NUT libraries |
| Whole-driver fake OFF/ON | 10 checks, 24 completed fake processes in 12 pairs; 1,210,665 captured bytes | Same stdout, return values and full encoded operation traces; AddressSanitizer and UndefinedBehaviorSanitizer enabled |
| Continuous protocol/capture/stager | 8 + 14 + 7 tests PASS | Synthetic inputs only |
| CI command preflight | 29 mock cases PASS | Real SwiftPM/Xcode write confinement and the full check were not executed |

The public replay uses Xcode 27.1, macOS SDK 27.0 and Python 3.15.2. Its new
temporary tree measured 14,442,376 bytes at completion. Every compiler/tool and
fake child has time and output limits. The sampled 1 GiB tree guard is not a
filesystem quota. Cancellation ownership is covered by contracts; abrupt
supervisor death and an actual OS-level abnormal cancellation campaign were not
tested by this run. No genuine HIDAPI implementation is linked in the fake.

The source recipe and exact pins are in
[CONTINUOUS_PORTABLE_REPLAY.md](CONTINUOUS_PORTABLE_REPLAY.md). It is a separate
local path; hosted CI does not yet acquire its admitted archive or run it.
Earlier failed preparations were retained during review: an incomplete test
fixture, missing pre-patch baseline modules, and a forbidden `chdir` import.
The final recipe supplies the baseline modules before all patches and redirects
the fake's directory operation; the import rejection was not weakened.

The formatter fixture is `backend/nut/test_continuous_formatter.c`, with
`check_continuous_formatter.py` accepting the exact strict-parser SHA-256.
The test includes the frozen patched APC source, renames NUT's main only in its
own translation unit and invokes private serializer helpers. Its local build
used the previously admitted NUT configuration/libraries. That build is distinct
from the public whole-driver recipe above; the formatter is not yet a portable
CI target. Legacy OS imports in that helper binary are outside its reviewed
entry-point call path. The real driver's lifecycle and electrical behavior
remain outside this evidence.

A new native diagnostic candidate was also compiled without execution. Of its
185 recorded inputs, 184 match the previous native candidate; only the patched
APC source changes. This is diagnostic preparation, not proof that the previous
live `session_lost` problem is solved.

Before an installable release: identify the loss of new measurements; qualify
bounded then longer continuous reading; observe the real app/menu/WidgetKit path
for recent, stale and missing data; verify installation, signatures and the exact
public revision. Energy units remain unverified. W/VA are derived from load and
nominal ratings. Electrical controls are outside the read-only first release.
