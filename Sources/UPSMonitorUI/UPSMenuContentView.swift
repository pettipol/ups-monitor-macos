import SwiftUI
import UPSModel

public struct UPSMenuContentView: View {
    public let sources: [MonitorSnapshot]
    public let selectedSourceKey: String?
    public let readState: UPSReadState
    public let now: Date
    public let maximumAge: TimeInterval
    public let acquisitionSucceeded: Bool
    public let onSelect: @MainActor @Sendable (String) -> Void
    public let onRefresh: @MainActor @Sendable () -> Void
    public let onOpenDetails: @MainActor @Sendable () -> Void

    public init(
        sources: [MonitorSnapshot],
        selectedSourceKey: String?,
        readState: UPSReadState,
        now: Date,
        maximumAge: TimeInterval = UPSMonitorFormatters.freshnessLimit,
        acquisitionSucceeded: Bool,
        onSelect: @escaping @MainActor @Sendable (String) -> Void,
        onRefresh: @escaping @MainActor @Sendable () -> Void,
        onOpenDetails: @escaping @MainActor @Sendable () -> Void
    ) {
        self.sources = sources
        self.selectedSourceKey = selectedSourceKey
        self.readState = readState
        self.now = now
        self.maximumAge = maximumAge
        self.acquisitionSucceeded = acquisitionSucceeded
        self.onSelect = onSelect
        self.onRefresh = onRefresh
        self.onOpenDetails = onOpenDetails
    }

    private var selected: MonitorSnapshot? {
        if let selectedSourceKey,
           let match = sources.first(where: { UPSMonitorFormatters.sourceKey(for: $0) == selectedSourceKey }) {
            return match
        }
        return sources.first
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: stateSymbol)
                    .foregroundStyle(stateColor)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(selected.map(sourceLabel(for:)) ?? "UPS Monitor")
                        .font(.headline)
                    Text(statusHeadline)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Button(action: onRefresh) {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
                .help("Refresh readings")
                .accessibilityLabel("Refresh readings")
            }

            if sources.count > 1 {
                Picker("UPS", selection: selectionBinding) {
                    ForEach(Array(sources.enumerated()), id: \.offset) { index, snapshot in
                        Text(UPSMonitorFormatters.sourceLabel(at: index, provider: snapshot.source.provider))
                            .tag(UPSMonitorFormatters.sourceKey(for: snapshot))
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
            }

            if let selected {
                metricSummary(for: selected)
                Text(UPSMonitorFormatters.freshnessLabel(of: selected, now: now,
                                                         maximumAge: maximumAge,
                                                         acquisitionSucceeded: acquisitionSucceeded))
                    .font(.caption)
                    .foregroundStyle(isFresh(selected) ? Color.secondary : Color.orange)
            } else {
                Text(UPSMonitorFormatters.readStateLabel(readState))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Divider()

            Button(action: onOpenDetails) {
                Label("Open details", systemImage: "list.bullet.rectangle")
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .help("Open UPS details")
        }
        .padding(14)
        .frame(width: 300)
    }

    private var selectionBinding: Binding<String> {
        Binding(
            get: { selected.map(UPSMonitorFormatters.sourceKey(for:)) ?? "" },
            set: onSelect
        )
    }

    private var statusHeadline: String {
        guard let selected else { return UPSMonitorFormatters.readStateLabel(readState) }
        if readState != .ready { return UPSMonitorFormatters.readStateLabel(readState) }
        return UPSMonitorFormatters.lineStateLabel(selected.status.lineState)
    }

    private var stateSymbol: String {
        if readState == .loading { return "arrow.clockwise" }
        if readState == .failed { return "exclamationmark.triangle" }
        if readState == .stopped { return "pause.circle" }
        guard let selected else {
            return switch readState {
            case .loading: "arrow.trianglehead.2.clockwise.rotate.90"
            case .ready, .noSources: "powerplug"
            case .failed: "exclamationmark.triangle"
            case .stopped: "pause.circle"
            }
        }
        if readState == .failed { return "exclamationmark.triangle" }
        return switch selected.status.lineState {
        case .onLine: "powerplug.fill"
        case .onBattery: "battery.25percent"
        case .unknown: "powerplug"
        }
    }

    private var stateColor: Color {
        guard let selected else { return readState == .failed ? .orange : .secondary }
        if !isFresh(selected) { return .orange }
        return switch selected.status.lineState {
        case .onLine: .green
        case .onBattery: .orange
        case .unknown: .secondary
        }
    }

    private func sourceLabel(for snapshot: MonitorSnapshot) -> String {
        let key = UPSMonitorFormatters.sourceKey(for: snapshot)
        let index = sources.firstIndex(where: { UPSMonitorFormatters.sourceKey(for: $0) == key }) ?? 0
        return UPSMonitorFormatters.sourceLabel(at: index, provider: snapshot.source.provider)
    }

    private func metricSummary(for snapshot: MonitorSnapshot) -> some View {
        let charge = snapshot.metrics.first(where: { $0.id == .batteryCharge })
        let runtime = snapshot.metrics.first(where: { $0.id == .batteryRuntime })
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Charge")
                    .foregroundStyle(.secondary)
                Spacer()
                Text(charge.map(UPSMonitorFormatters.metricValue) ?? "Not reported")
                    .monospacedDigit()
            }
            if let charge, charge.quality == .available, let value = charge.value {
                ProgressView(value: min(max(value, 0), 100), total: 100)
                    .tint(isFresh(snapshot) ? .accentColor : .orange)
                    .accessibilityLabel("Battery charge")
                    .accessibilityValue(UPSMonitorFormatters.metricValue(charge))
            }
            HStack {
                Text("Runtime estimate")
                    .foregroundStyle(.secondary)
                Spacer()
                Text(runtime.map(UPSMonitorFormatters.metricValue) ?? "Not reported")
                    .monospacedDigit()
            }
        }
        .font(.callout)
    }

    private func isFresh(_ snapshot: MonitorSnapshot) -> Bool {
        UPSMonitorFormatters.freshness(of: snapshot, now: now,
                                       maximumAge: maximumAge,
                                       acquisitionSucceeded: acquisitionSucceeded) == .fresh
    }
}
