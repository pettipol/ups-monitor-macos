# Changes in the bundled CPython runtime

The E96 real app and E98 synthetic app carry the same frozen helper
and CPython payload. This summary records the changes made by Python
Build Standalone (PBS) before UPS Monitor packaging and the changes
made when packaging the helper. It applies to the recorded app archives.

## Runtime input

The input is CPython 3.15.2 from PBS release `20261026`, target
`aarch64-apple-darwin`, the `pgo+lto-full` asset. The archive SHA-256 is
`17a41099bba8c18c45c527580014e75dc7a77300f619d7f5cdfecc57aca06f39`.
The input manifest binds the asset to PBS revision
`fa506e0858ac9f2cc5b289c137b888a2aa24d1ee` and records the hash of
`PYTHON.json`. [Pinned input](../backend/nut/bundled_python_runtime_inputs.json) ·
[PBS build script](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/build-cpython.sh)

## CPython source changes in the PBS build

The pinned recipe selects the changes below through its unconditional
and CPython 3.15.2 version branches. The package inspection establishes
the identity of the shipped payload. The PBS patch-application log
for the release asset is unavailable here.

| Area | Change recorded in the pinned PBS sources |
|---|---|
| Build-time freezing | PBS changes `configure.ac` to use the supplied Python and `Programs/_freeze_module.py` for freezing, including in non-cross builds that otherwise use the in-tree bootstrap. A Makefile target writes a wrapper exposing `PYTHON_FOR_BUILD`. [Freeze configuration patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-always-build-python-for-freeze.patch) · [Build Python wrapper patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-write-python-for-build-3.12.patch) |
| Apple shared-cache detection | PBS changes `_ctypes` to use the Apple platform availability check for the dyld shared-cache query, removing the older fallback that looked up the function through `dlopen` and `dlsym`. [ctypes patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-ctypes-callproc.patch) |
| Runtime library path | PBS changes how CPython finds the standard library relative to the runtime library. The patch attempts to resolve the library path for static as well as shared builds and corrects the parent-directory calculation. Its `/proc/self/maps` logic is Linux-specific. [Library path patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-python-getpath-library.patch) |
| Tcl library search | The Unix `_tkinter` patch looks under Python's installation prefix for Tcl's library directory. This is a recipe change. The helper's inclusion of Tcl/Tk requires separate payload evidence. [Tcl lookup patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-tkinter-3.14.patch) |
| Profile-guided optimization (PGO) | PBS adds LLVM profile diagnostics and switches instrumented runs to a mergeable pool of profile data files. These changes affect how the interpreter is built. [PGO statistics patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-pgo-print-statistics.patch) · [PGO profile pool patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-pgo-file-pool.patch) |
| Relocatable build details | The Makefile generates `build-details.json` with paths relative to its installed location. [Build details patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-python-relative-build-details.patch) |
| Internal C API test module | PBS declares the JIT entry symbol as external in `_testinternalcapi` to avoid a duplicate definition. [Test module patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-testinternalcapi-interpreter-extern.patch) |
| POSIX build compatibility | PBS includes the syscall header when configure finds it. Separate Linux-gated fallback code supplies raw system calls for `copy_file_range` and `memfd_create` when libc wrappers are missing. [Header patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-posixmodule-sys-syscall-header.patch) · [Fallback patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-posixmodule-syscall-fallback.patch) |
| Certificate lookup | PBS adds a Linux-only fallback in `ssl.py` for certificate files and directories on older Red Hat and Fedora systems. The source patch is applied by the recipe without a platform check. The added branch checks for Linux at runtime. [Certificate lookup patch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/patch-cpython-redhat-cert-file.patch) |

