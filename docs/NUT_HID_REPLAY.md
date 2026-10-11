# NUT HID Fallback Replay

Status: **expanded offline replay PASS on the base, corrective and merged master revisions, 2026-10-11**.
This synthetic replay is not a NUT driver, client, USB, UPS, electrical, or
hardware test. Its fixture layouts and reports are artificial and were not
captured from a device. No compatibility claim follows from it.

## Source Fence

The runner accepts only a clean checkout at one of three full source revisions.
It hashes the complete source files and extracts from the same verified bytes:

| Revision | `drivers/apcmicrolink-usb.c` SHA-256 | `drivers/apcmicrolink.c` SHA-256 |
|---|---|---|
| Base `1a8369f8688443a500527059167d2f66ca27535f` | `6e35c6fdbd6a60abbf76f70d638079f0fcf710c07105ec717f52e8c4b1cd96be` | `35fb79087eb7aee43ff14a30fd26ac21dc1586eed3fc94a43d80f1acfd241f3c` |
| Corrective commit `e0bb8ea64f7f8a140ad8908904186a05a324c295` | `5f4073e7597ce7b5f2fb2f9b2b3ebc49278eb78d29ec5e09b999896112a19a21` | `666a97bd870736a0b979a731225c4e41eb777d04e8ae786354a737a279561f19` |
| Merged master `73c4502191d025e35122463986a80c676e734b04` | `5f4073e7597ce7b5f2fb2f9b2b3ebc49278eb78d29ec5e09b999896112a19a21` | `91e3921a8cfea955ffef0c1d38ada2ee48f2d3dc0c55e94d5c284766cd7c5e50` |

It performs local Git inspection only and does not fetch source. It refuses an
unrecognized revision, dirty checkout, symlinked/missing input, or byte-hash
mismatch. The verified ancestry is PR 3714 merge
`d460f7b5829f15569914077fd3e5fcb64d087465`, then PR 3728 merge
`b3ca797a274d85103f7cb78d5da445c309911f78`, followed by the tested master
commit. The extracted decoder/getter/reset/publisher blocks are unchanged
between the corrective and merged revisions. In the full fenced files, the
additional master delta is outside the extracted blocks (driver version and
USB fallback-disabled startup handling). The selected commit is compared as a
source revision; this replay is not an application backport or a full-driver
integration test. In particular it does not exercise the padding scanner hook
or calibration map from PR 3714.

## Extracted Code

The generated translation unit copies the fallback declarations,
`hid_extract_bits`, `microlink_usb_try_decode_fallback`, and
`microlink_usb_get_hid_fallback` verbatim from `apcmicrolink-usb.c`. It also
copies the `MLINK_HID_FALLBACK_MAX_AGE_SEC` definition and
`microlink_publish_hid_fallback()` verbatim from `apcmicrolink.c`. The latter
is exercised with stubs that record `dstate_setinfo`, `status_init`,
`status_set`, and `status_commit` calls and their order. These stubs do not
emulate NUT dstate inference, so observed `OL`/`OB` tokens are not proof of a
final status value in a real NUT process.
The generated file preserves the copyright/GPL notices from both sources.

The callback's fallback-state reset statements are copied verbatim into a
small test-only wrapper. The wrapper is not the real USB/HID callback and does
not test callback dispatch, descriptor parsing, reopen, listener behavior, or
USB interaction. The replay also excludes the real dstate, driver dispatch,
NUT server, and `upsmon`. Compilation sets `WITH_LIBUSB_1_0=0` and does not
define `HAVE_PTHREAD`; concurrency and races are outside scope. Production
`microlink_now()` uses `time(NULL)`; a controlled test clock does not qualify
that wall-clock behavior.

## Scenarios

The C harness contains nine scenario functions: mapper guards; charge/runtime
before status; one status field followed by both; online/on-battery mapping
and call ordering; missing and expired status including the inclusive age
boundary and fresh-charge behavior; independent AC/discharging freshness in
both directions; negative maximum age and stale boundary; truncated-report
and clock-rollback residuals; callback-reset wrapper, cleared layout,
reinstalled layout, and valid post-reset status.

The base source is expected to reproduce default-zero/partial status
publication and freshness defects through the mapper. The corrective source
is expected to withhold those incomplete or stale cases. These expectations
are assertions about extracted source functions and recording stubs only.

Two known residuals are tested on all three revisions, not counted as fix
successes:
a matching but truncated report can refresh zero-extracted status fields, and
a backward wall-clock step can make old status appear fresh. Their relevance
to any real device is **NOT DEMONSTRATED**.

## Results

The coordinating reviewer inspected the extracted source, compiled fresh base,
corrective and merged-master binaries, inspected their dependencies, then
executed all three. All nine scenario functions passed on each revision. A
base PASS means that the known defects were reproduced, not that its status
handling is correct.
Charge/runtime alone emitted `OB` from default-zero status; fresh measurements
or a single fresh status flag kept incomplete/stale status publishable. The
corrective and merged revisions withheld those cases, including after the reset
wrapper and synthetic layout reinstallation. Fresh complete status emitted the expected
`OL` or `OB` tokens. Measurement writes preceded the status commit in the
tested online case.

All three revisions still emitted `OB` for the artificial matching-ID truncated
report and emitted old `OL` status after the controlled clock moved backward.
These residuals are not fixed or attributed to a real UPS by this replay.
The seven synthetic Python source-fence tests passed across all three allowed
revisions for positive controls and individual hash, missing-file and symlink
checks for both sources; wrong-HEAD and dirty-checkout tests use the base pin.
The harness's `FIXED-COMMIT` output denotes the corrected expectation class
for both corrective and merged pins; the runner prints the exact source pin.

`nm -u` showed only assertion, formatted-output, stack-protection, zeroing,
string-comparison and `difftime` symbols. `otool -L` showed only macOS
`libSystem`; there were no USB/libusb symbols or NUT driver libraries. These
are checks of these replay binaries, not a proof about a production build.
No driver, client, server, USB, or hardware code is executed by this replay.

## Use

The runner is offline by default and requires explicit source and scratch
paths. Each variant is written to a new scratch subdirectory; existing output
directories are refused. `extract` is the default action, `compile` builds
the synthetic C harness without running it, and `run` executes only that
harness. Keep scratch outside the repository and pinned source checkout.
Example:

```sh
python3 backend/nut/replay_hid_fallback.py \
  --source-root /path/to/clean/pinned-nut-checkout \
  --expected-revision 73c4502191d025e35122463986a80c676e734b04 \
  --scratch /path/outside/repository/hid-replay \
  --action compile
```

The Python source-fence tests run through `scripts/check.sh` and hosted CI
without an external NUT checkout. Normal validation does not fetch pinned
source or execute the compiled replay. The extracted upstream fragments and C
test are GPL-2.0-or-later; the Python runner and source-fence tests are MIT.

The separate [merged-pin candidate validation](NUT_HID_VALIDATION.md) adds a
bounded RED/GREEN replay for the local truncated-field and clock-rollback
candidate. It does not change the three-revision results above, and is not a
full-driver or hardware qualification.
