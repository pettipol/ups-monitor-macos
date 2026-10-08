import SwiftUI
import UPSEnergy
import UPSModel

public struct UPSDetailsView: View {
    public let sources: [MonitorSnapshot]
    public let selectedSourceKey: String?
    public let readState: UPSReadState
    public let now: Date
    public let maximumAge: TimeInterval
    public let acquisitionSucceeded: Bool
    public let history: [MonitorSnapshot]?
    public let energyEstimates: [MonitorEnergyEstimate]?
    public let onResetEnergy: (@MainActor @Sendable () -> Void)?
    public let onExportEnergy: (@MainActor @Sendable () -> Void)?
    public let onSelect: @MainActor @Sendable (String) -> Void
    public let onRefresh: @MainActor @Sendable () -> Void
    public let onExportJSON: (@MainActor @Sendable () -> Void)?
    public let onExportCSV: (@MainActor @Sendable () -> Void)?
    public let onClearHistory: (@MainActor @Sendable () -> Void)?

    @State private var showingClearConfirmation = false
    @State private var historyMetric: MonitorMetricID = .batteryCharge

    public init(
        sources: [MonitorSnapshot],
        selectedSourceKey: String?,
        readState: UPSReadState,
        now: Date,
        maximumAge: TimeInterval = UPSMonitorFormatters.freshnessLimit,
        acquisitionSucceeded: Bool,
        history: [MonitorSnapshot]? = nil,
        energyEstimates: [MonitorEnergyEstimate]? = nil,
        onResetEnergy: (@MainActor @Sendable () -> Void)? = nil,
        onExportEnergy: (@MainActor @Sendable () -> Void)? = nil,
        onSelect: @escaping @MainActor @Sendable (String) -> Void,
        onRefresh: @escaping @MainActor @Sendable () -> Void,
        onExportJSON: (@MainActor @Sendable () -> Void)? = nil,
        onExportCSV: (@MainActor @Sendable () -> Void)? = nil,
        onClearHistory: (@MainActor @Sendable () -> Void)? = nil
    ) {
        self.sources = sources
        self.selectedSourceKey = selectedSourceKey
        self.readState = readState
        self.now = now
        self.maximumAge = maximumAge
        self.acquisitionSucceeded = acquisitionSucceeded
        self.history = history
        self.energyEstimates = energyEstimates
        self.onResetEnergy = onResetEnergy
        self.onExportEnergy = onExportEnergy
        self.onSelect = onSelect
        self.onRefresh = onRefresh
        self.onExportJSON = onExportJSON
        self.onExportCSV = onExportCSV
        self.onClearHistory = onClearHistory
    }

    private var selected: MonitorSnapshot? {
        if let selectedSourceKey,
           let match = sources.first(where: { UPSMonitorFormatters.sourceKey(for: $0) == selectedSourceKey }) {
            return match
        }
        return sources.first
    }