The optional 3.15 getpath backport is selected by the recipe only if
its file exists. The exact path query at the pinned revision found no
such file. The Darwin shared-library packaging branch separately
sets a relocatable install name for `libpython` and rewrites the zlib
reference to the system library. Those are upstream binary packaging
steps. [PBS build script](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/build-cpython.sh#L733-L737) ·
[Darwin packaging branch](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/build-cpython.sh#L812-L856)

## UPS Monitor packaging changes

| Step | Change and evidence |
|---|---|
| Stage and normalize | The stager verifies the PBS archive and metadata, then selects the install tree, metadata and licenses as build inputs. The normalizer copies those files into a private build input tree and sets file modes for the copied Mach-O and data files. For example, it changes the staged `libpython3.15.dylib` mode from `0775` to `0755` while keeping the same file SHA-256. [Stager](../backend/nut/stage_bundled_python_runtime.py) · [Normalizer](../backend/nut/normalize_bundled_python.py) |
| Freeze the helper | PyInstaller 6.22.3 runs under the normalized PBS interpreter using locked offline wheel inputs. The output combines its arm64 bootloader and loader, the `pyi_rth_inspect` runtime hook, project entry-point code and selected Python imports. The recorded `CArchive` has 8 entries and the `PYZ` has 157 module names. The separate `base_library.zip` has 152 entries. Nine UPS Monitor runtime modules remain as external source in `ManagedOperationalRuntime/`. [Frozen build recipe](FROZEN_BUILD_RECIPE.md#build-the-helper-in-a-new-workspace) · [Helper specification](../backend/nut/UPSOperationalHelper.spec) |
| Package the shared library | The helper keeps `libpython3.15.dylib` in `Contents/Frameworks/` and provides an internal resources link. The final library has a different whole-file SHA-256 from the normalized build input. All 17 checked file-backed Mach-O sections match the normalized PBS copy. The final install name is `@rpath/libpython3.15.dylib`. These are binary packaging observations. The recipe contains no UPS Monitor patch step for CPython source. |
| Sign and assemble | The build checks the nested helper and library signatures and assembles the helper with the separately signed app and widget. E96 and E98 use the same helper executable, shared library and standard-library ZIP. Their native producers differ. Signing changes whole-file identity where applicable and provides no evidence of a Python source change. |

`PYZ` and ZIP counts describe the frozen artifacts. Modules, build tools and
wheels in the full PBS or developer-input archives are outside that subset.
See the metadata map for the declared extensions and separate notice scopes.
[Python runtime license inventory](PYTHON_RUNTIME_LICENSE_INVENTORY.md) ·
[Distribution readiness](DISTRIBUTION_READINESS.md#cpython-dependency-and-notice-map)

## Verified app payloads

The two app inventories agree on all 14 helper entries and the
complete runtime notice directory. The archive and key file
digests below identify the checked artifacts.

| Item | SHA-256 |
|---|---|
| E96 real app archive | `8dbc984cce32fbb111a498e8353b94f445fe0470aee17aa4c06bd4ddaff878b3` |
| E98 synthetic app archive | `a434827080b11f8d54d99dadd37a38bebe013de9e78c88e3056d4df8ebe70332` |
| Shared helper executable | `c7ee7402443a459891c21d174c443a70ea56458767def3deaee0c31eecce94b7` |
| Shared `libpython3.15.dylib` | `ffd41320665033f914dc13c6257864885963c4d87f6c0f658a734cb47d31bd0a` |
| Shared `base_library.zip` | `bea71056fdb4f88bdbeaf8688eeca7152ed3eaae15406ef42c83133e28b7311a` |

Retain the archive's extended CPython license
(`Contents/Resources/RuntimeNotices/python-LICENSE.cpython.txt`),
the complete notices and their `manifest.json` index. The extended file
is the exact one from the pinned PBS payload. Include this summary
with the release material for the identified runtime. PSF §2 covers
retention of the license and copyright notice. PSF and CNRI §3 describe
the change-summary requirements under their respective terms.
[Versioned CPython terms](https://github.com/python/cpython/blob/v3.15.2/LICENSE) ·
[Retained extended text](../third_party/frozen-runtime/python-LICENSE.cpython.txt) ·
[Notice index](../third_party/frozen-runtime/manifest.json)

The runtime change summary applies to the helper shipped in these
app archives. A mirror of the entire PBS archive or developer-input
kit has a separate inventory and distribution scope.
