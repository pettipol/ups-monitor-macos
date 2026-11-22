# Build the local SMC1500I preview

This procedure assembles the real Apple Silicon preview from a source-built
producer and the frozen helper. Building, signing and inspecting the package
work with the UPS disconnected. The canonical Swift manifest pins stay nil.

For the recorded first-IO package, use the frozen
[E122 recipient addendum](source-delivery/e122-first-io-2026-11-21/START_HERE.md)
to pair the reviewed public checkout, source companion and runtime notes.
It distinguishes recipient-generated pins from the identities of the private
reference package; following it does not authorize a USB trial.

Choose the native source profile explicitly. `NATIVE_PROFILE=hidapi-0.15`
uses the historical recipe below. `NATIVE_PROFILE=hidapi-0.16` uses the
[fresh-build procedure](../backend/nut/native-build/hidapi-0.16/README.md)
and the profile-specific notice index. `NATIVE_PROFILE=first-io-v1` adds the
explicit [first-IO source stage](../backend/nut/native-build/first-io-v1/README.md)
to that fresh build and selects its matching nine qualified runtime modules.
All routes produce a new local
candidate; neither reproduces the identity or qualification of E89. In
particular, E89 used a separately reviewed runtime variant that requested
cancellation after 90 seconds. That variant is not implied by selecting a
native profile here. Record the exact helper and runtime sources, limits
and validation for any new candidate before a separate execution trial.

For `first-io-v1`, first prepare the source-only stage using that profile's
recipe. Set `FIRST_IO_SOURCE_STAGE` to its canonical absolute root containing
`source/`, `runtime/` and `SOURCE_RECEIPT.json`. Pass
`--first-io-source-stage "$FIRST_IO_SOURCE_STAGE"` to the fresh native builder
and the frozen stager below. Both tools authenticate the complete stage bytes;
the source receipt alone is insufficient. The native build still configures
and builds its own seven generated inputs, then applies only the three admitted
source replacements before the pinned link audit. The runtime selection includes
the existing 90-second cancellation request; it does not guarantee a kernel
deadline or establish hardware compatibility.

Export a new reviewed HIDAPI 0.16 developer kit containing the updated builder,
stage validator and profile files. The builder must match its own copy in the
kit; an older kit with a different runner is rejected. Keep the existing kit
format and source provenance. This option changes neither the canonical runtime
modules nor the historical build profiles.

