# Source delivery for the UPS Monitor app and widget

The app-source archive contains 123 frontend, build and notice inputs and
80 test files from the reviewed E95 source snapshot. It also contains the
periodic MIT fixture used for E98, an archived edition of this guide and
the runtime change summary. The source manifest
identifies the exact files, modes and archived E96/E98 source changes.
E96 and E98 historically used the larger 539-file base. The 203-file
base and four additions form the verified 207-file app-source archive.

On 2026-11-20, E107 completed a local synthetic build from that archive:
the helper, periodic fixture, app and widget were rebuilt, with two
frontend changes for the new bundle identifier and runtime manifest pin.
The 77-entry app archive matched its restored tree, and four code
signatures passed before and after restoration. The Clang command needs
the explicit SDK path shown below; the immutable E106 guide omitted it.
The local artifact `UPS-Monitor-E107-Synthetic.app.tar.gz` has SHA-256
`705f733ea1597d4e1bcc01e7569692acbe1aff4f398262a6ecefeb2a42dc2f47`.
E108 passed the source subset's 455 distinct Swift test cases, including
two opt-in cases against synthetic loopback servers, as described below.

E109 built the real app and widget from the same 207-file source archive,
with version 0.1.0 (1) and fixture mode `NO`. The public preparer changed
two frontend files for the `org.openupsmonitor.mac.e109.real` app
identifier, its `.widget` extension and the compiled manifest pin. E109 reused the
14-entry E107 helper tree, signed a copy of the E105 reader ad hoc and
preserved the original mode-0600 unsigned reader. Static inspection
verified that signing preserved the reader's sections and payload.
The 83-entry archive matched the complete restored tree, with all four
signatures passing before and after restoration. The app and widget
declare macOS 14 as their deployment target. The frozen runtime requires
arm64 and macOS 27 or later.

| E109 artifact | SHA-256 |
|---|---|
| `UPS-Monitor-E109-Real.app.tar.gz` (12,811,474 bytes) | `2b783cf95d8f8d7804983d04b20fa9e6c7db3876e58ffbe48ac99ec12770356c` |
| Reused E107 helper executable | `701a07e7713c15b16b22b9d63ff51c5608ac8274f4bf64080164e72d30b501b3` |
| E109 signed E105 reader copy | `3d75472b8c0868a40723fa0010884c4abae29226a3959523dde0381c95030428` |
| E109 runtime manifest | `927b5a75b446ce05d510e3e3adbaaad0e86bde271d993db1e92567ebdd0a82af` |
| E109 full app tree inventory | `421735aa77e93f037c7f0c39bc993b50de4843147e4824f389f4a43757894156` |

These checks cover local build, assembly and static verification. The build
workflows issued no product launch commands and performed no USB operations. Independent
installation, app launch, widget rendering, clean Stop, sustained
operation, notarization and public release remain separate checks.
The current repository documentation carries these results and the
corrected commands. The immutable E106 tar retains its archived guide.

