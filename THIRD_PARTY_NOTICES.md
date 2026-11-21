# Third-Party Notices

This inventory covers the source tree, the local development app candidates and
the offline build inputs inspected on 2026-11-05. Original project material
uses the [MIT license](LICENSE). Each third-party component retains its own
terms.

## What each artifact contains

| Artifact | Materials and where to find their notices |
|---|---|
| Project source archive | Swift, Python, patches, fixtures, build recipes and notice files. The NUT-derived patches carry their own notices. See the [native recipe](backend/nut/native-build/README.md) for the upstream revisions. |
| Local SMC1500I app (E66) | The native producer at `Contents/MacOS/apcmicrolink-hidapi-operational` incorporates NUT code and HIDAPI's Darwin implementation. `Contents/Resources/NativeProducerNotices/` contains NUT's three original notice files, HIDAPI's four license texts and a README identifying the selected BSD-style option. The frozen helper has a separate `Contents/Resources/RuntimeNotices/` directory with 23 texts plus its README and manifest. |
| Local simulated app (E70) | The same executable path holds a simulator built from the project's C fixture. The helper and its runtime notices are included. App and widget select a dedicated simulated data store. |
| Local preview archive (E80) | E81 maps its exact helper, 157 PYZ namespaces, 152 ZIP entries, nine project Python files, libpython and native producer to recorded inputs and notice texts. The native code/data matches the E73 build, and libpython code/data matches the pinned PBS input. The [payload component inventory](docs/FROZEN_PAYLOAD_COMPONENTS.md) records the symbol-based extension map and the limits of nominal source associations. |
| Offline developer kit | The default kit includes the project tar, full pinned NUT source tar, three original HIDAPI 0.15.0 files, Python Build Standalone archive and six build wheels. The project tar contains the four pinned 0.15.0 license texts. The optional 0.16 profile adds four source files and four license texts under `native/hidapi-0.16/`. The wheels retain their individual metadata and license files, including vendored texts where present. The kit root contains the project license, a third-party inventory and checksums. See the [kit guide](docs/OFFLINE_DEVELOPER_KIT.md). |

The E66 build-source snapshot and the newer developer kit are separate artifacts.
Preparing a distribution requires reviewing the source and build instructions
against the exact binary selected for that distribution.

## Code and Build Inputs

