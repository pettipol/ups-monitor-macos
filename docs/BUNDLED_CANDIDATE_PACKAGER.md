# Bundled operational candidate packager

`prepare_bundled_operational_candidate.py` consumes a maintainer-created
staging `Contents` tree and the expected SHA-256 of the native producer. In the
bundled profile, the maintainer signs the nested Python runtime and producer;
in frozen mode, the maintainer signs the nested helper and producer. The
utility does not verify those signatures. The outer app is still unsigned. The
Swift pin must be a new file outside both `Contents` and the source checkout.
The utility refuses an existing managed backend, either control file, or pin
output. Default mode copies the ten backend modules admitted by the bundled
consumer and emits `runtime-tree.json` and `runtime-bundle.json`. Frozen mode
copies the nine allowlisted operational modules and emits
`frozen-runtime-tree.json` and `frozen-runtime-bundle.json`; its manifest has
no `backend.entrypoint` field because the frozen entrypoint is inside the
helper. Both modes validate the resulting closure with the public reader and
write a profile-specific pin to the explicit derived source location.

Example invocation. Set the variables to canonical absolute paths. The staging
`Contents` is prepared separately; the Swift output is a new derived source
file outside both that `Contents` and the checkout source:

```sh
python3 -I -S -B "${CHECKOUT_ROOT}/backend/nut/prepare_bundled_operational_candidate.py" \
  --contents "${STAGING_ROOT}/Contents" \
  --swift-output "${DERIVED_SOURCE_ROOT}/Sources/UPSRuntime/BundledOperationalReleasePins.swift" \
  --native-sha256 "$EXPECTED_NATIVE_SHA256"
```

The utility does not copy or change the Python runtime or native producer. It
does not sign or verify signatures, run Python or the producer, build or install
the app, or change the canonical release pin, which remains `nil`. The input
staging tree must already be normalized and its nested runtime and native code
must have their required signatures. Those signatures are prerequisites, not
results verified by this utility. An outer app signature and whole-app update
remain later packaging steps; the full runtime under `Resources` remains a
documented packaging exception.

The synthetic unit tests use small inert files. They validate deterministic
control output, native identity binding, backend closure, link rejection, and
refusal to overwrite. They do not qualify signing, the assembled app, a widget,
runtime execution, or hardware.

## Frozen-helper mode

Frozen mode requires a new candidate `Contents` with the signed helper at
`Helpers/UPSOperationalHelper.app`, the synthetic or approved native producer
at `MacOS`, and the `Resources` directory. Before invoking the finalizer, make
a separate candidate copy of the PyInstaller BUNDLE and set its two relative
symlink modes to the consumer's required `0777`: `Contents/Frameworks/base_library.zip`
and `Contents/Resources/libpython3.15.dylib`. Their targets and all file bytes
must stay unchanged. Verify the helper signature after this normalization;
the finalizer neither changes link modes nor signs or verifies the helper.

The profile-specific invocation uses the same closed options with `--frozen`:

```sh
python3 -I -S -B "${CHECKOUT_ROOT}/backend/nut/prepare_bundled_operational_candidate.py" \
  --frozen \
  --contents "${STAGING_ROOT}/Contents" \
  --swift-output "${DERIVED_SOURCE_ROOT}/Sources/UPSRuntime/FrozenOperationalReleasePins.swift" \
  --native-sha256 "$EXPECTED_NATIVE_SHA256"
```

The derived pin is for `FrozenOperationalReleasePins` only. Neither public
release pin is changed by this operation; both remain `nil` in the canonical
checkout. The finalizer's output is a local candidate, not a signed outer app
or release package.

## Local check with the complete payload

On 2026-10-29 the public utility also prepared one separate staging copy of
the complete CPython payload and a synthetic producer, using the existing
post-signing bytes. The generated inventory and manifest were byte-identical
to the previously checked package. The generated Swift pin had the same body
and manifest digest; only its explanatory header differed. The public
consumer accepted the closure with `check_process=False`.

The source files, original package, copied runtime and producer were checked
for unchanged bytes. This was a file-only preparation check, not a new
signature verification, build, payload execution, app/widget test or hardware
test. It does not qualify the runtime layout, distribution or notarization.
The public unit suite remains the reproducible small-fixture contract check;
the complete-payload result is separate local evidence.

## Frozen-helper verification status

The local PBS CPython 3.15.2 / PyInstaller 6.22.3 helper build, nested helper
signature checks, and frozen finalizer invocation passed. The helper contains
two Mach-O files, in `Contents/MacOS` and `Contents/Frameworks`. The upstream
BUNDLE emitted two relative symlinks at mode `0755`; the candidate copy changed
only those modes to the required `0777`, preserved targets and file bytes, and
passed the later signature verification. The frozen finalizer accepted the
normalized helper and wrote the derived pin without changing runtime or native
bytes.

Current local offline verification records 32 Python test cases and 26 Swift
test cases passing. One separate integrated synthetic helper session passed:
two samples reached the real AppModel, followed by Stop, receipt/EOF/child
cleanup, Quit and no relaunch. The outer container was a host fixture, with
no GUI executable; its native producer was synthetic. No claim is made for a binary
release, GUI/widget behavior, a real UPS, notarization, or a clean hosted CI
run. Full-runtime placement inside the helper and its PyInstaller bootloader
remain a platform and third-party-notice review item before distribution.
