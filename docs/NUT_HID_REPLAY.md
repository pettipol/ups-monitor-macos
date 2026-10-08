# NUT HID Fallback Replay

Status: **offline synthetic replay PASS for both pinned source revisions**.
Driver, USB, UPS hardware, and caller-to-`OL`/`OB` behavior remain **NOT_RUN**.
This is an offline source-code replay, not a NUT driver, client, USB, or UPS
test. Fixture layouts and values are artificial and are not captured device
reports.

Review date: 2026-10-08. The coordinating reviewer repeated the two compiled
replays, including independent AC/discharging age checks. A base replay PASS
means the known defects were reproduced, not that the base is correct.

## Source Fence

The runner accepts only a clean Git checkout at one of two full source
revisions:

- Base: `1a8369f8688443a500527059167d2f66ca27535f`.
- Corrective commit: `e0bb8ea64f7f8a140ad8908904186a05a324c295`.

It performs local `git` inspection only. It does not fetch or download source,
and refuses a mismatched revision, dirty checkout, or mismatch against the
known SHA-256 of the complete `apcmicrolink-usb.c` blob at either commit. It
hashes the bytes it then uses for extraction. The correction is replayed as the
exact source commit, not as an application backport or as an assertion that
its full PR stack is integrated.

## Extracted Code

The generated replay translation unit contains the fallback field/state
declarations, `hid_extract_bits`, `microlink_usb_try_decode_fallback`, and
`microlink_usb_get_hid_fallback`, copied verbatim from
`drivers/apcmicrolink-usb.c` at the selected commit. It adds only standard C
headers and preserves that file's upstream copyright and GPL notice. It uses a
test-provided `microlink_now()` clock function. It excludes
USB/libusb functions, driver dispatch, HID descriptor parsing, and the async
listener. The upstream getter contains conditional mutex calls; compilation
sets `WITH_LIBUSB_1_0=0` and does not define `HAVE_PTHREAD`, so those branches
are preprocessed out. Thread races and concurrent access are outside this
replay's scope.

The production `microlink_now()` in `apcmicrolink.h` calls `time(NULL)`. The
controlled replay clock is a test seam only; it does not change or qualify the
production wall-clock behavior. Clock rollback can make a negative `difftime`
appear fresh. The reset of fallback state remains inline in the HID report
descriptor callback, which is not extracted because it depends on USB/HID
parser types. No reopen/reset behavior is claimed or tested.

## Scenarios

Expected comparisons cover initial state; charge/runtime reports before either
status flag; one status flag followed by both; charge updates after status has
become stale; each status field refreshed separately while the other becomes
stale; a synthetic fresh absent-AC plus discharging state; negative age; and
the inclusive age boundary versus the first stale second. The base revision is
expected to publish default-zero status after charge/runtime refreshes and to
allow one fresh status field to keep the other stale field publishable. The
corrective revision is expected to withhold incomplete or stale status.

Two behaviors are recorded as **residuals**, not fix successes: a truncated
status report whose report ID matches can extract zero bits yet refresh the
status timestamp; and a backward wall-clock step can make old status appear
fresh. Their relationship to any real hardware is **NOT DEMONSTRATED**.

## Results

The base-source replay passed and reproduced the reported freshness failures:
charge/runtime alone made default-zero status publishable, one status field
made a partial snapshot publishable, and fresh charge kept stale status
publishable. Fresh AC also masked stale discharging, and fresh
discharging masked stale AC. The corrective-commit replay passed the
corresponding withholding checks in both directions. The synthetic absent-AC
plus discharging case passed on both revisions. These are assertions against
extracted source functions, not an integration or hardware qualification.

The two residual cases also reproduced on both revisions: a truncated
same-report-ID status update can refresh zero-extracted fields, and a backward
test-clock step is considered fresh. These are recorded as residual findings,
not fix successes; hardware relevance is **NOT DEMONSTRATED**.

Both compiled replay binaries were inspected with `nm -u` and `otool -L`.
Their only unresolved symbols were `__assert_rtn`, `difftime`, and `puts`, and
their only linked library was macOS `libSystem`; no USB/libusb symbol or NUT
driver library appeared. This checks the produced binaries only and does not
qualify production builds, concurrency, or any device behavior.

The caller that maps fallback values to NUT `OL`/`OB` is deliberately not
included. A synthetic `(AC absent, discharging)` pair exercises the exact HID
fallback getter output only; it does not replay an electrical transition or
prove the driver/server/supervisor path.

## Use

The repository runner is offline by default and requires explicit source and
scratch paths. Each source variant is written to a new scratch subdirectory;
existing output directories/files are refused. `extract` is the default action;
`compile` builds but does not run the C replay; `run` executes only the
synthetic replay binary. Keep scratch outside the repository and source
checkout. Example for the reviewed offline replay:

```sh
python3 backend/nut/replay_hid_fallback.py \
  --source-root /path/to/clean/pinned-nut-checkout \
  --expected-revision 1a8369f8688443a500527059167d2f66ca27535f \
  --scratch /path/outside/repository/hid-replay \
  --action run
```

Repeat with the clean checkout at the corrective commit, using a new scratch
path, to compare behavior.
The five synthetic source-fence unit tests run through `scripts/check.sh` and
hosted CI without an external NUT checkout. The compiled C replay is a separate
local check; normal validation does not fetch source or execute this C replay.
The extracted source fragments and C replay test remain GPL-2.0-or-later; this
does not change licensing of the surrounding application.