| Material | Recorded terms / status |
|---|---|
| Original UPS Monitor Mac source and documentation | MIT, as stated in [`LICENSE`](LICENSE). The notice does not relicense identified third-party material. |
| `backend/nut/stage_bundled_python_runtime.py`, its input manifest and synthetic tests | Original MIT offline packaging utility. It copies an explicitly supplied, hash-pinned Python distribution; it does not relicense, execute or download that distribution. [Scope](docs/BUNDLED_PYTHON_RUNTIME.md). |
| CPython 3.15.2 from python-build-standalone 20261026 | External candidate packaging input, not a binary included in this source repository. Upstream metadata records Python-2.0 and CNRI-Python for Python, plus separate extension/dependency terms. The stager retains the upstream metadata and license directory; complete distribution acceptance and notices for the final app remain open. [Pinned input](backend/nut/bundled_python_runtime_inputs.json); [runtime license inventory](docs/PYTHON_RUNTIME_LICENSE_INVENTORY.md). |
| Frozen runtime license texts in `third_party/frozen-runtime` | Twenty original PBS license files, the complete PyInstaller and hooks-contrib license texts, and the project MIT notice are retained byte for byte. The [manifest](third_party/frozen-runtime/manifest.json) records their source identities and scopes; the [guide](third_party/frozen-runtime/README.md) distinguishes incorporated runtime material from conservative/build-only retention. Presence of every retained text does not imply every full-distribution component is incorporated. |
| PyInstaller 6.22.3 | The locally built helper incorporates its bootloader/loader, icon and `pyi_rth_inspect` runtime hook. The complete [COPYING](third_party/frozen-runtime/pyinstaller-COPYING.txt) retains GPL terms, the bootloader exception and Apache terms for runtime hooks. These terms do not relicense the application's dependencies as MIT. [Versioned upstream source](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/COPYING.txt). |
| pyinstaller-hooks-contrib 2026.9 | Pinned build input; no contrib runtime hook was observed in the qualified helper's output tables. Its [complete LICENSE](third_party/frozen-runtime/pyinstaller-hooks-contrib-LICENSE.txt) is retained as build provenance, not a claim that a contrib runtime hook is embedded. [Versioned source](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/v2026.9/LICENSE). |
| `backend/nut/assemble_frozen_operational_runtime.py` | Original MIT assembly utility. It copies the admitted runtime and separately authenticated notices into a new app copy; it does not perform a license-compliance determination. The outer app must be signed after assembly. |
| `backend/nut/normalize_bundled_python.py`, `backend/nut/managed_bundled_operational_entrypoint.py` and their synthetic tests | Original project MIT code. The bundled CPython payload remains a separate upstream input with its own metadata and license files. |
| `backend/nut/replay_operational_portable_e31.py`, its input manifest and synthetic contract tests | Original MIT reconstruction/audit runner. It reuses the frozen continuous replay and NUT-derived patches; their licenses remain separate. It builds and runs only a simulated host after explicit admission. [Scope](docs/PUBLIC_OPERATIONAL_REPLAY_E31.md). |
| `backend/nut/replay_operational_portable_e32.py`, its input manifest, source hash map, Python validator and contracts | Original MIT orchestration and synthetic validation, extending the pinned public reconstruction with cleanup diagnostics. The source hash map contains relative paths and hashes, not the full upstream source. [Scope](docs/PUBLIC_CLEANUP_REPLAY_E32.md). |
| `backend/nut/replay_operational_native_e32.c`, `replay_operational_hooks_e32.h`, `nut-operational-cleanup-replay-hooks-e32.patch` | GPL-2.0-or-later NUT-derived synthetic host and test-only hooks. These are applied only to the separate fake tree, not the retained production diagnostic tree. They do not relicense the NUT source or qualify hardware behavior. |
| `backend/nut/nut-operational-cleanup-diagnostics-v1.patch` | GPL-2.0-or-later NUT-derived changes to APC and the shared session implementation. The two `production_source_*_e28.json` manifests record relative paths and source hashes; they do not contain the full upstream source tree. This source delta is distinct from the E31 replay baseline. [Provenance and order](docs/PRODUCTION_CLEANUP_DIAGNOSTICS.md). |
| `backend/nut/apcmicrolink-hidapi-shared.c`, `apcmicrolink-hidapi-shared-host.h`, `test_hidapi_shared_transport.c` | GPL-2.0-or-later, identified by SPDX; guarded implementation of the NUT transport interface and synthetic tests. The pinned NUT ABI header is supplied externally with its original notices. Default-off session integration is a separate increment, not an operational driver. [Scope](docs/NUT_HIDAPI_SHARED_CANDIDATE.md). |
| `backend/nut/replay_hidapi_shared_transport.py` | Original MIT build/test runner; this runner does not link HIDAPI or execute device operations. |
| `backend/nut/apcmicrolink-hid-descriptor-checked.c`, `.h`, `test_hid_descriptor_checked.c` | GPL-2.0-or-later. Bounded NUT-derived tokenizer/state logic, separate from the legacy HID parser ABI; exact source hashes and function origins are recorded in the header. Original source notices are retained. |
| `backend/nut/apcmicrolink-hidapi-native.c`, `.h`, `test_hidapi_native.c` | GPL-2.0-or-later. The real preview compiles the native host implementation. The test exercises it with synthetic inputs. |
| `backend/nut/replay_hid_descriptor_checked.py`, `replay_hidapi_native.py` | Original MIT offline runners. Only fake executables run; authentic native HIDAPI is optionally compiled/linked and never executed. |
| `backend/nut/apcmicrolink-hidapi-session.h`, `test_hidapi_session.c` | GPL-2.0-or-later, identified by SPDX; one-shot session API and synthetic lifecycle fixtures for the default-off candidate. No app, NUT-driver or hardware qualification follows. |
| `backend/nut/replay_hidapi_session.py` | Original MIT runner; executes only isolated synthetic HIDAPI scenarios after symbol/dependency checks. |
| `backend/nut/stage_hidapi_candidate.py`, `test_stage_hidapi_candidate.py` | Original MIT offline staging utility and synthetic tests; copies pinned external sources and all upstream license notices, never builds or executes them. |
| `backend/nut/nut-hidapi-observe-73c4502.patch` | GPL-2.0-or-later NUT-derived integration over the exact ninth guarded stack. Separate default-off, uninstalled observation target; native build NOT_RUN and no hardware qualification. [Scope](docs/NUT_HIDAPI_SHARED_CANDIDATE.md). |
| `backend/nut/extract_hidapi_nut.py`, `test_extract_hidapi_nut.py`, `replay_hidapi_nut.py`, `test_hidapi_nut_supervisor.py` | Original MIT offline extraction, replay and supervisor-test tools. Generated NUT C retains the original GPL-2.0-or-later notice verbatim. The local generated NUT configuration is external and private, not bundled. |
| `backend/nut/test_hidapi_nut.c` | GPL-2.0-or-later, identified by SPDX; synthetic surrounding services/HIDAPI for extracted NUT protocol functions and the production candidate modules. Not a complete NUT main or receive-decoder replay. |
| `backend/nut/test_hidapi_nut_config.h`, `test_replay_hidapi_nut_config.py` | Original MIT test-only branch-selection fixture and synthetic configuration-selection tests. This small public fixture is not the private generated NUT config and is not a production configuration. |
| `backend/nut/test_hidapi_full_driver.c`, `test_hidapi_full_os.h`, `test_hidapi_full_frames.c`, `.h`, `test_hidapi_full_frames_test.c` | GPL-2.0-or-later, identified by SPDX; synthetic HIDAPI, process observers, test-only OS guards and artificial Microlink frames for whole-NUT replay. The generated checksum helper preserves the pinned NUT copyright/GPL notice. No captured hardware data is included. |
| `backend/nut/replay_hidapi_full_driver.py`, `test_replay_hidapi_full_driver.py` | Original MIT local build/audit/replay tool and Python mocks. The whole-NUT configuration and archives are external private inputs, not distributed or portable release artifacts. |
| HIDAPI `hidapi-0.15.0`, commit `d6b2a974608dec3b76fb1e36c189f22b9cf3650c` | The real producer compiles the pinned Darwin source with the pinned headers. The project selected the BSD-style option in [LICENSE-bsd.txt](backend/nut/native-build/licenses/hidapi/LICENSE-bsd.txt). The offline kit checks the three vendor files and four license texts. |
| HIDAPI `hidapi-0.16.0`, commit `750c87abb03282a237297052b84522e6bb3c0616` | The [optional profile](backend/nut/native-build/hidapi-0.16/README.md) pins the Darwin implementation, both headers and input-ring header. The optional kit includes these files and the four original upstream license texts. The BSD-style license is selected in `native/hidapi-0.16/LICENSE-bsd.txt`. |
| `backend/nut/nut-guarded-monitor.patch` and `test_guarded_policy.c` | GPL-2.0-or-later, following the affected NUT source headers; the C test carries its own SPDX identifier. |
| `backend/nut/nut-guarded-monitor-73c4502.patch` | GPL-2.0-or-later; alternative guarded patch against exact NUT revision `73c4502191d025e35122463986a80c676e734b04`, not an application MIT file. |
| `backend/nut/nut-hid-fallback-validation-73c4502.patch` | GPL-2.0-or-later NUT-derived offline candidate against exact revision `73c4502191d025e35122463986a80c676e734b04`; remains a separate artifact, with bounded [combined build evidence](docs/NUT_COMBINED_CANDIDATE.md). |
| `backend/nut/nut-guarded-lifecycle-write-73c4502.patch` | GPL-2.0-or-later incremental candidate over the exact merged guard/HID combination; [bounded evidence and open gates](docs/NUT_LIFECYCLE_WRITE_CANDIDATE.md). |
| `backend/nut/nut-usb-async-state-73c4502.patch`, `test_usb_async_state.c` and generated excerpts | GPL-2.0-or-later; incremental NUT-derived patch over lifecycle/write, synthetic C test and excerpts preserving upstream notices; [scope](docs/NUT_ASYNC_STATE_CANDIDATE.md). |
| `backend/nut/replay_usb_async_state.py`, `test_replay_usb_async_state.py` | Original MIT runner and synthetic contracts; no driver execution. |
| `backend/nut/nut-usb-guard-deadline-73c4502.patch`, `test_usb_guard_deadline.c` and generated excerpts | GPL-2.0-or-later; incremental NUT-derived patch, synthetic C test and excerpts retaining upstream notices; [scope](docs/NUT_GUARD_DEADLINE_CANDIDATE.md). |
| `backend/nut/replay_usb_guard_deadline.py`, `test_replay_usb_guard_deadline.py` | Original MIT runner and synthetic contracts; no driver execution. |
| `backend/nut/nut-usb-owner-retention-73c4502.patch`, `test_usb_owner_retention.c` and generated excerpts | GPL-2.0-or-later; sixth incremental NUT-derived candidate and synthetic fixture; generated excerpts preserve both source copyright/GPL notices. [Scope and hashes](docs/NUT_OWNER_RETENTION_CANDIDATE.md). |
| `backend/nut/extract_usb_owner_retention.py`, `test_extract_usb_owner_retention.py` | Original MIT extract-only tool and synthetic contracts; no compilation or C/driver execution. |
| `backend/nut/nut-guarded-startup-stop-73c4502.patch`, `test_guarded_startup_stop.c` and generated excerpts | GPL-2.0-or-later; seventh incremental NUT-derived candidate and synthetic fixture. [Scope and provenance](docs/NUT_GUARDED_STARTUP_STOP_CANDIDATE.md). |
| `backend/nut/extract_guarded_startup_stop.py`, `test_extract_guarded_startup_stop.py` | Original MIT tools and synthetic contracts; no UPS driver or hardware execution. |
| `backend/nut/nut-guarded-reopen-stop-73c4502.patch`, `test_guarded_reopen_stop.c` and generated excerpts | GPL-2.0-or-later; eighth incremental NUT-derived candidate and wrapper reusing the ownership fixture. [Scope and provenance](docs/NUT_GUARDED_REOPEN_STOP_CANDIDATE.md). |
| `backend/nut/extract_guarded_reopen_stop.py`, `test_extract_guarded_reopen_stop.py` | Original MIT extract-only tool and synthetic contracts; no compilation or driver execution by the extractor. |
| `backend/nut/nut-guarded-probe-attempts-73c4502.patch` | GPL-2.0-or-later; ninth incremental NUT-derived candidate over the eight-patch stack, changing main, APC and USB source. [Scope and limits](docs/NUT_GUARDED_PROBE_CANDIDATE.md). |
| `backend/nut/nut-upsc-completion.patch` | GPL-2.0-or-later based on upstream `clients/upsc.c` and `clients/upsclient.c` headers. It is an unsubmitted patch against NUT, not an application MIT file. |
| `backend/nut/test_hid_fallback_replay.c` and generated NUT excerpts | GPL-2.0-or-later; generated excerpts retain upstream copyright and GPL notices. Exact source revisions/digests are in the replay runner; generated files are external, not bundled. |
| `backend/nut/test_hid_fallback_validation.c` and generated NUT excerpts | GPL-2.0-or-later; the test carries its own SPDX identifier and extracted fragments retain upstream copyright/GPL notices. Generated files are external, not bundled. |
| `backend/nut/test_guarded_dump_signals.c`, `test_usb_write_completion.c` and generated NUT excerpts | GPL-2.0-or-later; synthetic C harnesses with SPDX, generated excerpts retain upstream notices and are not bundled. |
| `backend/nut/replay_hid_fallback.py` and `test_replay_hid_fallback.py` | Original MIT-licensed offline source extraction and synthetic source-fence helpers. |
| `backend/nut/replay_hid_validation.py` and `test_replay_hid_validation.py` | Original MIT-licensed pinned candidate replay and synthetic path/source/output-fence tests; they do not run a NUT driver. |
| `backend/nut/replay_guarded_dump_signals.py`, `replay_usb_write_completion.py` and their Python tests | Original MIT replay/contract tools; bounded generated test programs, never a NUT driver. |
| `backend/nut/check_guarded_merged_rebase.py` | Original MIT-licensed static preservation checker; no full-driver or hardware execution. |
| `backend/nut/LICENSE-GPL2` | Complete GPL version 2 text copied from the pinned NUT source checkout; byte hash is recorded below. |
| `backend/nut/native-build/` | Source recipe for the real MicroLink producer. The CAL patch is NUT-derived (GPL-2.0-or-later); three HIDAPI 0.15.0 vendor sources are acquired separately, with the BSD license alternative selected. The [guide](backend/nut/native-build/README.md) identifies the inputs and notices. The compiled producer belongs to the real app package described above. |
| `backend/nut/check_upsc_completion.py`, `process_deadline.py` and their Python tests | Identified by `backend/nut/README.md` as original project/MIT helpers; they use synthetic fixtures and are not the app's NUT driver. |
| NUT source and `libusb` | The offline kit carries the original NUT tar. The local real preview carries the compiled producer. Its build uses libusb during configuration. The observed native link map resolves to IOKit, CoreFoundation and libSystem without a linked libusb library. |
| Apple IOKit, SwiftUI, Charts, Security and SQLite | Used through the Apple SDK or macOS system libraries/frameworks. No separate copies are listed as bundled project dependencies. |

