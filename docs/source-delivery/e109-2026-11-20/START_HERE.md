# UPS Monitor source delivery

Start with the guides under `docs/`. They include the explicit macOS SDK argument for the synthetic fixture, the delivered Swift test command and the E109 real-app assembly result. The two authenticated source archives retain their historical guides. Read those in-archive copies as provenance and use the guides beside this page for the current procedure.

## Verify and extract

From the directory containing this page, set `CHECKSUMS_SHA256` to the SHA-256 of `SHA256SUMS` received through the trusted delivery channel. Use a fresh private work directory. Leave the current guides outside the extracted app tree so its source inventory stays exact.

```sh
set -eu
: "${CHECKSUMS_SHA256:?Set the trusted SHA-256 of SHA256SUMS}"
printf '%s  %s\n' "$CHECKSUMS_SHA256" SHA256SUMS | shasum -a 256 -c -
shasum -a 256 -c SHA256SUMS
KIT_ROOT="$(pwd -P)"
umask 077
WORK_ROOT="$(mktemp -d /private/tmp/ups-source-delivery.XXXXXXXX)"
mkdir -m 700 "$WORK_ROOT/app"
APP_ARCHIVE="$KIT_ROOT/sources/UPS-Monitor-E96-E98-App-Source.tar"
tar -xpf "$APP_ARCHIVE" -C "$WORK_ROOT/app"
CHECKOUT_ROOT="$WORK_ROOT/app/ups-monitor-app-source"
NUT_DIR="$CHECKOUT_ROOT/backend/nut"
```

The app archive has 207 regular files. Compare the extracted paths, file modes, lengths and SHA-256 values against its 206 `SOURCE_MANIFEST.json` records plus the manifest itself. The manifest SHA-256 is `73739a9001307e4a4dba71eb44f0d854daa1dfc1912702754143bb85dbc01794`. Maintain an unmodified copy for Swift tests. The source preparer creates a separate frontend copy.

## Prepare local tools and upstream inputs

Use an Apple Silicon macOS 27 host with an existing trusted Python 3.15.2 interpreter that supports `compression.zstd`. Set `HOST_PYTHON` to the absolute path of the regular executable, resolving any final symlink first. Set `DEVELOPER_DIR` to the selected Xcode developer directory. The recorded toolchain was Xcode 27.2 (27B52), macOS SDK 27.2 and Apple Swift 6.4.2. The native builder also requires the pinned Autotools and other local tools listed in its delivered recipe. The ordinary Swift tests use the system-selected `/usr/bin/clang` for an inline test client. Provision the toolchain before using the offline procedure.

Get the original PBS release 20261026 asset and all six wheels before going offline. Use the filenames, upstream URLs, sizes and hashes in `$NUT_DIR/bundled_python_runtime_inputs.json` and `$NUT_DIR/frozen_build_inputs.json`. Set `PBS_ARCHIVE` to the verified PBS file and `WHEELHOUSE` to a directory containing the six verified wheel files. The native recipe has matching copies of these locks. The recipient creates any private developer kit required by the native builder from those inputs and the restored E104 recipe.

For app signing, supply your locally provisioned `SIGNING_IDENTITY`, `DEVELOPMENT_TEAM` and `UPS_APP_GROUP_ID`. The signed app and widget need the same recipient App Group. Keep these values and signing logs private. App and widget declare a macOS 14 deployment target. The bundled advanced runtime requires arm64 and macOS 27 or later.

## Choose the real or synthetic producer

### Real reader

Set the following variables. The current native guide creates `INPUT_ROOT`, restores `RECIPE_ROOT` and runs the builder into a new `OUTPUT_DIR`. Follow its **Restore the exact recipe**, **Prepare a private build kit** and **Build the native reader** sections. Use `$RECIPE_ROOT/recipe/backend/nut/native-build/hidapi-0.16/README.md` for the native tool versions, absolute paths and build limits. Set `KIT_TAR` and `AUTOTOOLS_BIN` as specified there. [Current native guide](docs/NATIVE_SOURCE_DELIVERY.md)

