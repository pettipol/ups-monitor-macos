# Local History

`UPSHistoryStore` stores validated `MonitorSnapshot` values in a dedicated
directory supplied by its caller. It never selects a path or opens a database
from the user's home directory implicitly.

The caller supplies a file URL to a private directory owned by the current user.
The directory and `history.sqlite3` file must be private (`0700` and `0600`).
New locations are created with those permissions. Existing locations with
unexpected permissions, symlinks, unknown application identifiers, schema
versions, or schema objects are rejected. SQLite opens use no-follow mode.
Schema version 1 uses SQLite from the Apple SDK, DELETE journaling, FULL
synchronization, secure delete, `trusted_schema=OFF`, and a bounded busy
timeout. It has no migration path.

Each record contains at most 64 KiB of typed JSON and indexed provider, source,
session, and capture-time fields. Reads validate the JSON and require the
indexed fields to match the decoded snapshot. An identical sample at the same
source/session/time is idempotent; a different sample at that key is rejected.
Append, duplicate checking, and age/row-count pruning share one transaction.
The caller-provided `now` time controls retention; future samples and samples
outside the retention window are rejected before mutation. `prune(now:)` runs
the same retention rules explicitly. Queries require an explicit source and
time interval and have a maximum row limit.

Bounded session summaries and cursor-based pages support the separate history
browser. See [catalog, pagination and displayed-page export](HISTORY_BROWSING.md).
Reads do not prune: retention is enforced on append or explicit prune, not as a
strict read-time expiration policy.

JSON export contains validated typed snapshots. CSV export covers only the
bounded query (up to its 10,000-row cap) and uses long-form status and metric
rows. It keeps the readable ISO-8601 timestamp and adds the numeric
`captured_at_reference_seconds` column, measured from Foundation's reference
date, 2001-01-01T00:00:00Z. Its `String(Double)` value round-trips the capture
instant at the stored `Date` precision, including submillisecond differences.
Missing values remain empty cells and finite zero remains `0`; metric unit,
quality, and provenance remain explicit. Cells are quoted and spreadsheet
formula prefixes are guarded for text cells. Typed numeric cells retain their
sign and are not formula-prefixed.

Deletion and `clear()` remove records visible through the application. SQLite's
`secure_delete` setting is enabled and checked, but this is not a promise of
physical erasure from SSD storage, filesystem snapshots, backups, exports, or
operating-system caches. History has not been qualified against real UPS
hardware.
