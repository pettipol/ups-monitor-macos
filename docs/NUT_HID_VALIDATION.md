# Experimental HID Fallback Validation

Status: **offline candidate replay PASS, 2026-10-11; full driver and hardware
NOT_RUN**. This is not an upstream-accepted change or an application runtime
backend. The original [three-pin replay](NUT_HID_REPLAY.md) remains a separate
historical comparison of upstream revisions.

## Scope

The candidate targets exact NUT master
`73c4502191d025e35122463986a80c676e734b04`, not a stable release. It addresses
two synthetic residuals observed in the upstream HID fallback:

- A matching report ID with missing field bytes could store a partial or zero
  value and refresh the status timestamp.
- A status timestamp later than the current wall clock could be accepted as
  fresh because its calculated age was negative.

The intended field policy is per-field, not per-report: a complete field may
be decoded even if another field in that report is incomplete. Report ID,
offset and size must be valid; the entire bit range must fit in the received
payload. Invalid or incomplete fields leave their previous value and timestamp
unchanged. Never-decoded optional charge/runtime values remain unavailable,
not zero. There is no new parser or reinterpretation of HID units.

The pinned parser records aggregate report lengths but does not expose a
per-field completeness predicate for these fallback descriptors. Its generic
value extractor does not supply the needed bounds check. A small local range
predicate therefore validates the existing offset/size representation; no
parser is replaced or imported.

The clock policy reads the clock once under the existing lock. An observed
future timestamp invalidates both status timestamps, so old cached status
cannot automatically reappear when the clock catches up. New complete status
reports are required. This is **not a monotonic-clock migration**: a backward
step that leaves the clock after both status timestamps is not detected by
this condition. Forward steps, real elapsed-time guarantees, concurrency and
the age of optional charge/runtime fields are not qualified by this candidate.

## Source Boundaries

`backend/nut/nut-hid-fallback-validation-73c4502.patch` is a separately named
GPL-2.0-or-later patch against the pristine pin. It is not the guarded-monitor
patch and does not add USB lifecycle restrictions. Stacking it with another
patch is not qualified by the standalone replay.

A later [combined candidate record](NUT_COMBINED_CANDIDATE.md) documents
separate source comparisons, synthetic harnesses and USB/serial builds with
the merged guarded patch. That evidence does not change this standalone
runner's hash fences or qualify driver execution and hardware.

`backend/nut/replay_hid_validation.py` uses the existing pinned extractor,
verifies pristine and candidate sources, and creates output outside the
repository and both source checkouts. The generated C contains exact bounded
fallback/publisher excerpts with upstream license notices, a test-only reset
wrapper, a controlled clock and recording stubs. It does not contain the
complete driver or real NUT dstate implementation.

The source pin is `73c4502191d025e35122463986a80c676e734b04`. The candidate
patch is `backend/nut/nut-hid-fallback-validation-73c4502.patch`, SHA-256
`80efa7d122e7f8248999a3d5633fcd994f6d1565e283c21afcec4818e45fe68b`; the
candidate USB source SHA-256 is
`12f7edde6e5da02372fffc24726c21dc56aa2b6de2c2eb85e5071499bb8ff3ff` and the
publisher source remains pinned at
`91e3921a8cfea955ffef0c1d38ada2ee48f2d3dc0c55e94d5c284766cd7c5e50`.
The runner requires a clean pristine source checkout and a candidate checkout
at the same HEAD with exactly the intended USB source modification; it checks
tracked/untracked state and both complete-file hashes. Its scratch root must
be outside the app repository and both NUT checkouts, not be a symlink, and
the per-mode output directory must not already exist.

The C test is GPL-2.0-or-later. The original Python orchestration and synthetic
source-fence tests are MIT. No upstream file is relicensed by the app license.

## Validation Record

The coordinator independently ran the runner against the exact pristine and
candidate trees. RED returned checker success only after the C harness exited
1 with exactly the 19 expected failure lines in order, the exact summary line,
and empty stderr. GREEN compiled and executed the candidate harness with exit
0, the exact success line, and empty stderr. A separately repeated
reviewer-test candidate binary inspection found only libSystem and UBSan
runtime dependencies, with no NUT driver or USB library linked. The local
Python contract suite has 13 tests and passes; it uses synthetic temporary
checkouts and mocked subprocess results and does not itself compile or execute
the C harness. These are bounded offline replay results, not full-driver build,
concurrency, live-path, or hardware qualification.

To run the replay, use a clean checkout at the pin for `SOURCE_ROOT`, a
separate candidate checkout at that same HEAD with only the intended USB
source file modified for `CANDIDATE_ROOT`, and a new scratch location outside
all three trees. The output subdirectories `pristine` and `candidate` must not
already exist. For example:

```sh
SOURCE_ROOT=/path/to/clean/nut-at-73c4502
CANDIDATE_ROOT=/path/to/candidate-nut-at-73c4502
SCRATCH=/tmp/nut-hid-validation-20261011
EXTRACT_SCRATCH=/tmp/nut-hid-validation-extract-20261011

python3 backend/nut/replay_hid_validation.py \
  --source-root "$SOURCE_ROOT" --candidate-root "$CANDIDATE_ROOT" \
  --scratch "$EXTRACT_SCRATCH" --mode extract
python3 backend/nut/replay_hid_validation.py \
  --source-root "$SOURCE_ROOT" --candidate-root "$CANDIDATE_ROOT" \
  --scratch "$SCRATCH" --mode red
python3 backend/nut/replay_hid_validation.py \
  --source-root "$SOURCE_ROOT" --candidate-root "$CANDIDATE_ROOT" \
  --scratch "$SCRATCH" --mode green
```

`extract` writes only the fenced source and does not invoke a compiler; use a
separate fresh scratch path because it and `green` both create a `candidate`
subdirectory. The shown paths must be new and must not already contain those
per-mode output directories.
`red` compiles and executes the pristine-source harness; `green` compiles and
executes the candidate-source harness. Both use C99, warnings-as-errors, and
UBSan. RED is accepted only for the exact 19-line failure transcript, exit 1,
and empty stderr. GREEN requires exit 0, the single expected success line,
and empty stderr. The command does not fetch source, build NUT, launch a
driver/server/client, or access a UPS.

No driver, server, scanner, USB handle, reset, self-test or electrical action
is part of this validation. Even a successful replay would not establish
SMC1500I firmware-10 compatibility, USB coexistence, shutdown safety or correct
real-world measurements.
