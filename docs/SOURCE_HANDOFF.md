# Prepare the E109 source handoff

This is the local, data-only preparation recipe for the frozen
`ups-monitor-e109-2026-11-20` profile. It creates the nine-file
`UPS-Monitor-E109-Source-Delivery` folder from two separately obtained,
unchanged source archives and the profile's frozen guide snapshots. Use
the `START_HERE.md` in the resulting folder for the recipient build
procedure. [Frozen profile](source-delivery/e109-2026-11-20/MANIFEST.json)

| Input archive | Size | SHA-256 |
| --- | ---: | --- |
| E106 `UPS-Monitor-E96-E98-App-Source.tar` | 2,078,720 bytes | `41f5a4081a2964c3e55b964e082a5601ee22fb9d7d8b4a8357e8fff7e0e3c506` |
| E104 `UPS-Monitor-E96-Native-Source.tar` | 40,273,920 bytes | `3995e50bc2f857104f756fc59e6cfb48b2c3dd82dd37627353c9820c8ad47ec5` |

Set `APP_SOURCE_TAR` and `NATIVE_SOURCE_TAR` to the absolute paths of
the two inputs. Their local filenames may differ from the table.
Set `PROFILE` to the frozen profile directory, either as an absolute
path or relative to the current directory. Set `OUTPUT_DIR` to a new
absolute path below an existing directory you own in mode 0700.
Run the following in the same shell on macOS.
The working set is about 42 MB plus the two original files already
present.

