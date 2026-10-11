# NUT Guarded Monitor Rebase

Status: **offline source/build evidence only; live hardware NOT_RUN; candidate
not qualified for protocol execution**.

## Source and Patch

`backend/nut/nut-guarded-monitor-73c4502.patch` is an experimental GPL-covered
patch against Network UPS Tools master commit
`73c4502191d025e35122463986a80c676e734b04`. This commit contains the upstream
merges of PR 3714 (`d460f7b5829f15569914077fd3e5fcb64d087465`) and PR 3728
(`b3ca797a274d85103f7cb78d5da445c309911f78`). The earlier
`nut-guarded-monitor.patch` remains unchanged and pinned to its original base.

The rebased diff touches the same six NUT paths as the earlier patch. The only
rebase adaptation is in `microlink_receive_once()`: the guarded deadline check
is before `microlink_try_extract_frame()`, and the merged upstream callback
that discards USB report padding remains after successful extraction. No other
guard behavior was changed for this rebase. The generated patch passes
`git apply --check` on a second clean copy at the pinned commit; SHA-256 of all
six resulting files matches the first patched copy.

## Offline Checks

- Synthetic C policy harness: **PASS**. It links the policy header and uses
  synthetic callbacks; it does not link or invoke libusb.
- Static call-site checks and built-in mutation checks: **PASS**. The test
  rejects seven in-memory mutations to selected guard paths.
- The separate merged-rebase preservation checker: **PASS**, including six
  in-memory mutations. It verifies pinned pristine input, the exact deadline
  insertion in the receive function, an unchanged padding function, the
  calibration map and USB header, and the extracted fallback/reset/publisher
  fragments. It is a bounded structural check, not a whole-driver audit.
- USB build: **PASS**, configured with `--with-usb=libusb-1.0` and the already
  available libusb 1.0.30; only the `apcmicrolink` target was built.
- Serial build: **PASS**, configured with `--with-usb=no`; only the
  `apcmicrolink` target was built.

The build emitted repeated Clang warnings about `/usr/local/include` being an
unsafe system include path, an existing circular generated-source dependency,
and allocator-wrapper warnings in NUT common code. Neither target had a
compile or link failure. Two initial bootstrap attempts failed on unresolved
Libtool macros or the `libtoolize` executable name; regeneration succeeded
after selecting the existing macOS `glibtoolize` and its macros. No source
behavior was changed to resolve those tooling failures.
Autotools were regenerated in a separate private
build-source copy using the existing Autoconf 2.73, Automake 1.19 and
`glibtoolize` 2.6.2; no packages were installed or updated. Detailed logs and
verification hashes are private under the dated workbench.

The coordinating reviewer independently applied the patch to a third pristine
tree, matched the six resulting file hashes, compiled and ran the synthetic
policy harness, and repeated both static checkers. The reviewer also inspected
the USB/serial build settings and binary dependencies and repeated the two
incremental build commands successfully. `CLOCK_MONOTONIC` is enabled in both
configurations; `WITH_USB` and libusb linkage occur only in the USB target.

## Reproduce Static Checks

With a clean external checkout at the exact pin and a separate copy with only
the new guarded patch applied, run from this repository root:

```sh
python3 backend/nut/check_guarded_merged_rebase.py \
  --pristine-root "$NUT_PRISTINE_ROOT" --patched-root "$NUT_PATCHED_ROOT"
python3 backend/nut/test_guarded_source_paths.py "$NUT_PATCHED_ROOT"
```

The two variables must identify those external source directories. These
checks read local sources and run Git inspection commands, not a NUT driver.
They are separate from the normal app CI, which does not fetch these NUT trees.
The existing C policy harness is also separate from that CI.

## Execution Boundary

No NUT driver binary was executed, including informational options. No driver,
server, daemon, scanner, UI, USB interface, device, or UPS was opened or run.
No protocol-level behavior, hardware compatibility, electrical behavior,
process lifetime, or shutdown safety is established by source inspection,
synthetic tests, or compilation.

## Remaining Boundaries

This guarded profile is experimental and specific to reviewed `apcmicrolink`
paths. It is not wire-read-only: normal Microlink STOP/INIT/NEXT, authentication,
reads, and cleanup traffic can still be sent if the driver is run. Its deadline
limits loop continuation, not the duration or effects of a blocking operating
system or USB call. No live protocol execution is authorized or qualified.

The separate [synthetic HID fallback replay](NUT_HID_REPLAY.md) still reproduces two residuals on
the base, corrective and merged source pins: a matching but truncated report
can publish zero-extracted status as `OB`, and a backward wall-clock step can
make old status appear fresh. Their relevance to any real device is **NOT
DEMONSTRATED**. This guarded rebase does not fix or qualify either residual.
