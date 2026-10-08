# History Browsing Store API

`UPSHistoryStore.sessions(limit:)` returns recent retained sessions, ordered by
last capture descending and then by provider, source, and session identifiers.
The requested limit must be from 1 through 500; one extra grouped row detects
`hasMore`. A session summary carries its validated source, decoded first and
last capture times, and retained sample count. Only the two boundary payloads
are decoded per session (one when both endpoints share a capture key). The list
is a bounded view of retained history, not a complete device inventory.

`queryPage(_:after:)` preserves the query's inclusive start/end range and source
filter, with ascending capture order. It reads at most `limit + 1` rows and
validates the lookahead record before reporting truncation. `nextAfter` is the
last returned decoded capture time only when another page exists; pass it as an
exclusive cursor to continue. Cursor dates must be finite, representable by the
store's microsecond index, and within the query range. Pagination uses indexed
capture keys, not offsets.

Both APIs validate typed JSON against indexed provider/source/session/time
fields, redact SQLite failures through `HistoryError`, and do not prune during
reads. They do not alter schema or the existing query/export semantics. Tests
use only synthetic snapshots and private temporary stores.

For exporting a displayed page without rerunning its query, call
`UPSHistoryStore.encodeExport(_:format:)` with exactly the page's records. It
validates the typed snapshots and the 10,000-record export cap, then produces
the same JSON or long-form CSV as the query-based export. It does not add,
filter, or deduplicate records.
