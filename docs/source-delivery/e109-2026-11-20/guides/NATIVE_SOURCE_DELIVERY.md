# Source for the UPS Monitor E96 native reader

## Verified local candidate

| Artifact | Recorded value |
|---|---|
| Source archive | `UPS-Monitor-E96-Native-Source.tar` |
| Archive SHA-256 | `3995e50bc2f857104f756fc59e6cfb48b2c3dd82dd37627353c9820c8ad47ec5` |
| Archive size | 40,273,920 bytes |
| Restored 60-file `project.tar` SHA-256 | `e0d5349b465c5c7a16f2caf5670e24bbd44a5800752c7940c6d23f02e7f17188` |

The local verification restored the 60 locked recipe files and reproduced
all 190 pre-CAL source hashes using the public preparer. All 18 patch
commands completed. The E105 run then exported and verified the private
kit with 24 regular files and completed all 35 build phases from the restored subset
on the recorded arm64 macOS host. The four 190-file source checkpoints passed.

| E105 artifact | SHA-256 | Size |
|---|---|---|
| Private build kit | `e191fa9dd64bc3d450af8477272bc0ae519c41a74af42dc5cd33b02122e9c221` | 92,272,640 bytes |
| Unsigned reader `PRODUCT` | `bde33f43235d3199622bccb8bc627ca264b2999ca38c75b4c14d599247efedd2` | 400,968 bytes |

E105 retained the unsigned reader in mode 0600. Its separate
`BUILD_RECEIPT.json` has SHA-256
`450415be1fb7dad515ea43c770284d0b119580ebed3dc9bd86e088a2463a66d4`.
E109 kept that original and signed an executable copy ad hoc for a
local real app archive. The 402,048-byte signed copy has SHA-256
`3d75472b8c0868a40723fa0010884c4abae29226a3959523dde0381c95030428`.
Static comparison verified the section ranges and payload bytes. The
sealing differences were the added `LC_CODE_SIGNATURE`, adjusted
`__LINKEDIT` sizes and appended signature data and alignment padding.
The reader remained unexecuted in both runs. Independent installation and
distribution remain open. [App source delivery](APP_SOURCE_DELIVERY.md) · [Distribution readiness](DISTRIBUTION_READINESS.md)

This archive contains the effective NUT/HIDAPI source, upstream inputs
and the recipe used to prepare and build the native reader. The source
delivery includes modification notices dated 2026-11-20, the date of
delivery preparation. The archived `PROVENANCE.json` records the historical
relationship between the unsigned E95 reader and the reader signed inside
E96. For the E105 reader used in E109, use the separate E105 build receipt
and the E109 signing comparison above. The current guides are maintained
outside the immutable source archives.

| Path | Contents |
|---|---|
| `effective-reader-source/` | Full effective NUT tree with the final HIDAPI 0.16.0 source, interfaces, build files and upstream notices. There are 25 comment-only annotations. |
| `inputs/nut.tar`, `inputs/hidapi-0.15/`, `inputs/hidapi-0.16/` | Original NUT archive and both original vendor source sets. The 0.15 files are for bootstrap. The final link uses 0.16. |
| `recipe/` | 60 source files, scripts, manifests and instructions needed by the native build route. The 21 patches and nine overlays carry delivery comments. |
| `RECIPE_MANIFEST.json`, `ANNOTATED_EFFECTIVE_SOURCES.json` | Digest and exact byte range for each reversible notice. They identify both the archived files and the build inputs before annotation. |
| `SOURCE_CHECKPOINTS.json`, `notices/` | Historical build-input hashes and the original native notices from E96. |

Preserve the copyright and license notices with these materials. The
effective source and recipe distribution copies keep their original
copyright and license text intact. The archive excludes the historical
full project tar, PBS, wheel files, build products and logs.

## Restore the exact recipe

Set `SOURCE_ARCHIVE` to this archive and `SOURCE_SHA256` to its digest
obtained through a trusted channel. Set `INPUT_ROOT` and `RECIPE_ROOT`
to new absolute paths whose parents already exist. Use an existing
Python 3.15.2 interpreter as `HOST_PYTHON`. The restore utility reads
the authenticated tar as data and writes only the original 60 recipe
files and `project.tar` into `RECIPE_ROOT`.