1. Run the **Resolve and validate the installed Apple toolchain** preflight in
   [FROZEN_BUILD_RECIPE.md](FROZEN_BUILD_RECIPE.md). It exports the selected
   `DEVELOPER_DIR` before Xcode tools are used and defines `XCODEBUILD`, `CLANG`,
   `MACOS_SDK_PATH`, and `CODESIGN`. Set `XCODE="$DEVELOPER_DIR"` so the native
   recipe uses that same Xcode. For `hidapi-0.15`, complete sections 1–5 of the
   [native recipe](../backend/nut/native-build/README.md), leaving its final
   non-executable product at the recorded `PRODUCT` path. For `hidapi-0.16`,
   complete the fresh-build procedure and bind its successful receipt as
   described below. Do not run either product. Run the
   frozen helper build in the same shell, using its validated tool paths. Keep
   its `BUILD_ROOT`, `BUILD_ROOT/dist/UPSOperationalHelper.app`, and the native
   recipe's `PRODUCT` variables. During native recipe step 5, record the
   product SHA-256 alongside the passing static audit as
   `NATIVE_PRODUCT_SHA256` (for example, calculate it during that audit with
   `shasum -a 256 "$PRODUCT"`). Use the recorded audit value in Step 2; do not
   recalculate it at the copy/check step. Set `CHECKOUT_ROOT` and
   `HOST_PYTHON` to the extracted reviewed project root and trusted host Python
   3.15.2. Set
   `SIGNING_IDENTITY`, `DEVELOPMENT_TEAM`, and `UPS_APP_GROUP_ID` from local
   development configuration; keep signing data private. If resuming in a new
   shell, repeat the toolchain preflight and `run_build_tool` definition, then
   set `NATIVE_PRODUCT` to the verified native product's absolute path and
   `HELPER_APP` to the verified frozen helper. The example commands are not a
   deadline supervisor. Use the shipped helper as shown in the
   [bounded build phase](FROZEN_BUILD_RECIPE.md#run-a-bounded-build-phase)
   for the ordered build phases. Its deadline and 1 MiB output cap apply to
   captured streams, not direct file writes by tools.

   For either fresh route, set `FRESH_NATIVE_ROOT` to the canonical absolute
   output directory. Record `NATIVE_RECEIPT_SHA256` with the completed build
   and reviewed static-audit results, then supply that recorded value here.
   Keep this build directory exclusively owned and unmodified throughout
   packaging. The following check binds the existing receipt to the expected
   profile and extracts its recorded product digest; it does not independently
   attest the compiler, rerun the static audit or execute the product.
   The 2 MiB producer limit below is the bundled runtime's admission limit.

   ```sh
   set -eu
   : "${NATIVE_PROFILE:=hidapi-0.16}"
   : "${FRESH_NATIVE_ROOT:?set the reviewed fresh-build output directory}" \
     "${NATIVE_RECEIPT_SHA256:?supply the receipt digest recorded after the build audit}" \
     "${HOST_PYTHON:?set the trusted host Python 3.15.2}"
   NATIVE_PRODUCT_SHA256="$("$HOST_PYTHON" -I -S -B - \
     "$FRESH_NATIVE_ROOT" "$NATIVE_RECEIPT_SHA256" "$NATIVE_PROFILE" \
     "${FIRST_IO_SOURCE_STAGE:-}" "$CHECKOUT_ROOT" <<'PYTHON'
   import hashlib, importlib.util, json, os, re, stat, sys
   from pathlib import Path

   root, expected = Path(sys.argv[1]), sys.argv[2]
   if (not root.is_absolute() or str(root) != sys.argv[1]
           or '..' in root.parts or root.resolve() != root or not root.is_dir()
           or re.fullmatch(r'[0-9a-f]{64}', expected) is None):
       raise SystemExit('Invalid fresh-build root or recorded receipt digest')
   fd = os.open(root / 'BUILD_RECEIPT.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
   with os.fdopen(fd, 'rb') as stream:
       info = os.fstat(stream.fileno())
       if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4 * 1048576:
           raise SystemExit('Invalid fresh-build receipt file')
       raw = stream.read(4 * 1048576 + 1)
   if len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != expected:
       raise SystemExit('Fresh-build receipt changed')
   receipt = json.loads(raw)
   profile, stage_path, checkout = sys.argv[3], sys.argv[4], Path(sys.argv[5])
   if profile == 'first-io-v1':
       validator_path = checkout / 'backend/nut/first_io_source_stage.py'
       spec = importlib.util.spec_from_file_location('first_io_package_gate', validator_path)
       validator = importlib.util.module_from_spec(spec)
       sys.modules[spec.name] = validator
       spec.loader.exec_module(validator)
       selected = validator.validate_source_stage(Path(stage_path), validator_path.parent)
       if (receipt.get('first_io_source_stage') != selected.identity
               or receipt.get('source_checkpoints', {}).get('post_first_io') != selected.native_map):
           raise SystemExit('Native build does not match the selected first-IO stage')
   elif (profile != 'hidapi-0.16' or 'first_io_source_stage' in receipt
         or 'post_first_io' in receipt.get('source_checkpoints', {})):
       raise SystemExit('Wrong native profile for the fresh-build receipt')
   product = receipt.get('product', {})
   hidapi = receipt.get('hidapi', {})
   if (type(receipt.get('schema')) is not int or receipt['schema'] != 1
           or receipt.get('state') != 'COMPILED_STATIC_AUDIT_ONLY'
           or receipt.get('reader_execution') != 'NOT_RUN'
           or product.get('name') != 'PRODUCT' or product.get('mode') != '0600'
           or product.get('architecture') != 'arm64' or product.get('signature') != 'ABSENT'
           or type(product.get('bytes')) is not int or not 0 < product['bytes'] <= 2097152
           or re.fullmatch(r'[0-9a-f]{64}', str(product.get('sha256'))) is None
           or hidapi.get('tag') != 'hidapi-0.16.0'
           or hidapi.get('commit') != '750c87abb03282a237297052b84522e6bb3c0616'
           or receipt.get('nut', {}).get('revision') != '73c4502191d025e35122463986a80c676e734b04'):
       raise SystemExit('Fresh-build receipt does not match the required audited profile')
   print(product['sha256'])
   PYTHON
   )"
   PRODUCT="$FRESH_NATIVE_ROOT/PRODUCT"
   NATIVE_PRODUCT="$PRODUCT"
   ```

2. Start from the native recipe's existing verified product. The recipe leaves
   it at mode `0600`; verify its recorded digest and mode, copy it into the new
   private build root without replacing an existing file, and change the copy's
   mode to `0755` before signing. Preserve the original product unchanged.
   `BUILD_ROOT` is created by the frozen recipe below `/private/tmp` with mode
   `0700`.

   ```sh
   set -eu
   : "${BUILD_ROOT:?run the frozen recipe in this shell}" \
     "${CODESIGN:?validated codesign path from the frozen recipe}" \
     "${NATIVE_PRODUCT_SHA256:?digest recorded with the passing native static audit}"
   NATIVE_PRODUCT="${NATIVE_PRODUCT:-${PRODUCT:-}}"
   : "${NATIVE_PRODUCT:?set the absolute path to the verified native PRODUCT}"
   test -f "$NATIVE_PRODUCT"
   test ! -L "$NATIVE_PRODUCT"
   test "$(stat -f '%Lp' "$NATIVE_PRODUCT")" = 600
   printf '%s  %s\n' "$NATIVE_PRODUCT_SHA256" "$NATIVE_PRODUCT" | shasum -a 256 -c -
   mkdir "$BUILD_ROOT/native"
   NATIVE_PRODUCER="$BUILD_ROOT/native/apcmicrolink-hidapi-operational"
   test ! -e "$NATIVE_PRODUCER"
   cp -p "$NATIVE_PRODUCT" "$NATIVE_PRODUCER"
   chmod 0755 "$NATIVE_PRODUCER"
   printf '%s  %s\n' "$NATIVE_PRODUCT_SHA256" "$NATIVE_PRODUCER" | shasum -a 256 -c -
   "$CODESIGN" --force --sign - --timestamp=none \
     --identifier org.openupsmonitor.real-operational-producer "$NATIVE_PRODUCER"
   "$CODESIGN" --verify --strict --verbose=2 "$NATIVE_PRODUCER"
   NATIVE_SHA256="$(shasum -a 256 "$NATIVE_PRODUCER" | awk '{print $1}')"
   ```

   This is the real producer path: **skip the synthetic C fixture build** in the
   frozen guide. The real product uses `org.openupsmonitor.real-operational-producer`
   and the real app identifier below; synthetic packaging uses the fixture
   producer, an app identifier ending `.synthetic`, and
   `UPS_WIDGET_FIXTURE_MODE=YES`.

3. Stage the signed real producer with the helper built by the frozen recipe.
   The staging root is new and below the recipe's private `BUILD_ROOT`; it must
   not already exist. The stage command reports the manifest digest used for the
   source-copy pin.

   ```sh
   : "${HELPER_APP:=$BUILD_ROOT/dist/UPSOperationalHelper.app}"
   CANDIDATE_ROOT="$BUILD_ROOT/real-frozen-candidate"
   test -d "$HELPER_APP"
   test ! -e "$CANDIDATE_ROOT"
   set --
   if test "${NATIVE_PROFILE:-hidapi-0.15}" = first-io-v1; then
     : "${FIRST_IO_SOURCE_STAGE:?set the admitted first-IO source stage}"
     set -- --first-io-source-stage "$FIRST_IO_SOURCE_STAGE"
   fi
   "$HOST_PYTHON" -I -S -B \
     "$CHECKOUT_ROOT/backend/nut/stage_frozen_operational_runtime.py" \
     --helper-app "$HELPER_APP" --native-producer "$NATIVE_PRODUCER" \
     --native-sha256 "$NATIVE_SHA256" --output-root "$CANDIDATE_ROOT" "$@" \
     > "$BUILD_ROOT/real-stage-result.json"
   MANIFEST_SHA256="$("$HOST_PYTHON" -I -S -B -c \
     'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
     "$BUILD_ROOT/real-stage-result.json")"
   case "$MANIFEST_SHA256" in *[!0-9a-f]*|'') exit 1;; esac
   test "${#MANIFEST_SHA256}" -eq 64
   ```

   For `first-io-v1`, run this pairing check before step 4. It rebinds the
   recorded native build receipt, the selected source stage, the frozen-stage
   receipt and its actual manifest. The native product digest checked before
   signing in step 2 and the signed-copy digest remain distinct. Retain both.
   This check does not replace the static build audit or code-signature checks.

   ```sh
   if test "${NATIVE_PROFILE:-hidapi-0.15}" = first-io-v1; then
     "$HOST_PYTHON" -I -S -B - "$CHECKOUT_ROOT" "$FIRST_IO_SOURCE_STAGE" \
       "$FRESH_NATIVE_ROOT" "$NATIVE_RECEIPT_SHA256" "$CANDIDATE_ROOT" \
       "$NATIVE_SHA256" "$MANIFEST_SHA256" <<'PYTHON'
   import hashlib, importlib.util, json, os, re, stat, sys
   from pathlib import Path

   checkout, source, native, expected, candidate, signed_pin, manifest_pin = sys.argv[1:]
   path = Path(checkout) / 'backend/nut/first_io_source_stage.py'
   spec = importlib.util.spec_from_file_location('first_io_pairing_gate', path)
   validator = importlib.util.module_from_spec(spec)
   sys.modules[spec.name] = validator
   spec.loader.exec_module(validator)
   selected = validator.validate_source_stage(Path(source), path.parent)

   def control(path, pin=None):
       if pin is not None and re.fullmatch(r'[0-9a-f]{64}', pin) is None:
           raise SystemExit('Invalid recorded pairing digest')
       if not path.is_absolute() or path.resolve(strict=True) != path:
           raise SystemExit('Noncanonical pairing input')
       fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
       with os.fdopen(fd, 'rb') as stream:
           info = os.fstat(stream.fileno())
           if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4 * 1048576:
               raise SystemExit('Invalid pairing control file')
           raw = stream.read(4 * 1048576 + 1)
       if len(raw) != info.st_size or (pin is not None and hashlib.sha256(raw).hexdigest() != pin):
           raise SystemExit('Pairing input changed')
       return json.loads(raw)

   built = control(Path(native) / 'BUILD_RECEIPT.json', expected)
   staged = control(Path(candidate) / 'receipt.json')
   manifest = control(Path(candidate) / 'stage/Contents/Resources/ManagedOperationalRuntime/frozen-runtime-bundle.json', manifest_pin)
   if (built.get('state') != 'COMPILED_STATIC_AUDIT_ONLY'
           or built.get('first_io_source_stage') != selected.identity
           or built.get('source_checkpoints', {}).get('post_first_io') != selected.native_map
           or staged.get('state') != 'STAGED_FROZEN_NOT_EXECUTED'
           or staged.get('first_io_source_stage') != selected.identity
           or staged.get('module_sha256') != selected.runtime_map
           or staged.get('manifest_sha256') != manifest_pin
           or staged.get('native_sha256') != signed_pin
           or manifest.get('backend', {}).get('module_sha256') != selected.runtime_map
           or manifest.get('native', {}).get('sha256') != signed_pin):
       raise SystemExit('Native/runtime profile pairing mismatch')
   print('FIRST_IO_PAIRING_PASS')
   PYTHON
   fi
   ```

   Do not also apply the historical bounded-backend recipe to this stage.
   Its admitted runtime already contains that qualification patch and the
   two first-IO changes. Retain the original HIDAPI 0.16 notice files and the
   separate [first-IO notice](../backend/nut/native-build/first-io-v1/NOTICE.md).
   Review corresponding-source and modified-file notices before distribution.

4. Prepare a private source copy with the exact real identifier assigned to this
   preview. It must be a distinct reverse-DNS identifier ending in `.real` and
   must not begin with `org.openupsmonitor.mac.preview`. Do not reuse a synthetic
   identifier. The preparation command writes only to a new candidate directory
   below a private temporary parent.

   ```sh
   : "${REAL_BUNDLE_ID:?set the dedicated real reverse-DNS identifier ending in .real}"
   SOURCE_PARENT="$(mktemp -d "$UPS_WORK_PARENT/ups-real-source.XXXXXXXX")"
   SOURCE_ROOT="$SOURCE_PARENT/candidate"
   test ! -e "$SOURCE_ROOT"
   "$HOST_PYTHON" -I -S -B \
     "$CHECKOUT_ROOT/scripts/prepare_synthetic_source.py" \
     --checkout "$CHECKOUT_ROOT" --output-root "$SOURCE_ROOT" \
     --pin-file "$CANDIDATE_ROOT/derived/FrozenOperationalReleasePins.swift" \
     --manifest-sha256 "$MANIFEST_SHA256" --real-preview \
     --bundle-identifier "$REAL_BUNDLE_ID" \
     > "$SOURCE_PARENT/prepare-result.json"
   ```

   This CLI creates a source-only snapshot and receipt; it does not build or
   launch anything. Check `prepare-result.json` reports
   `SOURCE_PREPARED_NOT_BUILT` and the expected identifier and manifest digest.

5. Build the real app and widget from `"$SOURCE_ROOT/source"` using the
   `SharedRelease` configuration and `UPS_WIDGET_FIXTURE_MODE=NO` explicitly.
   Supply the existing local development identity, team, and dedicated App Group.
   `XCODEBUILD` and `DEVELOPER_DIR` must be the validated values from the frozen
   recipe's toolchain preflight; `run_build_tool` must pass that same
   `DEVELOPER_DIR`. The following command uses a new derived-data directory:

   ```sh
   : "${SIGNING_IDENTITY:?set the local development signing identity}" \
     "${DEVELOPMENT_TEAM:?set the local development team ID}" \
     "${UPS_APP_GROUP_ID:?set the dedicated App Group ID}"
   run_build_tool "$XCODEBUILD" -project "$SOURCE_ROOT/source/UPSMonitor.xcodeproj" \
     -scheme UPSMonitor -configuration SharedRelease \
     -destination platform=macOS,arch=arm64 \
     -derivedDataPath "$BUILD_ROOT/real-xcode" \
     -clonedSourcePackagesDirPath "$BUILD_ROOT/real-swiftpm" \
     -disableAutomaticPackageResolution -skipPackageUpdates -jobs 4 -quiet build \
     "CODE_SIGN_IDENTITY=$SIGNING_IDENTITY" \
     CODE_SIGN_STYLE=Manual "DEVELOPMENT_TEAM=$DEVELOPMENT_TEAM" \
     "UPS_APP_GROUP_ID=$UPS_APP_GROUP_ID" \
     UPS_WIDGET_FIXTURE_MODE=NO CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO
   APP="$BUILD_ROOT/real-xcode/Build/Products/SharedRelease/UPS Monitor.app"
   ```

   Before assembly, verify the app and widget executables, real app identifier,
   `.widget` extension suffix, fixture mode `NO` in both property lists, shared
   group entitlements, absence of debug entitlements, and compiled manifest pin.
   Record these checks separately; `xcodebuild` success is not their evidence.

6. Assemble the runtime using the same public assembler. Before the final outer
   signature, add the native notices for the selected profile. For the historical
   route, set `NUT_SRC` to the verified upstream NUT source root. The fresh
   route retains the seven upstream texts in `FRESH_NATIVE_ROOT/upstream-notices`
   before removing its build scratch. `APP` is the Xcode product
   path assigned in Step 5. The assembler writes these exact destinations under
   `$APP/Contents`; each must be absent before assembly:

   - `Helpers/UPSOperationalHelper.app`
   - `MacOS/apcmicrolink-hidapi-operational`
   - `Resources/ManagedOperationalRuntime` (including
     `frozen-runtime-bundle.json` and `frozen-runtime-tree.json`)
   - `Resources/RuntimeNotices`

   ```sh
   RECIPE="$CHECKOUT_ROOT/backend/nut/native-build"
   case "${NATIVE_PROFILE:-hidapi-0.15}" in
     hidapi-0.15)
       NUT_NOTICE_SOURCE="${NUT_SRC:-${SRC:-}}"
       : "${NUT_NOTICE_SOURCE:?set the verified NUT source tree from the native recipe}"
       HIDAPI_NOTICE_SOURCE="$RECIPE/licenses/hidapi"
       NATIVE_NOTICE_TEXT="$RECIPE/licenses/native-notices.txt"
       NATIVE_NOTICE_MANIFEST="$RECIPE/licenses/native-producer.sha256"
       ;;
     hidapi-0.16|first-io-v1)
       : "${FRESH_NATIVE_ROOT:?set the reviewed fresh-build output directory}"
       NUT_NOTICE_SOURCE="$FRESH_NATIVE_ROOT/upstream-notices/nut"
       HIDAPI_NOTICE_SOURCE="$FRESH_NATIVE_ROOT/upstream-notices/hidapi"
       NATIVE_NOTICE_TEXT="$RECIPE/hidapi-0.16/native-notices.txt"
       NATIVE_NOTICE_MANIFEST="$RECIPE/hidapi-0.16/native-producer.sha256"
       if test "${NATIVE_PROFILE:-hidapi-0.15}" = first-io-v1; then
         FIRST_IO_NOTICE_SOURCE="$RECIPE/first-io-v1/NOTICE.md"
         FIRST_IO_NOTICE_SHA256=2c9eed60624d6b5108766c090aa9d210be3689e6b63846f98c0f66fa457e0262
       fi
       ;;
     *) printf '%s\n' 'Unsupported native source profile' >&2; exit 1 ;;
   esac
   test -d "$APP"
   for path in \
     Helpers/UPSOperationalHelper.app \
     MacOS/apcmicrolink-hidapi-operational \
     Resources/ManagedOperationalRuntime \
     Resources/RuntimeNotices
   do
     test ! -e "$APP/Contents/$path"
   done
   if test "${NATIVE_PROFILE:-hidapi-0.15}" = first-io-v1; then
     test ! -e "$APP/Contents/Resources/FirstIOProfileNotices"
   fi
   "$HOST_PYTHON" -I -S -B \
     "$CHECKOUT_ROOT/backend/nut/assemble_frozen_operational_runtime.py" \
     --runtime-contents "$CANDIDATE_ROOT/stage/Contents" \
     --app-contents "$APP/Contents" --manifest-sha256 "$MANIFEST_SHA256" \
     > "$BUILD_ROOT/real-assemble-result.json"
   NOTICE_DIR="$APP/Contents/Resources/NativeProducerNotices"
   test ! -e "$NOTICE_DIR"
   mkdir "$NOTICE_DIR"
   for name in COPYING LICENSE-GPL2 LICENSE-GPL3; do
     cp "$NUT_NOTICE_SOURCE/$name" "$NOTICE_DIR/$name"
   done
   for name in LICENSE.txt LICENSE-bsd.txt LICENSE-orig.txt LICENSE-gpl3.txt; do
     cp "$HIDAPI_NOTICE_SOURCE/$name" "$NOTICE_DIR/$name"
   done
   cp "$NATIVE_NOTICE_TEXT" "$NOTICE_DIR/README.txt"
   if test "${NATIVE_PROFILE:-hidapi-0.15}" = first-io-v1; then
     FIRST_IO_NOTICE_DIR="$APP/Contents/Resources/FirstIOProfileNotices"
     mkdir "$FIRST_IO_NOTICE_DIR"
     cp "$FIRST_IO_NOTICE_SOURCE" "$FIRST_IO_NOTICE_DIR/NOTICE.md"
     chmod 0644 "$FIRST_IO_NOTICE_DIR/NOTICE.md"
     printf '%s  %s\n' "$FIRST_IO_NOTICE_SHA256" "$FIRST_IO_NOTICE_DIR/NOTICE.md" \
       | /usr/bin/shasum -a 256 -c -
     test "$(stat -f '%Lp' "$FIRST_IO_NOTICE_DIR/NOTICE.md")" = 644
   fi
   ```

7. Verify the eight regular files against `NATIVE_NOTICE_MANIFEST`, selected
   in Step 6: the [historical notice checksums](../backend/nut/native-build/licenses/native-producer.sha256)
   or the [0.16 notice checksums](../backend/nut/native-build/hidapi-0.16/native-producer.sha256).
   They cover the three NUT texts at the pinned revision, the four HIDAPI texts and the native README.
   Use a private build directory, with absolute paths for `APP`, `RECIPE` and `HOST_PYTHON`.
   For `first-io-v1`, the separate profile notice is copied to
   `Contents/Resources/FirstIOProfileNotices/NOTICE.md` and checked against the
   source notice pin. It is intentionally outside the eight-file native notice
   manifest and the 25-file runtime notice set. This extra file is checked
   before outer signing; repeat its hash and mode check after signing as part of
   the final app inventory.
   Keep the assembler's separate runtime notices. Its JSON receipt records the current helper
   executable and the historical executable used for the notice inventory. A different digest
   calls for inspection of this build's embedded modules, runtime hooks and libraries. A matching
   executable still leaves the separately packaged libraries and native producer to verify.
   Verify the closure and nine external module hashes.
   Then sign only the outer app last and verify the signatures; the helper,
   widget, and producer must already have valid nested signatures. Do not use
   `--deep` to sign.

   ```sh
   verify_native_notices() (
     set -eu
     test ! -L "$APP/Contents/Resources/NativeProducerNotices" || exit 1
     cd "$APP/Contents/Resources/NativeProducerNotices" || exit 1
     "$HOST_PYTHON" -I -S -B - "$NATIVE_NOTICE_MANIFEST" <<'PYTHON' || exit 1
   from pathlib import Path
   import stat
   import sys

   names = {row.split("  ", 1)[1] for row in Path(sys.argv[1]).read_text().splitlines()}
   members = list(Path(".").iterdir())
   if (len(names) != 8 or names != {path.name for path in members}
           or any(not stat.S_ISREG(path.lstat().st_mode) for path in members)):
       raise SystemExit("Unexpected native notice files")
   PYTHON
     /usr/bin/shasum -a 256 -c "$NATIVE_NOTICE_MANIFEST"
   )
   verify_native_notices || exit 1
   "$CODESIGN" --force --sign "$SIGNING_IDENTITY" --timestamp=none \
     --preserve-metadata=identifier,entitlements,requirements,flags "$APP"
   "$CODESIGN" --verify --deep --strict --verbose=2 "$APP"
   "$CODESIGN" --verify --strict --verbose=2 \
     "$APP/Contents/PlugIns/UPSMonitorWidget.appex"
   "$CODESIGN" --verify --strict --verbose=2 \
     "$APP/Contents/Helpers/UPSOperationalHelper.app"
   "$CODESIGN" --verify --strict --verbose=2 \
     "$APP/Contents/MacOS/apcmicrolink-hidapi-operational"
   verify_native_notices || exit 1
   if test "${NATIVE_PROFILE:-hidapi-0.15}" = first-io-v1; then
     test ! -L "$APP/Contents/Resources/FirstIOProfileNotices" || exit 1
     test ! -L "$APP/Contents/Resources/FirstIOProfileNotices/NOTICE.md" || exit 1
     printf '%s  %s\n' "$FIRST_IO_NOTICE_SHA256" \
       "$APP/Contents/Resources/FirstIOProfileNotices/NOTICE.md" \
       | /usr/bin/shasum -a 256 -c -
     test "$(stat -f '%Lp' "$APP/Contents/Resources/FirstIOProfileNotices/NOTICE.md")" = 644
   fi
   ```

   After outer signing, repeat closure, embedded-pin, helper/native and
   widget inventory checks; confirm nested helper, widget and producer bytes did
   not change. If creating an archive, verify it against the assembled tree.

In the E74 development archive, static inspection of the shipped helper found
157 modules in the embedded Python archive, the `pyi_rth_inspect` runtime hook,
and 152 entries in the separate standard-library ZIP. Eleven extension
initializers in the shipped libpython matched static-library declarations in
the pinned Python distribution metadata. The app contained the license texts
listed for those extensions, including the texts for OpenSSL, SQLite and zstd.
These observations apply to that archived build. Repeat the comparison on the
binary intended for distribution.

The local E65 build used a two-step change of identifier in its derived source
copy. The explicit preparation option above produces the two final build-input
changes directly. Opening the ordinary app selects the Apple source. The
experimental managed mode has a separate startup path and hardware admission.
The real widget is named **UPS Monitor** and uses the production snapshot
directory. Its simulated counterpart is **UPS Monitor Synthetic Test**.

The packaged helper and producer require arm64 and macOS 27 or later. An Intel
slice in the outer application does not qualify an Intel managed runtime.
Local development signing, component license notices, installation from a
download, USB behavior and daily operation each have separate acceptance
criteria. See the [release checklist](RELEASE_CHECKLIST.md).

## Working from an offline developer kit

Use the [offline developer kit guide](OFFLINE_DEVELOPER_KIT.md) to export a
reviewed project source archive, original NUT and HIDAPI sources, pinned Python
archive, wheels and notices in one file. The recipient can prepare these inputs
from the extracted kit. The native recipe reconstructs the driver and applies
the CAL patch once. Building and signing the app still requires the matching
local toolchain, signing configuration and App Group.

Earlier private kits with a `sources/NativeProducerSourceParcel-E65.tar.gz`
member use the instructions inside their own README. That parcel already
contains the patched sources.

Test installation separately on a second compatible Mac using the exact
intended download. Record the archive digest, macOS and CPU, the installed
app and widget versions, ordinary startup with system security settings intact,
and the real widget's visible state. If using the synthetic companion to check
refresh without an UPS, record that companion's identity and its own fixture
store. A real-device refresh and a normal Stop each need separate evidence.

### Bounded qualification build

The 2026-11-05 E66 development package reuses the E65 signed producer and
frozen helper. Its separately pinned backend changes one of the nine modules
to request cancellation after 90 seconds during capture. A synthetic
integration exercised explicit Stop. A second, accelerated fixture exercised
timeout cancellation. The built app uses the 90-second module. The archive
and stable local copy have matching contents and valid local signatures.
The E66 build has not undergone a real USB session. Waiting for operating
system I/O or process cleanup can exceed the cancellation deadline.

### Reproduce the bounded backend from source

For the bounded build only, use the following block in place of step 3's
staging command, before preparing the outer source copy. Keep using the signed
producer and verified helper prepared in steps 1 and 2. Set `HELPER_APP` to
that helper bundle, `NATIVE_PRODUCER` to that signed binary and `NATIVE_SHA256`
to its verified digest. Use absolute paths. The build and signing inputs
determine the output manifest digest.

```sh
set -eu
: "${CHECKOUT_ROOT:?}" "${HOST_PYTHON:?}" "${HELPER_APP:?}" "${NATIVE_PRODUCER:?}" "${NATIVE_SHA256:?}"
test "$(stat -f '%Lp' "$UPS_WORK_PARENT")" = 700
QUAL_ROOT="$(mktemp -d "$UPS_WORK_PARENT/ups-bounded-build.XXXXXXXX")"
TOOL_DIR="$QUAL_ROOT/tool-checkout/backend/nut"
CANDIDATE_ROOT="$QUAL_ROOT/stage"
NUT_DIR="$CHECKOUT_ROOT/backend/nut"
QUAL_FILES="$NUT_DIR/qualification"
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

PRE=d89e56de325acd325f29a12596c50f4466e10521d6924e8bec868a1204f07ac3
PATCH_SHA=75e7a32a7032f07af8f97c78520389fa011320e26780da9066c237662892b1a9
printf '%s  %s\n' "$PRE" "$TOOL_DIR/managed_operational_entrypoint.py" | shasum -a 256 -c -
printf '%s  %s\n' "$PATCH_SHA" "$QUAL_FILES/smc1500i-90s.patch" | shasum -a 256 -c -
/usr/bin/patch --batch --forward --fuzz=0 -p1 -d "$TOOL_DIR" -i "$QUAL_FILES/smc1500i-90s.patch"
"$HOST_PYTHON" -I -S -B - "$QUAL_FILES/module-sha256.json" "$TOOL_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
pins = json.loads(Path(sys.argv[1]).read_bytes())
root = Path(sys.argv[2])
if len(pins) != 9 or any(hashlib.sha256((root / name).read_bytes()).hexdigest() != pin
                         for name, pin in pins.items()):
    raise SystemExit("qualification backend hash mismatch")
PY
"$HOST_PYTHON" -I -S -B "$TOOL_DIR/stage_frozen_operational_runtime.py" \
  --helper-app "$HELPER_APP" --native-producer "$NATIVE_PRODUCER" \
  --native-sha256 "$NATIVE_SHA256" --output-root "$CANDIDATE_ROOT"
MANIFEST_SHA256="$("$HOST_PYTHON" -I -S -B -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$CANDIDATE_ROOT/receipt.json")"
case "$MANIFEST_SHA256" in *[!0-9a-f]*|'') exit 1;; esac
test "${#MANIFEST_SHA256}" -eq 64
```

Keep `QUAL_ROOT`, `CANDIDATE_ROOT` and `MANIFEST_SHA256` in the same build phase
as step 4, or restore and verify those values from the retained receipts.
The qualification and source directories are created under the private
`UPS_WORK_PARENT` from the frozen build guide.

Use the new stage receipt and generated Swift pin for the remaining source
preparation, build, notice and signature steps. The upstream helper build
tools and the separate [native source recipe](../backend/nut/native-build/README.md)
are required to rebuild those components. The ordinary checkout keeps its
original entrypoint and disabled Swift pin. This source preparation runs no
app, widget or driver.

## Archive the verified app

Start with the **UPS Monitor.app** that passed the signature checks above. Keep
the bundle unchanged during packaging. Set `APP` to its absolute path,
`HOST_PYTHON` to the Python 3.15.2 executable, and `OUTPUT_DIR` to a new
directory under a private parent you own (mode 0700).

```sh
set -eu
: "${APP:?set the absolute path to the verified UPS Monitor.app}"
: "${OUTPUT_DIR:?set a new directory under your private build folder}"
: "${HOST_PYTHON:?set the trusted Python 3.15.2 executable}"
umask 077
"$HOST_PYTHON" -I -S -B - "$APP" "$OUTPUT_DIR" <<'PYTHON'
import gzip
import os
from pathlib import Path
import stat
import sys
import tarfile

app, dest = map(Path, sys.argv[1:])
if sys.version_info[:3] != (3, 15, 2):
    raise SystemExit("Expected Python 3.15.2")
if (app.resolve(strict=True) != app or app.name != "UPS Monitor.app"
        or not (app / "Contents/MacOS/UPS Monitor").is_file()):
    raise SystemExit("Expected the canonical path to the verified app")
parent = dest.parent
if (parent.resolve(strict=True) != parent or not parent.is_dir()
        or parent.stat().st_uid != os.getuid() or stat.S_IMODE(parent.stat().st_mode) != 0o700
        or dest.name in ("", ".", "..") or dest == app or app in dest.parents):
    raise SystemExit("Choose a new directory under a private parent outside the app")
dest.mkdir(mode=0o700, exist_ok=False)
archive = dest / "UPS-Monitor.app.tar.gz"
partial = dest / ".archive.partial"

def stop_on_walk_error(error):
    raise error

keys = ["."]
for directory, dirs, files in os.walk(app, onerror=stop_on_walk_error, followlinks=False):
    for name in dirs + files:
        keys.append((Path(directory) / name).relative_to(app).as_posix())

with partial.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                                              mtime=0, compresslevel=6) as gz:
    with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for key in sorted(keys):
            path = app / key
            name = app.name if key == "." else f"{app.name}/{key}"
            item = tar.gettarinfo(str(path), arcname=name)
            if item.issym():
                if Path(item.linkname).is_absolute() or not path.resolve(strict=True).is_relative_to(app):
                    raise ValueError(f"External or broken bundle link: {key}")
            elif not (item.isfile() or item.isdir()):
                raise ValueError(f"Unsupported bundle member: {key}")
            item.uid = item.gid = item.mtime = 0
            item.uname = item.gname = ""
            if item.isfile():
                with path.open("rb") as stream:
                    tar.addfile(item, stream)
            else:
                tar.addfile(item)

os.link(partial, archive)
partial.unlink()
print(archive)
PYTHON
shasum -a 256 "$OUTPUT_DIR/UPS-Monitor.app.tar.gz"
```

Record the SHA-256 and follow the extraction and signature checks below. The
E84 check reproduced the archived bytes from the same signed bundle on the
same Mac. Rebuilding or signing again can change the bundle bytes.

## Verify and inspect a locally staged archive

The E80 app archive contains the E74 bundle with updated E79 notice resources
and a new outer signature. The E79 developer kit supplies the source and inputs
separately. The separate E66 candidate opened and quit before acquisition
started in H12. See [compatibility](COMPATIBILITY.md) for hardware evidence.

Use a private, local copy of the archive from a maintainer you trust and keep it
unchanged throughout verification. Obtain the expected SHA-256 independently.
The following commands check the hash, extract the bundle into a new private
temporary directory and verify the four signatures without launching the app.

```sh
set -eu
umask 077
: "${ARCHIVE:?set the path to a trusted maintainer .tar.gz archive}"
: "${EXPECTED_SHA256:?set the independently obtained trusted SHA-256}"
case "$EXPECTED_SHA256" in
  *[!0-9a-f]*|'') echo "EXPECTED_SHA256 must be 64 lowercase hex characters" >&2; exit 1;;
esac
test "${#EXPECTED_SHA256}" -eq 64
ACTUAL="$(/usr/bin/shasum -a 256 < "$ARCHIVE")"
test "${ACTUAL%% *}" = "$EXPECTED_SHA256"
TMP_ROOT="${TMPDIR:-/private/tmp}"
case "$TMP_ROOT" in /*) ;; *) echo "TMPDIR must be an absolute path" >&2; exit 1;; esac
STAGE_ROOT="$(mktemp -d "${TMP_ROOT%/}/ups-preview-restore.XXXXXXXX")"
chmod 0700 "$STAGE_ROOT"
test "$(stat -f '%Lp' "$STAGE_ROOT")" = 700
/usr/bin/tar -xzpf "$ARCHIVE" -C "$STAGE_ROOT"
APP="$STAGE_ROOT/UPS Monitor.app"
test -d "$APP"
test ! -L "$APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
/usr/bin/codesign --verify --strict --verbose=2 \
  "$APP/Contents/PlugIns/UPSMonitorWidget.appex"
/usr/bin/codesign --verify --strict --verbose=2 \
  "$APP/Contents/Helpers/UPSOperationalHelper.app"
/usr/bin/codesign --verify --strict --verbose=2 \
  "$APP/Contents/MacOS/apcmicrolink-hidapi-operational"
printf 'Verified app: %s\n' "$APP"
```

A hash mismatch exits before the private staging directory is created. Keep the
extracted copy private. Preserve file modes with `-p`. During verification of
E80, plain `tar -xzf` with `umask 022` changed the modes of two symbolic links,
and the static admission check returned `file_mode`. With `tar -xzpf`, file
contents, modes and link targets matched, and the same static check passed.
Finder extraction, app launch, Gatekeeper assessment after download and use on
another Mac require separate validation.
