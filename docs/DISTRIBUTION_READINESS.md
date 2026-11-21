# Distribution readiness

The optional [first-IO diagnostic source profile](../backend/nut/native-build/first-io-v1/README.md)
is a later source-only candidate. It keeps the historical delivery identities
below unchanged. Its patch reconstruction is separate from a native rebuild,
an assembled package, corresponding-source delivery and distribution review.

**Status: open.** The real app, synthetic app and developer-input kit were
assembled locally. Each has a different distribution scope. For a real-app
download, the priority is to prepare the corresponding native source beside
the binary. Keeping the existing offline kit private is compatible with
that route. Mirroring the complete kit requires additional work on the third-party
archives it carries.

The 2026-11-21 first-IO candidate adds scoped local evidence: a fresh native
build, app/widget packaging with the exact previously checked helper reused,
local signing, and a same-machine archive restore with four static signature
checks. The product was not launched. Current UI, real Stop, continuity and
independent installation remain unqualified; no byte-for-byte reproducibility
claim is made. The signed archive remains private. The runtime-notice manifest field
`redistribution_review` remains `NOT_PERFORMED`; corresponding-source, license
and notice review must finish before distribution. CI has not covered the
later local source changes.

| Artifact reviewed | Contents and SHA-256 |
|---|---|
| **E96 real macOS app** | App, widget, frozen Python helper and NUT/HIDAPI reader. `8dbc984cce32fbb111a498e8353b94f445fe0470aee17aa4c06bd4ddaff878b3` |
| **E109 real macOS app** | Local app and widget from E106, unchanged E107 helper and signed E105 reader copy. `2b783cf95d8f8d7804983d04b20fa9e6c7db3876e58ffbe48ac99ec12770356c` |
| **E98 synthetic macOS app** | App, widget, the same frozen helper and a project fixture producer. `a434827080b11f8d54d99dadd37a38bebe013de9e78c88e3056d4df8ebe70332` |
| **E95 offline developer-input kit** | Project source snapshot, NUT source tar, both HIDAPI vendor profiles, complete pinned PBS input and six wheels. `08fecfbe77235dfe57c8cfc912a735ae54f69f9a21ef1071fea5e8207f224607` |

In the tables, **verified** means files or recorded build products were
checked for these artifacts. **Declared** identifies component information
from upstream metadata. An action in the last column remains open.

## App archives

The app archives preserve the original notices under
`Contents/Resources/RuntimeNotices/`. E96 and E109 carry eight
native notices under `NativeProducerNotices/`. E98 carries
`SyntheticProducerNotices/{LICENSE.txt,README.txt}`.

The E109 local archive restored an identical 83-entry tree and passed
all four signature checks on the original and restored bundles. It
includes 25 runtime notice files and the eight native notices. Local
static verification leaves independent installation, product launch,
widget rendering, clean Stop, USB operation, notarization and public
release open. [App source delivery](APP_SOURCE_DELIVERY.md)

