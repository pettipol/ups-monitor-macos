# Bounded cleanup diagnostics

An optional [first-IO source profile](../backend/nut/native-build/first-io-v1/README.md)
adds a separate `UPS_FIRST_IO_TRANSITION_V1` record and
`first-io-transition.json` to a staged candidate. It retains cleanup v1 and
the public feed schema. The record can be absent if cleanup does not reach
its emission point. This profile does not change the canonical runner or
qualify hardware behavior.

The operational Python runner can preserve a small diagnostic from native
stderr in `cleanup-diagnostic.json`. This separate artifact does not change
sample/end schema 2, the managed receipt, cancellation, or ownership decisions.
A failed capture remains failed, even if the diagnostic reports a clean close.

The native diagnostic producer remains a separate candidate. Successful parser
and synthetic streaming tests do not qualify a native build, hardware Stop,
daily monitoring, or the installed widget.

## Record and correlation

Only a line starting with `UPS_CLEANUP_DIAG_V1 ` is parsed. It must contain one
ASCII JSON object with exactly 18 scalar fields and end in LF, with a total
limit of 1,024 bytes. Duplicate fields, duplicate records, unknown fields,
non-integer numbers, strings, nested data and out-of-range values are rejected.
Foreign stderr is discarded after counting and hashing; it is never copied
into the sidecar. Raw capture files remain empty.

The sidecar has exactly these keys:

| Key | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `kind` | `ups-monitor.cleanup-diagnostic` |
| `state` | `absent`, `valid`, `invalid`, or `incomplete` |
| `error_code` | A fixed parser code, or null |
| `native_sha256` | Executable hash admitted by the runner |
| `stderr_eof` | Actual stderr EOF observed at this snapshot |
| `stderr_bytes` | All stderr bytes observed at this snapshot |
| `stderr_sha256` | Hash of those same bytes, including foreign stderr |
| `diagnostic` | Validated fields only when state is `valid`; otherwise null |

Correlate with the original managed receipt using the executable hash and
runner stderr count/hash. Never join records by device name or similar readings.
The app's receipt archive is described in [OPERATIONAL_RECEIPT_ARCHIVE.md](OPERATIONAL_RECEIPT_ARCHIVE.md).

`absent` means both streams reached EOF without a diagnostic. A missing file
instead means persistence was not performed, failed, or the artifact was not
retained. Neither means that native cleanup succeeded. `incomplete` preserves
uncertainty from a partial line or a stream that was not final at the first
runner return. Later retained-owner observation never rewrites this snapshot.
Resolved pipe EOF does not by itself resolve a blocked consumer or ownership.

The native fields describe reason and health before/after cleanup, the four
existing cleanup results, whether cleanup and its write callback were attempted,
the normalized callback count, and the observed cleanup interval. Callback
counts are not raw HIDAPI error codes: the native adapter can normalize them.
The cleanup interval uses existing clock observations and is not the duration
of an individual USB write. It can be valid while total session elapsed time
is invalid; the two intervals have different origins.

## Persistence and runtime admission

The runner snapshots the parser and accounting together, once, after its
existing drain/join sequence. Publication uses the admitted private output
directory descriptor, an exclusive temporary file, file fsync and close,
then a no-replace hard link. Files are mode 0600 and at most 4,096 bytes. An
existing final or temporary file is never overwritten. Persistence failures
do not alter the measurement result or cancel event and have no raw fallback.

The private directory is the trust boundary. This does not protect against a
hostile concurrent process running as the same user replacing a temporary name
between the final identity check and publication. A failed close is not retried
because the descriptor state is ambiguous; it may remain open. A failed unlink
may leave the bounded temporary file. No directory-fsync or crash-durability
guarantee is made.

`cleanup_diagnostics.py` is part of the exact nine-module operational admission
set in Python and Swift. It is imported only by the operational streaming
path. The older bounded runner does not require the parser. Frozen manifests
and historical replay pins remain unchanged: rebuilt bundles need new hashes.
These source changes alone do not update an installed app or admit a new native
executable.

## Offline verification

`scripts/check.sh` includes the pure parser and synthetic streaming suites.
The streaming fixtures use finite synthetic Python children and generated data;
they do not launch a UPS driver. Coverage includes foreign-byte accounting,
chunk boundaries, cancellation drain, truncated output, consumer failure,
exclusive publication, write/fsync/close/link faults and immutable unresolved
snapshots. Runtime admission tests use inert generated files.
