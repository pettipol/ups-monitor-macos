# Frozen helper build inputs and candidate staging

This procedure connects the public Python stager, PyInstaller spec, frozen
candidate stager and app assembler. It does not launch a helper, native producer,
app or widget. A new execution of the complete procedure still needs its own
build evidence; earlier local results are not a reproducible-build claim for a
different source revision, machine or signing identity.

## Observed local composition — 2026-11-04

The [real producer packaging procedure](REAL_PREVIEW_PACKAGE.md) uses a distinct
app identifier, source-built native producer and production widget store.

One complete SharedRelease synthetic app/widget package was composed in 25
bounded commands over 57.314 seconds from 504 frozen source files
(5,787,739 bytes). The helper/runtime used the pinned PBS archive and six
locked wheels; the synthetic producer came from the public C fixture. The
static closure had 25 entries and nine external backend modules bound to the
E60 process-deadline source. Four independent signature verifications passed;
the 25 notice files were copied and checked. No app, helper, producer, widget
or UPS path was launched. This single local composition does not qualify
bit-reproducibility, runtime, hosted CI,
distribution or notarization qualification; third-party redistribution review
remains **NOT PERFORMED**. See the [dated result](LOCAL_VALIDATION_2026-11-04.md#packaging-2026-11-04-e61).

The current profile is arm64/macOS 27 or later. The refreshed candidate uses
Xcode 27.2 (27B52), Apple Swift 6.4.2 and an already installed Python 3.15.2 with `compression.zstd` for host-side
tools. The separately staged PBS interpreter is the helper's build/runtime input,
not a substitute for the host tool before archive admission.

## Fixed inputs

- [PBS input](../backend/nut/bundled_python_runtime_inputs.json) pins the full
  CPython 3.15.2/20261026 archive, metadata and upstream URL.
- [Build input lock](../backend/nut/frozen_build_inputs.json) records all six
  wheels, including filename, size, SHA-256 and primary download/metadata URLs.
- [Hash-locked requirements](../backend/nut/frozen_build_requirements.txt) are
  for the macOS Python 3.15 build environment. They are not the app's dependency
  license list. Do not let pip resolve newer or platform-specific alternatives.
- [Helper spec](../backend/nut/UPSOperationalHelper.spec) uses its own source
  directory. Keep it beside the entrypoint and import aggregate in the reviewed
  checkout. The nine external backend modules must not be frozen into its PYZ.

Acquire the archive and six wheels separately from those URLs, preserving the
originals in durable storage with provenance; Downloads is transit only. Check
the archive and each wheel's exact size and hash against the locks before use.
The stager checks the PBS archive itself; pip checks wheel hashes again. These
tools do not download inputs. The versions are the qualified input set, not a
request to upgrade an existing environment. Any changed input requires a new
inventory, notice reconciliation and qualification.

## Resolve and validate the installed Apple toolchain

### Run a bounded build phase

Use the supervisor shipped in the verified project. The kit setup supplies
`CHECKOUT_ROOT`, `PBS_ARCHIVE` and `WHEELHOUSE`. If using a clone, set
those three absolute paths first. Set `HOST_PYTHON` to the trusted host
interpreter and `DEVELOPER_DIR` to the selected Xcode developer directory. Keep this setup
outside the extracted project so local build files stay out of Git's inventory.

```sh
umask 077
UPS_WORK_PARENT="$(mktemp -d /private/tmp/ups-build-parent.XXXXXXXX)"
export UPS_WORK_PARENT
run_build_phase() {
  "$HOST_PYTHON" -I -S -B - "$CHECKOUT_ROOT" "$1" "$2" "$UPS_WORK_PARENT" \
    "$DEVELOPER_DIR" "$HOME" "$HOST_PYTHON" "$PBS_ARCHIVE" "$WHEELHOUSE" <<'PY'
import hashlib
import runpy
import sys
from pathlib import Path
from threading import Event

project, phase, output, parent, developer, home, python, archive, wheels = map(Path, sys.argv[1:])
if phase.parent != parent or output.parent != parent or not phase.is_file() or phase.is_symlink():
    raise SystemExit("use a reviewed phase file and a fresh output path inside the private workspace")
module = runpy.run_path(str(project / "backend/nut/process_deadline.py"))
env = Path("/usr/bin/env")
args = [str(env), "-i", "PATH=/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL=C",
        f"HOME={home}", f"CHECKOUT_ROOT={project}", f"UPS_WORK_PARENT={parent}",
        f"DEVELOPER_DIR={developer}", f"HOST_PYTHON={python}", f"PBS_ARCHIVE={archive}",
        f"WHEELHOUSE={wheels}", "/bin/bash", "-eu", "-o", "pipefail", str(phase)]
result = module["run_bounded"](args, executable_sha256=hashlib.sha256(env.read_bytes()).hexdigest(),
    output_directory=output, timeout_seconds=600, termination_grace_seconds=5,
    maximum_output_bytes=1_048_576, cancel_event=Event())
print(f"{result.status.value} {result.trigger.value} returncode={result.returncode}")
if (result.status != module["RunStatus"].EXITED or result.trigger != module["RunTrigger"].COMPLETED
        or result.returncode != 0 or result.observation is None):
    raise SystemExit(1)
PY
}
```

Save the reviewed shell commands for one phase in a file directly under
`UPS_WORK_PARENT`. Keep commands that share variables and functions in that
file, or restore paths and digests explicitly between phases. For the real
preview include the native product path and its independently recorded SHA-256.
Use private local signing configuration for the outer app. To check the
supervisor before building, run:

```sh
printf '%s\n' 'test -f "$CHECKOUT_ROOT/Package.swift"' > "$UPS_WORK_PARENT/check-input.sh"
run_build_phase "$UPS_WORK_PARENT/check-input.sh" "$UPS_WORK_PARENT/check-input-log"
```

Use a fresh log directory name for each phase. The combined stdout/stderr
limit is 1 MiB; the deadline is 600 seconds and cleanup can take longer.
A redirect to a file or a compiler cache bypasses that capture limit.
Account separately for space used by build products and direct writes, and
for elapsed time across phases. Read the two private log files on failure
before deciding whether to retry.

### Xcode preflight

Run this once in the fresh build shell before any native compile, Xcode build,
or signature command. It exports the selected `DEVELOPER_DIR` before `xcrun`,
`xcodebuild`, or native compilation. It honors an explicitly supplied
`DEVELOPER_DIR`; if none is set, it uses the conventional full Xcode installation. It does not select,
install, or download Xcode. Stop if a check fails.

```sh
set -eu
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
test -d "$DEVELOPER_DIR"
DEVELOPER_DIR="$(cd "$DEVELOPER_DIR" && pwd -P)"
export DEVELOPER_DIR
XCODEBUILD="$DEVELOPER_DIR/usr/bin/xcodebuild"
CLANG="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
CODESIGN=/usr/bin/codesign
test -x "$XCODEBUILD"
test -x "$CLANG"
test -x "$CODESIGN"
MACOS_SDK_PATH="$("$XCODEBUILD" -sdk macosx -version Path)"
test -d "$MACOS_SDK_PATH"
MACOS_SDK_PATH="$(cd "$MACOS_SDK_PATH" && pwd -P)"
"$XCODEBUILD" -version
"$CLANG" --version
"$XCODEBUILD" -sdk macosx -version
CODESIGN_SHA256="$(shasum -a 256 "$CODESIGN" | awk '{print $1}')"
printf 'codesign_sha256=%s\n' "$CODESIGN_SHA256"
```

Keep these shell variables in the same shell for the steps below. `CLANG` and
`MACOS_SDK_PATH` are absolute paths from the selected Xcode; `CODESIGN` is the
installed macOS signing utility. Record the reported versions and SDK path with
the build evidence. These checks do not qualify the toolchain for release.

## Build the helper in a new workspace

Set `CHECKOUT_ROOT`, `HOST_PYTHON`, `PBS_ARCHIVE` and `WHEELHOUSE` to canonical
absolute paths. Use a new private workspace below `$UPS_WORK_PARENT`, with enough
free space for staging and build output. Use the bounded build phase above.
Do not reuse partial output after a
failure or run an acquired interpreter before the archive checks succeed.

```sh
set -eu
umask 077
BUILD_ROOT="$(mktemp -d "$UPS_WORK_PARENT/ups-frozen-build.XXXXXX")"
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/stage_bundled_python_runtime.py" \
  --archive "$PBS_ARCHIVE" --destination "$BUILD_ROOT/payload" \
  > "$BUILD_ROOT/payload-result.json"
mkdir -p "$BUILD_ROOT/python/Contents"
```

Normalize a separate copy using the existing public API. This reads only the
admitted payload and does not execute it. The payload's inventory hash binds
the copy; the normalizer rechecks its declared archive and metadata identities.

```sh
"$HOST_PYTHON" -I -S -B - "$CHECKOUT_ROOT" "$BUILD_ROOT" \
  > "$BUILD_ROOT/normalized-summary.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

checkout, root = map(Path, sys.argv[1:])
sys.path.insert(0, str(checkout / "backend/nut"))
from normalize_bundled_python import copy_normalized_python

payload = root / "payload"
digest = hashlib.sha256((payload / "runtime-tree.json").read_bytes()).hexdigest()
result = copy_normalized_python(payload, digest, root / "python/Contents")
raw = (json.dumps(result, sort_keys=True) + "\n").encode("utf-8")
if len(raw) > 8 * 1024 * 1024:
    raise RuntimeError("normalization receipt exceeds 8 MiB")
with (root / "normalized-result.json").open("xb") as receipt:
    receipt.write(raw)
print(json.dumps({
    "state": result["state"],
    "file_count": result["file_count"],
    "selected_bytes": result["selected_bytes"],
    "receipt_sha256": hashlib.sha256(raw).hexdigest(),
}, sort_keys=True))
PY
```

The complete receipt includes both file inventories and stays in the private
workspace. Only its bounded summary is printed: emitting the full receipt into a
1 MiB command log can exhaust that log limit after normalization has finished.
Bind the complete receipt to its summary digest and source inventory before
executing the normalized interpreter; do not continue after a truncated log.

Build with the normalized PBS interpreter, in an isolated environment. The
install step is offline, hash-locked and does not resolve dependencies or compile
bytecode. The commands retain the existing `HOME` value; caches are redirected
to the private build workspace. The wrapper supplies an explicit environment
instead of inheriting Python, pip or loader overrides. The wrapper passes the
validated `DEVELOPER_DIR` selected above; do not replace it with a hard-coded
path inside the wrapper.
The venv/ensurepip step may still create its own bytecode inside that workspace.

```sh
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
  --find-links "$WHEELHOUSE" \
  -r "$CHECKOUT_ROOT/backend/nut/frozen_build_requirements.txt"
run_build_tool "$VENV_PYTHON" -I -B -m PyInstaller --noconfirm \
  --distpath "$BUILD_ROOT/dist" --workpath "$BUILD_ROOT/work" \
  "$CHECKOUT_ROOT/backend/nut/UPSOperationalHelper.spec"
```

Verify that the venv interpreter resolves to this PBS copy. Inspect the build
tables, actual bundle, Mach-O dependencies, nested signature and notices before
accepting the result. The spec requests an ad-hoc arm64 helper; it neither grants
distribution signing nor proves that the output contains only expected imports.
Different build paths or signatures can change output hashes. Generate new pins
from the verified output; do not paste a digest from an earlier machine.

The build-tool subshell uses `umask 022` inside the private `0700` workspace.
This produces the bundle's required `0755` directories, `0644`/`0755` files
and executable producer. Keeping the outer `umask 077` for PyInstaller or
the compiler instead produces restrictive modes that the stager rejects.
Do not repair a signed or pinned bundle by changing its modes afterward.

## Stage the built helper and native producer

The following producer build is **synthetic-only**. For a real preview, skip
this subsection entirely: do not compile the C fixture. Follow
[REAL_PREVIEW_PACKAGE.md](REAL_PREVIEW_PACKAGE.md), which copies the already
verified non-executable product from the native recipe and uses the real
bundle identifier and `UPS_WIDGET_FIXTURE_MODE=NO`. A synthetic build uses the
fixture source, an identifier ending `.synthetic`, and
`UPS_WIDGET_FIXTURE_MODE=YES`.

For the synthetic path, build the producer from the public C fixture inside the
private workspace. Record the source, compiler/tool identity, exact command and
product hash; ad-hoc sign and verify the output before calculating the hash
supplied to the stage command. Staging accepts a separate binary and never
compiles or runs it.

```sh
NATIVE_PRODUCER="$BUILD_ROOT/native/apcmicrolink-hidapi-operational"
mkdir "$BUILD_ROOT/native"
run_build_tool "$CLANG" -arch arm64 -mmacosx-version-min=27.0 \
  -isysroot "$MACOS_SDK_PATH" -std=c11 -O2 -Wall -Wextra -Werror \
  -Wl,-dead_strip "$CHECKOUT_ROOT/backend/nut/fixtures/synthetic_operational_producer.c" \
  -o "$NATIVE_PRODUCER"
"$CODESIGN" --force --sign - --timestamp=none \
  --identifier org.openupsmonitor.synthetic-operational-producer "$NATIVE_PRODUCER"
"$CODESIGN" --verify --strict --verbose=2 "$NATIVE_PRODUCER"
NATIVE_SHA256="$(shasum -a 256 "$NATIVE_PRODUCER" | awk '{print $1}')"
```

`CLANG`, `MACOS_SDK_PATH` and `CODESIGN` are the validated paths from the
preflight section above. Before compiling, require that
`$BUILD_ROOT/native/apcmicrolink-hidapi-operational` does not exist. The locally
reviewed fixture build used Apple clang 21.0.0, arm64, minimum macOS 27.0 and
the macOS 27.2 SDK; see the E57 build receipt in private evidence. No producer
launch is part of this procedure. Run the compile/sign phase through the
bounded build phase above. Direct file writes remain
governed by the private workspace and disk-space rules.

Set `CANDIDATE_ROOT` to a new path below the private `BUILD_ROOT`; the path
must not exist because the stager creates it. Save its JSON result and extract
the generated manifest digest for the source preparation step.

```sh
CANDIDATE_ROOT="$BUILD_ROOT/frozen-candidate"
test ! -e "$CANDIDATE_ROOT"
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/stage_frozen_operational_runtime.py" \
  --helper-app "$BUILD_ROOT/dist/UPSOperationalHelper.app" \
  --native-producer "$NATIVE_PRODUCER" --native-sha256 "$NATIVE_SHA256" \
  --output-root "$CANDIDATE_ROOT" > "$BUILD_ROOT/stage-result.json"
MANIFEST_SHA256="$("$HOST_PYTHON" -I -S -B -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$BUILD_ROOT/stage-result.json")"
case "$MANIFEST_SHA256" in *[!0-9a-f]*|'') exit 1;; esac
test "${#MANIFEST_SHA256}" -eq 64
```


The stager copies the helper and native bytes, normalizes only the two documented
PyInstaller symlink modes, and calls the existing frozen finalizer. It produces
`stage/Contents`, its runtime manifest/inventory and
`derived/FrozenOperationalReleasePins.swift`. Source inputs remain unchanged.
Signature verification and proof of the compiled Swift pin remain caller tasks;
a successful copy is not signature or execution evidence.

## Build and assemble the outer app

Prepare the outer-app source copy with the bounded copy-only helper. The output
root must be new, under a private temporary directory, and have an existing
parent owned by the current user with no group or other write permission. The
helper reads Git's current tracked and non-ignored untracked file names, then
copies their current working-tree bytes (including tracked modifications).
Local `AGENTS.md` files and ignored files are omitted. Source files must already
have mode `0600`, `0644` or `0755`; those modes are preserved. The helper rejects
symlinks, hardlinks, special files, unsafe paths, oversized trees and occupied
output. Git name capture stops at 1 MiB and has a 10-second subprocess timeout.
Its cooperative 30-second deadline and metadata rechecks do not prove safety
against a same-UID concurrent race. A failure preserves any partial output for
inspection; remove it manually before retrying.

```sh
umask 077
SOURCE_PARENT="$(mktemp -d "$UPS_WORK_PARENT/ups-source.XXXXXXXX")"
SYNTHETIC_BUNDLE_ID=org.openupsmonitor.synthetic.e61.synthetic
SOURCE_ROOT="$SOURCE_PARENT/candidate"
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/scripts/prepare_synthetic_source.py" \
  --checkout "$CHECKOUT_ROOT" \
  --pin-file "$CANDIDATE_ROOT/derived/FrozenOperationalReleasePins.swift" \
  --manifest-sha256 "$MANIFEST_SHA256" \
  --bundle-identifier "$SYNTHETIC_BUNDLE_ID" \
  --output-root "$SOURCE_ROOT"
```

Use a reverse-DNS synthetic bundle identifier ending in `.synthetic`; it must
not use the preview identifier prefix. The helper accepts only the exact
generated `FrozenOperationalReleasePins.swift` form with the supplied lowercase
manifest digest. It changes exactly two files in `source/`: that frozen pin
and the eight app bundle identifiers in `UPSMonitor.xcodeproj/project.pbxproj`.
The Widget bundle identifier suffix remains `.widget`. Both canonical
`FrozenOperationalReleasePins` and `BundledOperationalReleasePins` must remain
`nil` in the checkout. Review `receipt.json` and its two before/after digests;
the receipt reports `SOURCE_PREPARED_NOT_BUILT`, contains no local absolute
paths, and records per-file before, after and destination size/mode/SHA-256
inventories. It is not build, signing, launch, USB or hardware evidence.

Build the app and widget from `"$SOURCE_ROOT/source"` with the `SharedRelease`
configuration, the already authorized development identity and App Group, and
`UPS_WIDGET_FIXTURE_MODE=YES` for the synthetic producer. Supply identity, team
and group values from private local input to the bounded controller; do not put
them in the repository, command transcript, or public receipt. Ordinary
`Release` does not configure the shared App Group. The fixture setting is
required for this caller; it does not qualify real producer behavior.

```sh
APP="$BUILD_ROOT/xcode/Build/Products/SharedRelease/UPS Monitor.app"
run_build_tool "$XCODEBUILD" -project "$SOURCE_ROOT/source/UPSMonitor.xcodeproj" \
  -scheme UPSMonitor -configuration SharedRelease \
  -destination platform=macOS,arch=arm64 \
  -derivedDataPath "$BUILD_ROOT/xcode" \
  -clonedSourcePackagesDirPath "$BUILD_ROOT/swiftpm" \
  -disableAutomaticPackageResolution -skipPackageUpdates -jobs 4 -quiet build \
  "CODE_SIGN_IDENTITY=$SIGNING_IDENTITY" \
  CODE_SIGN_STYLE=Manual "DEVELOPMENT_TEAM=$DEVELOPMENT_TEAM" \
  "UPS_APP_GROUP_ID=$UPS_APP_GROUP_ID" \
  UPS_WIDGET_FIXTURE_MODE=YES CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO
```

Before assembly, check that the app and widget executables exist, fixture mode
is enabled in both products, the expected synthetic bundle identifiers are
present, both entitlements contain the supplied shared group, and no debug
entitlement was introduced. Record those checks separately; a successful
`xcodebuild` exit alone is not their evidence.

Then use the public assembler with `CANDIDATE_ROOT/stage/Contents`, the built
app's `Contents`, and the freshly generated manifest hash. It also copies the
pinned notices. The destination must be a new app with runtime and notice
destination paths absent:

```sh
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/assemble_frozen_operational_runtime.py" \
  --runtime-contents "$CANDIDATE_ROOT/stage/Contents" \
  --app-contents "$APP/Contents" --manifest-sha256 "$MANIFEST_SHA256" \
  > "$BUILD_ROOT/assemble-result.json"
```

Verify the compiled app contains the freshly generated manifest digest and
validate the assembled runtime closure, native/helper bytes, modes, controls
and notice manifest before signing. Sign only the outer app last; do not use
`--deep` for signing because the helper already has its own nested signature.

```sh
"$CODESIGN" --force --sign "$SIGNING_IDENTITY" --timestamp=none \
  --preserve-metadata=identifier,entitlements,requirements,flags "$APP"
"$CODESIGN" --verify --deep --strict --verbose=2 "$APP"
"$CODESIGN" --verify --strict --verbose=2 \
  "$APP/Contents/PlugIns/UPSMonitorWidget.appex"
"$CODESIGN" --verify --strict --verbose=2 \
  "$APP/Contents/Helpers/UPSOperationalHelper.app"
"$CODESIGN" --verify --strict --verbose=2 \
  "$APP/Contents/MacOS/apcmicrolink-hidapi-operational"
```

After outer signing, repeat closure, embedded-pin, notice, helper/native and
widget inventory checks; confirm nested helper, widget and producer bytes did
not change. The local signing identity, team and App Group must be supplied by the operator
from local private configuration. Run these steps through the bounded build
phase above and retain the results for the package you produced.

No launch is part of this recipe. GUI/widget, clean Stop on the real UPS,
continuous monitoring, downloaded installation, hosted CI and distribution
signing/notarization remain separate [release gates](RELEASE_CHECKLIST.md).