`Package.swift` declares no remote Swift package dependencies. The Xcode project
references the local package. `UPSHistory` links the system `sqlite3` library;
the observed local SQLite version is recorded in [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md).

NUT is an independent upstream project. `backend/nut/COPYING.NUT` is its
licensing overview: it says most NUT files are GPL-2.0-or-later and describes
other license families present in the full upstream tree. It is not itself
the complete GPL text; the applicable GPL version 2 text for the identified
patches is included as `backend/nut/LICENSE-GPL2`. This repository contains
NUT-derived patches and synthetic C tests, not the entire upstream NUT tree. The
patches are not submitted or accepted upstream. The HID validation candidate
is not integrated into the application backend. Its separate combination with
the merged guarded patch has offline source/build evidence only, not runtime
or hardware qualification. The source archive carries the project patches and tests. The local real preview is described separately above.

Provenance check for `backend/nut/LICENSE-GPL2`: the repository copy has
SHA-256 `ab15fd526bd8dd18a9e77ebc139656bf4d33e97fc7238cd11bf60e2b9b8666c6`.
It matches both the workbench source file and `git show HEAD:LICENSE-GPL2` at
NUT revision `1a8369f8688443a500527059167d2f66ca27535f`.

The patched client source headers list Russell Kroll (1999 for `upsc.c`, 2002
for `upsclient.c`), Arnaud Quette (2012), Arjen de Korte (2008), and Jim Klimov
(2020-2026). The guarded driver and HID transport source headers list Lukas
Schmid and Nicolai Brogaard (2026). These are provenance/attribution facts
observed in the pinned source headers; this notice makes no independent legal
determination.

