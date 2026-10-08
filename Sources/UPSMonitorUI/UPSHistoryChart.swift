import Charts
import SwiftUI
import UPSModel

public enum HistoryPlotError: Error, Equatable, Sendable {
    case invalidSource
    case invalidMaximumGap
    case tooManySnapshots
    case invalidSnapshot
    case mixedSource
    case duplicateCaptureTime
}

public struct HistoryPlotPoint: Identifiable, Equatable, Sendable {
    public let date: Date
    public let value: Double
    public let segment: Int
    public let provenance: MonitorMetricProvenance

    public var id: Date { date }
}

public struct HistoryPlot: Equatable, Sendable {
    public let metric: MonitorMetricID
    public let points: [HistoryPlotPoint]

    public init(metric: MonitorMetricID, points: [HistoryPlotPoint]) {
        self.metric = metric
        self.points = points
    }
}

public enum HistoryPlotBuilder {
    public static let maximumSnapshotCount = 10_000

    public static func build(
        snapshots: [MonitorSnapshot],
        source: MonitorSource,
        metric: MonitorMetricID,
        maximumGap: TimeInterval = 10
    ) throws -> HistoryPlot {
        guard maximumGap.isFinite, maximumGap > 0 else { throw HistoryPlotError.invalidMaximumGap }
        do {
            try source.validate()
        } catch {
            throw HistoryPlotError.invalidSource
        }
        guard snapshots.count <= maximumSnapshotCount else { throw HistoryPlotError.tooManySnapshots }

        for snapshot in snapshots {
            do {
                try snapshot.validate()
            } catch {
                throw HistoryPlotError.invalidSnapshot
            }
            guard snapshot.source == source else { throw HistoryPlotError.mixedSource }
        }

        let ordered = snapshots.sorted { $0.capturedAt < $1.capturedAt }
        var dates = Set<Date>()
        for snapshot in ordered where !dates.insert(snapshot.capturedAt).inserted {
            throw HistoryPlotError.duplicateCaptureTime
        }

        var points: [HistoryPlotPoint] = []
        var previous: HistoryPlotPoint?
        var segment = 0

        for snapshot in ordered {
            guard let sample = snapshot.metrics.first(where: { $0.id == metric }),
                  sample.quality == .available,
                  let value = sample.value else {
                previous = nil
                continue
            }

            if let previous {
                let gap = snapshot.capturedAt.timeIntervalSince(previous.date)
                if gap > maximumGap || sample.provenance.rawValue != previous.provenance.rawValue {
                    segment += 1
                }
            } else if !points.isEmpty {
                segment += 1
            }

            let point = HistoryPlotPoint(
                date: snapshot.capturedAt,
                value: value,
                segment: segment,
                provenance: sample.provenance
            )
            points.append(point)
            previous = point
        }

        return HistoryPlot(metric: metric, points: points)
    }
}

/// Displays historical captures without implying freshness or bridging missing samples.
public struct UPSHistoryChart: View {
    public let snapshots: [MonitorSnapshot]
    public let source: MonitorSource
    public let metric: MonitorMetricID
    public let maximumGap: TimeInterval

    private let plotResult: Result<HistoryPlot, HistoryPlotError>

    public init(
        snapshots: [MonitorSnapshot],
        source: MonitorSource,
        metric: MonitorMetricID,
        maximumGap: TimeInterval = 10
    ) {
        self.snapshots = snapshots
        self.source = source
        self.metric = metric
        self.maximumGap = maximumGap
        do {
            plotResult = .success(try HistoryPlotBuilder.build(
                snapshots: snapshots, source: source, metric: metric, maximumGap: maximumGap
            ))
        } catch let error as HistoryPlotError {
            plotResult = .failure(error)
        } catch {
            plotResult = .failure(.invalidSnapshot)
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(UPSMonitorFormatters.metricName(metric))
                .font(.headline)
            switch plotResult {
            case .failure:
                ContentUnavailableView(
                    "History unavailable",
                    systemImage: "exclamationmark.triangle",
                    description: Text("The selected history data is invalid.")
                )
                .frame(height: 220)
            case .success(let plot) where plot.points.isEmpty:
                ContentUnavailableView(
                    "No history data",
                    systemImage: "chart.xyaxis.line",
                    description: Text("No valid samples are available for this metric.")
                )
                .frame(height: 220)
            case .success(let plot):
                chart(plot)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func chart(_ plot: HistoryPlot) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Chart(plot.points) { point in
                let provenance = UPSMonitorFormatters.provenanceLabel(point.provenance)
                let accessibilityLabel = Text(
                    "\(UPSMonitorFormatters.metricName(metric)), \(point.value.formatted()) \(UPSMonitorFormatters.unitLabel(metric.allowedUnit)), \(provenance)"
                )
                LineMark(
                    x: .value("Capture time", point.date),
                    y: .value(UPSMonitorFormatters.metricName(metric), point.value),
                    series: .value("Segment", point.segment)
                )
                .interpolationMethod(.linear)
                .foregroundStyle(by: .value("Provenance", provenance))
                .accessibilityLabel(accessibilityLabel)

                PointMark(
                    x: .value("Capture time", point.date),
                    y: .value(UPSMonitorFormatters.metricName(metric), point.value)
                )
                .foregroundStyle(by: .value("Provenance", provenance))
                .accessibilityLabel(accessibilityLabel)
            }
            .chartYAxisLabel(UPSMonitorFormatters.unitLabel(metric.allowedUnit))
            .frame(height: 220)
            Text("Provenance: " + provenanceSummary(plot.points))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .accessibilityLabel("\(UPSMonitorFormatters.metricName(metric)) history")
    }

    private func provenanceSummary(_ points: [HistoryPlotPoint]) -> String {
        let values = Set(points.map { $0.provenance.rawValue }).sorted()
        return values.compactMap { rawValue in
            MonitorMetricProvenance(rawValue: rawValue).map(UPSMonitorFormatters.provenanceLabel)
        }.joined(separator: ", ")
    }
}
