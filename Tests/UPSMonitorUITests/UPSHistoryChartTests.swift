import Foundation
import Testing
import UPSModel
@testable import UPSMonitorUI

private let plotSource = MonitorSource(
    provider: .nut,
    id: "history-source",
    sessionID: "history-session",
    identityStability: .configured
)

private func plotSnapshot(
    at seconds: TimeInterval,
    value: Double? = 40,
    quality: MonitorMetricQuality = .available,
    provenance: MonitorMetricProvenance = .reported,
    source: MonitorSource = plotSource,
    schemaVersion: Int = 1
) -> MonitorSnapshot {
    let metric = MonitorMetric(
        id: .upsLoad,
        value: quality == .available ? value : nil,
        unit: .percent,
        quality: quality,
        provenance: provenance
    )
    return MonitorSnapshot(
        schemaVersion: schemaVersion,
        source: source,
        capturedAt: Date(timeIntervalSince1970: seconds),
        status: MonitorStatus(quality: .available),
        metrics: [metric]
    )
}

private func buildPlot(
    _ snapshots: [MonitorSnapshot],
    source: MonitorSource = plotSource,
    maximumGap: TimeInterval = 10
) throws -> HistoryPlot {
    try HistoryPlotBuilder.build(snapshots: snapshots, source: source, metric: .upsLoad, maximumGap: maximumGap)
}

@Suite struct UPSHistoryChartTests {
    @Test func sortsSamplesAndRetainsNegativeAndZeroValues() throws {
        let currentSnapshots = [
            MonitorSnapshot(
                source: plotSource,
                capturedAt: Date(timeIntervalSince1970: 2),
                status: MonitorStatus(quality: .available),
                metrics: [MonitorMetric(id: .batteryCurrent, value: 0, unit: .amps, quality: .available, provenance: .reported)]
            ),
            MonitorSnapshot(
                source: plotSource,
                capturedAt: Date(timeIntervalSince1970: 1),
                status: MonitorStatus(quality: .available),
                metrics: [MonitorMetric(id: .batteryCurrent, value: -1.5, unit: .amps, quality: .available, provenance: .reported)]
            ),
        ]
        let plot = try HistoryPlotBuilder.build(
            snapshots: currentSnapshots, source: plotSource, metric: .batteryCurrent
        )

        #expect(plot.points.map(\.value) == [-1.5, 0])
        #expect(plot.points.map(\.date) == currentSnapshots.map(\.capturedAt).sorted())
        #expect(plot.points[0].segment == plot.points[1].segment)
    }

    @Test func missingSamplesLongGapsAndProvenanceChangesSplitSegments() throws {
        let snapshots = [
            plotSnapshot(at: 0, value: 20),
            plotSnapshot(at: 1, value: nil, quality: .unavailable),
            plotSnapshot(at: 2, value: 22),
            plotSnapshot(at: 30, value: 23),
            plotSnapshot(at: 31, value: 24, provenance: .estimated),
        ]

        let plot = try buildPlot(snapshots)

        #expect(plot.points.map(\.value) == [20, 22, 23, 24])
        #expect(plot.points.map(\.segment) == [0, 1, 2, 3])
        #expect(plot.points.map(\.provenance.rawValue) == ["reported", "reported", "reported", "estimated"])
    }

    @Test func invalidQualityAndMissingMetricCreateGapsWithoutZeroPoints() throws {
        let invalid = MonitorSnapshot(
            source: plotSource,
            capturedAt: Date(timeIntervalSince1970: 1),
            status: MonitorStatus(quality: .available),
            metrics: [MonitorMetric(id: .upsLoad, value: nil, unit: .percent, quality: .invalid, provenance: .reported)]
        )
        let missing = MonitorSnapshot(
            source: plotSource,
            capturedAt: Date(timeIntervalSince1970: 2),
            status: MonitorStatus(quality: .available),
            metrics: []
        )
        let plot = try buildPlot([plotSnapshot(at: 0, value: 0), invalid, missing, plotSnapshot(at: 3, value: 10)])

        #expect(plot.points.map(\.value) == [0, 10])
        #expect(plot.points.map(\.segment) == [0, 1])
    }

    @Test func duplicateTimesMixedSourcesAndMalformedSnapshotsAreRejected() {
        #expect(throws: HistoryPlotError.duplicateCaptureTime) {
            try buildPlot([plotSnapshot(at: 1), plotSnapshot(at: 1)])
        }

        let otherSource = MonitorSource(
            provider: .nut, id: "history-source", sessionID: "other-session", identityStability: .configured
        )
        #expect(throws: HistoryPlotError.mixedSource) {
            try buildPlot([plotSnapshot(at: 1), plotSnapshot(at: 2, source: otherSource)])
        }
        #expect(throws: HistoryPlotError.invalidSnapshot) {
            try buildPlot([plotSnapshot(at: 1, schemaVersion: 2)])
        }
        #expect(throws: HistoryPlotError.invalidSource) {
            try buildPlot([], source: MonitorSource(provider: .nut, id: "bad source", sessionID: "s", identityStability: .configured))
        }
    }

    @Test func inputAndGapBoundsAreValidated() {
        #expect(throws: HistoryPlotError.invalidMaximumGap) { try buildPlot([], maximumGap: 0) }
        #expect(throws: HistoryPlotError.invalidMaximumGap) { try buildPlot([], maximumGap: .infinity) }
        let oversized = (0...HistoryPlotBuilder.maximumSnapshotCount).map { plotSnapshot(at: Double($0)) }
        #expect(throws: HistoryPlotError.tooManySnapshots) { try buildPlot(oversized) }
    }

    @Test func oneValidSampleRemainsAStableVisiblePoint() throws {
        let snapshot = plotSnapshot(at: 99, value: 0)
        let plot = try buildPlot([snapshot])

        #expect(plot.points.count == 1)
        #expect(plot.points[0].id == snapshot.capturedAt)
        #expect(plot.points[0].value == 0)
        #expect(plot.points[0].segment == 0)
    }

    @MainActor @Test func viewInitializationKeepsRequestedSeriesAndDistinguishesEmptyInput() {
        let chart = UPSHistoryChart(snapshots: [], source: plotSource, metric: .outputVoltage)
        #expect(chart.snapshots.isEmpty)
        #expect(chart.source == plotSource)
        #expect(chart.metric == .outputVoltage)
        #expect(chart.maximumGap == 10)
    }
}
