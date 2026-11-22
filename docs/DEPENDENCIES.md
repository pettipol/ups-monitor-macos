# Dependency Baseline

CI input refresh: 2026-11-19. `actions/setup-python` v7.1.0 is pinned at
`6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` after checking the official tag,
release and action inputs. `actions/checkout` remains v7.0.1. The hosted image
inventory now lists Xcode 27.2 build 27B52; remote execution on the current
source remains unverified. See [CI review](CI.md#current-source-review-2026-11-19).
This refresh changes a CI build input, not the app's bundled Python runtime.

Toolchain refresh: 2026-11-04. Stable tools are preferred; exact revisions are
frozen for each qualification run. This list does not claim hardware
compatibility. Other component observations retain their recorded dates; the
table does not claim a fully qualified current baseline.

## Python Runtime Packaging Input: 2026-10-28

### Frozen candidate update: 2026-10-29

The separate [frozen helper profile](FROZEN_OPERATIONAL_RUNTIME.md) now packages
the pinned PBS CPython 3.15.2 input with PyInstaller 6.22.3. One local helper
session and the subsequent full app/widget packaging were qualified separately;
they are not installation or hardware qualification. The legacy host-local
profile described below remains distinct.

The observed build environment also used pyinstaller-hooks-contrib 2026.9,
altgraph 0.17.5, macholib 1.16.4, packaging 26.3 and setuptools 84.2.1.
All six wheel filenames, byte counts, URLs and SHA-256 values are now recorded
in the [public build input lock](../backend/nut/frozen_build_inputs.json), with
[hash-locked pip requirements](../backend/nut/frozen_build_requirements.txt) and
a [helper build/staging recipe](FROZEN_BUILD_RECIPE.md).
Its output tables identify the PyInstaller bootloader/loader and
`pyi_rth_inspect` runtime hook; the other listed packages are build inputs, not
automatically embedded app dependencies. Exact wheel identities for PyInstaller
and hooks-contrib, PBS archive/metadata hashes and retained license-file hashes
are recorded in the [notice manifest](../third_party/frozen-runtime/manifest.json).

The public assembler includes the [retained notices](../third_party/frozen-runtime/README.md)
outside the helper's runtime closure and requires outer signing afterwards.
This is a mechanical packaging check, not a complete distribution-compliance
audit. The current candidate remains synthetic, arm64/macOS 27+, with public
runtime pins disabled and hosted CI/release qualification still open.

### Initial packaging input

The experimental managed operational backend requires a Python interpreter,
in addition to the interpreter used by offline tests. Its current schema pins
an absolute host-local executable path and does not package its standard
library or dynamic dependencies. See [managed runtime](MANAGED_OPERATIONAL_RUNTIME.md).

The new [bundled Python stager](BUNDLED_PYTHON_RUNTIME.md) prepares a separate
payload from the official
[python-build-standalone 20261026 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026).
It pins CPython 3.15.2, aarch64-apple-darwin, pgo+lto, full archive SHA-256
`17a41099bba8c18c45c527580014e75dc7a77300f619d7f5cdfecc57aca06f39`.
This is an explicitly supplied build input, not a download or execution by the
stager. Its version matches the current release on
[Python downloads](https://www.python.org/downloads/) when checked on October 28.
Metadata and license files are retained. Dynamic-link closure, an app-bundle
layout, signing, relocation and adoption by the app remain separate gates.

The [complete local check on October 28](LOCAL_VALIDATION_2026-10-28.md) passed
before this packaging addition. It does not qualify the new stager or a future
release commit. The updated hosted CI and an installable runtime remain open.

## Toolchain Refresh: 2026-11-04

[Python 3.15.2](https://www.python.org/downloads/release/python-3152/) was
released on October 25 and is the current stable pin for local validation and
CI configuration. The separate `setup-python` provisioning on the hosted image
remains `NOT RUN`. The local tests use a private, source-built Python runtime
3.15.2 with the standard library only. That test usage is distinct from the
experimental managed backend's separately pinned interpreter requirement;
neither establishes a portable bundled application runtime.

The 2026-11-04 current local baseline is Xcode 27.2 build 27B52, Apple Swift
6.4.2 and macOS SDK 27.2. Apple lists Xcode 27.2 as stable and identifies the
compiler family as Swift 6.4; exact Swift 6.4.2 is from the local toolchain
observation. The full configured local check passed, including its toolchain preflight; see the
[dated result](LOCAL_VALIDATION_2026-11-04.md). Hosted CI was held at that
checkpoint because the observed alias mapped to RC build 27B48; the November 19
refresh above records the compatible inventory and still-unrun validation. The October 26 SDK
observation and October 28/29 validation results below remain historical
evidence for their recorded toolchains.

## Historical Toolchain Refresh: 2026-10-24

[Apple's release list](https://developer.apple.com/news/releases/) identifies
Xcode 27.1 (27A9275), released October 15, as stable; Xcode 27.2 is still an RC.
[Apple's requirements table](https://developer.apple.com/xcode/system-requirements)
lists Swift compiler 6.4 for Xcode 27.1. This does not establish the newest
standalone Swift toolchain or its exact internal build identifier.

[Python 3.15.1](https://www.python.org/downloads/release/python-3151/), released
October 21, is the latest stable version shown on
[Python downloads](https://www.python.org/downloads/).
[Python 3.14.9](https://www.python.org/downloads/release/python-3149/) is a
maintenance release of the 3.14 branch, not the latest global version.

The local validation script and CI workflow now select Xcode 27.1 build
27A9275, Swift 6.4 and Python 3.15.1 as a candidate baseline. The local Python
3.15.1 suites passed, but the current full Xcode/check path and a new hosted CI
run remain unqualified. Remote setup-python provisioning of 3.15.1 is
configured but `NOT RUN`; support by that hosted image is not demonstrated.
Other components were not rechecked in this toolchain-only refresh.

## Current Local Baseline and Historical Evidence

| Component | Version | Role and source |
|---|---|---|
| Xcode | 27.2 (27B52), current local baseline validated 2026-11-04 | Build toolchain; [Apple releases](https://developer.apple.com/news/releases/) |
| Swift | 6.4.2 (observed locally); Apple lists family 6.4 | Application language; [Apple requirements](https://developer.apple.com/xcode/system-requirements/) |
| macOS SDK | 27.2 (observed locally on 2026-11-04) | Compilation SDK; deployment target is a separate choice |
| SQLite (Apple SDK/system) | 3.54.0 observed locally | `import SQLite3; sqlite3_libversion()` through Xcode Swift; no separately bundled engine; [SQLite documentation](https://www.sqlite.org/docs.html) |
| Python | 3.15.2 | Test toolchain and interpreter required by the experimental managed backend. The separate PBS packaging input is not yet adopted as an installable app runtime. |
| NUT stable | 2.8.5 | Does not contain apcmicrolink; [release](https://github.com/networkupstools/nut/releases/tag/v2.8.5) |
| NUT experimental | 1a8369f8688443a500527059167d2f66ca27535f | Candidate source build, not a release; [commit](https://github.com/networkupstools/nut/commit/1a8369f8688443a500527059167d2f66ca27535f) |
| libusb | 1.0.30 | Optional NUT USB dependency; [release](https://github.com/libusb/libusb/releases/tag/v1.0.30) |

NUT is an independent upstream project with its own licensing requirements.
The original two patches in `backend/nut/` retain GPL-2.0-or-later licensing
and apply to the exact experimental revision above. A separately named
guarded rebase targets `73c4502191d025e35122463986a80c676e734b04`; see that
directory's README for the distinct pins and qualification boundaries.
No NUT source is relicensed under the application's MIT license.
Other package dependencies must be reviewed and recorded before adoption.

The Python 3.15.1 runtime used for the historical 2026-10-24 local tests was
installed from Astral's
[python-build-standalone 20261021 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261021),
asset `cpython-3.15.1+20261021-aarch64-apple-darwin-install_only_stripped.tar.gz`,
SHA-256 `1a4eb4d5aa82400de6eeb94e6fc6d870f5fabc97eb1d801f7eeba8072117b11c`.
It is a local test toolchain only, not an application runtime dependency or
bundled component. The 2026-10-08 Xcode 27.0/Python 3.14.8 validation records
below remain historical. The current local full check is recorded above;
hosted execution of the current revision is `NOT RUN`, so release acceptance
remains open despite the compatible image inventory observed on November 19.

Hosted automation uses `actions/checkout` v7.0.1 and `actions/setup-python`
v7.1.0 pinned to reviewed release commits; exact SHAs, source links and the
preview hosted-image limitation are recorded in [CI.md](CI.md). These are
CI-only inputs, not application runtime dependencies or included app code.

## Source Prerelease Refresh

The 2026-10-08 pre-publication check found the same stable releases: Apple's
release index lists Xcode 27 (27A266a), with 27.1 RC and 27.2 beta separate;
[Swift's installer page](https://www.swift.org/install/macos/) lists 6.4.0;
Python's macOS download is 3.14.8. Official GitHub latest-release responses
still identify NUT 2.8.5, libusb 1.0.30, checkout 7.0.1 and setup-python 7.0.0.
NUT master still resolves to the experimental SHA above. No baseline or
dependency was changed for the source archive; experimental NUT remains an
explicit exception, not a stable dependency or bundled binary.

## Upstream Replay Refresh

On 2026-10-11 the official latest-release records still identify NUT 2.8.5
and libusb 1.0.30. The observed NUT master has advanced to
`73c4502191d025e35122463986a80c676e734b04`, initially admitted as the third
exact source pin in the [offline HID replay](NUT_HID_REPLAY.md). This does
not change the original full-driver/patch baseline in the table above.
The guarded patch does not apply unchanged to the new master; see the
[upstream review](NUT_UPSTREAM_STATUS.md). No new runtime dependency or
driver binary has been adopted. Other toolchain versions were not refreshed
by this bounded NUT review and need rechecking before another release.

The subsequent same-day [guarded rebase](NUT_GUARDS_MERGED.md) adds a separately
named patch and offline USB/serial build evidence for that exact master.
The original patch and its source pin remain unchanged. These binaries were
not executed, installed, bundled or published; this is not adoption of a live
backend or a new stable NUT release.
