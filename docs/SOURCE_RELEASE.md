# Source-Only Preview Archive

This procedure describes the source distribution workflow for
`0.1.0-preview.1`. Publication status, the exact commit, checksums and completed
checks belong to the [release page](https://github.com/pettipol/ups-monitor-macos/releases),
not this procedure. The coordinating maintainer chooses and records the reviewed full
commit and creates any tag or release only after the relevant acceptance
checks. A source-only preview is not an app release, a signed or notarized
binary, or evidence of hardware compatibility.

## Create

From the repository root, select the reviewed full commit explicitly. Use a
new output directory outside the repository. `git archive` reads that commit's
tracked tree, not the working tree: uncommitted and untracked files are not
included, and `.git` metadata is not included. Review the committed tree and
archive listing for accidental private material before distribution.

```bash
set -euo pipefail

FULL_COMMIT='<reviewed-full-commit-hash>'
OUTPUT_DIR='<new-empty-output-directory-outside-repository>'
ARCHIVE='ups-monitor-macos-0.1.0-preview.1-source.tar.gz'

test "$(git rev-parse --verify "$FULL_COMMIT^{commit}")" = "$FULL_COMMIT"
test ! -e "$OUTPUT_DIR"
mkdir -m 700 "$OUTPUT_DIR"

git archive --format=tar \
  --prefix='ups-monitor-macos-0.1.0-preview.1/' \
  "$FULL_COMMIT" | gzip -n > "$OUTPUT_DIR/$ARCHIVE"

(cd "$OUTPUT_DIR" && shasum -a 256 "$ARCHIVE" > "$ARCHIVE.sha256")
```

Record the full commit hash, `VERSION`, archive SHA-256, and Git and gzip
implementations/versions used. `gzip -n` omits the original filename and
timestamp from the gzip header; it does not promise byte-identical compressed
output across different gzip implementations or versions. Reproduction of the
same archive bytes requires the same commit, commands, and tool versions.

The archive contains the tracked project tree, including code, documentation,
tests, fixtures and notices. It does not include `.git` metadata or ignored or
untracked build output or workbench files. The source-only distribution must
not add a NUT client, daemon, UPS driver, or libusb binary. It includes the
repository's NUT-derived patches and their GPL-2.0-or-later notices; those
materials are not relicensed as MIT.

## Verify Before Extraction

Check the checksum and inspect the archive member list before extracting. Do
not extract over an existing directory.

```bash
set -euo pipefail

cd '<output-directory>'
shasum -a 256 -c ups-monitor-macos-0.1.0-preview.1-source.tar.gz.sha256
tar -tzf ups-monitor-macos-0.1.0-preview.1-source.tar.gz
```

Confirm that every member is under the expected versioned prefix and that the
contents match the reviewed tracked tree. Then extract into a fresh directory
and run the repository's documented validation from its root:

```bash
set -euo pipefail

EXTRACT_PARENT='<new-empty-extraction-parent>'
test ! -e "$EXTRACT_PARENT"
mkdir -m 700 "$EXTRACT_PARENT"
tar -xzf '<output-directory>/ups-monitor-macos-0.1.0-preview.1-source.tar.gz' \
  -C "$EXTRACT_PARENT"
cd "$EXTRACT_PARENT/ups-monitor-macos-0.1.0-preview.1"
bash scripts/check.sh
```

This validates the extracted source using the pinned local toolchain and
produces the documented ad-hoc build checks; it does not launch the app,
run the widget, access UPS hardware, or qualify compatibility. Xcode may
register its build products with LaunchServices as part of a normal build;
that is not proof of installed widget selection or rendering.
Keep binary download, signing, notarization, widget registration, and hardware
claims as separate open gates.
