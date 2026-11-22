# Frozen runtime notices

This directory retains 23 original license texts byte for byte, plus this guide
and a hash manifest. The flat `python-` filenames correspond to the original
`python/licenses/` names recorded in the manifest. The assembly tool copies the
directory to the outer app's `Contents/Resources/RuntimeNotices/` before signing.
It does not change the independently verified helper or runtime closure.

## Scope of the retained materials

- **CPython 3.15.2 / python-build-standalone 20261026:** all 20 license files from
  the pinned full distribution are retained. This is deliberately conservative:
  inclusion of a text does not establish that every component of the full Python
  distribution is present in, used by, or applicable to the smaller frozen helper.
  Five texts were not referenced by the distribution's component metadata and
  remain marked as retained/unmapped. The build repository's MPL license is not
  assigned to the resulting Python payload.
- **PyInstaller 6.22.3:** the complete COPYING text includes its GPL terms,
  bootloader exception, and Apache terms. The observed helper contains the
  bootloader/loader code, its icon, and the Apache-licensed `pyi_rth_inspect`
  runtime hook. The exception is not a blanket MIT relicensing of dependencies.
- **pyinstaller-hooks-contrib 2026.9:** its complete LICENSE is retained as build
  provenance. No contrib runtime hook was observed in the qualified helper's
  script table; its presence here does not claim one was embedded.
- **UPS Monitor:** the project MIT notice applies to original project code.
  It does not relicense Python, PyInstaller, NUT, or other third-party material.

The frozen build also used altgraph, macholib, packaging, and setuptools. Their
packages were not observed in that helper's output tables. Build environment
licenses remain relevant to that environment; this directory does not claim
that every tool or vendored dependency is embedded in the app.

## Verification and limits

The manifest records versions, original archive members, hashes, upstream URLs,
and the observed helper's build-table identity. Its PBS binding checks the input
identity declared by the runtime manifest, not the legal applicability of each
text or the contents of an arbitrary rebuilt executable. Reconcile the actual
payload again whenever its inputs or build graph change.

## App variants and native notices

The project has two separate local app variants. The real SMC1500I path bundles
a source-built NUT/HIDAPI native producer. Its app carries the eight files in
`Contents/Resources/NativeProducerNotices/`: three NUT notice texts, four
HIDAPI license texts, and a README recording the selected HIDAPI BSD-style
option. The synthetic path bundles the project's fixture producer, uses a
`.synthetic` app identifier and `UPS_WIDGET_FIXTURE_MODE=YES`, and is for
fabricated-data checks without a real UPS. The native notices describe the real
NUT/HIDAPI producer; they do not identify the fixture producer.

Both paths can carry the same frozen Python helper and its separate
`Contents/Resources/RuntimeNotices/`. Read each app's native producer and bundle
contents before attributing a notice to that app. Copy verification and code
signing do not establish complete license compliance or release readiness.

The assembly receipt reports the historical helper executable SHA-256 recorded
in this notice manifest and the current helper SHA-256 verified from the runtime
manifest. It also reports `EXACT_EXECUTABLE_MATCH` or
`DIFFERENT_EXECUTABLE_REVIEW_REQUIRED`. A difference keeps the build usable for
assembly but calls for inspection of that helper's embedded modules, runtime
hooks and libraries. A match does not identify the native producer variant or
clear the separately bundled libraries. `COPY_VERIFIED` means only that the
listed notice files were copied and rechecked; `redistribution_review` remains
`NOT_PERFORMED` in either case.

Original primary texts: [PyInstaller](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/COPYING.txt),
[hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/v2026.9/LICENSE),
[CPython](https://github.com/python/cpython/blob/v3.15.2/LICENSE).
The Python files retained here are those supplied in the pinned PBS archive,
including its extended CPython license text; they are not replacements copied
from a different source revision.
