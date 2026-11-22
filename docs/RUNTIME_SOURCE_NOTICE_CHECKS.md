# Runtime source and notice checks

This note records two bounded, payload-specific provenance checks. It does not
establish general redistribution readiness or legal clearance.

## PyInstaller `pyi_rth_inspect`

The E122 archive is pinned by SHA-256
`e48ae1588e1aea1509f863d997f78fa2a3fe07723ea41427d0ea57504200ee01`. Its
embedded helper has SHA-256
`5196e5ffbaa4ef638e8f5229db0dc523693ff429c0b8ba29bbfe0789d0648eee`. The
helper's `pyi_rth_inspect` entry was 2,921 marshalled bytes, SHA-256
`ca24500f196bfd784ce10d5b73f404d9350b10b12bd483890eb266905207bffe`.

The locked PyInstaller 6.22.3 wheel SHA-256 is
`052f4a1cd4f81092ccb7a18fe8ebc9ecf832a5917317e39fb3775af4e959b253`. Its
`PyInstaller/hooks/rthooks/pyi_rth_inspect.py` member SHA-256 is
`e9db311f97b750a30a422e0bf2bdcff7514da67cd35b0f6189ad786956ff1abc`, matching
the retained source for tag commit
[`ecd7993d65c43b254f4e3f718e36d5b4a70a3ed5`](https://github.com/pyinstaller/pyinstaller/blob/ecd7993d65c43b254f4e3f718e36d5b4a70a3ed5/PyInstaller/hooks/rthooks/pyi_rth_inspect.py).
Compiling those source bytes with optimization 0 and the pinned Python 3.15.2,
then applying the documented recursive `co_filename` rewrite to
`pyi_rth_inspect.py`, produced the exact 2,921-byte marshal stream above.
The filename transformation follows PyInstaller's
[`archive/writers.py` at the pinned tag commit](https://github.com/pyinstaller/pyinstaller/blob/ecd7993d65c43b254f4e3f718e36d5b4a70a3ed5/PyInstaller/archive/writers.py)
and its code-object helper in
[`building/utils.py`](https://github.com/pyinstaller/pyinstaller/blob/ecd7993d65c43b254f4e3f718e36d5b4a70a3ed5/PyInstaller/building/utils.py).
The packed code object was neither deserialized nor executed. A synthetic
change to the `base_library.zip` constant produced a structural mismatch,
including in `co_consts`.

The full hook source and retained `COPYING` text were checked separately.
The `COPYING` file is byte-identical in the locked wheel, upstream tree,
repository and E122; its SHA-256 is
`0598064c7d2718e38d7914a7d08343b2fa008e3bea9ebba2aa7a6ffa5900dd64`.
The hook's comments and copyright text are not inferred from bytecode. The
bounded NOTICE-name inventory found no dedicated NOTICE path in the locked
wheel or reconstructed PyInstaller tag tree. These results concern this hook
and its retained source and notice inputs; they do not establish that the
entire helper is otherwise unmodified.

## OpenSSL 3.5.9 source and retained license

| Item | Pinned observation |
|---|---|
| PBS-declared source archive | 53,279,637 bytes; SHA-256 `603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a`; [official release archive](https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz) |
| Archive inventory | 6,078 members; no dedicated NOTICE-named paths. Two names contain `userNotice` as part of X.509 source/test material, not as NOTICE documents. |
| Retained license | SHA-256 `7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a`; the release, repository copy, and E122 retained text are byte-identical. [OpenSSL license at the resolved release commit](https://github.com/openssl/openssl/blob/45e844fa2a14ec92d146bd8f5778ac130b6625fb/LICENSE.txt) |
| PBS recipe | [`build-openssl-3.5.sh` at its pinned source revision](https://github.com/astral-sh/python-build-standalone/blob/fa506e0858ac9f2cc5b289c137b888a2aa24d1ee/cpython-unix/build-openssl-3.5.sh), source SHA-256 `a3953acc0acc5122cd51ece0f9ec1795e1b2a60a4a3a9ff58358a0e2be530171`. It extracts the pinned archive and places its source patch inside a Linux-target conditional. This is recipe inspection, not evidence of a completed build or patch application. |

The repository's pinned runtime inputs are recorded in the
[`frozen_build_inputs.json` at the public E125 source revision](https://github.com/pettipol/ups-monitor-macos/blob/053f831ab7ee315439252a33095cce176a211837/backend/nut/frozen_build_inputs.json).
The archive and retained license checks do not establish actual binary
linkage, component-notice applicability, or a completed upstream build log.

These checks close only the stated source and notice questions for the named
payloads. General redistribution review remains **NOT PERFORMED**; widget and
hardware qualification remain open.
