import Foundation
import UPSModel

public enum UPSReadState: String, Equatable, Sendable {
    case loading
    case ready
    case noSources
    case failed
    case stopped
}

public enum UPSMonitorFormatters: Sendable {
    public static let freshnessLimit: TimeInterval = 15

    public static func sourceKey(for snapshot: MonitorSnapshot) -> String {
        "\(snapshot.source.provider.rawValue)|\(snapshot.source.id)|\(snapshot.source.sessionID)"
    }

    public static func sourceLabel(at index: Int, provider: MonitorProvider) -> String {
        "UPS \(index + 1) · \(providerLabel(provider))"
    }

    public static func providerLabel(_ provider: MonitorProvider) -> String {
        switch provider {
        case .apple: "Apple"
        case .nut: "NUT"
        }
    }

    public static func readStateLabel(_ state: UPSReadState) -> String {
        switch state {
        case .loading: "Reading"
        case .ready: "Current"
        case .noSources: "No UPS detected"
        case .failed: "Read failed"
        case .stopped: "Monitoring stopped"
        }
    }

    public static func freshness(
        of snapshot: MonitorSnapshot,
        now: Date,
        maximumAge: TimeInterval = freshnessLimit,
        acquisitionSucceeded: Bool
    ) -> SnapshotFreshness {
        evaluateFreshness(snapshot: snapshot, now: now, maximumAge: maximumAge,
                          acquisitionSucceeded: acquisitionSucceeded)
    }

    public static func freshnessLabel(
        of snapshot: MonitorSnapshot,
        now: Date,
        maximumAge: TimeInterval = freshnessLimit,
        acquisitionSucceeded: Bool
    ) -> String {
        switch freshness(of: snapshot, now: now, maximumAge: maximumAge,
                         acquisitionSucceeded: acquisitionSucceeded) {
        case .fresh: "Updated \(relativeAge(from: snapshot.capturedAt, to: now))"
        case .stale: "Stale · last capture \(timestamp(snapshot.capturedAt))"
        }
    }

    public static func relativeAge(from date: Date, to now: Date) -> String {
        let interval = now.timeIntervalSince(date)
        guard interval.isFinite, interval >= 0 else { return "time unknown" }
        if interval < 10 { return "just now" }
        if interval < 60 { return "\(Int(interval.rounded(.down))) sec ago" }
        if interval < 3_600 { return "\(Int(interval / 60)) min ago" }
        if interval < 86_400 { return "\(Int(interval / 3_600)) hr ago" }
        guard interval / 86_400 < Double(Int.max) else { return "Very old" }
        return "\(Int(interval / 86_400)) days ago"
    }

    public static func timestamp(_ date: Date) -> String {
        date.formatted(date: .abbreviated, time: .shortened)
    }

    public static func metricValue(_ metric: MonitorMetric) -> String {
        guard metric.quality == .available, let value = metric.value, value.isFinite else {
            return qualityLabel(metric.quality)
        }
        let number = value.formatted(.number.precision(.significantDigits(1...6)))
        return "\(number) \(unitLabel(metric.unit))"
    }

    public static func metricName(_ id: MonitorMetricID) -> String {
        switch id {
        case .batteryCharge: "Battery charge"
        case .batteryRuntime: "Runtime estimate"
        case .batteryTimeToFull: "Time to full charge"
        case .batteryVoltage: "Battery voltage"
        case .batteryVoltageNominal: "Battery nominal voltage"
        case .batteryCurrent: "Battery current"
        case .batteryTemperature: "Battery temperature"
        case .inputVoltage: "Input voltage"
        case .inputVoltageNominal: "Input nominal voltage"
        case .inputCurrent: "Input current"
        case .inputCurrentNominal: "Input nominal current"
        case .inputFrequency: "Input frequency"
        case .inputFrequencyNominal: "Input nominal frequency"
        case .inputRealPower: "Input real power"
        case .inputRealPowerNominal: "Input nominal real power"
        case .inputApparentPower: "Input apparent power"
        case .outputVoltage: "Output voltage"
        case .outputVoltageNominal: "Output nominal voltage"
        case .outputCurrent: "Output current"
        case .outputCurrentNominal: "Output nominal current"
        case .outputFrequency: "Output frequency"
        case .outputFrequencyNominal: "Output nominal frequency"
        case .upsLoad: "UPS load"
        case .upsRealPower: "UPS real power"
        case .upsRealPowerNominal: "UPS nominal real power"
        case .upsApparentPower: "UPS apparent power"
        case .upsApparentPowerNominal: "UPS nominal apparent power"
        case .upsTemperature: "UPS temperature"
        case .appleSourceCurrent: "Source current"
        case .appleSourceTemperature: "Source temperature"
        }
    }

    public static func unitLabel(_ unit: MonitorMetricUnit) -> String {
        switch unit {
        case .percent: "%"
        case .seconds: "s"
        case .volts: "V"
        case .amps: "A"
        case .hertz: "Hz"
        case .watts: "W"
        case .voltAmps: "VA"
        case .celsius: "°C"
        }
    }

    public static func qualityLabel(_ quality: MonitorMetricQuality) -> String {
        switch quality {
        case .available: "Available"
        case .unavailable: "Not reported"
        case .invalid: "Invalid reading"
        case .calculating: "Calculating"
        }
    }

    public static func provenanceLabel(_ provenance: MonitorMetricProvenance) -> String {
        switch provenance {
        case .reported: "Reported"
        case .derived: "Derived"
        case .estimated: "Estimated"
        case .driverDerived: "Driver-derived"
        }
    }

    public static func lineStateLabel(_ state: MonitorLineState) -> String {
        switch state {
        case .onLine: "On line"
        case .onBattery: "On battery"
        case .unknown: "Unknown"
        }
    }

    public static func statusFlagLabel(_ flag: MonitorStatusFlag) -> String {
        switch flag {
        case .lowBattery: "Low battery"
        case .highBattery: "High battery"
        case .replaceBattery: "Replace battery"
        case .outputOff: "Output off"
        case .bypass: "Bypass"
        case .calibration: "Calibration"
        case .charging: "Charging"
        case .discharging: "Discharging"
        case .overload: "Overload"
        case .trim: "Trim"
        case .boost: "Boost"
        case .forcedShutdown: "Forced shutdown"
        case .alarm: "Alarm"
        case .sourceOffline: "Source offline"
        }
    }

    public static func healthLabel(_ health: MonitorBatteryHealth) -> String {
        switch health {
        case .good: "Good"
        case .fair: "Fair"
        case .poor: "Poor"
        case .unknown: "Unknown"
        }
    }

    public static func statusQualityLabel(_ quality: MonitorStatusQuality) -> String {
        switch quality {
        case .available: "Available"
        case .unavailable: "Not reported"
        case .invalid: "Invalid status"
        case .unqualified: "Unqualified status"
        }
    }
}
