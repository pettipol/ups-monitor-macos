# NUT Qualification Artifacts

Base revision: `1a8369f8688443a500527059167d2f66ca27535f` of
[Network UPS Tools](https://github.com/networkupstools/nut). These are source
qualification artifacts, not an installed service or a production backend.

| File | Scope |
|---|---|
| `nut-upsc-completion.patch` | Reject interrupted or mismatched client variable lists |
| `nut-guarded-monitor.patch` | Experimental opt-in apcmicrolink USB restrictions; hardware untested |
| `check_upsc_completion.py` | Actual client test with an ephemeral synthetic loopback server |
| `test_guarded_policy.c` | Compiled policy-header tests with fake callbacks, no libusb |
| `process_deadline.py` | Offline qualification helper: bounded child process, private output, no automatic driver launch |
| `test_process_deadline*.py` | Synthetic subprocess and lifecycle regressions; never execute a UPS driver |

The two patches affect disjoint files and apply to the pristine base revision.
Read [client evidence](../../docs/NUT_CLIENT_COMPLETION.md) and
[driver limitations](../../docs/NUT_GUARDS.md) before interpreting test results.
No test here demonstrates physical UPS compatibility, USB coexistence, or
correct electrical measurements.

Patch context lines intentionally contain their unified-diff leading spaces.
Check source whitespace in the patched NUT checkout with `git diff --check`;
do not strip whitespace from the exported patch data. In this application
checkout use `git diff --check -- . ':(exclude)backend/nut/*.patch'` in addition
to `git apply --check` against the pinned NUT source.

## License Boundary

The two patch files are derived from NUT source at
`1a8369f8688443a500527059167d2f66ca27535f`; they retain
**GPL-2.0-or-later** according to the affected upstream source headers. The
guarded C test is marked `GPL-2.0-or-later` in its own SPDX header. None of
these artifacts is relicensed by the application's MIT license.

The completion patch changes `clients/upsc.c` and `clients/upsclient.c`.
Their upstream headers list Russell Kroll (1999 in `upsc.c`; 2002 in
`upsclient.c`), Arnaud Quette (2012), Arjen de Korte (2008), and Jim Klimov
(2020-2026), and state GPL version 2 or (at the recipient's option) any later
version. The guarded patch changes the experimental `drivers/apcmicrolink.c`,
whose upstream header lists Lukas Schmid and Nicolai Brogaard, each copyright
2026, and states the same GPL terms. The guarded patch header also records the
pinned source revision and provenance. The completion patch itself has no
standalone SPDX/provenance header; this adjacent notice records its source
files, observed attribution and license basis. The absence of that header
alone is not a finding of legal noncompliance.

`LICENSE-GPL2` is the complete GPL version 2 text copied from the pinned NUT
source checkout. Its SHA-256 is recorded in `THIRD_PARTY_NOTICES.md`.
`COPYING.NUT` is NUT's licensing overview: it describes license families in
the full upstream tree and is not itself the complete GPL text. This
repository contains the patches and guarded C test, not the complete NUT
source tree or NUT/libusb binaries.

The original Python synthetic qualification helpers and tests are identified
as application/MIT material. They do not include NUT source and do not
authorize or perform hardware testing.

See [process supervision limits](../../docs/PROCESS_DEADLINE.md); these helpers
are not part of the app's read-only NUT transport and do not authorize hardware
tests or qualify a caller's argument list.
