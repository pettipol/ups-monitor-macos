import SwiftUI
import UPSEnergy

public enum UPSEnergySummaryFormatters: Sendable {
    public static func channelLabel(_ channel: MonitorEnergyChannel) -> String {
        switch channel {
        case .input: "Input"
        case .ups: "UPS"
        }
    }

    public static func stateLabel(_ state: MonitorEnergyState) -> String {
        switch state {
        case .unavailable: "Unavailable"
        case .collecting: "Collecting"
        case .estimated: "Estimated"
        case .paused: "Paused"
        }
    }

    public static func energyLabel(_ estimate: MonitorEnergyEstimate) -> String {
        guard let energyWh = estimate.energyWh,
              energyWh.isFinite,
              energyWh >= 0,
              estimate.coveredDurationSeconds.isFinite,
              estimate.coveredDurationSeconds > 0 else {
            return "Energy not available"
        }
        return "\(formatNumber(energyWh)) Wh estimated"
    }

    public static func coverageLabel(_ estimate: MonitorEnergyEstimate) -> String {
        guard estimate.coveredDurationSeconds.isFinite,
              estimate.coveredDurationSeconds >= 0 else {
            return "Coverage unavailable"
        }
        let duration: String
        if estimate.coveredDurationSeconds > 1_000_000 {
            duration = formatNumber(estimate.coveredDurationSeconds)
        } else {
            duration = estimate.coveredDurationSeconds.formatted(.number.precision(.fractionLength(0...1)))
        }
        let breaks = estimate.gapOrBreakCount >= 0 ? "\(estimate.gapOrBreakCount)" : "unavailable"
        return "\(duration) s covered · \(breaks) breaks"
    }

    public static func provenanceLabel(_ estimate: MonitorEnergyEstimate) -> String {
        let provenance = estimate.powerProvenances.map(UPSMonitorFormatters.provenanceLabel)
        guard !provenance.isEmpty else { return "Watt provenance not recorded" }
        return "Watt data: " + provenance.joined(separator: ", ")
    }

    public static func sampleDatesLabel(_ estimate: MonitorEnergyEstimate) -> String {
        switch (estimate.firstCapturedAt, estimate.lastCapturedAt) {
        case let (first?, last?) where isFinite(first) && isFinite(last) && first == last:
            "Samples: \(UPSMonitorFormatters.timestamp(first))"
        case let (first?, last?) where isFinite(first) && isFinite(last) && first <= last:
            "Samples: \(UPSMonitorFormatters.timestamp(first)) – \(UPSMonitorFormatters.timestamp(last))"
        case (nil, nil):
            "Sample dates unavailable"
        case let (first?, nil) where !isFinite(first):
            "Sample dates unavailable"
        case let (nil, last?) where !isFinite(last):
            "Sample dates unavailable"
        case let (first?, last?) where !isFinite(first) || !isFinite(last) || first > last:
            "Sample dates unavailable"
        default:
            "Sample dates incomplete"
        }
    }

    public static func accessibilityLabel(_ estimate: MonitorEnergyEstimate) -> String {
        [
            channelLabel(estimate.channel),
            stateLabel(estimate.state),
            energyLabel(estimate),
            coverageLabel(estimate),
            provenanceLabel(estimate),
            sampleDatesLabel(estimate),
        ].joined(separator: ", ")
    }

    private static func isFinite(_ date: Date) -> Bool {
        date.timeIntervalSince1970.isFinite
    }

    private static func formatNumber(_ value: Double) -> String {
        if value != 0, (value < 0.001 || value > 1_000_000) {
            return value.formatted(.number.notation(.scientific).precision(.significantDigits(1...4)))
        }
        return value.formatted(.number.precision(.significantDigits(1...6)))
    }
}

/// Shows application-estimated energy from accepted active-watt samples.
public struct UPSEnergySummaryView: View {
    public let estimates: [MonitorEnergyEstimate]
    public let onReset: (@MainActor @Sendable () -> Void)?
    public let onExport: (@MainActor @Sendable () -> Void)?

    @State private var confirmsReset = false

    public init(
        estimates: [MonitorEnergyEstimate],
        onReset: (@MainActor @Sendable () -> Void)? = nil,
        onExport: (@MainActor @Sendable () -> Void)? = nil
    ) {
        self.estimates = estimates
        self.onReset = onReset
        self.onExport = onExport
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Energy estimates")
                    .font(.headline)
                Spacer()
                if let onExport {
                    Button(action: onExport) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .help("Export energy estimates")
                    .accessibilityLabel("Export energy estimates")
                }
                if onReset != nil {
                    Button {
                        confirmsReset = true
                    } label: {
                        Image(systemName: "arrow.counterclockwise")
                    }
                    .help("Reset energy estimates")
                    .accessibilityLabel("Reset energy estimates")
                    .confirmationDialog(
                        "Reset energy estimates?",
                        isPresented: $confirmsReset,
                        titleVisibility: .visible
                    ) {
                        Button("Reset estimates", role: .destructive) {
                            onReset?()
                        }
                        Button("Cancel", role: .cancel) {}
                    }
                }
            }

            ForEach(MonitorEnergyChannel.allCases, id: \.rawValue) { channel in
                if let estimate = estimates.first(where: { $0.channel == channel }) {
                    estimateRow(estimate)
                } else {
                    missingRow(channel)
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func estimateRow(_ estimate: MonitorEnergyEstimate) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(UPSEnergySummaryFormatters.channelLabel(estimate.channel))
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Text(UPSEnergySummaryFormatters.stateLabel(estimate.state))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(UPSEnergySummaryFormatters.energyLabel(estimate))
                .font(.body.monospacedDigit())
            Text(UPSEnergySummaryFormatters.coverageLabel(estimate))
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(UPSEnergySummaryFormatters.provenanceLabel(estimate))
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(UPSEnergySummaryFormatters.sampleDatesLabel(estimate))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(UPSEnergySummaryFormatters.accessibilityLabel(estimate))
    }

    private func missingRow(_ channel: MonitorEnergyChannel) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(UPSEnergySummaryFormatters.channelLabel(channel))
                .font(.subheadline.weight(.semibold))
            Text("Energy not available")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}
