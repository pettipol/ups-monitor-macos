# Third-Party Notices

This inventory reflects the repository and build configuration reviewed on
2026-10-08. It is not a legal opinion or a complete scan of future changes.

## Code and Build Inputs

| Material | Recorded terms / status |
|---|---|
| Original UPS Monitor Mac source and documentation | MIT, as stated in [`LICENSE`](LICENSE). The notice does not relicense identified third-party material. |
| `backend/nut/nut-guarded-monitor.patch` and `test_guarded_policy.c` | GPL-2.0-or-later, following the affected NUT source headers; the C test carries its own SPDX identifier. |
| `backend/nut/nut-upsc-completion.patch` | GPL-2.0-or-later based on upstream `clients/upsc.c` and `clients/upsclient.c` headers. It is an unsubmitted patch against NUT, not an application MIT file. |
| `backend/nut/test_hid_fallback_replay.c` and generated NUT excerpts | GPL-2.0-or-later; generated excerpts retain upstream copyright and GPL notices. Exact source revisions/digests are in the replay runner; generated files are external, not bundled. |
| `backend/nut/replay_hid_fallback.py` and `test_replay_hid_fallback.py` | Original MIT-licensed offline source extraction and synthetic source-fence helpers. |
| `backend/nut/LICENSE-GPL2` | Complete GPL version 2 text copied from the pinned NUT source checkout; byte hash is recorded below. |
| `backend/nut/check_upsc_completion.py`, `process_deadline.py` and their Python tests | Identified by `backend/nut/README.md` as original project/MIT helpers; they use synthetic fixtures and are not the app's NUT driver. |
| NUT source and `libusb` | Built only in an external workbench for offline qualification. Neither the NUT source tree, libusb, nor their compiled binaries are included in this application repository or current app bundle. |
| Apple IOKit, SwiftUI, Charts, Security and SQLite | Used through the Apple SDK or macOS system libraries/frameworks. No separate copies are listed as bundled project dependencies. |

`Package.swift` declares no remote Swift package dependencies. The Xcode project
references the local package. `UPSHistory` links the system `sqlite3` library;
the observed local SQLite version is recorded in [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md).

NUT is an independent upstream project. `backend/nut/COPYING.NUT` is its
licensing overview: it says most NUT files are GPL-2.0-or-later and describes
other license families present in the full upstream tree. It is not itself
the complete GPL text; the applicable GPL version 2 text for the identified
patches is included as `backend/nut/LICENSE-GPL2`. This repository contains
the two patches and C tests, not the entire upstream NUT tree. The
patches are not submitted or accepted upstream. No NUT or libusb binary is
currently distributed here.

Provenance check for `backend/nut/LICENSE-GPL2`: the repository copy has
SHA-256 `ab15fd526bd8dd18a9e77ebc139656bf4d33e97fc7238cd11bf60e2b9b8666c6`.
It matches both the workbench source file and `git show HEAD:LICENSE-GPL2` at
NUT revision `1a8369f8688443a500527059167d2f66ca27535f`.

The patched client source headers list Russell Kroll (1999 for `upsc.c`, 2002
for `upsclient.c`), Arnaud Quette (2012), Arjen de Korte (2008), and Jim Klimov
(2020-2026). The guarded driver's source header lists Lukas Schmid and Nicolai
Brogaard (2026). These are provenance/attribution facts observed in the pinned
source headers; this notice makes no independent legal determination.

## Review Items Before Distribution

- Confirm applicable notices and source obligations for any future distribution
  that includes NUT binaries or a larger upstream source set. The current
  repository contains patches and tests, not the complete upstream tree.
- `nut-upsc-completion.patch` has no SPDX/provenance header of its own. Its
  adjacent README now identifies the pinned source files, copyright names
  observed in their headers and GPL terms. Whether to add metadata to the patch
  remains a maintainer decision; the missing header alone is not a legal verdict.
- Re-audit all files and generated app-bundle contents before packaging. Any
  future NUT or libusb binary distribution needs its exact version, notices,
  corresponding source/patches and build instructions reviewed together.
- Full binary-compliance audit remains **OPEN**; this file records the current
  source artifacts and observed build inputs only.
- This repository does not define a separate CLA or DCO process. Contributor
  terms and any future mixed-origin code require maintainer review; this notice
  does not grant rights beyond the identified licenses.

See [`DEPENDENCIES.md`](docs/DEPENDENCIES.md), [`REUSE_REVIEW.md`](docs/REUSE_REVIEW.md),
and [`backend/nut/README.md`](backend/nut/README.md) for the bounded evidence.