```sh
(
  set -eu
  umask 077
  : "${PROFILE:?Set the profile directory}"
  : "${APP_SOURCE_TAR:?Set the E106 app-source archive}"
  : "${NATIVE_SOURCE_TAR:?Set the E104 native-source archive}"
  : "${OUTPUT_DIR:?Set a new output directory}"

  fail() { printf '%s\n' "$1" >&2; exit 1; }
  case "$PROFILE" in /*) ;; *) PROFILE="$(pwd -P)/$PROFILE" ;; esac
  for required_path in "$APP_SOURCE_TAR" "$NATIVE_SOURCE_TAR" "$OUTPUT_DIR"; do
    case "$required_path" in /*) ;; *) fail 'Use absolute input and output paths.' ;; esac
  done

  verify_file() (
    verify_path="$1"
    verify_bytes="$2"
    verify_sha="$3"
    test -f "$verify_path" && test ! -L "$verify_path" || fail 'Expected a regular input file.'
    test "$(stat -f '%z' "$verify_path")" = "$verify_bytes" || fail 'Input size mismatch.'
    verify_sum="$(shasum -a 256 < "$verify_path")"
    test "${verify_sum%% *}" = "$verify_sha" || fail 'Input SHA-256 mismatch.'
  )
  profile_index="$PROFILE/SHA256SUMS"
  index_sha=a3181790de66659e5e3723e4c778fea57ba351178dcf542d6ef4da8a29101472
  verify_file "$profile_index" 763 "$index_sha"
  digest_for() { awk -v relative="$1" '$2 == relative { print $1 }' "$profile_index"; }
  verify_named() { verify_file "$1" "$2" "$(digest_for "$3")"; }

  app_name=UPS-Monitor-E96-E98-App-Source.tar
  native_name=UPS-Monitor-E96-Native-Source.tar
  verify_named "$APP_SOURCE_TAR" 2078720 "sources/$app_name"
  verify_named "$NATIVE_SOURCE_TAR" 40273920 "sources/$native_name"
  verify_named "$PROFILE/START_HERE.md" 12224 START_HERE.md
  verify_named "$PROFILE/guides/APP_SOURCE_DELIVERY.md" 22015 docs/APP_SOURCE_DELIVERY.md
  verify_named "$PROFILE/guides/NATIVE_SOURCE_DELIVERY.md" 7966 docs/NATIVE_SOURCE_DELIVERY.md
  verify_named "$PROFILE/guides/DISTRIBUTION_READINESS.md" 22171 docs/DISTRIBUTION_READINESS.md
  verify_named "$PROFILE/MANIFEST.json" 7104 MANIFEST.json

  if test -e "$OUTPUT_DIR" || test -L "$OUTPUT_DIR"; then
    fail 'Output path already exists.'
  fi
  output_parent="$(dirname "$OUTPUT_DIR")"
  test -d "$output_parent" && test ! -L "$output_parent" || fail 'Expected a real output parent.'
  test "$(stat -f '%u:%Lp' "$output_parent")" = "$(id -u):700" || fail 'Use a private output parent you own.'
  mkdir -m 700 "$OUTPUT_DIR"
  mkdir -m 755 "$OUTPUT_DIR/docs" "$OUTPUT_DIR/sources"

  install -m 644 "$APP_SOURCE_TAR" "$OUTPUT_DIR/sources/$app_name"
  install -m 644 "$NATIVE_SOURCE_TAR" "$OUTPUT_DIR/sources/$native_name"
  install -m 644 "$PROFILE/START_HERE.md" "$OUTPUT_DIR/START_HERE.md"
  install -m 644 "$PROFILE/guides/APP_SOURCE_DELIVERY.md" "$OUTPUT_DIR/docs/APP_SOURCE_DELIVERY.md"
  install -m 644 "$PROFILE/guides/NATIVE_SOURCE_DELIVERY.md" "$OUTPUT_DIR/docs/NATIVE_SOURCE_DELIVERY.md"
  install -m 644 "$PROFILE/guides/DISTRIBUTION_READINESS.md" "$OUTPUT_DIR/docs/DISTRIBUTION_READINESS.md"
  verify_named "$OUTPUT_DIR/sources/$app_name" 2078720 "sources/$app_name"
  tar -xOf "$OUTPUT_DIR/sources/$app_name" \
    ups-monitor-app-source/runtime-notes/CPYTHON_RUNTIME_CHANGES.reference.txt \
    > "$OUTPUT_DIR/docs/CPYTHON_RUNTIME_CHANGES.md"
  chmod 644 "$OUTPUT_DIR/docs/CPYTHON_RUNTIME_CHANGES.md"
  install -m 644 "$PROFILE/MANIFEST.json" "$OUTPUT_DIR/MANIFEST.json"
  verify_file "$profile_index" 763 "$index_sha"
  (cd "$OUTPUT_DIR" && shasum -a 256 -c "$profile_index")

  while read -r pin leaf; do
    staged_file="$OUTPUT_DIR/$leaf"
    test -f "$staged_file" && test ! -L "$staged_file" || fail 'Unexpected output type.'
    test "$(stat -f '%Lp' "$staged_file")" = 644 || fail 'Unexpected output mode.'
  done < "$profile_index"
  install -m 644 "$profile_index" "$OUTPUT_DIR/SHA256SUMS"
  verify_file "$OUTPUT_DIR/SHA256SUMS" 763 "$index_sha"
  test "$(stat -f '%Lp' "$OUTPUT_DIR/SHA256SUMS")" = 644
  test "$(stat -f '%Lp' "$OUTPUT_DIR")" = 700
  test "$(stat -f '%Lp' "$OUTPUT_DIR/docs")" = 755
  test "$(stat -f '%Lp' "$OUTPUT_DIR/sources")" = 755
  tree="$(cd "$OUTPUT_DIR" && LC_ALL=C find . ! -path . -print | LC_ALL=C sort)"
  test "$tree" = './MANIFEST.json
./SHA256SUMS
./START_HERE.md
./docs
./docs/APP_SOURCE_DELIVERY.md
./docs/CPYTHON_RUNTIME_CHANGES.md
./docs/DISTRIBUTION_READINESS.md
./docs/NATIVE_SOURCE_DELIVERY.md
./sources
./sources/UPS-Monitor-E96-E98-App-Source.tar
./sources/UPS-Monitor-E96-Native-Source.tar' || fail 'Output tree differs from the profile.'
  printf '%s  %s\n' "$index_sha" SHA256SUMS
)
```

A successful run prints the digest of the eight-row checksum index.
The directory contains nine regular files, totaling 42,434,840 bytes.
For an incomplete run, keep the output private and use a new directory
after diagnosing the failure. A recipient verifies the index against
its digest from the trusted delivery channel before following
`START_HERE.md`.

This profile preserves the E109 guide snapshots across later revisions
to the main documentation. Create a new named profile if the intended
archive or guide bytes change. The folder contains source and
instructions. Recipient tool provisioning, separate acquisition of
the pinned PBS asset and six wheels, local signing setup and optional
interop inputs are described in the recipient guide. Local composition
leaves compilation, testing, installation, runtime behavior, CI and
release authorization to their respective checks.
