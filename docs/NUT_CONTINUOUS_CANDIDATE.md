# NUT continuous HIDAPI candidate

Status: offline candidate source and synthetic whole-driver replay. No native
candidate binary was executed and no UPS was opened.

## Contents

- `nut-hidapi-continuous-73c4502.patch` adds a distinct, uninstalled
  `apcmicrolink-hidapi-continuous` target to the pinned H03 NUT source.
- `apcmicrolink-continuous.c/.h` provide the strict NDJSON schema, fixed
  schedule checks, provenance metadata checks and serialization helpers.
- `test_continuous_helpers.c` exercises named synthetic contract cases.
- `replay_continuous_native.c` supplies a fake HID host to the actual NUT
  `main.c`, `apcmicrolink.c`, descriptor parser and `dstate.c` path.
- `test_replay_continuous.py` checks complete stream records and lifecycle
  counters from that fake-only executable.
- `stage_hidapi_continuous.py` verifies the H03 source inventory and patch
  hash, then makes a new copy and applies the patch. It never changes H03.

## Candidate boundaries

The target is separate from the H03 observer and does not replace it. Its
compile profile sets `MLINK_HIDAPI_NATIVE_CANDIDATE=1` and
`MLINK_HIDAPI_CONTINUOUS_CANDIDATE=1`. Only the continuous target suppresses
the early stdout banner. It requires explicit `monitor_stream_v1`, direct
foreground `-s` operation and the exact `-d1` dump profile. Stream stdout is
only bounded NDJSON; NUT warnings and diagnostics remain on stderr.

One native session is admitted. The finite loop emits no more than 24 samples
at five-second slot anchors, skips missed slots, stops new acquisition at
120000 ms including startup, and has a 130-second guard for one cleanup STOP.
The native owner is closed before a successful `duration_complete` record.
There is no stream reconnect, retry, command, socket or control path.

The descriptor/page fixture is synthetic and does not copy any device report.
It uses a complete descriptor parsed by NUT: page 0 carries geometry and
definition bytes through offset 47, page 1 carries the descriptor-backed
values, and page 2 is unrelated filler. The replay checks all 17 fields,
including status, charge, runtime, load, nominal ratings, derived W/VA and
their observation times. An `unrelated-refresh` case rebuilds the NUT blob
from a newer page 2 while page 1 is unchanged; field timestamps stay at the
original time. Other named cases cover skipped slots, acquisition cutoff,
geometry change, malformed descriptor, and retained close ownership.

The fake links no real HIDAPI implementation and cannot access hardware. It
proves the real NUT main/driver/parser/update/cleanup path only with the
synthetic callbacks. It does not prove native HID enumeration, device
compatibility, field availability on an UPS, macOS runtime behavior, or the
future Python/Swift/widget path. Those remain NOT_RUN.

## Offline verification

### Pinned inputs and staging

The patch targets NUT 2.8.5.1 at upstream revision `73c4502`. Its vendored
HIDAPI source is 0.15.0. The H03 file inventory is pinned to SHA-256
`22f5cb265db94204707326cc63f25981d803f310d769a5a4500e72f33435e26e`; the
stager also verifies the complete file, directory and symlink inventory and
the patch's pinned hash. No additional source dependency is fetched.

Use a pristine local H03 source tree and its matching inventory JSON. Supply
their locations and a new, nonexistent staging destination explicitly:

```sh
export NUT_H03_SOURCE=/path/to/nut-h03/source
export NUT_H03_INVENTORY=/path/to/source-inventory-h03.json
export NUT_CONTINUOUS_STAGE=/path/to/new/nut-continuous-stage
python3 backend/nut/stage_hidapi_continuous.py \
  --source "$NUT_H03_SOURCE" \
  --inventory "$NUT_H03_INVENTORY" \
  --output "$NUT_CONTINUOUS_STAGE"
```

The stager refuses an existing destination and never modifies its source.
Run it from the repository root so it can locate the checked-in patch.

