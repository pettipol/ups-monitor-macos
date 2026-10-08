# Application Snapshot and History Contract

This is the P2 implementation contract, not evidence of working storage or UI.

## Shared Snapshot

`UPSModel` depends on `UPSCore` and `NUTData`; it performs no I/O. It supplies a
versioned, Codable, Equatable, Sendable `MonitorSnapshot` shared by the app,
history and future widget. Source backends remain separate, never merged by name.

Required public shape (implementation may add typed supporting enums):

- `MonitorSource`: `provider` (Apple or NUT), caller-generated `id`, `sessionID`,
  `identityStability` (session-local or configured). No names or hardware IDs.
  ASCII IDs are 1...64 bytes, start with an alphanumeric, and contain only
  alphanumerics, period, underscore or hyphen. Apple's ordinal IDs are not
  stable device identity; an explicit caller session is required.
- `MonitorSnapshot`: `schemaVersion` fixed to 1, `source`, `capturedAt`, typed
  `status`, and `[MonitorMetric]`. Each metric has allowlisted ID, value, unit,
  quality and provenance. Reject duplicate metric IDs and more than 64 metrics.
- `validate()` throws for incompatible schema, invalid source/date, non-finite
  values, inconsistent value/quality or ID/unit pairs. Codable decoding also
  validates; storage revalidates before accepting caller-constructed values.
- Missing/invalid/calculating values are nil, not zero. Finite zero is valid.
  Percent battery charge is 0...100, load may exceed 100. Preserve nominal
  ratings, W/VA, estimated runtime and driver-derived power separately.
- Apple `sourceCurrent`/`sourceTemperature` remain source-location fields;
  do not relabel them as battery measurements without evidence.
- Preserve native time-to-full, charging boolean, battery health and internal
  failure, including false versus absent. Input mains state, output-off and
  native source-offline are distinct; no generic off state may conflate them.
- Backend input units and dictionary-key/measurement-ID agreement are checked
  before conversion, not silently overwritten by expected target units.
- Adapter methods accept an explicit `MonitorSource`. Apple requires a present
  UPS and rejects internal batteries. NUT requires matching caller source ID.
  Preserve raw backend status uncertainty instead of inventing a mains state.
- Freshness is evaluated separately from measurement quality using caller time
  and age limit. A failed acquisition makes last-known data stale immediately;
  negative/non-finite age or invalid policy is never fresh. It does not retime
  cached data or make stale samples eligible for integration.

No raw vendor dictionaries, experimental energy, guessed power factor or
generated watts enter this format. It does not itself make power eligible for
the independent energy integrator. It is not a polling coordinator.

## History

`UPSHistory` depends on `UPSModel` and Apple SDK `SQLite3`. The verified local
runtime is SQLite 3.54.0; no separately installed SQLite engine is adopted.
Use a dedicated directory passed explicitly by the caller, never infer or open
an existing user database. Tests use only new temporary directories.

- Actor-serialized SQLite connection, prepared/bound statements, schema version
  and application identifier. Unknown existing files/schemas fail closed, not
  erased or migrated speculatively. Explicit close and reopen must work.
  Check the complete schema object allowlist, including unexpected triggers.
- Directory 0700 and DB 0600; refuse final directory/database symlinks. Do not
  chmod arbitrary preexisting directories or follow a preexisting DB symlink.
- One writer with DELETE journaling, FULL synchronization and secure_delete=ON.
  Validate pragma results and use a short bounded busy timeout. Widget reads
  an atomic shared snapshot later, not this database.
  Open with SQLite NOFOLLOW, disable trusted_schema, require a file URL and
  current-user ownership. This is not protection against a hostile same-user
  process concurrently replacing an ancestor directory.
- Append validated snapshots as typed JSON plus indexed source/time metadata.
  Re-reading validates payload and its agreement with indexed metadata.
  Repeated identical samples are idempotent; conflicting data at the same
  source/session/time is an error, not a silent overwrite.
  Compare validated decoded snapshots, not encoded bytes: Set element order
  is not semantic data. Limit each stored payload to 64 KiB before copying or
  decoding it. Insertion, duplicate handling and pruning share one transaction;
  an error rolls back all mutations from that append.
- Bounded time-range queries, explicit source/session, deterministic order and
  row cap. Retention by age and global row count; do not bridge missing time.
  `append(_:now:)` uses an explicit injectable acquisition/retention clock,
  defaulting to the caller's current wall time, never the sample timestamp.
  Reject future captures and samples older than the retention window; neither
  rejection may delete stored history. An explicit `prune(now:)` applies the
  same policy without a new sample. A valid caller clock is required; no
  protection against an incorrect system clock is claimed.
- JSON and long-form CSV exports contain only typed records, units, quality,
  provenance, source/session and timestamps. Preserve zero versus absent values
  and status-only samples. No raw SQL, paths, or upstream error text in errors.
  Numeric CSV cells retain their numeric sign; spreadsheet formula escaping
  applies to text cells only. Export covers exactly the bounded query, not an
  implicit promise to export all rows in an unbounded history.
- Explicit deletion/clear removes app-visible history; do not claim secure
  erasure from SSDs, snapshots, Time Machine, exports or operating-system caches.

SQLite's [secure_delete documentation](https://www.sqlite.org/pragma.html#pragma_secure_delete)
was checked through BrowserOS on 2026-10-08. Its overwrite behavior is a
database-level measure, not a promise of physical erasure or backup deletion.
