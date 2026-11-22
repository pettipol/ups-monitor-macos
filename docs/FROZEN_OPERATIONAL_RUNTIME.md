# Frozen operational helper

The frozen profile packages the existing managed operational backend behind a small PyInstaller macOS helper. Its profile is `apc-smc1500i-operational-frozen-v1` (arm64, minimum macOS 27.0). The helper executable is at outer `Contents/Helpers/UPSOperationalHelper.app/Contents/MacOS/UPSOperationalHelper`; its Python runtime is contained inside that helper. The synthetic producer remains at outer `Contents/MacOS`.

The nine operational Python modules stay outside the helper's Python archive, under outer `Contents/Resources/ManagedOperationalRuntime`. The frozen manifest records their exact hashes but has no `backend.entrypoint` field. The helper admits the declared runtime closure (helper, external backend and native producer) before compiling the pinned module bytes and handing off to the existing adapter and `serve` lifecycle. Outer app code and resources are outside this closure and need their own signing and package verification. The default pins for both bundled and frozen profiles remain `nil`; only a reviewed derived source copy can receive a manifest pin.

## Build and candidate preparation

See the [public input and staging recipe](FROZEN_BUILD_RECIPE.md) for the complete
wheel lock, isolated helper build commands and copy-only candidate staging.
The recipe does not establish a new end-to-end build or hardware qualification.

The local helper was built with PBS CPython 3.15.2 and PyInstaller 6.22.3. Its generated BUNDLE contains two Mach-O files: `Contents/MacOS/UPSOperationalHelper` and `Contents/Frameworks/libpython3.15.dylib`. The upstream BUNDLE also produced two relative symlinks with mode `0755`: `Contents/Frameworks/base_library.zip` and `Contents/Resources/libpython3.15.dylib`. The public closure reader requires symlink mode `0777`. A separate candidate copy must therefore normalize exactly those link modes to `0777` before signature verification and manifest creation. The local copy changed no file bytes and passed helper signature verification after normalization. The finalizer does not change modes or signatures, and admission must not be weakened to accept the upstream mode.

The public assembly command is:

```sh
python3 backend/nut/assemble_frozen_operational_runtime.py \
  --runtime-contents "/path/to/approved-runtime/Contents" \
  --app-contents "/path/to/newly-built-app/Contents" \
  --manifest-sha256 "YOUR_64_CHARACTER_MANIFEST_SHA256"
```

Replace the example paths and manifest digest before running the command.

`--runtime-contents` and `--app-contents` must be distinct, non-overlapping real `Contents` directories. The app must already be built from the derived Swift source carrying the same manifest pin. The destination must not already contain the helper, backend, native producer, runtime control files, or `Resources/RuntimeNotices`; the command refuses to overwrite those paths. It validates and copies the admitted runtime closure, controls and the separately authenticated notice resources. It does not build, sign, execute, or establish that the app binary embeds the requested pin. The caller must verify the compiled pin and preserve the helper's nested signature.

The reproducible packaging order is:

1. Build the helper BUNDLE with the pinned PBS-based PyInstaller environment.
2. Stage the helper and already signed native producer into a new outer-app `Contents` copy; normalize the two helper symlink modes to `0777` without changing their targets or payload bytes.
3. Verify the nested helper signature on that normalized copy.
4. Run `prepare_bundled_operational_candidate.py --frozen` to add the nine allowlisted backend modules, `frozen-runtime-tree.json`, `frozen-runtime-bundle.json`, and a derived `FrozenOperationalReleasePins.swift` outside the app and source checkout.
5. Build the outer app and widget from that derived Swift source. Run the assembly command above to copy the admitted closure into the newly built app. Sign the outer app last, without deep signing; then verify the outer app with `codesign --verify --deep --strict` and revalidate the helper signature, manifest, inventory, native producer, and compiled Swift pin.

The finalizer's frozen mode emits nine module hashes and deliberately omits `backend.entrypoint`; the frozen entrypoint is compiled into the helper. It refuses pre-existing backend/control/pin files and does not normalize or sign its input. See [Bundled candidate packager](BUNDLED_CANDIDATE_PACKAGER.md) for its portable CLI.

## Retained notices

The assembly tool requires the versioned `third_party/frozen-runtime` resources:
23 original license texts, their scope guide, and a manifest pinned in the tool.
All contents are read and checked before the first runtime write. Missing,
altered or extra resources, a mismatched declared PBS input, or an occupied
destination are errors; there is no option to omit notices silently.

These resources go in outer `Contents/Resources/RuntimeNotices`, outside the
helper and the 25-entry runtime closure. Their separate hashes and the final
outer signature must be checked after copying. Adding them does not alter the
existing runtime manifest or imply that its consumer authenticates the notices.
The [resource guide](../third_party/frozen-runtime/README.md) and
[source manifest](../third_party/frozen-runtime/manifest.json) record the exact
versions and original archive members. This conservative set and successful copy
verification do not establish full license compliance or release readiness.

## Local verification status

The E49 helper build, helper signature verification, frozen candidate finalization, 32 Python offline test cases, and 26 Swift offline test cases passed. E49 also passed one synthetic host session through the built helper, with two updated samples followed by Stop, receipt validation, stream EOFs, child collection, and Quit without relaunch. This was a host/session check, not a launch of the main app or WidgetKit.

For E50, 468 frozen source files were checked and a local SharedRelease arm64 app/widget candidate was built with fixture mode enabled. The assembly suite passed 6 Python tests; the focused Swift suite passed 10 tests (8 XCTest and 2 Swift Testing). The admitted E49 helper closure was assembled into the candidate, the outer app was signed, and the final app signature verified. The final candidate inventory contains 47 app entries and 37,537,317 regular-file bytes. These are E50-specific counts and are not added to the E49 suite totals.

E50's candidate was **not launched**: no main app, helper, or fake producer was executed in E50. GUI/widget observation is `NOT_RUN_MAC_LOCKED`; no real UPS/USB, installation, hosted CI, notarization, clean-host, or Intel qualification was performed. The public bundled and frozen release pins remain `nil`. A restricted-context `codesign` read reported an untrusted certificate and invalid entitlement blob; normal-access signature and entitlement reads succeeded, with no signature or entitlement altered. This local synthetic candidate does not qualify release or hosted CI.

The full Python payload and PyInstaller bootloader carry third-party notice and license obligations that must be retained and reviewed before distribution. The existing license inventory records supplied metadata; it is not a legal redistribution determination.

No binary release, GUI or widget qualification, real UPS operation, notarization, clean-host installation, hosted CI, or Intel support is claimed. A local synthetic pass would not by itself qualify those paths or release readiness.
