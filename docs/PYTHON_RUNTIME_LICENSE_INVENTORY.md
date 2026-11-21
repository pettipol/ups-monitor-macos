# CPython 3.15.2 runtime license inventory

This inventory reproduces the license names and relative file references recorded in the upstream build metadata for the pinned CPython distribution. It is a metadata map, not a legal analysis or permission to redistribute.

## Pinned input

- Provider: `python-build-standalone`, release `20261026`.
- Asset: `cpython-3.15.2+20261026-aarch64-apple-darwin-pgo+lto-full.tar.zst`.
- Archive SHA-256: `17a41099bba8c18c45c527580014e75dc7a77300f619d7f5cdfecc57aca06f39`.
- CPython metadata `PYTHON.json` SHA-256: `6256d1667b03c2f582c7ba0b4c058f59acd02c8b1819ceca3ce904349e13e1bc`.
- The inventory concerns the full CPython 3.15.2 aarch64 Apple Darwin PGO+LTO candidate. It does not determine whether every included component is used by the application.

## Component declarations

Each row reproduces one component/variant metadata record, its declared license-name strings, and its `license_paths`. A row may name multiple files and multiple terms. The metadata does **not** establish that each individual term applies to every file listed in that row. The table does not infer a linked library’s license from a filename or association.

| Component | Variant | Declared license names | Relative license paths recorded in that metadata row |
|---|---|---|---|
| `python` | `core` | `Python-2.0`, `CNRI-Python` | `licenses/LICENSE.cpython.txt` |
| `_bz2` | `default` | `bzip2-1.0.6` | `licenses/LICENSE.bzip2.txt` |
| `_ctypes` | `default` | `MIT` | `licenses/LICENSE.libffi.txt` |
| `_curses` | `default` | `X11` | `licenses/LICENSE.ncurses.txt` |
| `_curses_panel` | `default` | `X11` | `licenses/LICENSE.ncurses.txt` |
| `_decimal` | `default` | `BSD-2-Clause` | `licenses/LICENSE.mpdecimal.txt` |
| `_hashlib` | `default` | `Apache-2.0` | `licenses/LICENSE.openssl-3.txt` |
| `_lzma` | `default` | `0BSD` | `licenses/LICENSE.liblzma.txt` |
| `_remote_debugging` | `default` | `BSD-3-Clause` | `licenses/LICENSE.zstd.txt` |
| `_sqlite3` | `default` | `Zlib` | `licenses/LICENSE.sqlite.txt`<br>`licenses/LICENSE.zlib-ng.txt`<br>`licenses/LICENSE.zlib.txt` |
| `_ssl` | `default` | `Apache-2.0` | `licenses/LICENSE.openssl-3.txt` |
| `_tkinter` | `default` | `TCL`, `Zlib` | `licenses/LICENSE.tcl.txt`<br>`licenses/LICENSE.zlib-ng.txt`<br>`licenses/LICENSE.zlib.txt` |
| `_uuid` | `default` | `BSD-3-Clause` | `licenses/LICENSE.libuuid.txt` |
| `_zstd` | `default` | `BSD-3-Clause` | `licenses/LICENSE.zstd.txt` |
| `binascii` | `default` | `Zlib` | `licenses/LICENSE.zlib-ng.txt`<br>`licenses/LICENSE.zlib.txt` |
| `pyexpat` | `default` | `MIT` | `licenses/LICENSE.expat.txt` |
| `readline` | `default` | `BSD-3-Clause` | `licenses/LICENSE.libedit.txt` |
| `zlib` | `default` | `Zlib` | `licenses/LICENSE.zlib-ng.txt`<br>`licenses/LICENSE.zlib.txt` |

## License files carried in the payload

The following 20 regular files were present under `licenses/` in the normalized candidate. SHA-256 and byte counts identify the exact files without reproducing their contents. A file shown as “not cited” was copied but had no matching path in the `PYTHON.json` metadata records above; it was retained and not pruned.