| Component and scope | Terms and controlling text | Material available | What to complete for distribution |
|---|---|---|---|
| **Original UPS Monitor code** in the E96, E98 and E109 app, widget and Python modules, and original project files in the E95 snapshot | MIT requires retaining the copyright and permission notice in copies or substantial portions. Third-party files and NUT-derived changes retain their own terms. [Project LICENSE](../LICENSE) · [Project inventory](../THIRD_PARTY_NOTICES.md) | Project MIT text in the app archives and the kit. The [app source delivery](APP_SOURCE_DELIVERY.md) identifies the selected frontend, helper sources, qualification patch, fixture and recipient build procedure. E107 rebuilt the synthetic app from the delivered 207-file source archive; the restored 77-entry tree and four signatures before and after restoration passed. The guide records the explicit macOS SDK argument. E108 passed 455 distinct Swift cases from the unmodified subset, including two opt-in cases with a separately qualified NUT client and synthetic loopback servers. E109 compiled the real frontend from the same subset and reused the unchanged E107 helper. | Keep the original notice and matching source materials with the selected package. Independent installation and release checks remain open. Identify the native reader separately in release materials. |
| **NUT-based reader** in E96 and E109, built from revision `73c4502191d025e35122463986a80c676e734b04` with project changes | The MicroLink driver is GPL-2.0-or-later. GPLv2 §§1–2 cover retained notices, dated notices of modifications and terms for the distributed derived work. §2 also distinguishes aggregation of independent works. §3 covers distribution of object code and corresponding source. [Driver header](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/drivers/apcmicrolink.c#L1-L75) · [NUT scope](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/COPYING) · [GPLv2](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/LICENSE-GPL2) | Verified reader and signing comparison. The [native-source delivery](NATIVE_SOURCE_DELIVERY.md) records the annotated source, original NUT and HIDAPI inputs, native notices and 60-file recipe. Recipe restoration and the 190-file pre-CAL checkpoints passed. E105 compiled the restored 60-file recipe and statically audited its unsigned output on the recorded arm64 host. E109 signed a copy and verified its sections and payload before local assembly. | Pair the reader with complete corresponding source at the chosen distribution point. Finish the review of dated modification notices, applicable build and installation instructions, composition and app/helper interfaces. Independent installation and hardware operation remain open. The bundle layout and process boundary alone leave the scope of GPLv2 §2 unresolved. |
| **HIDAPI 0.16.0**, commit `750c87abb03282a237297052b84522e6bb3c0616`, statically built into the E96 reader | Upstream offers alternatives. The build selects the BSD-style option, which requires preservation of the copyright, conditions and disclaimer for source and binary redistribution and restricts endorsement. [License selection](https://github.com/libusb/hidapi/blob/750c87abb03282a237297052b84522e6bb3c0616/LICENSE.txt) · [BSD conditions](https://github.com/libusb/hidapi/blob/750c87abb03282a237297052b84522e6bb3c0616/LICENSE-bsd.txt) | The four original texts and selection note are verified in E96. The Darwin source and headers are available in E95. | Preserve the BSD notices in recipient materials and include those source inputs in the reader source delivery. The BSD terms do not create a separate source-delivery requirement. |
| **Project fixture producer** in E98 | MIT under the actual periodic fixture's own header and the project notice. [Periodic fixture source](../backend/nut/fixtures/synthetic_operational_periodic.c) · [Project LICENSE](../LICENSE) | Verified synthetic binary and the two fixture notices. The periodic source has SHA-256 `ead60dcd079a8a4467183181f95f1b306d24253e990b9363b1ff35252c136861` and is supplied alongside the existing baseline fixture. The E98 archive excludes the E96 reader and its native notices. | Keep the periodic source, notice and build recipe with the selected package. Recipient builds generate their own binary and manifest identities. Apply the common helper checks below to E98 as well. |
| **PyInstaller 6.22.3 bootloader and related embedded files**, E96 and E98 | The exception in `COPYING.txt` lines 18–28 addresses the bootloader and related files combined with an application. Modified or separately distributed PyInstaller files remain governed by the applicable terms. [COPYING and exception](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/COPYING.txt#L1-L42) | Verified helper archive tables identify the bootloader/loader build and Python payload. The complete COPYING text is retained. | Keep COPYING and record which PyInstaller files were included and whether they were modified. The exception does not extend to unrelated dependencies or clear the standalone bootloader wheel. |
| **PyInstaller `pyi_rth_inspect` runtime hook**, E96 and E98 | Apache-2.0 §4 requires the license, notices of changed files where applicable, relevant source attributions and reproduction of pertinent NOTICE contents when the distributed work includes a NOTICE. [Hook at tag](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/PyInstaller/hooks/rthooks/pyi_rth_inspect.py) · [Apache terms in COPYING](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/COPYING.txt) | Hook name in the actual helper archive tables. Complete COPYING retained. No NOTICE found in the checked wheel or at the queried root path. | Check against the precise distribution source for the shipped hook and carry any applicable NOTICE and change notices. The root-path check is limited to the queried location. |
| **CPython 3.15.2 from PBS 20261026**, E96 and E98 helper | Python-2.0 and CNRI-Python in the input metadata, with historical and bundled-software terms. PSF §2 requires the license and copyright notice. PSF and CNRI §3 address brief change summaries for derivatives under their respective conditions. [CPython terms](https://github.com/python/cpython/blob/v3.15.2/LICENSE) · [Pinned PBS CPython build](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/build-cpython.sh) | Packaged `libpython3.15.dylib`, `base_library.zip` and helper module tables verified. The app carries the extended CPython text from the pinned PBS archive. The PBS build script applies source patches. | Include the [runtime change summary](CPYTHON_RUNTIME_CHANGES.md) and the extended CPython text with the selected app. Reconcile actual extensions and bundled libraries using the map below. |
| **macOS frameworks and libraries** | OS/SDK references are tracked separately from redistributed files. [Dependency inventory](DEPENDENCIES.md) | The E96 native link audit resolved IOKit, CoreFoundation and libSystem. Helper and app use system dependencies, including system SQLite for app history. The Python extension's SQLite association is separate. libusb was used at configure time for the native build. No libusb library appears in the final native link map or app inventory. | Recheck the final bundle and load dependencies for the selected distribution. A future vendored library requires a new component row with its own terms and materials. |

### CPython dependency and notice map

These extension names and associated libraries are **declared** by
`PYTHON.json` in the pinned PBS input. The E96/E98 library has the exact
whole-file SHA-256 of the library previously inspected: `ffd41320665033f914dc13c6257864885963c4d87f6c0f658a734cb47d31bd0a`.
The PBS archive and metadata identities also match. This binds the earlier
98 exact initializer names to this library: 16 of the 17 metadata-mapped
initializers are present; the exact `_tkinter` initializer is absent from
this library. It does not establish use at runtime or independently prove
each declared static-library link. All 25 runtime-notice files, including
the 24-entry manifest, match by name, size and digest in E81, E96 and E98.
The 152 decoded standard-library ZIP entries also match, while the ZIP
container digest differs from E81. These component comparisons do not
transfer the old whole-helper inventory or PYZ to the new helper.
The filenames below use
the common `RuntimeNotices/python-LICENSE.` prefix and `.txt` suffix.
[Pinned metadata and notice hashes](PYTHON_RUNTIME_LICENSE_INVENTORY.md)

| Declared extension or dependency | Applicable text and material available | Remaining check |
|---|---|---|
| `_bz2` → bzip2 | `bzip2`, copyright and bzip2 conditions on distribution, origin, altered sources and endorsement | Match the included library and retain its original terms. |
| `_ctypes` → libffi and `pyexpat` → Expat | `libffi`, `expat`, MIT copyright and permission texts | Map each shipped dependency to its own text. |
| `_decimal` → mpdecimal, `_uuid` → libuuid, `_remote_debugging` and `_zstd` → zstd, `readline` → libedit | `mpdecimal`, `libuuid`, `zstd`, `libedit`. Preserve the original BSD-family conditions and disclaimers, including any endorsement clause applicable to the text. | Resolve the actual linked or incorporated copy. macOS also supplies libedit. |
| `_curses`, `_curses_panel` → ncurses | `ncurses`, X11-style copyright and permission conditions, including the text's name-use condition | Distinguish the declared notices from system ncurses and libpanel dependencies. |
| `_lzma` → liblzma | `liblzma`, 0BSD text | Keep the authenticated text with the dependency map. |
| `_ssl`, `_hashlib` → OpenSSL 3.5.9 | `openssl-3`, Apache-2.0 §4. The PBS metadata declares static OpenSSL links and its registry pins this version. The retained text matches the tag. [PBS registry](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/pythonbuild/downloads.json) · [OpenSSL terms](https://github.com/openssl/openssl/blob/openssl-3.5.9/LICENSE.txt) | Bind that library to the shipped binary and check the exact corresponding source distribution for changes and any applicable NOTICE. The checked root NOTICE paths do not settle this. |
| `_sqlite3` → SQLite and compression libraries | `sqlite`, `zlib`, `zlib-ng`. The SQLite text identifies the original SQLite dedication to the public domain and describes title and warranty. The compression libraries have separate terms. | Keep the SQLite notice and resolve the compression libraries independently. |
| `binascii` and `zlib` → compression libraries | `zlib`, `zlib-ng`. Identify the origin accurately, mark altered source and preserve the notice in source distributions under the applicable text. | Resolve which compression implementation is carried and which is a system reference. |
| `_tkinter` → Tcl and compression libraries | `tcl`, `zlib`, `zlib-ng` retained from metadata | Establish presence for the selected payload before attributing these components. |
| Retained without a metadata mapping | `bdb`, `libX11`, `libXau`, `libxcb`, `tix` | Keep the texts as retained notices. A file in this row alone does not establish the component's presence. |

## What a kit mirror would also distribute

The wheel archives below are standalone build inputs. None is a member
of E96 or E98. The helper output inspection identifies the PyInstaller
runtime hook separately. In those tables there is no observed contrib
runtime hook or embedded altgraph, macholib, packaging or setuptools
package. The kit records original wheel names and digests in the
[locked build inputs](../backend/nut/frozen_build_inputs.json).

| Kit input | Terms and controlling text | Material available | What to complete if mirroring |
|---|---|---|---|
| **Project source and upstream NUT/HIDAPI inputs** | Project MIT and NUT-derived file terms remain scoped separately. NUT's full tree includes other license families identified in its [COPYING](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/COPYING). The HIDAPI BSD option applies to the selected files. [0.15 terms](https://github.com/libusb/hidapi/blob/d6b2a974608dec3b76fb1e36c189f22b9cf3650c/LICENSE-bsd.txt) · [0.16 terms](https://github.com/libusb/hidapi/blob/750c87abb03282a237297052b84522e6bb3c0616/LICENSE-bsd.txt) | Original full NUT tar, project source and patches, HIDAPI 0.15.0 bootstrap inputs and 0.16.0 reader inputs with their respective original notices. | Preserve the upstream tar and its per-file notices and the original notices for both vendor profiles. Provide the exact source/patch order and any applicable modification notices for project changes. |
| **PBS 20261026 full archive** | CPython and third-party terms above apply to their contents. MPL 2.0 §§3.1–3.4 apply to covered PBS files and require source availability for covered executable forms. The PBS repository license alone does not classify the whole Python archive. [PBS MPL](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/LICENSE) · [Archive format](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/docs/distributions.md) | Original tar with notices, metadata, Python files, libraries, objects and some generated C sources. The `full` variant's build directory does not establish complete editable source. | Review all shipped PBS members, beyond the helper subset. Identify covered executables, source and patch paths and any needed source delivery. Provide the applicable CPython change summary and dependency notices for this larger payload. |
| **PyInstaller 6.22.3** wheel | PyInstaller GPL terms for standalone bootloader redistribution. The binary-combination exception concerns the app/helper. [COPYING](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/COPYING.txt) | The universal wheel has `run` and `runw` in `PyInstaller/bootloader/Darwin-64bit/`. The observed wheel contains COPYING and has no C source, `wscript`, `pyproject.toml` or `setup.py`. | Obtain and bind the complete corresponding source and bootloader build scripts to these wheel binaries, then choose and implement the applicable GPL source-delivery method. The pinned [bootloader recipe](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/bootloader/wscript) and [source build configuration](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/pyproject.toml) are starting points. Alternatively leave this wheel upstream. |
| **pyinstaller-hooks-contrib 2026.9** wheel | Ordinary hooks GPL-2.0-or-later and runtime hooks Apache-2.0 under the [versioned LICENSE](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/v2026.9/LICENSE). | The wheel retains its license and readable `.py` hook files. No `.pyc` or NOTICE member was observed. | Confirm the distributed hook sources and any needed assembly inputs using the [source configuration](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/v2026.9/pyproject.toml). Check Apache §4 for any applicable changes or notices. Treat the source wheel separately from PyInstaller's compiled bootloaders. |
| **altgraph 0.17.5** and **macholib 1.16.4** wheels | MIT. The original governing notice for each is its `.dist-info/LICENSE`, supported by the wheel's metadata. | Both individual texts are present in the locked wheels. | Keep both original notices as part of the intact wheels. |
| **packaging 26.3** wheel | Apache-2.0 **or** BSD-2-Clause in wheel metadata and `.dist-info/licenses/LICENSE`. | Selector and both texts included. | Preserve all three files. Record the license option relied on for redistribution and apply its conditions. |
| **setuptools 84.2.1** wheel, including vendored code | MIT for setuptools under its `.dist-info/licenses/LICENSE`. Vendored terms are separate. In this wheel, autocommand 2.2.2 is labelled LGPLv3 in its `.dist-info/METADATA` with a corresponding license. The two config NOTICE files identify MPL-2.0 material from validate-pyproject, BSD-3-Clause fastjsonschema material and generated files. | Wrapper license, vendored licenses, two notices, editable Python modules for autocommand and generation information for validators. | Preserve the complete notice set. Identify the terms and source form for the precise vendored files, including any preferred inputs needed for generated covered code. Check LGPLv3 conditions for the distribution form where applicable and MPL §§3.1–3.4 for the covered material. |

## Release checklist

### Real app with corresponding source

1. Pair the selected app download with a separate reader source archive
   from the same distribution point, following GPLv2 §3(a) and the
   provision for equivalent source access for downloads. Include the
   preferred form for modification, interface definitions, pinned NUT
   base, effective patches and added files, HIDAPI inputs and the scripts
   controlling compilation and installation. A generic upstream link
   would omit the changes used in this reader. An offer under §3(b)
   has its own conditions, including at least three years. §3(c) is
   limited to qualifying pass-through of an offer.
2. Bind the selected reader to its source, build receipt and signing
   comparison in the release manifest. The E104 provenance file links
   the historical E95 unsigned reader
   `843d12d945ca3137372ca3473f628e9701990b16b04d028aaa88cfa42f34413a`
   to the E96 signed reader
   `e6cb869dcc3a6a444a855e26e4e18f0872f29a8c649cfddde5d27fe5b7268d20`.
   E109 links the unsigned E105 reader
   `bde33f43235d3199622bccb8bc627ca264b2999ca38c75b4c14d599247efedd2`
   to the signed copy
   `3d75472b8c0868a40723fa0010884c4abae29226a3959523dde0381c95030428`.
   Verify complete editable inputs against the effective source map and
   replay the public preparation recipe. Record any receipt differences
   after adding source notices. Matching a signed binary byte for byte
   is a separate reproducibility question. [Native source delivery](NATIVE_SOURCE_DELIVERY.md)
3. Check the effective NUT changes for prominent dated GPLv2 §2(a)
   notices. In the 190-entry non-vendor map, the original comparison
   found 165 unchanged paths, 10 modified upstream files and 15 added
   files. The last three diffs added no dated modification notice
   across the five files they touch. That observation says nothing
   about notices already in those files. Check the complete effective
   files and retain copyright, license and warranty notices.
4. Include the runtime notice index, CPython/PBS change summary and exact
   component reconciliation. Surface the matching source download and
   notices in the release materials. For E98, carry the fixture source
   provenance and shared runtime materials without the E96 reader or
   its native notices.

### Developer inputs

1. A public source-and-recipe route can leave the existing E95 mirror
   private. Document the exact upstream inputs and hashes needed to
   recreate the kit locally using the [offline kit guide](OFFLINE_DEVELOPER_KIT.md).
   Keep the reader's corresponding source available with the real app
   under the chosen source-delivery method.
2. For a complete mirrored kit, pair the PyInstaller wheel with its
   verified source delivery, complete the PBS and other wheel checks
   above, and inventory all redistributed files and notices in the
   final tar. Authenticate the mirror and any separately supplied source
   with a release manifest. Publish only the selected artifacts after
   checking what a recipient can actually obtain.

This record covers source and notice delivery for specific local
artifacts. Distribution remains open. Signing for distribution,
notarization, installation, sustained operation and hardware
qualification have separate acceptance criteria.
