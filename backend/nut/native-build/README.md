# Native APC MicroLink build recipe

An optional [HIDAPI 0.16 profile](hidapi-0.16/README.md) follows the
cancellation-boundary candidate. It pins the new vendor layout and final
source map separately. The 0.15 recipe and recorded result below retain
their historical identities. The [developer kit](../../../docs/OFFLINE_DEVELOPER_KIT.md)
defaults to 0.15. Its optional 0.16 profile adds a separate upstream source
tree and retains 0.15 for sections 1–3. After section 3, apply the
cancellation-boundary patch and verify that source checkpoint, then follow
the 0.16 profile’s staging, pre-link and audit instructions.

An [optional cancellation-boundary candidate](WRITE_CANCEL_BOUNDARY.md) applies
after the post-CAL source checkpoint below. Its native/shared fake-HID comparison
is verified separately. The recorded product and build result in this recipe
remain the historical post-CAL baseline; installed previews are unchanged.

**Result: `COMPILED_STATIC_AUDIT_ONLY`.** The candidate product is ARM64, 403,760 bytes, mode `0600`, SHA-256 `5887ff6fab5b1e932d614790d7a374afdfad4cdd4162a7f34ba6b2152ca2d7de`; minimum macOS 27.0, built with SDK 27.2. All 12 recorded build/audit phases returned 0. There were two nonfatal compiler warnings. This is a static candidate only: the real driver was not launched; no USB/HID, UPS behavior, installation, signing, publication, or bit-for-bit reproducibility is qualified.

The [post-CAL manifest](production_source_post_cal.json) lists all 190 pre-CAL and post-CAL hashes, the two-file CAL delta, vendor pins, generated headers/archives, product result, and audit limits. The [CAL patch](nut-cal-status-freshness.patch) is applied once.

## 1. Reconstruct the 190-file source checkpoint

