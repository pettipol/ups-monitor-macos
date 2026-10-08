import SwiftUI
import UPSModel
import UPSMonitorUI
import UPSWidgetData

public struct UPSWidgetView: View {
    public let payload: WidgetSnapshot?
    public let date: Date
    public let isMedium: Bool
    public let unavailableReason: String?

    public init(payload: WidgetSnapshot?, date: Date, isMedium: Bool, unavailableReason: String? = nil) {
        self.payload = payload
        self.date = date
        self.isMedium = isMedium
        self.unavailableReason = unavailableReason
    }

    public var body: some View {
        Group {
            if let snapshot = UPSWidgetPresentation.snapshot(payload) {
                VStack(alignment: .leading, spacing: 5) {
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
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 5) {
                header(for: snapshot)
                chargeRow(snapshot, prominent: false)
                chargeProgress(snapshot)
                stateLine()
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Divider()

            VStack(alignment: .leading, spacing: 4) {
                metricRow("Runtime estimate", id: .batteryRuntime, snapshot: snapshot)
                metricRow("Real power", id: .upsRealPower, snapshot: snapshot)
                metricRow("Apparent power", id: .upsApparentPower, snapshot: snapshot)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func header(for snapshot: MonitorSnapshot) -> some View {
        HStack(spacing: 6) {
            Image(systemName: UPSWidgetPresentation.symbol(payload: payload, date: date))
                .accessibilityHidden(true)
            Text("UPS · \(UPSMonitorFormatters.providerLabel(snapshot.source.provider))")
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
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

    private func metricRow(_ title: String, id: MonitorMetricID, snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Text(UPSWidgetPresentation.metricValue(id, in: snapshot))
                .font(.caption.weight(.medium))
                .monospacedDigit()
                .fixedSize(horizontal: false, vertical: true)
                .lineLimit(2)
        }
    }

    private func emptyContent() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: UPSWidgetPresentation.symbol(payload: payload, date: date))
                .font(.title3)
                .accessibilityHidden(true)
            Text(UPSWidgetPresentation.stateLabel(payload: payload, date: date,
                                                  unavailableReason: unavailableReason))
                .font(.subheadline.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

enum UPSWidgetPresentation {
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

    static func chargeValue(_ snapshot: MonitorSnapshot) -> String {
        guard let metric = chargeMetric(snapshot), let value = metric.value else {
            return snapshot.metrics.first(where: { $0.id == .batteryCharge })
                .map { UPSMonitorFormatters.qualityLabel($0.quality) } ?? "Not reported"
        }
        return "\(number(value))%"
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
