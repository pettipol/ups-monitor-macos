# Synthetic operational producer

`backend/nut/fixtures/synthetic_operational_producer.c` is a small MIT-licensed
fixture for exercising the continuous operational protocol. It is not a UPS
driver and its sample values are fabricated: it emits `OL`, charge `90` then
`91`, runtime `3000` then `2995`, and marks the other fields unavailable. The
word `observed` in its protocol records describes fixture output, not hardware
telemetry.

The producer accepts only the consumer's fixed argument vector and expected
executable basename. It uses the monotonic clock, signal handlers and stdout;
it has no USB/HID/IOKit, file, network or child-process access. Output is capped
at 8192 bytes. SIGTERM/SIGINT produce one `End cancelled` record and exit 0.
Its 30-second `alarm()` exits 124 without an End record. That is a fixture
timeout, separate from the `guard_deadline=35` argument and from any hardware
safety fuse.

## Build for a local synthetic test

Use a new temporary output directory. Set `SDKROOT` to an SDK installed with the
selected local Xcode and record the resolved SDK version; do not assume that a
particular SDK version remains installed. The `-mmacosx-version-min=27.0` flag
is the deployment minimum, not the SDK version. Do not build into the checkout
or launch the result automatically. The command mirrors the fixture build flags
in the frozen build procedure:

```sh
set -eu
OUT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ups-synthetic-producer.XXXXXX")"
OUTPUT="$OUT_ROOT/apcmicrolink-hidapi-operational"
test -d "$SDKROOT"
xcrun --sdk "$SDKROOT" --show-sdk-version
clang -arch arm64 -mmacosx-version-min=27.0 -isysroot "$SDKROOT" \
  -std=c11 -O2 -Wall -Wextra -Werror -Wl,-dead_strip \
  backend/nut/fixtures/synthetic_operational_producer.c -o "$OUTPUT"
chmod 0755 "$OUTPUT"
codesign --force --sign - --timestamp=none \
  --identifier org.openupsmonitor.synthetic-operational-producer "$OUTPUT"
codesign --verify --strict --verbose=2 "$OUTPUT"
otool -L "$OUTPUT"
```

Confirm the load list contains only `/usr/lib/libSystem.B.dylib`. Record the
new output hash, compiler version and resolved SDK version; a previous fixture
binary's hash does not establish the hash of a new build. For the surrounding frozen helper
inputs and staging procedure, see [Frozen build recipe](FROZEN_BUILD_RECIPE.md).