Use a private shell with the absolute paths `NUT_REPO`, `HIDAPI_REPO`, `CHECKOUT_ROOT`, `HOST_PYTHON` and `AUTOTOOLS_BIN` already set. The first two are local copies of [NUT](https://github.com/networkupstools/nut) and [HIDAPI](https://github.com/libusb/hidapi). Use a fresh scratch location without spaces (upstream autogen splits the Python command). Run the examples in order. As in the [source procedure](../../../docs/PRODUCTION_SOURCE_RECONSTRUCTION.md), use bounded subprocesses and logs; the shell snippets alone do not impose those limits. The observed build used 600 s and 1 MiB of output per phase, a 1-hour campaign deadline and a sampled 2 GiB scratch limit.

```sh
set -eu
umask 077
SCRATCH="$(mktemp -d "${UPS_WORK_PARENT:-/private/tmp}/ups-native-build.XXXXXXXX")"
SRC="$SCRATCH/source"
BUILD="$SCRATCH/build"
OUTPUT="$SCRATCH/reconstructed"
PRODUCT="$SCRATCH/apcmicrolink-hidapi-operational"
RECIPE="$CHECKOUT_ROOT/backend/nut/native-build"
NUT_TAR="$SCRATCH/upstream.tar"
PREFIX_UNUSED=/private/tmp/ups-monitor-prefix-unused
mkdir "$SRC" "$BUILD"
```

Use the full NUT Git archive at commit `73c4502191d025e35122463986a80c676e734b04`. A checkout is unnecessary; the archive command reads the existing repository.

With an offline developer kit, set `NUT_ARCHIVE_INPUT` to its unmodified
`native/nut.tar` and `HIDAPI_SOURCE_DIR` to its `native/hidapi` directory.
Those inputs replace the two local upstream repositories in sections 1 and 2.

```sh
if [ -n "${NUT_ARCHIVE_INPUT:-}" ]; then
  cp "$NUT_ARCHIVE_INPUT" "$NUT_TAR"
else
  git -C "$NUT_REPO" -c tar.umask=0002 archive --format=tar 73c4502191d025e35122463986a80c676e734b04 > "$NUT_TAR"
fi
printf '%s  %s\n' e3ea175565c461a9e741df77dd91103d695b9c60f8d423d9b6ce6c778f98615f "$NUT_TAR" | shasum -a 256 -c -
```

Require SHA-256 `e3ea175565c461a9e741df77dd91103d695b9c60f8d423d9b6ce6c778f98615f`. Run the public [source reconstruction CLI](../prepare_production_source.py) with its same-checkout inputs and the reviewed macOS Python 3.15.2 (`-I -S -B`, no optimization), choosing a new output directory:

```sh
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/prepare_production_source.py" \
  --backend-dir "$CHECKOUT_ROOT/backend/nut" \
  --nut-archive "$NUT_TAR" \
  --deadline-helper "$CHECKOUT_ROOT/backend/nut/process_deadline.py" \
  --output-dir "$OUTPUT"
```

Require exit 0 and `SOURCE_ONLY_PASS`. Extract the verified full archive in the empty source directory; the original contains six known relative locale symlinks. Overlay only the 190 files produced by the source CLI, checking their pre-CAL hashes before replacing the upstream files. Apply the CAL patch once, then check all 190 postimages.

```sh
tar -xf "$NUT_TAR" -C "$SRC"
"$HOST_PYTHON" -I -S -B - "$OUTPUT" "$SRC" "$RECIPE" <<'PY'
import hashlib, json, sys
from pathlib import Path
out, src, recipe = map(Path, sys.argv[1:])
receipt = json.loads((out / 'SOURCE_RECEIPT.json').read_bytes())
pre = json.loads((recipe.parent / 'production_source_post_e28.json').read_bytes())['source_sha256']
if receipt['state'] != 'SOURCE_ONLY_PASS' or receipt['source_sha256'] != pre or len(pre) != 190:
    raise SystemExit('wrong source checkpoint')
for name, expected in pre.items():
    source, target = out / 'source' / name, src / name
    if source.is_symlink() or target.is_symlink() or not target.resolve().is_relative_to(src.resolve()):
        raise SystemExit('redirected source: ' + name)
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('wrong preimage: ' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
PY
printf '%s  %s\n' 6bbd25a40c073e8ed86b5f59840f3dcd830df1b851731261c47b2e81b2b3775d "$RECIPE/nut-cal-status-freshness.patch" | shasum -a 256 -c -
/usr/bin/patch --batch --fuzz=0 -p1 --no-backup-if-mismatch -d "$SRC" -i "$RECIPE/nut-cal-status-freshness.patch"
"$HOST_PYTHON" -I -S -B - "$SRC" "$RECIPE" <<'PY'
import hashlib, json, sys
from pathlib import Path
src, recipe = map(Path, sys.argv[1:])
pins = json.loads((recipe / 'production_source_post_cal.json').read_bytes())['post_cal_sha256']
if len(pins) != 190 or any(hashlib.sha256((src / n).read_bytes()).hexdigest() != h for n, h in pins.items()):
    raise SystemExit('wrong post-CAL source tree')
PY
```

## 2. Stage HIDAPI 0.15.0

Stage only the three vendor files and four license texts. This step does not copy earlier versions of the seven project modules over the verified post-CAL tree.

```sh
VENDOR="$SRC/drivers/hidapi-candidate"
mkdir "$VENDOR" "$VENDOR/licenses"
for member in mac/hid.c hidapi/hidapi.h mac/hidapi_darwin.h; do
  if [ -n "${HIDAPI_SOURCE_DIR:-}" ]; then
    cp "$HIDAPI_SOURCE_DIR/$member" "$VENDOR/${member##*/}"
  else
    git -C "$HIDAPI_REPO" show "hidapi-0.15.0:$member" > "$VENDOR/${member##*/}"
  fi
done
for name in LICENSE.txt LICENSE-bsd.txt LICENSE-gpl3.txt LICENSE-orig.txt; do
  cp "$RECIPE/licenses/hidapi/$name" "$VENDOR/licenses/$name"
done
"$HOST_PYTHON" -I -S -B - "$VENDOR" "$RECIPE" <<'PY'
import hashlib, json, sys
from pathlib import Path
vendor, recipe = map(Path, sys.argv[1:])
pins = json.loads((recipe / 'production_source_post_cal.json').read_bytes())['hidapi']
files = {vendor / Path(n).name: h for n, h in pins['source_sha256'].items()}
files.update({vendor / 'licenses' / n: h for n, h in pins['license_sha256'].items()})
if len(files) != 7 or any(hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in files.items()):
    raise SystemExit('wrong HIDAPI source or notice')
PY
```

The candidate selects only HIDAPI's BSD-style option. Its exact text is in [`licenses/hidapi/LICENSE-bsd.txt`](licenses/hidapi/LICENSE-bsd.txt); retain copyright, conditions, disclaimer, and no-endorsement clause. The alternatives are present for the source-stage contract, not cumulative terms. Reuse the canonical [NUT attribution](../COPYING.NUT) and [GPL-2 text](../LICENSE-GPL2); do not duplicate them here. The complete NUT source archive also carries the project's original license files. These notes are provenance, not a complete distribution compliance determination.

## 3. Configure and produce the five archives

Pin the tool/resource closure. The observed toolchain was Autoconf 2.73, Automake 1.19, libtool 2.6.2, m4 1.4.21, pkgconf 3.0.10, libusb 1.0.30, Xcode 27.2 (27B52), SDK macOS 27.2. Deployment minimum is macOS 27.0. Select the build tools before bootstrap, configure or make. The following locations match the Apple Silicon Homebrew layout; point them at the same verified versions if installed elsewhere. The bootstrap uses the project's real generators, including its Python and Perl generators; bare `autoreconf` is insufficient on the Git archive.

The developer kit supplies the reader inputs. The build host supplies these six tools or libraries. To obtain their source separately, use the release archives below and compare each download with its SHA-256 before use. The GNU digests were checked against the published source bytes. The pkgconf and libusb digests are the asset digests recorded by their upstream releases. Installed tool versions are checked below.

| Source archive | SHA-256 |
|---|---|
| [autoconf-2.73.tar.xz](https://ftp.gnu.org/gnu/autoconf/autoconf-2.73.tar.xz) | `9fd672b1c8425fac2fa67fa0477b990987268b90ff36d5f016dae57be0d6b52e` |
| [automake-1.19.tar.xz](https://ftp.gnu.org/gnu/automake/automake-1.19.tar.xz) | `e3e2c2e3abf37898138db5b6c1d1dc35c9160c5978be7947d2c741705251d445` |
| [libtool-2.6.2.tar.xz](https://ftp.gnu.org/gnu/libtool/libtool-2.6.2.tar.xz) | `2ef1067c16c97db930fd740cc9bc3d3ba9a583804ae5ac42cc3e8719e49e191e` |
| [m4-1.4.21.tar.xz](https://ftp.gnu.org/gnu/m4/m4-1.4.21.tar.xz) | `f25c6ab51548a73a75558742fb031e0625d6485fe5f9155949d6486a2408ab66` |
| [pkgconf-3.0.10.tar.xz](https://github.com/pkgconf/pkgconf/releases/download/pkgconf-3.0.10/pkgconf-3.0.10.tar.xz) | `9371b2f6372da574d4c6dc96fe9b1463037bcf6afcb6671c1555afde7b17e2de` |
| [libusb-1.0.30.tar.bz2](https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2) | `fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf` |

```sh
BREW_PREFIX="${BREW_PREFIX:-/opt/homebrew}"
export DEVELOPER_DIR="${XCODE:-/Applications/Xcode.app/Contents/Developer}"
export SDKROOT="$DEVELOPER_DIR/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
CLANG="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
CLANGXX="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang++"
export MACOSX_DEPLOYMENT_TARGET=27.0 NUT_VERSION_PREFER_GIT=false LC_ALL=C
export PATH="$AUTOTOOLS_BIN:$BREW_PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export M4="$BREW_PREFIX/opt/m4/bin/m4" LIBTOOLIZE="$BREW_PREFIX/opt/libtool/bin/glibtoolize"
export PKG_CONFIG="$BREW_PREFIX/opt/pkgconf/bin/pkgconf"
export PKG_CONFIG_LIBDIR="$BREW_PREFIX/opt/libusb/lib/pkgconfig"
export ACLOCAL_PATH="$BREW_PREFIX/opt/pkgconf/share/aclocal:$BREW_PREFIX/opt/libtool/share/aclocal"
export PKG_CONFIG_PATH= PKG_CONFIG_SYSROOT_DIR=
export AUTOCONF="$AUTOTOOLS_BIN/autoconf" AUTOHEADER="$AUTOTOOLS_BIN/autoheader"
export AUTORECONF="$AUTOTOOLS_BIN/autoreconf" AUTOM4TE="$AUTOTOOLS_BIN/autom4te"
export AUTOMAKE="$AUTOTOOLS_BIN/automake" ACLOCAL="$AUTOTOOLS_BIN/aclocal"
"$HOST_PYTHON" -I -S -B - "$RECIPE/production_source_post_cal.json" <<'PY'
import json, os, platform, subprocess, sys
from pathlib import Path

if (sys.platform, platform.machine(), sys.version_info[:3]) != ("darwin", "arm64", (3, 15, 2)):
    sys.exit("Use the documented macOS arm64 host Python 3.15.2.")
from compression import zstd

pins = json.loads(Path(sys.argv[1]).read_bytes())["build"]["toolchain"]
env = os.environ
probes = (
    *[([env[tool.upper()], "--version"], f"{tool} (GNU Autoconf) " + pins["autoconf"])
      for tool in ("autoconf", "autoheader", "autoreconf", "autom4te")],
    *[([env[tool.upper()], "--version"], f"{tool} (GNU automake) " + pins["automake"])
      for tool in ("automake", "aclocal")],
    ([env["LIBTOOLIZE"], "--version"], Path(env["LIBTOOLIZE"]).name + " (GNU libtool) " + pins["libtool"]),
    ([env["M4"], "--version"], "m4 (GNU M4) " + pins["m4"]),
    ([env["PKG_CONFIG"], "--version"], pins["pkgconf"]),
    ([env["PKG_CONFIG"], "--modversion", "libusb-1.0"], pins["libusb"]),
    (["/usr/bin/xcrun", "--sdk", env["SDKROOT"], "--show-sdk-version"], pins["SDK"].removeprefix("macOS ")),
)

def probe(args):
    try:
        return subprocess.check_output(args, text=True, timeout=15).splitlines()
    except (OSError, subprocess.SubprocessError) as error:
        sys.exit(f"Could not query {args[0]}: {error}")

for args, expected in probes:
    lines = probe(args)
    if lines[:1] != [expected]:
        sys.exit(f"{' '.join(args)}: expected {expected!r}, got {lines[:1]!r}")

version, build = pins["Xcode"].removesuffix(")").split(" (")
if probe([str(Path(env["DEVELOPER_DIR"]) / "usr/bin/xcodebuild"), "-version"]) != [
    "Xcode " + version, "Build version " + build
]:
    sys.exit("Expected Xcode " + pins["Xcode"])
print("Native build host versions match the recorded toolchain.")
PY

( cd "$SRC" && PYTHON="$HOST_PYTHON -I -S -B" /bin/sh ./autogen.sh )
( cd "$BUILD" && CFLAGS="-O0 -g0 -ffile-prefix-map=$SCRATCH=/usr/src/ups-monitor" \
  "$SRC/configure" --prefix="$PREFIX_UNUSED" \
  --with-all=no --with-drivers=apcmicrolink --with-doc=no --with-ssl=no \
  --disable-inplace-runtime --disable-shared-private-libs \
  --with-usb=libusb-1.0 --with-apcmicrolink-hidapi=yes \
  "CC=$CLANG" "CXX=$CLANGXX" )
make -C "$BUILD/include" nut_version.h
make -C "$BUILD/common" V=1 libparseconf.la libcommon.la libcommonversion.la
make -C "$BUILD/drivers" V=1 libdummy_serial.la libdummy_upsdrvquery.la
```

This produced `config.h`, `nut_version.h`, `libparseconf.a`, `libcommon.a`, `libcommonversion.a`, `libdummy_serial.a`, and `libdummy_upsdrvquery.a`; their observed hashes are in the manifest.

## 4. Link the candidate

With the same toolchain and deployment target, link the 11 translation units and five archives. Keep the result non-executable until preparing a separately qualified runtime.

```sh
"$CLANG" --no-default-config -isysroot "$SDKROOT" -std=gnu99 -O0 -g0 \
  -ffile-prefix-map="$SCRATCH"=/usr/src/ups-monitor \
  -Wall -Wextra -Wno-unused-parameter \
  -DMLINK_HIDAPI_NATIVE_CANDIDATE=1 -DMLINK_HIDAPI_CONTINUOUS_CANDIDATE=1 \
  -DMLINK_CONTINUOUS_PACING_V2=1 -DMLINK_HIDAPI_OPERATIONAL_V2=1 \
  -I "$BUILD/include" -I "$SRC/include" -I "$SRC/drivers" \
  -I "$SRC/drivers/hidapi-candidate" \
  "$SRC/drivers/main.c" "$SRC/drivers/dstate.c" \
  "$SRC/drivers/apcmicrolink.c" "$SRC/drivers/apcmicrolink-maps.c" \
  "$SRC/drivers/apc_common.c" "$SRC/drivers/apcmicrolink-continuous.c" \
  "$SRC/drivers/apcmicrolink-hidapi-shared.c" \
  "$SRC/drivers/apcmicrolink-hid-descriptor-checked.c" \
  "$SRC/drivers/apcmicrolink-hidapi-native.c" \
  "$SRC/drivers/hidapi-candidate/hid.c" \
  "$SRC/drivers/apcmicrolink-operational-freshness.c" \
  "$BUILD/drivers/.libs/libdummy_serial.a" \
  "$BUILD/drivers/.libs/libdummy_upsdrvquery.a" \
  "$BUILD/common/.libs/libcommon.a" \
  "$BUILD/common/.libs/libcommonversion.a" \
  "$BUILD/common/.libs/libparseconf.a" \
  -framework IOKit -framework CoreFoundation -lm \
  -Wl,-map,"$SCRATCH/native.map" -o "$PRODUCT"
chmod 600 "$PRODUCT"
```

Do not run install targets or launch the product. The observed map had 11 TU objects and 8 members from four archives; `parseconf.o` was resolved inside `libcommon.a`. All five archives were passed.

## 5. Verify the static result

Run and retain `otool -L`, `otool -hv`, `otool -l`, full `nm`, and `strings -a` output. Observed: IOKit, CoreFoundation, and libSystem dependencies; ARM64 Mach-O executable; one macOS build-version record with min 27.0 and SDK 27.2. A full-symbol search for `replay`, `fake`, or `fixture` found no match. Do not infer absence of hardware/process/network imports: this real driver intentionally links IOKit. The tested home-path check passed, while a generic scratch configure-prefix string remained in the binary. Two compiler warnings were nonfatal.

The CAL offline campaign passed 10 synthetic groups (1,337 checks including fixture setup assertions). Descriptor parsing, real timeout/cancellation, transport, driver execution, UPS compatibility, and release are not qualified by these results.
