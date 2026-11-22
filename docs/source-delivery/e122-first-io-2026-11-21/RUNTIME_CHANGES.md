# Runtime change and payload identity summary

This recipient-specific technical note binds the E122 helper payload to its pinned runtime inputs. The public project change summary describes E96/E98; this note records the distinct E122 helper, library, ZIP and notice-manifest identities. It does not assert a source rebuild or prove runtime use of every declared component.

## E122 payload observed

| Item | Bundle-relative path | Bytes | SHA-256 |
|---|---|---:|---|
| Frozen helper executable | `Contents/Helpers/UPSOperationalHelper.app/Contents/MacOS/UPSOperationalHelper` | 2,053,344 | `5196e5ffbaa4ef638e8f5229db0dc523693ff429c0b8ba29bbfe0789d0648eee` |
| CPython shared library | `Contents/Helpers/UPSOperationalHelper.app/Contents/Frameworks/libpython3.15.dylib` | 20,361,632 | `ffd41320665033f914dc13c6257864885963c4d87f6c0f658a734cb47d31bd0a` |
| Standard-library ZIP | `Contents/Helpers/UPSOperationalHelper.app/Contents/Resources/base_library.zip` | 1,424,864 | `528ab1e1c75fae2f608e7fa5d5023f5510117dd57fcc8950bb7328f279043c6f` |
| Frozen runtime manifest | `Contents/Resources/ManagedOperationalRuntime/frozen-runtime-bundle.json` | 1,795 | `fc17aa831ea72af31dcdf2c39a8ab0e2f53552ddd73143e648390e79300dd4d5` |
| Runtime notice manifest | `Contents/Resources/RuntimeNotices/manifest.json` | 9,094 | `29b970b594e4dc4098a4021ffb3292b7f44de2cf0f87c1492d7b3df2e2130290` |

The ZIP path above is the regular file; the helper's `Contents/Frameworks/base_library.zip` is an internal symbolic link. The payload manifest declares arm64, minimum macOS 27.0, CPython 3.15.2, and PBS release 20261026.

## Pinned runtime and build materials

- PBS CPython asset: `cpython-3.15.2+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst`, SHA-256 `17a41099bba8c18c45c527580014e75dc7a77300f619d7f5cdfecc57aca06f39`; `PYTHON.json` SHA-256 `6256d1667b03c2f582c7ba0b4c058f59acd02c8b1819ceca3ce904349e13e1bc`; PBS revision `fa506e0858ac9f2cc5b289c137b888a2aa24d1ee`.
- PyInstaller 6.22.3 wheel SHA-256 `052f4a1cd4f81092ccb7a18fe8ebc9ecf832a5917317e39fb3775af4e959b253`; hooks-contrib 2026.9 wheel SHA-256 `fb3e67dd64122561724c48ad0366ac9e8c16e638b63bf7d85de03bf3fdbf06c3`.
- E122's helper SHA exactly matches the helper inspected in the versioned [frozen payload inventory](https://github.com/pettipol/ups-monitor-macos/blob/01e8e67e29db2fbf1ba7bcfb11f9aa32251323c3/docs/FROZEN_PAYLOAD_COMPONENTS.md#L10-L13). That inspection recorded eight CArchive entries, 157 PYZ names, and `pyi_rth_inspect`; this same-byte helper identity supports transferring those helper-content observations. It does not transfer E80's native producer evidence. The applicable source and notice/NOTICE pairing for the hook remains open for distribution review.
- E122 carries 25 regular runtime notice files: its manifest, README, and 23 license texts. Twenty PBS license texts are retained; five have no `license_paths` reference in the pinned PBS component metadata. The manifest groups all 20 under `cpython-pbs`; use the [component/notice inventory](https://github.com/pettipol/ups-monitor-macos/blob/01e8e67e29db2fbf1ba7bcfb11f9aa32251323c3/docs/PYTHON_RUNTIME_LICENSE_INVENTORY.md) for the declared 18 component/variant records and unresolved mapping boundaries.

## Recorded change scope and open work

The pinned PBS recipe records upstream CPython build changes in freeze configuration, Apple `_ctypes` cache detection, runtime library path resolution, Tcl lookup, PGO, relative build details, an internal C API test symbol, POSIX syscall compatibility, and certificate fallback. The specific PBS patch-application log for this release asset is unavailable; the recipe selection and shipped payload identities are distinct evidence. See the [versioned PBS build script](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/build-cpython.sh) and the current [runtime packaging summary](https://github.com/pettipol/ups-monitor-macos/blob/01e8e67e29db2fbf1ba7bcfb11f9aa32251323c3/docs/CPYTHON_RUNTIME_CHANGES.md).

The project packaging record describes staging and normalization, PyInstaller freezing, shared-library packaging and signing. The E122 runtime differs from the helper identities published for E96/E98; those older whole-file values are not substitutes for the E122 pins above. The app archive does not contain a standalone CPython change summary, so retain this note alongside the recipient-specific pairing materials.

The E122 standard-library ZIP decodes to 152 named entries, matching the E96 and E109 decoded entry sets; container hashes are E96 `bea71056fdb4f88bdbeaf8688eeca7152ed3eaae15406ef42c83133e28b7311a`, E109 `9b70e8f4d4bf1c53abac1b9a01be0ba66acf86b0dd719d5274db3ff6bcafe997`, and E122 `528ab1e1c75fae2f608e7fa5d5023f5510117dd57fcc8950bb7328f279043c6f`. The full E96 digest is from the checked regular ZIP member of the E96 app archive. The immutable E106 source archive retains a truncated historical ZIP metadata value; do not use that truncated value as an archive identity. This ZIP comparison does not transfer historical helper executable or native producer evidence to E122.

Still open for distribution review: reconcile the exact E122 helper contents and included libraries/extensions against the PBS metadata and applicable source forms; resolve the five unmapped retained license texts and any dependencies not established as present; review applicable PyInstaller bootloader/hook source and notices; and complete the distribution review. E122's runtime manifest explicitly records `redistribution_review: NOT_PERFORMED`. This note is technical evidence, not legal advice, a compatibility determination, or clearance.
