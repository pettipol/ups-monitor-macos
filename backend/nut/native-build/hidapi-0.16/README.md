# Optional HIDAPI 0.16 source profile

This profile upgrades the verified [cancellation-boundary candidate](../WRITE_CANCEL_BOUNDARY.md)
to [HIDAPI 0.16.0](https://github.com/libusb/hidapi/releases/tag/hidapi-0.16.0),
commit `750c87abb03282a237297052b84522e6bb3c0616`. The historical 0.15
recipe and installed app defaults retain their recorded identities.
No new HIDAPI interrupt or queue API is called by the native adapter.

The additional project patch changes only the compile-time header-version
check and its diagnostic. Apply it after the cancellation-boundary patch,
not to the earlier raw project files. The upstream macOS backend changes
independently; its synchronous `IOHIDDeviceSetReport` writes still have no
new cancellation guarantee. Shared opening and orderly Stop on a real UPS
require separate qualification.

## Build a fresh reader from an offline kit

Use the opt-in 0.16 [developer kit](../../../../docs/OFFLINE_DEVELOPER_KIT.md)
that contains this build script. Obtain the kit's outer SHA-256 separately
from a trusted maintainer. Run the script from the same reviewed project
revision as the kit. The script checks its own SHA-256 against the copy in
the kit, as well as the outer archive and its member checksums.

This procedure uses an already installed, trusted arm64 macOS 27 host, Python
3.15.2, Xcode 27.2 (27B52) and SDK 27.2. Use Autoconf 2.73 and Automake 1.19
in one local prefix. It uses the Apple Silicon Homebrew layout for GNU
libtool 2.6.2, m4 1.4.21, pkgconf 3.0.11 and libusb 1.0.30, and uses the
Xcode-selected GNU Make 3.81. The tool checks observe versions and verify
that the selected executables and build resources keep the same identity
through the run. Provision these tools before going offline.

Set `HOST_PYTHON` and `CHECKOUT_ROOT` to absolute paths. Set `KIT_TAR` and
`KIT_SHA256` to the tar and the trusted digest. Set `AUTOTOOLS_BIN` to the
canonical absolute bin directory of the Autoconf/Automake prefix. Set
`OUTPUT_DIR` to a new absolute path whose parent already exists. Use
canonical paths with no symlinked parent. If needed, add
`--developer-dir "$DEVELOPER_DIR"` with the canonical Xcode developer path.
The Python, Autotools and Xcode paths may contain ASCII letters, digits
and the characters `/`, `_`, `.`, `+`, `@` and `-`.

```sh
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/build_fresh_hidapi_candidate.py" \
  --kit "$KIT_TAR" --kit-sha256 "$KIT_SHA256" \
  --autotools-bin "$AUTOTOOLS_BIN" --output-dir "$OUTPUT_DIR"
```

For the optional first-IO diagnostic candidate, first prepare and retain the
[verified source stage](../first-io-v1/README.md), then add
`--first-io-source-stage "$FIRST_IO_SOURCE_STAGE"` to this command. Export a
new reviewed kit containing the updated builder and validator: the running
builder must still match its archived copy. The option authenticates all 207
stage files before tool setup, overlays only the three selected native files
after the ordinary 0.16 source gate, and records the selected source identity.
Keep the same stage for the matching runtime and follow the
[package pairing checks](../../../../docs/REAL_PREVIEW_PACKAGE.md).
Without this option, the existing 0.16 path and source map remain unchanged.

The script reconstructs the 190-file NUT checkpoint, applies CAL and stages
HIDAPI 0.15.0 to configure and build two headers and five archives. It checks
the source and generated HIDAPI configure probe for compile-and-link behavior.
Autoconf can run ordinary toolchain checks. The three make invocations are
limited to the version header, common archives and transport dummy archives.
The script checks the resulting headers, archive members and symbol indexes
and retains the original bytes. It then applies the write-cancellation patch
and the 0.16 version gate, verifies the two resulting source checkpoints,
and stages the eight 0.16 implementation and notice files. The link uses
the seven inputs just checked and rehashes them before and after linking.

On success, `PRODUCT` is an unsigned thin arm64 Mach-O with minimum macOS
27.0 and mode `0600`. `BUILD_RECEIPT.json` records
`COMPILED_STATIC_AUDIT_ONLY`, the product SHA-256, source and vendor identities,
effective toolchain, commands and static audit. The seven raw inputs are
under `generated/`, the link map and configure log under `audit/`, and the
original notices under `upstream-notices/`. The fresh hashes identify this
run. Configure embeds scratch paths in a header and Apple archives carry
member metadata, so fresh raw hashes may differ across runs. Packaging and
hardware qualification require their own evidence.

Each subprocess is bounded to 600 seconds and 1 MiB combined output. The
campaign checks a 20-minute limit, 2 GiB allocated scratch and a separate
4 MiB raw configure-log limit. A failed step produces a `HOLD` receipt and
keeps available bounded diagnostics. A normal run cleans its private
scratch. The script uses local files and tools and leaves the reader
unexecuted. Keep the output private if it contains local paths.

## Reconstruct the historical validation

The shell commands below document the historical candidate that reused the
seven E64 build inputs. A fresh build uses the preceding procedure and its
own receipt. Replay of this historical candidate requires the original
seven retained bytes.

## Inputs and source preparation

Use a private, disposable source tree. First follow the [native recipe](../README.md)
through sections 1–3, using the 0.15.0 input tree for the base configuration.
Follow the cancellation-boundary guide through its complete 190-file
comparison. An opt-in [developer kit](../../../../docs/OFFLINE_DEVELOPER_KIT.md)
supplies the eight files listed in [manifest.json](manifest.json) under
`native/hidapi-0.16/`. For separately obtained inputs, use the pinned commit.
Preserve their original
paths: `mac/hid.c` includes `../src/core/hidapi_input_ring.h`.
Do not use the legacy stager to overwrite the verified project source.

Set `HOST_PYTHON` to an absolute executable path. Set `CHECKOUT_ROOT`, `SRC`
and `HIDAPI_SOURCE_DIR` to canonical absolute directories with no symlinked
components. On macOS, use `/private/tmp` for a source scratch path rather
than the `/tmp` alias. `SRC` must be the verified post-cancellation source and
`HIDAPI_SOURCE_DIR` the supplied 0.16 upstream tree, not the 0.15 developer kit.
Run each shell block as a standalone command under the existing bounded
subprocess and log procedure. Keep the private trees exclusively owned by
this preparation and discard the scratch if a command fails after staging.
There is no network acquisition in this step.

```sh
(
set -eu
"$HOST_PYTHON" -I -S -B - "$SRC" "$CHECKOUT_ROOT" "$HIDAPI_SOURCE_DIR" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path, PurePosixPath

def directory(value, label):
    path = Path(value)
    if (not path.is_absolute() or '..' in path.parts or str(path) != str(value)
            or path.resolve() != path or not path.is_dir()):
        raise SystemExit('unsafe directory: ' + label)
    return path

def relative(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts or path.as_posix() != name:
        raise SystemExit('unsafe relative manifest path: ' + name)
    return path

def read(root, name, label):
    path = root / relative(name)
    if path.resolve() != path or not path.is_file():
        raise SystemExit(label + ': ' + name)
    return path.read_bytes()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

source = directory(sys.argv[1], 'SRC')
checkout = directory(sys.argv[2], 'CHECKOUT_ROOT')
incoming = directory(sys.argv[3], 'HIDAPI_SOURCE_DIR')
profile = directory(checkout / 'backend/nut/native-build/hidapi-0.16', 'profile')
drivers = directory(source / 'drivers', 'SRC/drivers')
manifest = json.loads(read(profile, 'manifest.json', 'wrong profile manifest'))
base_raw = read(profile.parent, 'production_source_post_write_cancel.json', 'wrong base manifest')
if sha(base_raw) != manifest['base_manifest_sha256']:
    raise SystemExit('wrong cancellation-boundary manifest')
base = json.loads(base_raw)['post_write_cancel_sha256']
post = manifest['post_hidapi_016_sha256']
if (len(base) != 190 or base.keys() != post.keys()
        or {n for n in base if base[n] != post[n]} != {'drivers/apcmicrolink-hidapi-native.c'}):
    raise SystemExit('wrong version-gate source inventory')
if any(sha(read(source, n, 'wrong source input')) != h for n, h in base.items()):
    raise SystemExit('wrong source checkpoint')
patch = 'version-gate.patch'
if sha(read(profile, patch, 'wrong patch input')) != manifest['gate_patch_sha256']:
    raise SystemExit('wrong version-gate patch')
vendor = drivers / 'hidapi-0.16.0'
if vendor.exists() or vendor.is_symlink():
    raise SystemExit('vendor destination already exists')
rows = manifest['hidapi']['files']
if len(rows) != 8 or len({row['path'] for row in rows}) != 8:
    raise SystemExit('wrong vendor file inventory')
verified = {}
for row in rows:
    name = row['path']
    data = read(incoming, name, 'wrong vendor input')
    if len(data) != row['bytes'] or sha(data) != row['sha256']:
        raise SystemExit('wrong vendor input: ' + name)
    verified[name] = data
vendor.mkdir()
for name, data in verified.items():
    target = vendor / relative(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
if any(sha(read(vendor, row['path'], 'wrong staged vendor input')) != row['sha256'] for row in rows):
    raise SystemExit('vendor copy changed')
subprocess.run(['/usr/bin/patch', '-f', '-F', '0', '-p1', '-d', str(source),
                '-i', str(profile / patch)], check=True)
if any(sha(read(source, n, 'wrong patched source input')) != h for n, h in post.items()):
    raise SystemExit('wrong HIDAPI 0.16 project source')
PY
)
```

The manifest separates 190 NUT source files, four vendor implementation files,
four vendor license texts, two generated headers and five static archives.
The seven generated-input hashes identify the reused E64 build inputs; this
profile's validation did not regenerate them. Use the base recipe for their provenance and verify every hash of the retained inputs before linking this recorded candidate.

## Compile without executing

Use the toolchain and generated inputs from the base recipe. The observed
build used Xcode 27.2 (27B52), SDK 27.2, ARM64, and minimum macOS 27.0.
Before linking, point `BUILD` at the canonical absolute build directory and
run this check on the same seven files the link command will use.

```sh
(
set -eu
"$HOST_PYTHON" -I -S -B - "$BUILD" "$CHECKOUT_ROOT" <<'PY'
import hashlib, json, sys
from pathlib import Path, PurePosixPath

build, checkout = map(Path, sys.argv[1:])
for path, raw in zip((build, checkout), sys.argv[1:], strict=True):
    if (not path.is_absolute() or '..' in path.parts or str(path) != raw
            or path.resolve() != path or not path.is_dir()):
        raise SystemExit('unsafe build or checkout directory')
profile = checkout / 'backend/nut/native-build/hidapi-0.16/manifest.json'
if profile.resolve() != profile or not profile.is_file():
    raise SystemExit('unsafe profile manifest')
rows = json.loads(profile.read_bytes())['reused_generated_input_sha256']
if (len(rows) != 7 or sum(name.endswith('.h') for name in rows) != 2
        or sum(name.endswith('.a') for name in rows) != 5):
    raise SystemExit('wrong generated input inventory')
for name, expected in rows.items():
    relative = PurePosixPath(name)
    if not relative.parts or relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
        raise SystemExit('unsafe generated input path: ' + name)
    path = build / relative
    if path.resolve() != path or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('wrong generated input: ' + name)
PY
)
```

Retain the original translation-unit and archive order. In its link command:

- Replace the single `hidapi-candidate` include with absolute paths
  `$SRC/drivers/hidapi-0.16.0/mac` and `$SRC/drivers/hidapi-0.16.0/hidapi`.
- Replace `$SRC/drivers/hidapi-candidate/hid.c` with
  `$SRC/drivers/hidapi-0.16.0/mac/hid.c`.
- Add `-arch arm64` and `-Wl,-no_adhoc_codesign`; keep minimum macOS 27.0,
  the existing feature macros, IOKit/CoreFoundation linking and mode `0600`.
- Pass absolute source/include/archive paths and keep
  `-ffile-prefix-map="$SCRATCH"=/usr/src/ups-monitor`, with `SRC=$SCRATCH/source`
  and `BUILD=$SCRATCH/build`. Relative source arguments leave a different
  `__FILE__` string in the product, even with the prefix-map option.

Retain the link map and static audits described in the base recipe. Do not
launch the product, including for `--help`, or run install targets. Update
the HIDAPI version/commit in any newly packaged native notice description;
do not relabel an older package or reuse its expected executable hash.

## Validation scope

On 2026-11-19 the native product compiled and passed its static ARM64 audit.
Headers from 0.15 were rejected at compile time. The upstream pure-memory
queue test passed 22 cases; a separate full-driver fake-HID replay preserved
all six cancellation/error outcomes of the earlier candidate. These tests
did not open an actual or virtual HID device.

An independent reconstruction from the private effective-source kit used in this validation
verified all three 190-file stages and compiled the reader with the seven
generated inputs. With absolute normalized paths, all nine on-disk sections
matched the original candidate; only the 16-byte Mach-O `LC_UUID` differed.
That is not byte-for-byte identity of the complete executable. The relative
path recipe also compiled but embedded a different source-name string.

This directory documents source preparation, static build and synthetic
validation. The optional developer kit carries the profile’s source inputs.
App packaging requires 0.16.0 native notices, producer and runtime pins, and
its own signing, installation and runtime qualification. NUT retains its
component licenses. HIDAPI's
BSD-style alternative is selected; preserve the four upstream license texts
and the selected BSD copyright, conditions, disclaimer and no-endorsement
clause. No dependency is relicensed under the application's MIT license.