| Relative path | Bytes | SHA-256 | Metadata references |
|---|---:|---|---|
| `licenses/LICENSE.bdb.txt` | 7293 | `3bdff06e69991c94664f2ef5c5f8096f60b7dbec071756ea6cc26b445e06ec5b` | Not cited by metadata; retained |
| `licenses/LICENSE.bzip2.txt` | 1743 | `1f38bbc7caacafd65169276d759c0d88c991b753b643ce35d0e45ea1971dd441` | `_bz2` (`bzip2-1.0.6`) |
| `licenses/LICENSE.cpython.txt` | 36164 | `86e61415828a8b5b06ec8d024e6f086ce155a8b85fd0c419c0ba4dc004e74fdd` | `python` (`Python-2.0`, `CNRI-Python`) |
| `licenses/LICENSE.expat.txt` | 1144 | `122f2c27000472a201d337b9b31f7eb2b52d091b02857061a8880371612d9534` | `pyexpat` (`MIT`) |
| `licenses/LICENSE.libX11.txt` | 47018 | `2daec087a88e7c9b8082557cdeebad5bbb8155a4137472f0b22e269cd99d0c1e` | Not cited by metadata; retained |
| `licenses/LICENSE.libXau.txt` | 1148 | `56abe29bb1d9806a9e04fa9f80fed2c0f18027594df3f098148d814aef6bddfa` | Not cited by metadata; retained |
| `licenses/LICENSE.libedit.txt` | 1614 | `29cea33c32bbc9785142386377915612a2fa786482c46843383384aded2e09b1` | `readline` (`BSD-3-Clause`) |
| `licenses/LICENSE.libffi.txt` | 1132 | `deaf3a42effb551a5b140fa9afefed183a27f1341c6d1bf430d106a5e6931fc0` | `_ctypes` (`MIT`) |
| `licenses/LICENSE.liblzma.txt` | 660 | `9a4062de0a2c388a98cf35a35d348b62fa97c838a71c3c28ee1a2d7d0a565b02` | `_lzma` (`0BSD`) |
| `licenses/LICENSE.libuuid.txt` | 1432 | `122ee1f7e258f2c3c0e538a75c037684f420454bf3850ddc74ce750bbf5fe86b` | `_uuid` (`BSD-3-Clause`) |
| `licenses/LICENSE.libxcb.txt` | 1337 | `c5ffbfeaa501071ceeb97b7de2c0d703fdaa35de01c0fb6cbac1c28453a3e9fd` | Not cited by metadata; retained |
| `licenses/LICENSE.mpdecimal.txt` | 1284 | `669512af7219f58be03a398766d7c9da11a3b3df9d3f05cb74c5ceca25c8da3b` | `_decimal` (`BSD-2-Clause`) |
| `licenses/LICENSE.ncurses.txt` | 1447 | `87a4c4442337b8968ef956031c406b74f9cb7149b7ba87311bdaba534816201c` | `_curses` (`X11`); `_curses_panel` (`X11`) |
| `licenses/LICENSE.openssl-3.txt` | 10175 | `7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a` | `_hashlib` (`Apache-2.0`); `_ssl` (`Apache-2.0`) |
| `licenses/LICENSE.sqlite.txt` | 1481 | `38bef3d28b24f145ea293bd3b6eb4b20396982abc8303128fb493986ea5bc719` | `_sqlite3` (`Zlib`) |
| `licenses/LICENSE.tcl.txt` | 2255 | `c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16` | `_tkinter` (`TCL`, `Zlib`) |
| `licenses/LICENSE.tix.txt` | 2826 | `3ac5cdd0bef6c43ce34c6a7ced452081d9e5a0bf94082b9f9147d23ec9e214f5` | Not cited by metadata; retained |
| `licenses/LICENSE.zlib-ng.txt` | 867 | `6c9f0d975b41afaa34d22f55bb8986ce69e5cb7ad327cb2b28820cd425edf5ee` | `_sqlite3` (`Zlib`); `_tkinter` (`TCL`, `Zlib`); `binascii` (`Zlib`); `zlib` (`Zlib`) |
| `licenses/LICENSE.zlib.txt` | 995 | `818922b2620f12801a12bf78e399644a30990e66824abd8ca8ec24d451d6f92c` | `_sqlite3` (`Zlib`); `_tkinter` (`TCL`, `Zlib`); `binascii` (`Zlib`); `zlib` (`Zlib`) |
| `licenses/LICENSE.zstd.txt` | 1549 | `7055266497633c9025b777c78eb7235af13922117480ed5c674677adc381c9d8` | `_remote_debugging` (`BSD-3-Clause`); `_zstd` (`BSD-3-Clause`) |

## Inventory limits

- 15 distinct relative paths are cited by the metadata; all resolve to files in the copied payload.
- 5 copied license files are not cited by those metadata paths: `licenses/LICENSE.bdb.txt`, `licenses/LICENSE.libX11.txt`, `licenses/LICENSE.libXau.txt`, `licenses/LICENSE.libxcb.txt`, `licenses/LICENSE.tix.txt`.
- The uncited files remain part of the payload. This inventory does not infer which component or terms they belong to.
- License-name strings above are declarations in upstream metadata; they are not a compatibility determination, notice-sufficiency finding, or redistribution approval.
- Final distribution review must consider the complete app payload and applicable upstream obligations. No legal review is represented here.