The ownership candidate also changes `drivers/libusb1.c` (Eaton and Arnaud
Quette, 2016; Jim Klimov, 2021-2024) and `drivers/nut_libusb.h` (Arnaud Quette,
2003-2016; Peter Selinger, 2005; Jim Klimov, 2021). Their headers state GPL
version 2 or later; those original headers are preserved in the patched source.

## Review Items Before Distribution

The [artifact-specific distribution matrix](docs/DISTRIBUTION_READINESS.md)
separates the real app, synthetic app and developer-input kit, with source
delivery and notice actions for each. It records scoped findings, not a
completed distribution approval.

The [E80 component map](docs/FROZEN_PAYLOAD_COMPONENTS.md) supplies the static
inventory for that local archive. Its 17 upstream extension declarations
resolve to authenticated notice files, with 16 exact initializer-name matches
in instruction-bearing sections of the packaged libpython. Review the
corresponding source delivery and applicable terms for the artifacts selected
for publication.

- Reconcile the complete frozen payload, its build inputs and the retained notice
  texts whenever the dependency graph changes. The notice manifest's PBS binding
  verifies declared input identity, not the applicability or sufficiency of all
  terms. Review the real and simulated producer variants separately using the
  contents of the chosen binary package.
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
- Public redistribution review remains **OPEN** for the selected app and its
  matching source. The inventory above records the material inspected locally.
- This repository does not define a separate CLA or DCO process. Contributor
  terms and any future mixed-origin code require maintainer review; this notice
  does not grant rights beyond the identified licenses.

See [`DEPENDENCIES.md`](docs/DEPENDENCIES.md), [`REUSE_REVIEW.md`](docs/REUSE_REVIEW.md),
and [`backend/nut/README.md`](backend/nut/README.md) for the bounded evidence.
