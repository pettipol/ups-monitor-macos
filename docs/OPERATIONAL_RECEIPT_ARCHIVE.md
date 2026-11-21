# Operational receipt archive

## Purpose

Preserve the original bytes of the final managed operational v2 receipt in the private session directory. The receipt is diagnostic evidence bound to the `launch_id`; its presence does not mean capture succeeded or prove native cleanup.

The v2 protocol is unchanged. The archive uses `managed-receipt.json` (at most 65,536 bytes, one JSON line ending in LF) and a separate `managed-receipt-status.json` summary (schema 1, at most 1 KiB):

```json
{"byte_count":123,"launch_id":"...","schema_version":1,"sha256":"...","state":"valid"}
```

The sidecar `state` is `valid`, `invalid`, or `absent`. The controller also exposes `notRequested`, `pending`, and `writeFailed`; these describe in-memory lifecycle state and do not extend the sidecar schema. The digest and byte count describe the bytes delivered by the final `finished` event. If `outputWithinBounds` is false, they do not include bytes discarded after the stream limit. Invalid raw bytes are never archived.

## Timing and validation

Persistence is attempted once on the `finished` event, after stdout and stderr EOF and process reap. A preliminary `receipt` event does not write files. For the `.operational` profile only, the bytes are validated with `ManagedOperationalReceipt.decode(data, launchID:)`, without requiring `provesCleanup`. A structurally valid receipt that reports unresolved cleanup can therefore be preserved, while the existing gates continue to keep ownership unresolved.

An empty receipt produces `absent`. A malformed receipt, wrong launch ID, oversized receipt, or `outputWithinBounds == false` produces `invalid`. None of these cases creates `managed-receipt.json`. For a valid receipt, the archive is written before the sidecar. A failure in either write sets `writeFailed`, leaves the controller `unresolved`, retains the owner marker, and returns `false` to waiters. Partial or already-renamed files are not removed automatically.

## Atomic write and file safety

`ManagedSyntheticOwner` reuses its pinned root and session directory descriptors and the existing `secureMarker()` check. Each file is written through a deterministic temporary name opened with `O_CREAT|O_EXCL|O_NOFOLLOW` and mode `0600`. The implementation completes the write, calls `fsync` on the file, rechecks identity, mode, and ACLs, publishes with `renameatx_np(..., RENAME_EXCL)`, then calls `fsync` on the session directory. A final-name or temporary-name collision fails closed: there is no overwrite, symlink following, or automatic cleanup. A terminal event is processed at most once, including duplicate callbacks.

The original gates run after the archive attempt: return code, output bounds, cleanup proof, any prior unresolved state, and owner resolution. A failed capture remains failed. A receipt that does not prove cleanup may be archived, but it cannot resolve ownership. The synthetic and native profiles retain `notRequested` and their existing flow.

## Synthetic coverage

`ManagedOperationalSessionTests.swift` covers clean cancellation and byte/hash/mode preservation; a failed `guard_error` receipt; a valid receipt with unproved cleanup; wrong launch ID; absent and oversized output; final and temporary-name collisions and symlinks; sidecar write failure after a valid archive; preliminary receipt events; and duplicate final callbacks. Existing tests continue to cover the strict v2 decoder, failed state, and owner marker. These are synthetic scenarios and do not establish native cleanup success or qualify measurements.

## Limits

This change covers Swift receipt persistence only. It does not implement native stderr diagnostics, interpret the electrical meaning of a receipt, or authorize another hardware trial. No native cleanup diagnostic is claimed to be available by this document.
