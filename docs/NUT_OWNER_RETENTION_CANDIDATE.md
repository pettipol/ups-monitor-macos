# Offline USB Ownership Candidate

Date: 2026-10-11. **Experimental source disclosure; NOT an installed backend.**
The sixth incremental patch addresses the pending-transfer gaps found in the
[five-patch lifecycle review](NUT_LIFECYCLE_REVIEW.md). It does not qualify
Microlink traffic, electrical continuity, real libusb teardown or process exit.
The application, installed widget and native Apple reader are unchanged.

## Reproducible Input

Use a separate source checkout at NUT
`73c4502191d025e35122463986a80c676e734b04`, apply the five patches in the exact
order documented in [the preceding candidate](NUT_GUARD_DEADLINE_CANDIDATE.md),
then apply `backend/nut/nut-usb-owner-retention-73c4502.patch` from this project.
The original-base guarded patch and the completion-client patch are not part
of this stack. No driver command or hardware test is required to apply it.
No dependency version is changed or newly adopted in this candidate.

Patch SHA-256:
`0b788743c7c68cc767b4fbe3a099bbecec6aac73da5adb7b9a0e571e07095766`.

| Source file | Five-patch input SHA-256 | Six-patch candidate SHA-256 |
|---|---|---|
| `drivers/apcmicrolink-usb.c` | `1b7e3d3b8cdb54910e68f28a8bea4e10b6f4cdef4f5143ffacd64ff2aa6af42a` | `d6f61c595fd87e3f7d4e416ba8f8d6e04293ea3ff12c93dce60ad0384b4d056d` |
| `drivers/apcmicrolink-usb.h` | `1b0ac143a8c99a161930562b441f1340ca8bd971d4bb2315e46a98e1b8a75ba8` | `b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29` |
| `drivers/libusb1.c` | `91f973115337b5a5976676ff1cff5f0d706698f2af1014e5a7b4459abc83206f` | `633fe750df7c4f74079caf9fa8d57e42483023b2009d068c286d3850b1570c42` |
| `drivers/nut_libusb.h` | `d62c51a4c8145909c7feb6f4059cdb5f9753bcd2a372726e8f05ee3ef87a2ab8` | `6472654d77b2acc349ea1e886450190500bef4525699df26f56a5cc77bd518c4` |

`drivers/apcmicrolink.c` is unchanged from the five-patch input, SHA-256
`3bc7eadc8e2fae657df1b8f0e37f3baf53fd9a6e20a7da3c029d218193d2177d`.
Only the four files in the table are changed by this patch. Application to a
fresh copy of the frozen input was checked and all source bytes compared with
the reviewed candidate. Historical patches and replay pins remain unchanged.

## Ownership Contract

A heap-allocated generation owns the transfer, buffer, device and context.
Its pointer remains stable as transfer `user_data`. A detached pump is created
before submission; submission/cancellation reservations are made under the
existing mutex and libusb calls occur outside it. The pump explicitly handles
events, but synchronous libusb calls on the main thread may also dispatch
callbacks. A reserved call can finish after stop is requested.

Stop requests cancellation without declaring completion. If acknowledgement
has not arrived after the observation loop, the generation remains retained;
close, reset/reopen, repeated open and synchronous input fallback cannot treat
it as idle. Reaping requires a terminal transfer and pump-exit acknowledgement.
Pending ownership also holds the backend context against its exit hook.

This relies on the existing single-main-thread public driver call contract.
The context hold is an idempotent flag, not a general multi-client reference
counter. The requested 100 pauses of 10 ms are not a measured one-second OS
deadline. Retaining resources is intentional while a callback or call remains
unresolved; it is not a solution for indefinite process lifetime.

## Evidence

Separate USB/libusb-1.0/pthread and serial driver builds passed for these exact
source hashes. Existing generated templates from the pinned baseline were
used. Neither compiled NUT driver was executed, including informational flags.
Windows, libusb-0.1 and USB without pthreads were not built.

Earlier private synthetic checks exercised ten ordinary ownership cases and
six guarded-clock cases, using exact extracted functions, real pthreads and
local libusb-shaped mocks. Their results are supplementary recorded evidence,
not cases run by the public extractor or by normal CI. No ASan/TSan result is
claimed for this ownership candidate.

The public integration fixture covers six selected cases:

