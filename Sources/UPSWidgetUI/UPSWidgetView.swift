import SwiftUI
import UPSModel
import UPSMonitorUI
import UPSWidgetData

public struct UPSWidgetView: View {
    public let payload: WidgetSnapshot?
    public let date: Date
    public let isMedium: Bool
    public let unavailableReason: String?
    public let isSyntheticFixture: Bool

    public init(payload: WidgetSnapshot?, date: Date, isMedium: Bool, unavailableReason: String? = nil,
                isSyntheticFixture: Bool = false) {
        self.payload = payload
        self.date = date
        self.isMedium = isMedium
        self.unavailableReason = unavailableReason
        self.isSyntheticFixture = isSyntheticFixture
    }

    public var body: some View {
        Group {
            if let snapshot = UPSWidgetPresentation.snapshot(payload) {
                VStack(alignment: .leading, spacing: isMedium ? 2 : 5) {
                    if isMedium {
                        mediumContent(snapshot)
                    } else {
                        smallContent(snapshot)
                    }
                    Spacer(minLength: 0)
                    captureFooter(snapshot)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            } else {
                emptyContent()
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func smallContent(_ snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            header(for: snapshot)
            chargeRow(snapshot, prominent: true)
            chargeProgress(snapshot)
            stateLine()
        }
    }

    private func mediumContent(_ snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                HStack(spacing: 5) {
                    Image(systemName: UPSWidgetPresentation.symbol(payload: payload, date: date))
                        .accessibilityHidden(true)
                    Text(UPSWidgetPresentation.headerLabel(
                        providerLabel: UPSMonitorFormatters.providerLabel(snapshot.source.provider),
                        isSyntheticFixture: isSyntheticFixture,
                        presentationName: payload?.presentationName,
                        sourceProvider: snapshot.source.provider
                    ))
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                        .accessibilityLabel(UPSWidgetPresentation.accessibilityHeaderLabel(
                            providerLabel: UPSMonitorFormatters.providerLabel(snapshot.source.provider),
                            isSyntheticFixture: isSyntheticFixture,
                            presentationName: payload?.presentationName
                        ))
                        .help(UPSWidgetPresentation.accessibilityHeaderLabel(
                            providerLabel: UPSMonitorFormatters.providerLabel(snapshot.source.provider),
                            isSyntheticFixture: isSyntheticFixture,
                            presentationName: payload?.presentationName
                        ))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Text("Charge  \(UPSWidgetPresentation.chargeValue(snapshot, includeProvenance: true))")
                    .font(.caption2.weight(.semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }

            stateLine()

            LazyVGrid(columns: UPSWidgetPresentation.mediumGridColumns, alignment: .leading,
                      spacing: 2) {
                ForEach(UPSWidgetPresentation.mediumMetricIDs, id: \.self) { id in
                    metricCell(UPSWidgetPresentation.mediumMetricTitle(id), id: id, snapshot: snapshot)
                }
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func header(for snapshot: MonitorSnapshot) -> some View {
        HStack(spacing: 6) {
            Image(systemName: UPSWidgetPresentation.symbol(payload: payload, date: date))
                .accessibilityHidden(true)
            Text(UPSWidgetPresentation.headerLabel(
                providerLabel: UPSMonitorFormatters.providerLabel(snapshot.source.provider),
                isSyntheticFixture: isSyntheticFixture,
                presentationName: payload?.presentationName,
                sourceProvider: snapshot.source.provider
            ))
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
                .accessibilityLabel(UPSWidgetPresentation.accessibilityHeaderLabel(
                    providerLabel: UPSMonitorFormatters.providerLabel(snapshot.source.provider),
                    isSyntheticFixture: isSyntheticFixture,
                    presentationName: payload?.presentationName
                ))
                .help(UPSWidgetPresentation.accessibilityHeaderLabel(
                    providerLabel: UPSMonitorFormatters.providerLabel(snapshot.source.provider),
                    isSyntheticFixture: isSyntheticFixture,
                    presentationName: payload?.presentationName
                ))
            Spacer(minLength: 0)
        }
    }

    private func chargeRow(_ snapshot: MonitorSnapshot, prominent: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text("Charge")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 4)
            Text(UPSWidgetPresentation.chargeValue(snapshot))
                .font(prominent ? .title2.weight(.semibold) : .title3.weight(.semibold))
                .monospacedDigit()
        }
    }

    @ViewBuilder
    private func chargeProgress(_ snapshot: MonitorSnapshot) -> some View {
        if let charge = UPSWidgetPresentation.chargeMetric(snapshot), let value = charge.value {
            ProgressView(value: min(max(value, 0), 100), total: 100)
                .tint(.accentColor)
                .accessibilityLabel("Battery charge")
                .accessibilityValue(UPSWidgetPresentation.chargeValue(snapshot))
        }
    }

    private func stateLine() -> some View {
        Text(UPSWidgetPresentation.statusLine(payload: payload, date: date))
            .font(.caption.weight(.medium))
            .foregroundStyle(UPSWidgetPresentation.isStale(payload: payload, date: date) ? Color.orange : Color.primary)
            .fixedSize(horizontal: false, vertical: true)
            .lineLimit(2)
    }

    private func captureFooter(_ snapshot: MonitorSnapshot) -> some View {
        HStack(spacing: 4) {
            let timestamp = snapshot.capturedAt.formatted(
                date: isMedium ? .abbreviated : .omitted,
                time: .shortened
            )
            Text("Captured \(timestamp)")
                .lineLimit(1)
            Spacer(minLength: 4)
            Text(snapshot.capturedAt, style: .relative)
                .lineLimit(1)
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .monospacedDigit()
    }

    private func metricCell(_ title: String, id: MonitorMetricID, snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Text(UPSWidgetPresentation.metricValue(id, in: snapshot))
                .font(.caption2.weight(.medium))
                .monospacedDigit()
                .lineLimit(2)
                .minimumScaleFactor(0.8)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 35, maxHeight: 35, alignment: .topLeading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(UPSMonitorFormatters.metricName(id))
        .accessibilityValue(UPSWidgetPresentation.metricValue(id, in: snapshot))
    }

    private func emptyContent() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: UPSWidgetPresentation.symbol(payload: payload, date: date))
                .font(.title3)
                .accessibilityHidden(true)
            if let marker = UPSWidgetPresentation.syntheticMarkerLabel(isSyntheticFixture: isSyntheticFixture) {
                Text(marker)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.orange)
            }
            Text(UPSWidgetPresentation.stateLabel(payload: payload, date: date,
                                                  unavailableReason: unavailableReason))
                .font(.subheadline.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

enum UPSWidgetPresentation {
    private static let technicalNameSuffix = try? NSRegularExpression(
        pattern: #"\A(.+?) FW:UPS [0-9]+(?:\.[0-9]+)+ / ID=[0-9]+\z"#
    )

    static let mediumMetricIDs: [MonitorMetricID] = [
        .batteryRuntime, .upsLoad, .upsRealPower,
        .inputVoltage, .outputVoltage, .upsApparentPower,
    ]
    static let mediumGridColumns = Array(repeating: GridItem(.flexible(minimum: 0), alignment: .leading), count: 3)

    static func mediumMetricTitle(_ id: MonitorMetricID) -> String {
        switch id {
        case .upsLoad: "Load"
        case .upsRealPower: "Real power"
        case .upsApparentPower: "Apparent power"
        default: UPSMonitorFormatters.metricName(id)
        }
    }

    static func syntheticMarkerLabel(isSyntheticFixture: Bool) -> String? {
        isSyntheticFixture ? "Synthetic UPS" : nil
    }

    static func headerLabel(providerLabel: String, isSyntheticFixture: Bool,
                            presentationName: String? = nil,
                            sourceProvider: MonitorProvider? = nil) -> String {
        if isSyntheticFixture { return "Synthetic UPS" }
        guard let name = UPSMonitorFormatters.presentationName(presentationName) else {
            return "UPS · \(providerLabel)"
        }
        let visibleName = sourceProvider == .apple ? compactAppleName(name) ?? name : name
        return "\(visibleName) · \(providerLabel)"
    }

    static func accessibilityHeaderLabel(providerLabel: String, isSyntheticFixture: Bool,
                                         presentationName: String? = nil) -> String {
        headerLabel(providerLabel: providerLabel, isSyntheticFixture: isSyntheticFixture,
                    presentationName: presentationName)
    }

    private static func compactAppleName(_ name: String) -> String? {
        let fullRange = NSRange(name.startIndex..<name.endIndex, in: name)
        guard let match = technicalNameSuffix?.firstMatch(in: name, range: fullRange),
              let prefixRange = Range(match.range(at: 1), in: name) else { return nil }
        let prefix = String(name[prefixRange])
        guard !prefix.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              prefix == prefix.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
        return prefix
    }

    static func stateLabel(payload: WidgetSnapshot?, date: Date, unavailableReason: String? = nil) -> String {
        guard let payload else { return unavailableReason ?? "Widget data unavailable" }
        guard (try? payload.validate()) != nil else { return unavailableReason ?? "Widget data unavailable" }
        switch payload.acquisition {
        case .active:
            guard payload.snapshot != nil else { return "Widget data unavailable" }
            guard !isStale(payload: payload, date: date) else { return "Stale capture" }
            return "Last capture"
        case .noSources: return "No UPS detected"
        case .readFailed: return payload.snapshot == nil ? "Read failed" : "Read failed · stale"
        case .stopped: return payload.snapshot == nil ? "Monitoring stopped" : "Stopped · stale"
        }
    }

    static func snapshot(_ payload: WidgetSnapshot?) -> MonitorSnapshot? {
        guard let payload, (try? payload.validate()) != nil else { return nil }
        return payload.snapshot
    }

    private static func capturedLineState(_ snapshot: MonitorSnapshot?) -> String {
        guard let snapshot else { return "Widget data unavailable" }
        return UPSMonitorFormatters.lineStateLabel(snapshot.status.lineState)
    }

    static func statusLine(payload: WidgetSnapshot?, date: Date) -> String {
        guard let payload, let snapshot = snapshot(payload) else {
            return stateLabel(payload: payload, date: date)
        }
        let prefix: String
        switch payload.acquisition {
        case .active: prefix = isStale(payload: payload, date: date) ? "Stale capture" : "Last capture"
        case .noSources: return "No UPS detected"
        case .readFailed: prefix = "Read failed · stale"
        case .stopped: prefix = "Stopped · stale"
        }
        return "\(prefix) · \(capturedLineState(snapshot))"
    }

    static func isStale(payload: WidgetSnapshot?, date: Date) -> Bool {
        guard let payload, payload.snapshot != nil else { return true }
        return payload.isStale(at: date)
    }

    static func ageLabel(_ snapshot: MonitorSnapshot, date: Date) -> String {
        UPSMonitorFormatters.relativeAge(from: snapshot.capturedAt, to: date)
    }

    static func chargeMetric(_ snapshot: MonitorSnapshot) -> MonitorMetric? {
        snapshot.metrics.first(where: { $0.id == .batteryCharge && $0.quality == .available && $0.value?.isFinite == true })
    }

    static func chargeValue(_ snapshot: MonitorSnapshot, includeProvenance: Bool = false) -> String {
        guard let metric = chargeMetric(snapshot), let value = metric.value else {
            return snapshot.metrics.first(where: { $0.id == .batteryCharge })
                .map { UPSMonitorFormatters.qualityLabel($0.quality) } ?? "Not reported"
        }
        let valueLabel = "\(number(value))%"
        guard includeProvenance else { return valueLabel }
        return "\(valueLabel) · \(UPSMonitorFormatters.provenanceLabel(metric.provenance))"
    }

    static func metricValue(_ id: MonitorMetricID, in snapshot: MonitorSnapshot) -> String {
        guard let metric = snapshot.metrics.first(where: { $0.id == id }) else { return "Not reported" }
        guard metric.quality == .available, let value = metric.value, value.isFinite else {
            return UPSMonitorFormatters.qualityLabel(metric.quality)
        }
        let measurement: String
        if id == .batteryRuntime {
            let (scaled, unit) = runtime(value)
            measurement = "\(number(scaled)) \(unit)"
        } else {
            measurement = "\(number(value)) \(UPSMonitorFormatters.unitLabel(metric.unit))"
        }
        return "\(measurement) · \(UPSMonitorFormatters.provenanceLabel(metric.provenance))"
    }

    static func symbol(payload: WidgetSnapshot?, date: Date) -> String {
        guard let payload else { return "questionmark.circle" }
        guard (try? payload.validate()) != nil else { return "questionmark.circle" }
        switch payload.acquisition {
        case .active:
            guard let snapshot = payload.snapshot else { return "questionmark.circle" }
            if isStale(payload: payload, date: date) { return "clock" }
            switch snapshot.status.lineState {
            case .onLine: return "powerplug.fill"
            case .onBattery: return "battery.25percent"
            case .unknown: return "questionmark.circle"
            }
        case .noSources: return "powerplug"
        case .readFailed: return "exclamationmark.triangle"
        case .stopped: return "pause.circle"
        }
    }

    private static func number(_ value: Double) -> String {
        value.formatted(.number.precision(.significantDigits(1...4)))
    }

    private static func runtime(_ seconds: Double) -> (Double, String) {
        guard seconds.isFinite, seconds >= 0 else { return (seconds, "s") }
        if seconds >= 3_600 { return (seconds / 3_600, "hr") }
        if seconds >= 60 { return (seconds / 60, "min") }
        return (seconds, "s")
    }
}
