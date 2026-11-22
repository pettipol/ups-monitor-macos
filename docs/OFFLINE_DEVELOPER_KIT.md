# Offline developer kit for UPS Monitor

This kit supplies the project and upstream inputs for the Apple Silicon
managed reader. Source preparation uses a trusted macOS host Python 3.15.2
with `compression.zstd` and the command-line tools used by the native recipe.
The default `hidapi-0.15` kit includes the original NUT source tar, three
HIDAPI 0.15.0 source files, a Python Build Standalone archive and the six
locked wheels. Its four HIDAPI license texts are in the project source tar.
The optional `hidapi-0.16` kit includes the same inputs and adds four upstream
source files and four license texts under `native/hidapi-0.16/`. The profile
locks, patch series, helper notices and build instructions are in the project
source tar. The Apple SDK and each developer’s signing configuration are
provided locally. After extracting the project in the steps below, open
`backend/nut/native-build/README.md` under `CHECKOUT_ROOT`. Section 3 lists the
six upstream tool archives and checks the selected versions before bootstrap.

## Use the kit

Obtain the outer tar's SHA-256 separately from a trusted maintainer. Set
`KIT_TAR` to its absolute path and `KIT_SHA256` to that digest. Use one shell
for the following steps. They create a fresh private workspace and read the
source without starting UPS Monitor or connecting to a device.

```sh
set -eu
: "${KIT_TAR:?set the absolute archive path}" "${KIT_SHA256:?set the trusted digest}"
printf '%s  %s\n' "$KIT_SHA256" "$KIT_TAR" | shasum -a 256 -c -
umask 077
WORK="$(mktemp -d "${UPS_WORK_PARENT:-/private/tmp}/ups-developer.XXXXXXXX")"
printf 'Developer workspace: %s\n' "$WORK"
umask 022
tar -xf "$KIT_TAR" -C "$WORK"
KIT="$WORK/UPS-Monitor-Developer-Inputs"
(cd "$KIT" && shasum -a 256 -c SHA256SUMS)
CHECKOUT_ROOT="$WORK/project"
mkdir "$CHECKOUT_ROOT"
tar -xf "$KIT/source/project.tar" -C "$CHECKOUT_ROOT" --strip-components 1
test -f "$CHECKOUT_ROOT/Package.swift"
NUT_ARCHIVE_INPUT="$KIT/native/nut.tar"
HIDAPI_SOURCE_DIR="$KIT/native/hidapi"
PBS_ARCHIVE="$KIT/python/cpython-3.15.2+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst"
WHEELHOUSE="$KIT/python/wheels"
export CHECKOUT_ROOT NUT_ARCHIVE_INPUT HIDAPI_SOURCE_DIR PBS_ARCHIVE WHEELHOUSE
```

1. Set `HOST_PYTHON` to the absolute path of your trusted host interpreter.
   For `hidapi-0.16`, go directly to step 3 to build the native reader.
   For `hidapi-0.15`, follow sections 1 and 2 of `backend/nut/native-build/README.md` in the
   extracted project. The two native input variables above let you skip
   upstream Git checkouts. At the end of section 2 the full source tree
   contains the 190 checked post-CAL files, three HIDAPI sources and four
   HIDAPI license texts. Preserve the private path printed above and the
   native recipe's workspace for the next steps.
2. To stage the Python payload as data before building the helper, run the
   command below. The interpreter used to run the stager is installed on
   the host. It does not execute the Python distribution inside the kit.
   Keep the resulting inventory for the build record.

```sh
"${HOST_PYTHON:?set the trusted host Python path}" -I -S -B \
  "$CHECKOUT_ROOT/backend/nut/stage_bundled_python_runtime.py" \
  --archive "$PBS_ARCHIVE" --destination "$WORK/python-payload" > "$WORK/python-staging.json"
```