```sh
set -eu
ROOT=UPS-Monitor-E96-Native-Source
printf '%s  %s\n' "$SOURCE_SHA256" "$SOURCE_ARCHIVE" | shasum -a 256 -c -
mkdir -m 700 "$INPUT_ROOT"
tar -xf "$SOURCE_ARCHIVE" -C "$INPUT_ROOT" "$ROOT/restore_recipe.py" "$ROOT/inputs"
INPUTS="$INPUT_ROOT/$ROOT/inputs"
"$HOST_PYTHON" -I -S -B "$INPUT_ROOT/$ROOT/restore_recipe.py" \
  --archive "$SOURCE_ARCHIVE" --sha256 "$SOURCE_SHA256" --output-dir "$RECIPE_ROOT"
PROJECT_SHA256="$(shasum -a 256 "$RECIPE_ROOT/project.tar" | cut -d ' ' -f 1)"
```

## Prepare a private build kit

Find the pinned PBS asset and wheels in
`recipe/backend/nut/bundled_python_runtime_inputs.json` and
`recipe/backend/nut/frozen_build_inputs.json` under `RECIPE_ROOT`.
Obtain those original files separately from their upstream providers
before going offline. Set `PBS_ARCHIVE` and `WHEELHOUSE` to these inputs,
and `KIT_TAR` to a new absolute output path. The public exporter verifies
their hashes. The kit is a local build input for the existing tooling.

```sh
"$HOST_PYTHON" -I -S -B "$RECIPE_ROOT/recipe/scripts/export_developer_kit.py" \
  --source "$RECIPE_ROOT/project.tar" --source-sha256 "$PROJECT_SHA256" \
  --nut-archive "$INPUTS/nut.tar" --hidapi-source "$INPUTS/hidapi-0.15" \
  --native-profile hidapi-0.16 --hidapi-016-source "$INPUTS/hidapi-0.16" \
  --pbs-archive "$PBS_ARCHIVE" --wheels "$WHEELHOUSE" --output "$KIT_TAR"
KIT_SHA256="$(shasum -a 256 "$KIT_TAR" | cut -d ' ' -f 1)"
```

The restored 60-file `project.tar` has a new digest, and so does a kit
made with it. Use the digests computed above. The original NUT, vendor,
patch, PBS and wheel digests remain the recipe inputs.

## Build the native reader

Follow the fresh build section of
`recipe/backend/nut/native-build/hidapi-0.16/README.md` under
`RECIPE_ROOT` for the pinned tool versions, environment, safe paths
and audit. It uses an Apple Silicon macOS 27 host, Xcode 27.2 (27B52),
the macOS 27.2 SDK and the indicated local Autotools, pkgconf and
libusb versions. Set `AUTOTOOLS_BIN` and `OUTPUT_DIR` as specified
there. Run the existing builder against the kit you just created.

```sh
"$HOST_PYTHON" -I -S -B "$RECIPE_ROOT/recipe/backend/nut/build_fresh_hidapi_candidate.py" \
  --kit "$KIT_TAR" --kit-sha256 "$KIT_SHA256" \
  --autotools-bin "$AUTOTOOLS_BIN" --output-dir "$OUTPUT_DIR"
```

The builder reconstructs the pre-CAL checkpoint, applies CAL and uses
HIDAPI 0.15 for bootstrap and generation of two headers and five
archives. It then applies the write-cancel and version-gate patches,
checks the final source and uses HIDAPI 0.16 for the link. The native
recipe ends at the unsigned `PRODUCT` with mode 0600 and a static
build receipt. The historical generated inputs and signed application
have their own identities.

For a later app build, the reader's bundle path is
`Contents/MacOS/apcmicrolink-hidapi-operational`. The app-side
workflow verifies the reader's digest before creating an executable
copy, keeps the eight native notices and binds the copy to the app
runtime manifest. E109 verified local assembly and signing with the
separate 207-file E106 app-source archive and the helper built from it
in E107. The native archive supplies the reader source and its build
recipe. [App packaging procedure](APP_SOURCE_DELIVERY.md)

## Restore utility tests

The original restore utility and its tests use the project's MIT license.
The byte-identical scripts are available under `scripts/`.
[Project license](../LICENSE) · [Restore utility](../scripts/restore_recipe.py) · [Tests](../scripts/test_restore_recipe.py)

Run the data-only fixtures locally from the repository root on macOS 27
with Python 3.15.2.

```sh
"$HOST_PYTHON" -I -S -B scripts/test_restore_recipe.py -v
```

The local run passed three unittest cases. They cover exact byte and mode
restoration, USTAR metadata, preserving an existing output directory,
and four rejection subcases covering altered bytes, path traversal,
duplicate members and a foreign symlink. The hosted CI workflow is
outside this evidence.
