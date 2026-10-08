# Historical Metric Plot

`HistoryPlotBuilder.build(snapshots:source:metric:maximumGap:)` is a pure,
bounded transformation. It accepts at most 10,000 snapshots for one exact
`MonitorSource`, validates the source and each version-1 snapshot, rejects
duplicate capture dates, sorts by capture time, and requires a finite positive
maximum gap (10 seconds by default).

`HistoryPlot.points` contains stable date-identified points with the capture
date, original value, integer segment, and metric provenance. A missing metric
or a non-available metric quality contributes no point and breaks the line.
Capture gaps larger than the configured maximum and provenance changes also
start a new segment. Valid zero and negative values are retained when allowed
by the model. The builder does not interpolate, smooth, merge identities,
calculate energy, or infer freshness/currentness.

`UPSHistoryChart` renders the requested metric using Swift Charts, distinct
series for each segment, provenance-based mark colors, and explicit provenance
labels. Each line and point also carries an accessibility label with metric,
value, unit, and provenance. Empty valid history
and invalid input have separate empty states. The chart does not select a
metric, access storage, read hardware, or imply that historical captures are
current. Its plot area has a fixed height of 220 points.

Synthetic tests exercise ordering, missing and invalid samples, provenance and
time-gap boundaries, duplicate timestamps, exact-source isolation, malformed
snapshots, bounds, valid negative/zero values, and a single-point dataset.
View construction and compilation do not prove actual rendering or accessibility
interaction; those remain unverified.