### Native candidate build

On macOS, provide Xcode Command Line Tools, Autoconf, Automake, Libtool,
pkg-config, and libusb-1.0 development headers. The candidate requires the
libusb configuration for NUT header selection, but does not link or call
libusb. HIDAPI 0.15.0 is already pinned and staged in the candidate source.
The target is uninstalled and is never run by these build commands.

```sh
cd "$NUT_CONTINUOUS_STAGE"
autoreconf -fi
./configure --with-all=no --with-usb=libusb-1.0 \
  --with-apcmicrolink-hidapi=yes
make -C drivers apcmicrolink-hidapi-continuous
```

This normal build regenerates `Makefile.in` from the checked-in `Makefile.am`.
If the autotools or libusb development inputs are unavailable, the native
candidate build is **NOT_RUN**; a fake-only replay is not a substitute for it.
The candidate program must remain mode 0600 if a local build artifact is
retained. Do not execute it or connect an UPS as part of offline verification.

### Synthetic whole-driver replay

From the candidate source copy, the helper suite is built and run with:

```sh
cc -std=c99 -Wall -Wextra -Werror -pedantic -I drivers \
  drivers/apcmicrolink-continuous.c drivers/test-apcmicrolink-continuous.c \
  -o /private/tmp/test-apcmicrolink-continuous
/private/tmp/test-apcmicrolink-continuous
```

The whole-driver replay is built from H03's configured include tree and static
libraries, substituting only the native host factory with
`drivers/test-replay-continuous-native.c`. To reproduce it, set
`H03_BUILD` to a configured build directory made from the same pinned H03
source and `NUT_REPO` to this checkout, then run from the staged source root:

```sh
export H03_BUILD=/path/to/configured/nut-h03-build
export NUT_REPO=/path/to/ups-monitor-macos
clang -std=gnu99 -O0 -g -Wall -Wextra -Wno-unused-parameter \
  -DMLINK_HIDAPI_NATIVE_CANDIDATE=1 \
  -DMLINK_HIDAPI_CONTINUOUS_CANDIDATE=1 \
  -DMLINK_HIDAPI_CONTINUOUS_REPLAY=1 \
  -I "$H03_BUILD/include" -I include -I drivers -I "$NUT_REPO/backend/nut" \
  -I "$NUT_H03_SOURCE/include" -I "$NUT_H03_SOURCE/drivers" \
  drivers/main.c drivers/dstate.c drivers/apcmicrolink.c \
  drivers/apcmicrolink-maps.c drivers/apc_common.c \
  drivers/apcmicrolink-continuous.c drivers/apcmicrolink-hidapi-shared.c \
  drivers/apcmicrolink-hid-descriptor-checked.c \
  drivers/test-replay-continuous-native.c \
  "$H03_BUILD/drivers/.libs/libdummy_serial.a" \
  "$H03_BUILD/drivers/.libs/libdummy_upsdrvquery.a" \
  "$H03_BUILD/common/.libs/libcommon.a" \
  "$H03_BUILD/common/.libs/libcommonversion.a" \
  "$H03_BUILD/common/.libs/libparseconf.a" -lm \
  -o /private/tmp/replay-continuous-candidate
chmod 700 /private/tmp/replay-continuous-candidate
python3 "$NUT_REPO/backend/nut/test_replay_continuous.py" \
  /private/tmp/replay-continuous-candidate
chmod 600 /private/tmp/replay-continuous-candidate
```

The configured H03 build supplies generated headers and static libraries; its
configuration flags are those used for a NUT 2.8.5.1 Darwin build with USB
headers enabled. The fake binary is temporary and mode 0600 outside execution.
It uses only synthetic callbacks. Do not execute a genuine native candidate or
attach an UPS during this offline procedure.

`Makefile.am` is the source-of-truth target declaration. `Makefile.in` is
generated and is not hand-edited. The native continuous target still needs an
offline link build and independent review before it can be considered
build-qualified.
