# Reconstructing the historical operational source

This source-only procedure reconstructs the 190-file production checkpoint
used by the historical operational driver. It does not compile or launch a
driver, helper, app, widget or hardware test. It is a prerequisite for a complete
source build, not that complete build.

## Observed local validation — 2026-11-04

One source-only reconstruction matched all 190 files against the separately
retained production archive. Two private input copies, each with one altered
byte in a patch or baseline source, were rejected before creating output.
Four synthetic cancellation tests passed. An earlier unit gate stopped before
any reconstruction because two tests did not expect the sticky cancellation
error again at context exit; those expectations were corrected and that failed
result was retained. No compiler or hardware was used.

The input manifest keeps its frozen `DRAFT_NOT_RUN` admission label to preserve
the reviewed hash. That label is not a run result: require exit 0 and the
generated source receipt described below. This utility remains experimental.

## Fixed inputs

Use macOS and Python 3.15.2 with `-I -S -B`, without optimization. The CLI and
`SOURCE_PREPARATION_INPUTS.json` must remain together in `backend/nut` of the
reviewed checkout. It reuses the pinned continuous source reconstruction and
operational patch manifests. The corrected process supervisor is pinned
separately; the historical replay manifests are not rewritten.

The NUT base is commit
`73c4502191d025e35122463986a80c676e734b04` from
[Network UPS Tools](https://github.com/networkupstools/nut). The required tar
SHA-256 is
`e3ea175565c461a9e741df77dd91103d695b9c60f8d423d9b6ce6c778f98615f`.
This pin identifies the admitted `git archive --format=tar` serialization,
without a prefix, rather than GitHub's generated download tarball. Acquire the
source separately from upstream, preserve provenance, and verify the archive
hash before use. A mismatch is a failure; do not substitute a new pin simply to
make it pass. The reconstruction does not fetch or run Git.

## Source-only invocation

Set `CHECKOUT_ROOT`, `HOST_PYTHON` and `NUT_ARCHIVE` to absolute paths. Use a new
private directory below `/private/tmp` or the system temporary directory. The
CLI's output path must not exist and must not overlap any input. Run this
command through a supervisor with a 300-second overall deadline and at most
1 MiB of captured output; the shell example alone does not impose that limit.

```sh
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/prepare_production_source.py" \
  --backend-dir "$CHECKOUT_ROOT/backend/nut" \
  --nut-archive "$NUT_ARCHIVE" \
  --deadline-helper "$CHECKOUT_ROOT/backend/nut/process_deadline.py" \
  --output-dir "$SOURCE_OUTPUT"
```

Success requires exit 0 and `SOURCE_RECEIPT.json` with `SOURCE_ONLY_PASS` and
exactly the 190 names and hashes in `production_source_post_e28.json`. The
pipeline checks twelve baseline patches, five production patches, two
freshness modules and the diagnostic patch, including complete pre/post
checkpoints. It does not add the operational fake hooks. Some older replay
seams and test sources remain in this historical selection; these 190 files
are not a native compilation allowlist.

Each patch command has bounded time and output. The source tree is checked
against a 128 MiB limit; this is a monitored limit, not an instantaneous kernel
quota. Input verification followed by patch reopening is not atomic against
concurrent mutation. Use a private verified input copy and retain before/after
hashes. Preserve failed evidence; use a fresh output for any separately planned
correction.

## Continue to the native build

This source-only step ends with the verified 190-file tree. The
[native build guide](../backend/nut/native-build/README.md) explains how to
overlay it on the full NUT source, apply the later CAL/freshness changes,
stage HIDAPI sources and notices, and generate the two headers and five
static libraries. That follow-on build passed locally without running the
driver. No electrical control or calibration is part of either procedure.

Source reconstruction does not establish binary reproducibility, hardware
compatibility, clean Stop on a real device, continuous monitoring, signing for
distribution or dependency-license compliance. See
[the build recipe](FROZEN_BUILD_RECIPE.md) for the separate helper/app package
and [validation status](VALIDATION.md) for the evidence boundaries.
