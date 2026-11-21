# Cancellation before a native HID write

This optional source candidate distinguishes cancellation detected immediately
before `hid_write()` from a negative result returned by `hid_write()`. It applies
to the reconstructed operational V2 source after the CAL patch. The earlier
build manifest and installed preview retain their recorded identities.

## Behavior and contract

The native adapter returns `MLINK_WRITE_CANCELLED_BEFORE_IO` only when an
ordinary write is cancelled before calling HID. Actual negative HID results
are normalized to `-1` in V2. After leaving the host callback, shared transport
accepts the distinct cancellation result only with an admitted session in
STARTING or ACTIVE phase,
no previous failure and a confirmed Stop request. It uses the existing Stop
transition. Genuine negative and short writes remain failures, including when
Stop arrives immediately afterward. Cleanup keeps its single-attempt rule.

Compile the native adapter, shared transport and shared host header together.
Their function signatures and layouts are unchanged, but the V2 callback return
contract has changed. Mixing these files with an older or external callback
that returns generic `-2` values is unsupported. V1 behavior is preserved.

The historical H13 acquisition produced real telemetry but failed the normal
Stop acceptance criterion. Its saved diagnostics do not establish whether this
cancellation race caused its initial IO state. Correcting the simulated race
does not retrospectively change that hardware result.

## Offline comparison

First reconstruct the 190-file post-CAL source using sections 1 and 2 of the
[native build recipe](README.md). Keep that source unchanged for the comparison.
The two pinned HIDAPI headers must be staged under `drivers/hidapi-candidate`.
The comparison has no native-HID execution option.

With absolute paths already set for `HOST_PYTHON`, `CHECKOUT_ROOT`, `SRC` and a
new `REPLAY_OUTPUT` directory outside the source and checkout, run:

```sh
"$HOST_PYTHON" -I -S -B "$CHECKOUT_ROOT/backend/nut/replay_hidapi_write_cancel.py" \
  --source-dir "$SRC" --output-dir "$REPLAY_OUTPUT"
```

The replay verifies all 190 source hashes, the candidate manifest and patch,
the existing fixture and the two HIDAPI headers. It builds temporary copies
with original and corrected adapters. Each copy runs the original V1 and V2
native suites and ten cancellation/error cases. Before each matrix, the binary
must link only libSystem, define its synthetic HID functions and have no
hardware or network imports covered by the audit. The hash used for execution
is the hash checked at that audit. Binaries and scratch are removed afterward.

`RESULT.json` must report `PASS_FAKE_ONLY`. Logs are capped at 1 MiB per command,
each process has a deadline, and the campaign checks a 300-second budget.
Compilation uses a private temporary directory. `--developer-dir` can select
an Xcode installation; the default is `/Applications/Xcode.app/Contents/Developer`.
These software limits depend on operating-system scheduling.

Observed on 2026-11-19 with Xcode 27.2 (27B52) and Python 3.15.2:

- Ten boundary cases passed for each variant. Only pre-HID cancellation changed
  from IO to Stop. Actual HID errors, short writes and cleanup failures retained
  their failure outcomes.
- The original V1 and V2 suites passed on both variants.
- Altered source, altered patch, altered manifest and an existing output
  directory were rejected before compilation or output modification.

This replay covers the native/shared adapter boundary. Full driver integration,
app/widget behavior, a new hardware trial and sustained monitoring are separate
acceptance steps. It does not open a device or qualify an installed preview.

## Apply to a new source candidate

Use a private copy of the verified post-CAL source. Before applying the patch,
check the candidate manifest hash
`ae9c3fbb61ba0224dc9929bad2f91e19718b42532ff70ddd74b20f3ecc1cb6a4`
and patch hash
`e11ef7e8f496d35ecf82136cc313a478a1205305f8c5ee858d1e4118d8931f64`.
Apply `nut-write-cancel-boundary-v2.patch` once with `patch --batch --forward
--fuzz=0 -p1` at that source root. Require exit 0 and compare every one of the
190 files with `post_write_cancel_sha256` in
[the candidate manifest](production_source_post_write_cancel.json).
Exactly three source hashes differ from post-CAL.

Continue the native build only after that comparison. Retain a new product
hash and build receipt; the previous post-CAL product hash is not an expected
hash for the changed binary. Building this source does not authorize launching
the driver. The existing packaged previews and their source manifests must not
be relabeled as containing this change.