```sh
SOURCE_ARCHIVE="$KIT_ROOT/sources/UPS-Monitor-E96-Native-Source.tar"
SOURCE_SHA256="3995e50bc2f857104f756fc59e6cfb48b2c3dd82dd37627353c9820c8ad47ec5"
INPUT_ROOT="$WORK_ROOT/native-input"
RECIPE_ROOT="$WORK_ROOT/native-recipe"
KIT_TAR="$WORK_ROOT/private-native-kit.tar"
OUTPUT_DIR="$WORK_ROOT/native-build"
```

After the authenticated native archive has been restored and the builder has succeeded, extract the eight notices needed by the app assembler. This directory is separate from both the restored recipe and the builder output. The archive's `PROVENANCE.json` describes the historical E95/E96 reader. Take the new reader digest from the build receipt you just generated.

```sh
tar -xf "$SOURCE_ARCHIVE" -C "$INPUT_ROOT" UPS-Monitor-E96-Native-Source/notices
PRODUCT="$OUTPUT_DIR/PRODUCT"
NATIVE_NOTICE_SOURCE="$INPUT_ROOT/UPS-Monitor-E96-Native-Source/notices"
PRODUCT_SHA256="$("$HOST_PYTHON" -I -S -B -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    receipt = json.load(stream)
if receipt["state"] != "COMPILED_STATIC_AUDIT_ONLY":
    raise SystemExit("native build receipt did not pass static audit")
print(receipt["product"]["sha256"])
' "$OUTPUT_DIR/BUILD_RECEIPT.json")"
test "$(stat -f %Lp "$PRODUCT")" = 600
printf '%s  %s\n' "$PRODUCT_SHA256" "$PRODUCT" | shasum -a 256 -c -
```