Obtain the separately delivered [E104 native-source candidate](#real-reader)
for the real reader. Use the periodic fixture for a synthetic preview.
Build and signing parameters, runtime manifest hashes and local install
locations belong to the new candidate.

## Set up the source and tools

Verify the app-source archive against its trusted SHA-256 and unpack it
in a new private workspace. Compare the files with `SOURCE_MANIFEST.json`
and set `CHECKOUT_ROOT` to the directory containing `Package.swift`.
Install or provision the tools before going offline. The archived
app builds used Apple Silicon, macOS 27, Xcode 27.2 (27B52), the macOS
27.2 SDK and Apple Swift 6.4.2. Use an absolute `HOST_PYTHON` for
Python 3.15.2 with `compression.zstd` available. Set `DEVELOPER_DIR`
to the selected Xcode developer directory and retain the tool versions.

The public source preparer reads Git's tracked and non-ignored
working-tree file names. Initialize local metadata in the verified
private copy if it came from a tar file. No remote or commit is needed.
Keep all build products outside `CHECKOUT_ROOT`.

```sh
(
  set -eu
  cd "$CHECKOUT_ROOT"
  test -f Package.swift
  test ! -e .git
  test ! -L .git
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR
  export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
  git init --quiet --template=
  git config --local core.excludesFile /dev/null
)
set -eu
umask 077
UPS_WORK_PARENT="$(mktemp -d /private/tmp/ups-app-build.XXXXXXXX)"
BUILD_ROOT="$UPS_WORK_PARENT/build"
mkdir "$BUILD_ROOT"
export DEVELOPER_DIR
XCODEBUILD="$(xcrun --find xcodebuild)"
CLANG="$(xcrun --find clang)"
MACOS_SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
CODESIGN=/usr/bin/codesign
NUT_DIR="$CHECKOUT_ROOT/backend/nut"
```

Verify the selected toolchain with `"$XCODEBUILD" -version`,
`"$XCODEBUILD" -sdk macosx -version` and `"$CLANG" --version`.
Use the supplied `backend/nut/process_deadline.py` `run_bounded` API
for reviewed build phases with a new capture directory, owned-group
cancellation, a per-phase limit of 600 s and combined capture of 1 MiB.
Keep the setup, commands and outputs in the private workspace. Direct
file writes by tools and total build time need their own limits.

## Build the frozen helper

Set `PBS_ARCHIVE` and `WHEELHOUSE` to the privately obtained original
inputs. The [PBS lock](../backend/nut/bundled_python_runtime_inputs.json)
identifies CPython 3.15.2 from release `20261026`. The
[wheel lock](../backend/nut/frozen_build_inputs.json) identifies
PyInstaller 6.22.3 and the other five wheel inputs. The sources and their
digests come from these locks.

```sh
"$HOST_PYTHON" -I -S -B "$NUT_DIR/stage_bundled_python_runtime.py" \
  --archive "$PBS_ARCHIVE" --destination "$BUILD_ROOT/payload"
mkdir -p "$BUILD_ROOT/python/Contents"
"$HOST_PYTHON" -I -S -B - "$NUT_DIR" "$BUILD_ROOT" <<'PY'
import hashlib
from pathlib import Path
import sys

tools, root = map(Path, sys.argv[1:])
sys.path.insert(0, str(tools))
from normalize_bundled_python import copy_normalized_python

payload = root / "payload"
pin = hashlib.sha256((payload / "runtime-tree.json").read_bytes()).hexdigest()
result = copy_normalized_python(payload, pin, root / "python/Contents")
assert result["state"] == "PRESIGN_NORMALIZED_NOT_EXECUTED"
PY
BUILD_PYTHON="$BUILD_ROOT/python/Contents/Resources/PythonRuntime/install/bin/python3.15"
mkdir "$BUILD_ROOT/tmp" "$BUILD_ROOT/cache" "$BUILD_ROOT/pyinstaller-cache"
run_build_tool() (
  umask 022
  env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" LC_ALL=C \
    TMPDIR="$BUILD_ROOT/tmp" XDG_CACHE_HOME="$BUILD_ROOT/cache" \
    PYTHONDONTWRITEBYTECODE=1 PIP_CONFIG_FILE=/dev/null \
    PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-cache" \
    DEVELOPER_DIR="$DEVELOPER_DIR" "$@"
)
run_build_tool "$BUILD_PYTHON" -I -B -m venv "$BUILD_ROOT/venv"
VENV_PYTHON="$BUILD_ROOT/venv/bin/python3.15"
run_build_tool "$VENV_PYTHON" -I -B -m pip --disable-pip-version-check install \
  --no-index --no-deps --no-compile --no-cache-dir --require-hashes --only-binary=:all: \
  --find-links "$WHEELHOUSE" -r "$NUT_DIR/frozen_build_requirements.txt"
run_build_tool "$VENV_PYTHON" -I -B -m PyInstaller --noconfirm \
  --distpath "$BUILD_ROOT/dist" --workpath "$BUILD_ROOT/work" "$NUT_DIR/UPSOperationalHelper.spec"
HELPER_APP="$BUILD_ROOT/dist/UPSOperationalHelper.app"
"$CODESIGN" --verify --strict --verbose=2 "$HELPER_APP"
```

Check that the venv uses the normalized interpreter. Inspect the new
helper's Mach-O dependencies, embedded Python archive, standard-library
ZIP and runtime hooks. The archived E96/E98 helper includes
`pyi_rth_inspect`; the nine operational modules listed below are
external bundle resources. Preserve the extended CPython license and
the complete runtime notice directory and index.

The [CPython change summary](CPYTHON_RUNTIME_CHANGES.md)
is a verbatim reference from the full project. Its document references
describe that checkout. Use this guide for the subset's build procedure.

## Prepare the producer

Create an executable copy at `$BUILD_ROOT/native/apcmicrolink-hidapi-operational`.
Use only the section for the chosen profile.

### Real reader

Use the companion `UPS-Monitor-E96-Native-Source.tar`, SHA-256
`3995e50bc2f857104f756fc59e6cfb48b2c3dd82dd37627353c9820c8ad47ec5`.
Its README explains the restored recipe, private kit and existing
HIDAPI 0.16 fresh builder. Keep the successful static build receipt
and the reader digest recorded in it. Set `PRODUCT` to the unsigned
reader from that build, `PRODUCT_SHA256` to that recorded digest and
`NATIVE_NOTICE_SOURCE` to the companion's verified `notices/`.

```sh
test "$(stat -f '%Lp' "$PRODUCT")" = 600
printf '%s  %s\n' "$PRODUCT_SHA256" "$PRODUCT" | shasum -a 256 -c -
mkdir "$BUILD_ROOT/native"
NATIVE_PRODUCER="$BUILD_ROOT/native/apcmicrolink-hidapi-operational"
cp -p "$PRODUCT" "$NATIVE_PRODUCER"
chmod 0755 "$NATIVE_PRODUCER"
printf '%s  %s\n' "$PRODUCT_SHA256" "$NATIVE_PRODUCER" | shasum -a 256 -c -
PRODUCER_SIGN_ID=org.openupsmonitor.real-operational-producer
```

Use an app identifier ending in `.real`, with fixture mode `NO`.
Keep the original mode-0600 reader.

### Periodic synthetic producer

Use the [periodic C source](../backend/nut/fixtures/synthetic_operational_periodic.c),
SHA-256 `ead60dcd079a8a4467183181f95f1b306d24253e990b9363b1ff35252c136861`.
The preserved file carries its MIT header. The command builds arm64 C11
with optimization and warnings treated as errors, without an explicit
deployment-target override.
Pass the selected macOS SDK explicitly when invoking Clang in the clean
environment; the archived E106 guide omitted this parameter. The frozen
runtime requires arm64 and macOS 27 or later.

```sh
mkdir "$BUILD_ROOT/native"
NATIVE_PRODUCER="$BUILD_ROOT/native/apcmicrolink-hidapi-operational"
run_build_tool "$CLANG" -isysroot "$MACOS_SDK_PATH" \
  -arch arm64 -std=c11 -Wall -Wextra -Werror -O2 \
  "$NUT_DIR/fixtures/synthetic_operational_periodic.c" -o "$NATIVE_PRODUCER"
PRODUCER_SIGN_ID=org.openupsmonitor.synthetic-operational-producer
```

Use an app identifier ending in `.synthetic`, with fixture mode `YES`.
This producer supplies fabricated data and does not communicate with an UPS.

### Verify and freeze this runtime

Use a new producer copy. Ad-hoc sign it as nested code and verify it
before recording its digest. The app and widget will use their own
local development signing configuration.

```sh
"$CODESIGN" --force --sign - --timestamp=none \
  --identifier "$PRODUCER_SIGN_ID" "$NATIVE_PRODUCER"
"$CODESIGN" --verify --strict --verbose=2 "$NATIVE_PRODUCER"
NATIVE_SHA256="$(shasum -a 256 "$NATIVE_PRODUCER" | cut -d ' ' -f 1)"

QUAL_ROOT="$(mktemp -d "$UPS_WORK_PARENT/ups-bounded.XXXXXXXX")"
TOOL_DIR="$QUAL_ROOT/tool-checkout/backend/nut"
CANDIDATE_ROOT="$QUAL_ROOT/stage"
mkdir -p "$TOOL_DIR"
for name in stage_frozen_operational_runtime.py prepare_bundled_operational_candidate.py \
  managed_bundled_operational_entrypoint.py normalize_bundled_python.py \
  managed_frozen_operational_entrypoint.py bundled_python_runtime_inputs.json \
  managed_operational_entrypoint.py app_controlled_operational.py \
  operational_capture.py operational_publication.py continuous_capture.py \
  continuous_protocol.py process_deadline.py bounded_stream_dispatch.py cleanup_diagnostics.py
do
  cp "$NUT_DIR/$name" "$TOOL_DIR/$name"
done
QUAL_PATCH="$NUT_DIR/qualification/smc1500i-90s.patch"
printf '%s  %s\n' d89e56de325acd325f29a12596c50f4466e10521d6924e8bec868a1204f07ac3 \
  "$TOOL_DIR/managed_operational_entrypoint.py" | shasum -a 256 -c -
printf '%s  %s\n' 75e7a32a7032f07af8f97c78520389fa011320e26780da9066c237662892b1a9 \
  "$QUAL_PATCH" | shasum -a 256 -c -
/usr/bin/patch --batch --forward --fuzz=0 -p1 -d "$TOOL_DIR" -i "$QUAL_PATCH"
"$HOST_PYTHON" -I -S -B - "$NUT_DIR/qualification/module-sha256.json" "$TOOL_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path

pinfile, root = map(Path, sys.argv[1:])
pins = json.loads(pinfile.read_bytes())
if len(pins) != 9 or any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
                         for name, digest in pins.items()):
    raise SystemExit("qualification source digest mismatch")
PY
"$HOST_PYTHON" -I -S -B "$TOOL_DIR/stage_frozen_operational_runtime.py" \
  --helper-app "$HELPER_APP" --native-producer "$NATIVE_PRODUCER" \
  --native-sha256 "$NATIVE_SHA256" --output-root "$CANDIDATE_ROOT"
MANIFEST_SHA256="$("$HOST_PYTHON" -I -S -B -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$CANDIDATE_ROOT/receipt.json")"
```

The exact [qualification patch](../backend/nut/qualification/smc1500i-90s.patch)
and [nine-file map](../backend/nut/qualification/module-sha256.json)
describe the bounded profile used in both archived apps. The profile
uses 35 s startup and 15 s progress timeouts, then requests cancellation
after 90 s during capture. Its termination grace is 2 s. Kernel
operations and cleanup can take longer.

## Prepare the app and widget source copy

Choose a dedicated reverse-DNS `BUNDLE_ID` with the selected suffix,
and set `FIXTURE_MODE` to `NO` for real or `YES` for synthetic.
Supply the matching ID and group provisioning through the recipient's
own local signing configuration. The widget uses the additional
`.widget` suffix. Use the new staging manifest and generated Swift
file. The pins in the base source stay unset.

```sh
SOURCE_ROOT="$UPS_WORK_PARENT/app-candidate"
set --
if test "$FIXTURE_MODE" = NO; then
  set -- --real-preview
else
  test "$FIXTURE_MODE" = YES
fi
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/scripts/prepare_synthetic_source.py" \
  --checkout "$CHECKOUT_ROOT" --output-root "$SOURCE_ROOT" \
  --pin-file "$CANDIDATE_ROOT/derived/FrozenOperationalReleasePins.swift" \
  --manifest-sha256 "$MANIFEST_SHA256" --bundle-identifier "$BUNDLE_ID" "$@"
```

The preparer changes the frozen Swift pin and the bundle ID settings
in `UPSMonitor.xcodeproj/project.pbxproj`. E96, E107 and E109 used
these two frontend changes. The archived E98 used four further edits in
`$SOURCE_ROOT/source`, after the public two-file preparation.

| E98 additional file | Archived choice |
|---|---|
| `App/Info.plist` | Set `CFBundleVersion` to `2`. |
| `Widget/Info.plist` | Set `CFBundleVersion` to `2`. |
| `Sources/UPSWidgetBridge/WidgetGroupConfiguration.swift` | Set the synthetic kind to `UPSMonitorSyntheticFixtureE70` and the synthetic store directory to `UPSWidgetSyntheticFixtureE70`. |
| `Widget/UPSMonitorWidget.swift` | Set the synthetic gallery name to `UPS Monitor E70 Synthetic Test`. |

Record these choices when reconstructing the E98 profile. A new
synthetic candidate can choose its own isolated kind and store name.
The same recipient App Group must be present in both signed products.
Keep it distinct from any existing production snapshot store.

## Build, assemble and verify

Set `SIGNING_IDENTITY`, `DEVELOPMENT_TEAM` and `UPS_APP_GROUP_ID`
from private local provisioning for the new app and widget. Build
only the private source copy. Do not retain signing parameters in
public transcripts.

```sh
APP="$BUILD_ROOT/xcode/Build/Products/SharedRelease/UPS Monitor.app"
run_build_tool "$XCODEBUILD" -project "$SOURCE_ROOT/source/UPSMonitor.xcodeproj" \
  -scheme UPSMonitor -configuration SharedRelease -destination platform=macOS,arch=arm64 \
  -derivedDataPath "$BUILD_ROOT/xcode" -clonedSourcePackagesDirPath "$BUILD_ROOT/swiftpm" \
  -disableAutomaticPackageResolution -skipPackageUpdates -jobs 4 -quiet build \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=YES REGISTER_APP_WITH_LAUNCH_SERVICES=NO \
  "CODE_SIGN_IDENTITY=$SIGNING_IDENTITY" CODE_SIGN_STYLE=Manual \
  "DEVELOPMENT_TEAM=$DEVELOPMENT_TEAM" "UPS_APP_GROUP_ID=$UPS_APP_GROUP_ID" \
  "UPS_WIDGET_FIXTURE_MODE=$FIXTURE_MODE" CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO \
  OTHER_CODE_SIGN_FLAGS=--timestamp=none
"$HOST_PYTHON" -I -S -B "$NUT_DIR/assemble_frozen_operational_runtime.py" \
  --runtime-contents "$CANDIDATE_ROOT/stage/Contents" \
  --app-contents "$APP/Contents" --manifest-sha256 "$MANIFEST_SHA256"
```

Verify the new bundle IDs, fixture flags, matching App Group entitlements,
absence of a debug entitlement and the embedded app manifest pin against
the new receipt. Verify the helper and producer hashes and the nine
external source hashes.

For real, copy the eight verified companion files into
`$APP/Contents/Resources/NativeProducerNotices`: `COPYING`,
`LICENSE-GPL2`, `LICENSE-GPL3`, `LICENSE.txt`, `LICENSE-bsd.txt`,
`LICENSE-orig.txt`, `LICENSE-gpl3.txt` and `README.txt`. Check the
copied bytes against the companion's notice hashes. For synthetic,
create `SyntheticProducerNotices/LICENSE.txt` from [the MIT license](../LICENSE)
and `SyntheticProducerNotices/README.txt` identifying the periodic
source hash and the newly signed fixture hash. Keep the separate
`RuntimeNotices` directory from the assembler in either case.

```sh
"$CODESIGN" --force --sign "$SIGNING_IDENTITY" --timestamp=none \
  --preserve-metadata=identifier,entitlements,requirements,flags "$APP"
"$CODESIGN" --verify --deep --strict --verbose=2 "$APP"
"$CODESIGN" --verify --strict --verbose=2 "$APP/Contents/PlugIns/UPSMonitorWidget.appex"
"$CODESIGN" --verify --strict --verbose=2 "$APP/Contents/Helpers/UPSOperationalHelper.app"
"$CODESIGN" --verify --strict --verbose=2 "$APP/Contents/MacOS/apcmicrolink-hidapi-operational"
```

Sign the outer app last and retain its checked nested code. Recheck the
compiled pin, fixture identity, modes, internal links, notice files and
nested bytes. If archiving an app, reopen the finished archive in a
new folder, preserve modes and compare the complete tree before
repeating all four signature checks.

For local installation, place the verified signed app in a new local
folder with its metadata intact. Repeat the same signed-copy checks
there. A recipient's normal app opening and widget gallery checks
belong to the separate installation trial. The source evidence makes
no claim about independent installation, notarization, live USB,
widget rendering or continuous operation.

## Test the unmodified app sources

Use `CHECKOUT_ROOT` from the verified archive, with the base runtime pins
still `nil`, rather than the source copy generated for a signed app.
The archive contains 77 Swift test files and three JSON resources for
13 test targets. The ordinary suite needs no remote SwiftPM dependency
or extra test fixture. It does not run the native UPS reader or the
frozen app helper. It compiles small, inline C clients used by its tests;
the system-selected `/usr/bin/clang` must already be usable. Do not change
the system toolchain as part of this check.

Create a private workspace for test products and caches. The phase below
is the command used by the E108 test route, not a timeout wrapper. Apply
the public `run_bounded` supervisor described above, with 600 seconds and
1 MiB of combined capture, and monitor the owned workspace's allocation.

```sh
UPS_TEST_ROOT="$(mktemp -d /private/tmp/ups-app-tests.XXXXXXXX)"
for part in home tmp clang-cache swift-cache swiftpm-modulecache \
  swiftpm-scratch swiftpm-cache config security; do
  mkdir "$UPS_TEST_ROOT/$part"
done
/usr/bin/env -i \
  PATH=/usr/bin:/bin:/usr/sbin:/sbin LC_ALL=C TZ=UTC \
  DEVELOPER_DIR="$DEVELOPER_DIR" \
  HOME="$UPS_TEST_ROOT/home" TMPDIR="$UPS_TEST_ROOT/tmp" \
  XDG_CACHE_HOME="$UPS_TEST_ROOT/swiftpm-cache" \
  PYTHONDONTWRITEBYTECODE=1 DisableExecutionPolicyExceptionRegistration=YES \
  CLANG_MODULE_CACHE_PATH="$UPS_TEST_ROOT/clang-cache" \
  SWIFT_MODULE_CACHE_PATH="$UPS_TEST_ROOT/swift-cache" \
  SWIFTPM_MODULECACHE_OVERRIDE="$UPS_TEST_ROOT/swiftpm-modulecache" \
  /usr/bin/swift test --build-system swiftbuild \
  --package-path "$CHECKOUT_ROOT" \
  --scratch-path "$UPS_TEST_ROOT/swiftpm-scratch" \
  --cache-path "$UPS_TEST_ROOT/swiftpm-cache" \
  --config-path "$UPS_TEST_ROOT/config" \
  --security-path "$UPS_TEST_ROOT/security" \
  --manifest-cache none --disable-dependency-cache
```

Two `UPSCInteropTests` cases intentionally skip when the three opt-in
variables are absent. To run them, first obtain the qualified relocatable
client bundle and its adjacent library described under [Swift adapter interoperability](NUT_CLIENT_COMPLETION.md#swift-adapter-interoperability)
in the full repository. That guide, its patch/checker and the client
binaries are outside this app-source archive. Python must also be
available at a verified absolute path. E108 reused the previously
qualified client and library as test inputs; it did not rebuild them.

Repeat the same command and workspace, adding these environment arguments
before `/usr/bin/swift`, and append `--skip-build --filter UPSCInteropTests`
to the Swift arguments:

- `UPS_TEST_UPSC="$VERIFIED_UPSC"`, the qualified client path.
- `UPS_TEST_UPSC_SHA256="$VERIFIED_UPSC_SHA256"`, its verified SHA-256.
- `UPS_TEST_PYTHON="$HOST_PYTHON"`, the verified Python path.

Use a 90-second bound and the same output cap for that phase. The test
starts its own inline Python server on `127.0.0.1` with an ephemeral
port. It must pass both named cases without skips; no real UPS endpoint
is involved. If its prerequisites are unavailable, report those two
cases as not run rather than as passed.

E108 recorded 157 Swift Testing passes and 296 XCTest passes in the
ordinary phase, plus two declared skips. The filtered phase passed those
same two skipped XCTest cases: 455 distinct cases passed overall, not
457. Both phases exited normally. The macOS alias test also remained in
the suite; it creates and removes two UUID directories in the system
and user temporary roots outside `TMPDIR`. Check those roots for newly
remaining directories without deleting unrelated files, then remove
only the owned test workspace after its process groups have closed.

This verifies the delivered Swift subset on the recorded host. It does
not cover the full repository's Python/reader tests, privacy/version
checks, hosted CI, installed widget rendering or real USB behavior.