    public var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(selected.map(sourceLabel(for:)) ?? "UPS Monitor")
                        .font(.title2.weight(.semibold))
                    Text(selected.map(statusHeadline(for:)) ?? UPSMonitorFormatters.readStateLabel(readState))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: onRefresh) {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .help("Refresh readings")
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)

            Divider()

            if sources.count > 1 {
                HStack {
                    Picker("UPS", selection: selectionBinding) {
                        ForEach(Array(sources.enumerated()), id: \.offset) { index, snapshot in
                            Text(UPSMonitorFormatters.sourceLabel(at: index, provider: snapshot.source.provider))
                                .tag(UPSMonitorFormatters.sourceKey(for: snapshot))
                        }
                    }
                    .frame(maxWidth: 260, alignment: .leading)
                    Spacer()
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let selected {
                        liveStatus(for: selected)
                        metricSection(title: "Battery", ids: Self.batteryMetrics, snapshot: selected)
                        metricSection(title: "Input", ids: Self.inputMetrics, snapshot: selected)
                        metricSection(title: "Output", ids: Self.outputMetrics, snapshot: selected)
                        metricSection(title: "UPS", ids: Self.upsMetrics, snapshot: selected)
                        if selected.source.provider == .apple {
                            metricSection(title: "Source measurements", ids: Self.sourceMetrics, snapshot: selected)
                        }
                    } else {
                        ContentUnavailableView(UPSMonitorFormatters.readStateLabel(readState),
                                               systemImage: emptySymbol,
                                               description: Text(emptyDescription))
                            .frame(maxWidth: .infinity, minHeight: 180)
                    }

                    if let energyEstimates {
                        UPSEnergySummaryView(estimates: energyEstimates,
                                             onReset: onResetEnergy, onExport: onExportEnergy)
                    }

                    if let selected, let history, !history.isEmpty {
                        historySection(for: selected, history: history)
                    }

                    if onExportJSON != nil || onExportCSV != nil || onClearHistory != nil {
                        historyCommands
                    }
                }
                .padding(20)
                .frame(maxWidth: 860, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .frame(minWidth: 580, minHeight: 520)
        .confirmationDialog("Clear stored history?", isPresented: $showingClearConfirmation,
                            titleVisibility: .visible) {
            Button("Clear history", role: .destructive) { onClearHistory?() }
            Button("Cancel", role: .cancel) {}
        }
    }

    private static let batteryMetrics: [MonitorMetricID] = [
        .batteryCharge, .batteryRuntime, .batteryTimeToFull, .batteryVoltage,
        .batteryVoltageNominal, .batteryCurrent, .batteryTemperature,
    ]
    private static let inputMetrics: [MonitorMetricID] = [
        .inputVoltage, .inputVoltageNominal, .inputCurrent, .inputCurrentNominal,
        .inputFrequency, .inputFrequencyNominal, .inputRealPower, .inputRealPowerNominal,
        .inputApparentPower,
    ]
    private static let outputMetrics: [MonitorMetricID] = [
        .outputVoltage, .outputVoltageNominal, .outputCurrent, .outputCurrentNominal,
        .outputFrequency, .outputFrequencyNominal,
    ]
    private static let upsMetrics: [MonitorMetricID] = [
        .upsLoad, .upsRealPower, .upsRealPowerNominal, .upsApparentPower,
        .upsApparentPowerNominal, .upsTemperature,
    ]
    private static let sourceMetrics: [MonitorMetricID] = [.appleSourceCurrent, .appleSourceTemperature]

    private var selectionBinding: Binding<String> {
        Binding(
            get: { selected.map(UPSMonitorFormatters.sourceKey(for:)) ?? "" },
            set: onSelect
        )
    }

    private var emptySymbol: String {
        return switch readState {
        case .loading: "arrow.trianglehead.2.clockwise.rotate.90"
        case .ready, .noSources: "powerplug"
        case .failed: "exclamationmark.triangle"
        case .stopped: "pause.circle"
        }
    }

    private var emptyDescription: String {
        return switch readState {
        case .loading: ""
        case .ready, .noSources: "No UPS detected"
        case .failed: "The last readings may be stale"
        case .stopped: "Monitoring is stopped"
        }
    }

    private func sourceLabel(for snapshot: MonitorSnapshot) -> String {
        let key = UPSMonitorFormatters.sourceKey(for: snapshot)
        let index = sources.firstIndex(where: { UPSMonitorFormatters.sourceKey(for: $0) == key }) ?? 0
        return UPSMonitorFormatters.sourceLabel(at: index, provider: snapshot.source.provider)
    }

    private func statusHeadline(for snapshot: MonitorSnapshot) -> String {
        guard readState == .ready else { return UPSMonitorFormatters.readStateLabel(readState) }
        return UPSMonitorFormatters.lineStateLabel(snapshot.status.lineState)
    }

    private func liveStatus(for snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: statusSymbol(snapshot))
                    .foregroundStyle(isFresh(snapshot) ? statusColor(snapshot) : Color.orange)
                    .accessibilityHidden(true)
                Text(statusHeadline(for: snapshot))
                    .font(.headline)
                Spacer()
                    Text(UPSMonitorFormatters.freshnessLabel(of: snapshot, now: now,
                                                             maximumAge: maximumAge,
                                                             acquisitionSucceeded: acquisitionSucceeded))
                    .font(.callout)
                    .foregroundStyle(isFresh(snapshot) ? Color.secondary : Color.orange)
            }

            HStack(spacing: 16) {
                Label(boolLabel(snapshot.status.isCharging), systemImage: "bolt")
                Label(healthLabel(snapshot.status.batteryHealth), systemImage: "heart.text.square")
                Label(boolLabel(snapshot.status.internalFailure, yes: "Internal failure", no: "No internal failure"),
                      systemImage: "exclamationmark.triangle")
            }
            .font(.callout)
            .foregroundStyle(.secondary)

            Text("Status quality · \(UPSMonitorFormatters.statusQualityLabel(snapshot.status.quality))")
                .font(.caption)
                .foregroundStyle(.secondary)

            if !snapshot.status.flags.isEmpty {
                Text(snapshot.status.flags.sorted(by: { $0.rawValue < $1.rawValue })
                    .map(UPSMonitorFormatters.statusFlagLabel).joined(separator: " · "))
                    .font(.callout)
                    .textSelection(.enabled)
            }
        }
    }

    private func metricSection(title: String, ids: [MonitorMetricID], snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            Divider()
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 9) {
                ForEach(ids, id: \.self) { id in
                    metricRow(id, snapshot: snapshot)
                }
            }
        }
    }

    private func metricRow(_ id: MonitorMetricID, snapshot: MonitorSnapshot) -> some View {
        let metric = snapshot.metrics.first(where: { $0.id == id })
        return GridRow(alignment: .firstTextBaseline) {
            Text(UPSMonitorFormatters.metricName(id))
                .frame(width: 190, alignment: .leading)
                .foregroundStyle(.secondary)
            Text(metric.map(UPSMonitorFormatters.metricValue) ?? "Not reported")
                .monospacedDigit()
                .frame(minWidth: 100, maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            Text(metricMetadata(metric))
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 190, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func metricMetadata(_ metric: MonitorMetric?) -> String {
        guard let metric else { return "" }
        return "\(UPSMonitorFormatters.qualityLabel(metric.quality)) · \(UPSMonitorFormatters.provenanceLabel(metric.provenance))"
    }

    private func historySection(for snapshot: MonitorSnapshot, history: [MonitorSnapshot]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Past hour", selection: $historyMetric) {
                ForEach(MonitorMetricID.allCases, id: \.self) {
                    Text(UPSMonitorFormatters.metricName($0)).tag($0)
                }
            }
            .frame(maxWidth: 360, alignment: .leading)
            UPSHistoryChart(snapshots: history, source: snapshot.source,
                            metric: historyMetric, maximumGap: maximumAge)
        }
    }

    @ViewBuilder
    private var historyCommands: some View {
        HStack(spacing: 12) {
            if let onExportJSON {
                Button(action: onExportJSON) {
                    Label("Export JSON", systemImage: "curlybraces")
                }
                .help("Export queried history as JSON")
            }
            if let onExportCSV {
                Button(action: onExportCSV) {
                    Label("Export CSV", systemImage: "tablecells")
                }
                .help("Export queried history as CSV")
            }
            Spacer()
            if onClearHistory != nil {
                Button(role: .destructive) {
                    showingClearConfirmation = true
                } label: {
                    Label("Clear history", systemImage: "trash")
                }
                .help("Clear stored history")
            }
        }
    }

    private func statusSymbol(_ snapshot: MonitorSnapshot) -> String {
        switch readState {
        case .loading: return "arrow.clockwise"
        case .failed: return "exclamationmark.triangle"
        case .stopped: return "pause.circle"
        case .noSources: return "powerplug"
        case .ready: break
        }
        return switch snapshot.status.lineState {
        case .onLine: "powerplug.fill"
        case .onBattery: "battery.25percent"
        case .unknown: "powerplug"
        }
    }

    private func statusColor(_ snapshot: MonitorSnapshot) -> Color {
        return switch snapshot.status.lineState {
        case .onLine: .green
        case .onBattery: .orange
        case .unknown: .secondary
        }
    }

    private func isFresh(_ snapshot: MonitorSnapshot) -> Bool {
        UPSMonitorFormatters.freshness(of: snapshot, now: now, maximumAge: maximumAge,
                                       acquisitionSucceeded: acquisitionSucceeded) == .fresh
    }

    private func boolLabel(_ value: Bool?, yes: String = "Charging", no: String = "Not charging") -> String {
        guard let value else { return "Not reported" }
        return value ? yes : no
    }

    private func healthLabel(_ value: MonitorBatteryHealth?) -> String {
        guard let value else { return "Not reported" }
        return UPSMonitorFormatters.healthLabel(value)
    }
}
