# History Browser and Plot Contract

History browsing is separate from live source selection and recording. Opening
the browser may open/create the app's own private store but must not enable
recording, change the live source, publish historical samples to WidgetKit or
read hardware. The default recording policy remains off on every launch.

## Store

Add `HistorySessionSummary` with source, firstCapturedAt, lastCapturedAt and
sampleCount; `HistorySessionList` with sessions and hasMore; and `HistoryPage`
with records, hasMore and nextAfter (the final returned capture time when more
records exist). List sessions with a validated limit 1...500 (default 100),
ordered last capture descending then provider/source/session. Group only exact
indexed provider/source/session; decode and validate representative payloads.
Do not expose server names, paths or hardware IDs. Summary timestamps are
catalog metadata; queries must not lose boundary rows from rounding.

`sessions(limit:)` and `queryPage(_:after:)` are read operations, without pruning
or schema changes. `queryPage` keeps the existing query's inclusive range and
source, ascending capture order, maximum limit 10000, and reads at most limit+1
rows to detect truncation. A cursor is exclusive, validated finite and within
the query range; use the same microsecond conversion as indexed records. The
unique indexed identity/time key makes the last decoded capture a safe cursor.
No OFFSET pagination or unbounded payload scan. Validate every returned row and
the lookahead row, matching the existing query's corrupt-record behavior.

## Plot

Add a pure, bounded plot builder and native Swift Charts view. Input is one
exact MonitorSource, one MonitorMetricID, an array of snapshots and an explicit
finite positive maximum gap. Reject malformed snapshots, mixed sources,
duplicate capture times or input over 10000 records. Sort valid input by capture
time. An unavailable/invalid/missing metric creates a gap, never a zero.

Split line segments at missing/invalid samples, capture gaps exceeding the
maximum, and provenance changes. Never join distinct sessions or smooth across
gaps. Keep negative values where the model permits them. A single valid sample
is still visible as a point. W, VA, voltage/current locations and nominal ratings
are separate selectable metrics, not combined axes. Display provenance clearly.
Charts show historical captures, not current status or integrated energy.

## Browser

Use an explicit session picker with generic ordinal/provider/date labels, a
range picker (hour/day/week/session), metric picker and bounded previous/next
pages. Select a retained session without changing the live selection. Anchor
ranges to that session's last capture so old sessions remain browsable. Page
size 2000; show record count and whether another page exists. Never silently
present a limited page as the whole interval. Exports must be clearly labeled
as the displayed page and preserve all its typed metrics in JSON/CSV.

Session listing is capped and announces truncation; it is not a complete
historical device inventory. Provide refresh, explicit close, per-session
delete and all-history clear with separate destructive confirmations. Deletion
does not imply secure physical erasure. Browser request generations and terminal
close/stop fence late asynchronous results. Keep display errors redacted.

## Evidence

Use only temporary private stores and synthetic snapshots. Prove pagination
boundaries/subseconds/truncation, invalid query/cursor, session isolation and
corrupt data handling. Plot tests cover gaps, provenance, negative/zero values,
single points, duplicates and bounds. Controller tests prove that browsing does
not enable recording or affect live/widget selection, and that page/export/
delete state stays consistent. Compilation is not visual or accessibility proof.