| Case | Synthetic assertion |
|---|---|
| `flush-active-race` | Active state changes from 1 to 0 with an owner still present and no stop request; flush must not fall through to synchronous input. |
| `guarded-reopen-no-reset` | The guarded reconnect path does not reset the mock device. |
| `pending-open-reopen-flush` | Pending ownership blocks repeated open, close/reopen and synchronous flush until acknowledgement. |
| `open-start-pending` | Unresolved startup does not enable synchronous fallback. |
| `reopen-start-pending` | The old quiescent handle may close; unresolved ownership of the new handle remains retained. |
| `open-fallback` | A failure with no submitted transfer still permits the ordinary fallback. |

The coordinator and Luna reproduced these cases in a private harness with
UBSan, exact output/status checks, empty stderr and a ten-second bound per
process. A mutation changing the final flush owner check back to an active
check fails the specific synchronous-input assertion. The fixture maintains
per-generation allocation/free accounting, including reused addresses.

`extract_usb_owner_retention.py` is deliberately **extract-only**. It checks
source pins and fresh external output boundaries, preserves upstream notices
in generated C, and copies the synthetic fixture. It does not build or run
anything. Python contract tests use synthetic source inputs and do not prove
the C scenarios. Set `CANDIDATE` to the six-patch source tree and `SCRATCH` to a
new directory outside both source and this repository:

```sh
python3 backend/nut/extract_usb_owner_retention.py --mode extract \
  --source "$CANDIDATE" --scratch "$SCRATCH"
```

Generated manifests remain `EXTRACTED_NOT_RUN`. The C fixture includes older
ownership scenarios for context; only the six cases above belong to this
integration qualification. Exact source functions are surrounded by test
declarations and recording stubs; this is not a complete NUT driver. Policy,
USB and descriptor helpers are mocked. Real callback ordering, kernel I/O,
protocol STOP, startup-fatal cleanup and whole-process exit are not executed.

The public package was independently extracted from a fresh application of
all six patches, then compiled and run by the coordinator. All six selected
cases passed with exact stdout, empty stderr and the same ten-second test
process bound. The generated C differs from the prior integration unit only
by preserved copyright/license comments; the fixture differs only by its
generated include filename. Five Python extraction contracts pass, including
an end-to-end synthetic check of the real output files and manifest. Together
with the existing backend/privacy suite, 113 Python tests pass locally.

| Public replay artifact | SHA-256 |
|---|---|
| Generated C | `ac877280713977335f7b824ea84d4a8aef60014e23aa910bb8bfa20bc4db9850` |
| C fixture | `c16666c10254405ca20cbc4b3c9c0642cb8048e2978a7e736a64134eaebd7326` |

For a separate, manual synthetic build on the qualified macOS toolchain:

```sh
clang -std=gnu11 -O0 -g -pthread -fsanitize=undefined \
  -fno-sanitize-recover=undefined "$SCRATCH/test_usb_owner_retention.c" \
  -o "$SCRATCH/usb_owner_retention"
nm -u "$SCRATCH/usb_owner_retention"
otool -L "$SCRATCH/usb_owner_retention"
```

Inspect the fixture and linkage before any execution: only C/POSIX and UBSan
runtime references are expected, not libusb, IOKit or NUT libraries. The
fixture executable accepts one case name from the table. Each qualified run
used `UBSAN_OPTIONS=halt_on_error=1` and a supervising ten-second subprocess
timeout; required results are exit 0, exactly `PASS <case>` plus newline on
stdout, and empty stderr. Compilation, crashes or timeouts are not a PASS.
The extractor itself does not perform any of these later steps. Normal CI
runs Python contracts and application checks, not this C replay or a driver.

## Remaining Gate

A focused source review found no new concrete lifetime defect in the guarded
dump path under the stated assumptions. This permits experimental disclosure,
not hardware execution. Startup publishes the context hold before submission;
the backend hook skips `libusb_exit` while held. Driver cleanup is registered
only after `upsdrv_initups` returns. These are source facts, not a dynamic
process-exit proof. A zero process exit status alone also cannot prove a
complete dump: the inherited backend alarm uses `_exit(0)`.

Read the separate [protocol evidence](NUT_PROTOCOL_EVIDENCE.md) before
interpreting STOP/INIT or cancellation. The source-only question
[NUT #3751](https://github.com/networkupstools/nut/issues/3751) remains open,
with no visible maintainer answer at the 2026-10-11 check. This candidate has
not been submitted or accepted upstream. No real USB experiment, recovery
procedure or forced-termination policy is authorized by its publication.
