# Components in the local E80 preview

This inventory identifies the packaged components in the local E80 development
archive, SHA-256
`fa52c17c719127acb2d85aed6f3cc08f162094b8429e4332c827a32ba46a5eb6`.
It supports review of the exact files selected for a future distribution.

| Packaged component | Recorded origin and notice location |
|---|---|
| Frozen helper `UPSOperationalHelper` | SHA-256 `5196e5ffbaa4ef638e8f5229db0dc523693ff429c0b8ba29bbfe0789d0648eee`. The PyInstaller 6.22.3 reader identified eight CArchive entries and 157 PYZ module names. Loader modules, bootstrap and `pyi_rth_inspect` map to the complete `RuntimeNotices/pyinstaller-COPYING.txt`. The project entrypoint maps to `RuntimeNotices/ups-monitor-LICENSE.txt`. |
| Packaged libpython | The code and data match the library from the pinned CPython 3.15.2 PBS 20261026 distribution. All 20 Mach-O sections match, as does the entire prefix before the signature after normalizing three signature-related size fields. The signature accounts for the remaining size difference. Upstream component declarations and their original texts are recorded in the [runtime license inventory](PYTHON_RUNTIME_LICENSE_INVENTORY.md). |
| `base_library.zip` | SHA-256 `528ab1e1c75fae2f608e7fa5d5023f5510117dd57fcc8950bb7328f279043c6f`. All 152 entry names have corresponding standard-library source paths in the pinned PBS distribution. Each packaged entry was inventoried by size and hash. |
| Project Python modules | Nine source files are present under `ManagedOperationalRuntime/`. The PYZ also names `frozen_runtime_imports` and `managed_bundled_operational_entrypoint`, whose sources are present in the E74 build-source archive. These project modules map to `RuntimeNotices/ups-monitor-LICENSE.txt`. |
| Native MicroLink producer | The packaged binary matches the E73 source build before the signature after the same three size-field normalizations. Its build record identifies the NUT-derived sources, HIDAPI Darwin source and project adapters. `NativeProducerNotices/` carries eight authenticated files. The [native build recipe](../backend/nut/native-build/README.md) records source inputs, patches and the selected HIDAPI license alternative. |

The static parser read archive metadata and compressed-module hashes. Payload
modules and the helper remained unexecuted. The PYZ names provide an inventory
of the packaged namespaces. Source-byte equivalence for each compiled Python
module requires separate evidence.

Of the 157 PYZ names, 155 have corresponding standard-library paths in the PBS
input and two identify the project modules listed above. The same nominal
association covers all 152 ZIP entries. The PBS top-level license declaration
identifies `Python-2.0`, `CNRI-Python` and `licenses/LICENSE.cpython.txt`.
The packaged `RuntimeNotices/python-LICENSE.cpython.txt` matches the
authenticated source text.

## Compiled extensions and retained notices

The packaged libpython symbol table contains 98 defined `PyInit_` names in
instruction-bearing sections. Sixteen of the 17 extension declarations carrying
`license_paths` in PBS metadata have an exact initializer-name match.
For those sixteen, the table below maps the upstream notice paths to the
authenticated files under `RuntimeNotices/`.

| Extension implementation observed | Packaged notice files |
|---|---|
| `_bz2` | `python-LICENSE.bzip2.txt` |
| `_ctypes` | `python-LICENSE.libffi.txt` |
| `_curses`, `_curses_panel` | `python-LICENSE.ncurses.txt` |
| `_decimal` | `python-LICENSE.mpdecimal.txt` |
| `_hashlib`, `_ssl` | `python-LICENSE.openssl-3.txt` |
| `_lzma` | `python-LICENSE.liblzma.txt` |
| `_remote_debugging`, `_zstd` | `python-LICENSE.zstd.txt` |
| `_sqlite3` | `python-LICENSE.sqlite.txt`, `python-LICENSE.zlib-ng.txt`, `python-LICENSE.zlib.txt` |
| `_uuid` | `python-LICENSE.libuuid.txt` |
| `binascii`, `zlib` | `python-LICENSE.zlib-ng.txt`, `python-LICENSE.zlib.txt` |
| `pyexpat` | `python-LICENSE.expat.txt` |
| `readline` | `python-LICENSE.libedit.txt` |

The remaining declaration concerns `_tkinter`. Its initializer was unobserved
in this check, and its declared notices remain included. All 17 declarations
resolve to authenticated packaged texts. Static-library names and license
terms in the upstream metadata retain their status as upstream declarations.
The full set of 23 runtime texts and eight native notice files was preserved.

## Distribution review

The original notice manifest retains the historical helper identity
`96c564fc6ba1e21a0da6dcc0182fcd4cd54a51dd3d328cd69aadfab96967a020`.
This inventory records the current helper identity alongside that history.
The match to the exact PBS library supports use of its declared dependencies
when reviewing the current payload.

Public distribution still requires the maintainer to assess the applicable
terms, corresponding-source delivery where required, and the signing and
installation procedure for the chosen release.