Use these values in **Real reader** in the app guide. That procedure signs a separate executable copy and retains the unsigned original. Use fixture mode `NO` and a recipient bundle ID ending in `.real`. [Current app guide](docs/APP_SOURCE_DELIVERY.md#real-reader)

### Synthetic fixture

Use **Periodic synthetic producer** in the app guide, including `-isysroot "$MACOS_SDK_PATH"`. This path builds the MIT fixture from the app archive and uses fixture mode `YES` with a bundle ID ending in `.synthetic`. Keep its widget kind and store separate from any existing installation. [Current app guide](docs/APP_SOURCE_DELIVERY.md#periodic-synthetic-producer)

## Build, assemble and verify the app

Follow **Set up the source and tools** and **Build the frozen helper** in the current app guide, then the producer section selected above. Continue with **Verify and freeze this runtime**, **Prepare the app and widget source copy** and **Build, assemble and verify**. The app archive contains the helper spec, qualification patch, nine-file postimage map and public staging and assembly tools. Generate the runtime manifest and Swift pin from your own staged inputs. Retain the runtime notices and the producer notices for the chosen profile. Verify the app, widget, helper and producer signatures, then compare the entire archived and restored tree and repeat the signature checks. [Current app guide](docs/APP_SOURCE_DELIVERY.md)

Use the delivered `run_bounded` API for the app and Swift phases. The native builder already supervises its own phases. The shell function below invokes that API with the selected executable's actual SHA-256, an explicit argument list and a new capture directory for each call. Its first command argument must be an absolute path to a regular executable. Resolve any final symlink before passing the path. The capture parent must already exist, be private and belong to your user.

```sh
SUPERVISOR="$NUT_DIR/process_deadline.py"
SUPERVISOR_SHA256="81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e"
printf '%s  %s\n' "$SUPERVISOR_SHA256" "$SUPERVISOR" | shasum -a 256 -c -
CAPTURE_PARENT="$WORK_ROOT/captures"
mkdir -m 700 "$CAPTURE_PARENT"

bounded_phase() (
  set -eu
  test "$#" -ge 3
  phase_seconds="$1"
  phase_capture="$2"
  shift 2
  case "$1" in
    /*) ;;
    *) printf '%s\n' 'Use an absolute executable path.' >&2; exit 2 ;;
  esac
  if ! test -f "$1" || ! test -x "$1" || test -L "$1"; then
    printf '%s\n' 'Use a regular executable and resolve any final symlink first.' >&2
    exit 2
  fi
  executable_sha="$(shasum -a 256 "$1" | cut -d ' ' -f 1)"
  "$HOST_PYTHON" -I -S -B - "$SUPERVISOR" "$phase_capture" "$phase_seconds" "$executable_sha" "$@" <<'PY'
from pathlib import Path
import runpy
import signal
import sys
from threading import Event

module_path, capture, seconds, executable_sha, *argv = sys.argv[1:]
api = runpy.run_path(module_path)
cancel = Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: cancel.set())
try:
    result = api["run_bounded"](
        argv, executable_sha256=executable_sha, output_directory=Path(capture),
        timeout_seconds=float(seconds), termination_grace_seconds=3,
        maximum_output_bytes=1_048_576, cancel_event=cancel,
    )
except api["BoundedRunError"] as error:
    print(error.code.value, file=sys.stderr)
    raise SystemExit(1)
print(result.status.value, result.trigger.value, result.returncode)
raise SystemExit(int((result.status.value, result.trigger.value, result.returncode)
                     != ("exited", "completed", 0)))
PY
)

# Example using the XCODEBUILD path selected by the app guide.
bounded_phase 120 "$CAPTURE_PARENT/xcode-version" "$XCODEBUILD" -version
```

The function prints the supervisor outcome only. Read the tool's output from `stdout.bin` and `stderr.bin` in that phase's capture directory. Keep the guide's direct data reads for `PRODUCT_SHA256` and `MANIFEST_SHA256`. If you capture a digest-producing command, read and verify its digest explicitly from `stdout.bin`.

Preserve the environment specified by the app guide by passing the explicit `/usr/bin/env -i` invocation and its arguments to the function where needed. When the guide uses the shell function `run_build_tool`, apply the boundary inside that function to its `env -i` command and use a different capture path for every phase. The supervisor gives the child empty standard input. For bounded phases shown as inline Python here-documents in the guide, pass the same text with Python `-c` or from a private script file. Allow up to 600 seconds for an app build or ordinary Swift test phase and 90 seconds for the filtered loopback tests. Track the workspace allocation and the overall build time separately. Preserve diagnostics on failure and wait for process closeout before removing your workspace.

## Test the base Swift source

Follow **Test the unmodified app sources** with the original `CHECKOUT_ROOT` and base runtime pins. The ordinary suite uses local SwiftPM targets and fixtures. The two `UPSCInteropTests` cases skip unless all three opt-in variables are supplied. The optional phase needs a qualified relocatable NUT client, its adjacent `libupsclient.7.dylib` and a trusted Python path. The fixture is an inline synthetic loopback server. If these external inputs are unavailable, record the two skips. The E108 ordinary run passed 453 cases. The separate opt-in phase passed the two skipped cases, bringing that historical total to 455 distinct passes. [Swift instructions](docs/APP_SOURCE_DELIVERY.md#test-the-unmodified-app-sources)

## Find references in the extracted sources

| Reference | Location |
| --- | --- |
| App source, PBS and wheel locks, periodic fixture, qualification patch and postimage map | Under `$CHECKOUT_ROOT`, using the app guide's original relative paths. The locks and runtime tools are in `backend/nut/`. |
| Project MIT license and runtime notices | `$CHECKOUT_ROOT/LICENSE` and `$CHECKOUT_ROOT/third_party/frozen-runtime/`. |
| Restore utility, upstream inputs and eight native notices | `$INPUT_ROOT/UPS-Monitor-E96-Native-Source/`. The restore utility is at the top of that extracted archive. |
| Native builder, kit exporter and recipe guides | `$RECIPE_ROOT/recipe/`, including `backend/nut/native-build/hidapi-0.16/README.md`. The recipe also contains the historical offline kit and frozen build guides and `THIRD_PARTY_NOTICES.md`. |
| CPython change summary and distribution assessment | Open the copies beside this page. The CPython summary matches the archived reference bytes. [CPython change summary](docs/CPYTHON_RUNTIME_CHANGES.md) · [Distribution readiness](docs/DISTRIBUTION_READINESS.md) |

The full repository's dependency and Python license inventories, separate NUT client qualification guide and standalone restore utility tests are contextual references. The build path above uses the delivered source, tools and notices plus the external prerequisites identified here. Historic build checks are local. Independent reproducibility, installation, product launch, widget observation, clean Stop, continuous use, USB behavior, hosted CI, notarization and public release each require their own evidence.