3. For `hidapi-0.15`, continue with sections 3–5 of the base native recipe
   to configure, link and audit the reader. Keep
   `HIDAPI_SOURCE_DIR="$KIT/native/hidapi"` in that path.
   For `hidapi-0.16`, follow the
   [fresh build procedure](../backend/nut/native-build/hidapi-0.16/README.md#build-a-fresh-reader-from-an-offline-kit).
   The fresh build script takes the original kit tar and its trusted SHA-256.
   It reconstructs and configures a new NUT source tree, so the manual
   native source preparation in step 1 is optional for this profile.
   It builds and checks the two headers and five archives before linking
   and auditing the 0.16 reader. Keep the receipt, source identities and
   unexecuted product together.
4. Use `docs/FROZEN_BUILD_RECIPE.md` with `PBS_ARCHIVE` and `WHEELHOUSE`
   for the frozen helper in either profile. The historical app layout,
   signing and verification in `docs/REAL_PREVIEW_PACKAGE.md` use the
   0.15.0 native notice and producer pins. Use the guide's fresh 0.16
   instructions with the new reader's receipt and notices. That path
   derives a new runtime closure, manifest and matching Swift pin before
   signing and component verification.
   App assembly and qualification require their own review. For the historical
   0.15.0 Xcode workflow, initialize the extracted project’s local Git metadata
   as shown in `docs/SOURCE_RELEASE.md`. Use the documented time and output
   limits when running the build.

## Export a kit as a maintainer

Select the full reviewed commit and use that same revision of the exporter.
For the example below set `CHECKOUT_ROOT` to the project, `FULL_COMMIT` to
its full object ID and `EXPORT_DIR` to a new absolute path outside the
checkout. `NUT_REPO` is a local NUT repository containing the pinned commit.
`HIDAPI_SOURCE_DIR` holds the upstream hidapi-0.15.0 sources with their
original relative paths. Obtain `PBS_ARCHIVE` and the wheel files in
`WHEELHOUSE` using the URLs in the project's `backend/nut/bundled_python_runtime_inputs.json`
and `backend/nut/frozen_build_inputs.json`. The exporter reads these local
inputs, checks their pinned identities and creates a new tar.

```sh
set -eu
test "$(git -C "$CHECKOUT_ROOT" rev-parse --verify "$FULL_COMMIT^{commit}")" = "$FULL_COMMIT"
mkdir -m 700 "$EXPORT_DIR"
git -C "$CHECKOUT_ROOT" -c tar.umask=0022 archive --format=tar \
  --prefix=ups-monitor-source/ "$FULL_COMMIT" > "$EXPORT_DIR/project.tar"
git -C "$NUT_REPO" -c tar.umask=0002 archive --format=tar 73c4502191d025e35122463986a80c676e734b04 > "$EXPORT_DIR/nut.tar"
SOURCE_SHA256="$(shasum -a 256 "$EXPORT_DIR/project.tar" | cut -d ' ' -f 1)"
git -C "$CHECKOUT_ROOT" show "$FULL_COMMIT:scripts/export_developer_kit.py" > "$EXPORT_DIR/export_developer_kit.py"
"$HOST_PYTHON" -I -S -B "$EXPORT_DIR/export_developer_kit.py" \
  --source "$EXPORT_DIR/project.tar" --source-sha256 "$SOURCE_SHA256" \
  --nut-archive "$EXPORT_DIR/nut.tar" --hidapi-source "$HIDAPI_SOURCE_DIR" \
  --pbs-archive "$PBS_ARCHIVE" --wheels "$WHEELHOUSE" --output "$EXPORT_DIR/UPS-Monitor-Developer-Inputs.tar"
shasum -a 256 "$EXPORT_DIR/UPS-Monitor-Developer-Inputs.tar"
```

For the optional profile, use a reviewed project tar that includes the 0.16
profile, set `HIDAPI_016_SOURCE_DIR` to the tree from the pinned HIDAPI 0.16.0
commit and give the output a new path. Keep the 0.15.0 tree for the base build.

```sh
"$HOST_PYTHON" -I -S -B "$EXPORT_DIR/export_developer_kit.py" \
  --source "$EXPORT_DIR/project.tar" --source-sha256 "$SOURCE_SHA256" \
  --nut-archive "$EXPORT_DIR/nut.tar" --hidapi-source "$HIDAPI_SOURCE_DIR" \
  --native-profile hidapi-0.16 --hidapi-016-source "$HIDAPI_016_SOURCE_DIR" \
  --pbs-archive "$PBS_ARCHIVE" --wheels "$WHEELHOUSE" \
  --output "$EXPORT_DIR/UPS-Monitor-Developer-Inputs-HIDAPI-016.tar"
shasum -a 256 "$EXPORT_DIR/UPS-Monitor-Developer-Inputs-HIDAPI-016.tar"
```

Record the commit, source digest and kit digest. A private pre-commit preview
can use a separately reviewed, single-root source tar and its known digest.
Record it as a source snapshot. Check the third-party terms for the actual
artifacts before public redistribution. For a binary release, separately
verify installation, signing and the behavior of the installed widget on
the intended Mac.
