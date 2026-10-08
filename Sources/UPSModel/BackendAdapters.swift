import Foundation
import UPSCore
import NUTData

public enum MonitorAdapterError: Error, Equatable {
    case invalidSource
    case sourceMismatch
    case sourceUnavailable
    case metricMismatch
}

public enum MonitorSnapshotAdapter {
    public static func fromApple(
        _ snapshot: PowerSourceSnapshot,
        source: MonitorSource,
        powerSourceID: String
    ) throws -> MonitorSnapshot {
        guard source.provider == .apple else { throw MonitorAdapterError.invalidSource }
        try source.validate()
        guard snapshot.availability == .available,
              let powerSource = snapshot.sources.first(where: { $0.id == powerSourceID }),
              powerSource.kind == .ups, powerSource.isPresent == true else {
            throw MonitorAdapterError.sourceUnavailable
        }

        let metrics = try [
            appleMetric(.batteryCharge, powerSource.charge, inputUnit: .ratio, scale: 100),
            appleMetric(.batteryRuntime, powerSource.timeToEmpty, inputUnit: .seconds),
            appleMetric(.batteryTimeToFull, powerSource.timeToFullCharge, inputUnit: .seconds),
            appleMetric(.batteryVoltage, powerSource.batteryVoltage, inputUnit: .volts),
            appleMetric(.appleSourceCurrent, powerSource.sourceCurrent, inputUnit: .amps),
            appleMetric(.appleSourceTemperature, powerSource.sourceTemperature, inputUnit: .celsius),
        ]
        var flags: Set<MonitorStatusFlag> = []
        if powerSource.isCharging == true { flags.insert(.charging) }
        let lineState: MonitorLineState
        let statusQuality: MonitorStatusQuality
        switch powerSource.state {
        case .acPower: lineState = .onLine; statusQuality = .available
        case .batteryPower: lineState = .onBattery; statusQuality = .available
        case .offLine:
            lineState = .unknown
            statusQuality = .unqualified
            flags.insert(.sourceOffline)
        case .unknown: lineState = .unknown; statusQuality = .unqualified
        }
        let status = MonitorStatus(lineState: lineState, flags: flags, quality: statusQuality,
                                   internalFailure: powerSource.internalFailure,
                                   batteryHealth: powerSource.batteryHealth.map(batteryHealth),
                                   isCharging: powerSource.isCharging)
        let result = MonitorSnapshot(source: source, capturedAt: snapshot.capturedAt, status: status, metrics: metrics)
        try result.validate()
        return result
    }

    public static func fromNUT(_ snapshot: NUTSnapshot, source: MonitorSource) throws -> MonitorSnapshot {
        guard source.provider == .nut else { throw MonitorAdapterError.invalidSource }
        try source.validate()
        guard snapshot.sourceID == source.id else { throw MonitorAdapterError.sourceMismatch }
        var metrics: [MonitorMetric] = []
        for (key, value) in snapshot.metrics {
            guard key == value.identifier, value.unit == value.identifier.unit else {
                throw MonitorAdapterError.metricMismatch
            }
            metrics.append(try nutMetric(value))
        }
        metrics.sort { $0.id.rawValue < $1.id.rawValue }
        var flags = Set(snapshot.status.flags.compactMap { MonitorStatusFlag(rawValue: $0.rawValue) })
        if snapshot.status.lineState == .off { flags.insert(.outputOff) }
        let status = MonitorStatus(
            lineState: lineState(snapshot.status.lineState),
            flags: flags,
            quality: statusQuality(snapshot.status.quality)
        )
        let result = MonitorSnapshot(source: source, capturedAt: snapshot.capturedAt, status: status, metrics: metrics)
        try result.validate()
        return result
    }

    private static func appleMetric(_ id: MonitorMetricID, _ metric: Metric, inputUnit: MetricUnit, scale: Double = 1) throws -> MonitorMetric {
        guard metric.unit == inputUnit else { throw MonitorAdapterError.metricMismatch }
        return MonitorMetric(
            id: id,
            value: metric.value.map { $0 * scale },
            unit: id.allowedUnit,
            quality: metricQuality(metric.quality),
            provenance: provenance(metric.provenance)
        )
    }

    private static func nutMetric(_ metric: NUTMetric) throws -> MonitorMetric {
        let provenance: MonitorMetricProvenance
        switch metric.provenance {
        case .reported: provenance = .reported
        case .estimated: provenance = .estimated
        case .derivedByDriver: provenance = .driverDerived
        }
        let quality: MonitorMetricQuality
        switch metric.quality {
        case .available: quality = .available
        case .unavailable: quality = .unavailable
        case .invalid: quality = .invalid
        }
        guard let id = MonitorMetricID(rawValue: metric.identifier.rawValue) else { throw MonitorAdapterError.metricMismatch }
        return MonitorMetric(
            id: id,
            value: metric.value,
            unit: unit(metric.unit),
            quality: quality,
            provenance: provenance
        )
    }

    private static func metricQuality(_ quality: MetricQuality) -> MonitorMetricQuality {
        switch quality {
        case .available: .available
        case .unavailable: .unavailable
        case .invalid: .invalid
        case .calculating: .calculating
        }
    }

    private static func provenance(_ value: MetricProvenance) -> MonitorMetricProvenance {
        switch value {
        case .reported: .reported
        case .derived: .derived
        case .estimated: .estimated
        }
    }

    private static func lineState(_ state: NUTLineState) -> MonitorLineState {
        switch state {
        case .onLine: .onLine
        case .onBattery: .onBattery
        case .off: .unknown
        case .unknown: .unknown
        }
    }

    private static func statusQuality(_ quality: NUTStatusQuality) -> MonitorStatusQuality {
        switch quality {
        case .available: .available
        case .unavailable: .unavailable
        case .invalid: .invalid
        case .unqualified: .unqualified
        }
    }

    private static func batteryHealth(_ health: BatteryHealth) -> MonitorBatteryHealth {
        switch health {
        case .good: .good
        case .fair: .fair
        case .poor: .poor
        case .unknown: .unknown
        }
    }

    private static func unit(_ unit: NUTMetricUnit) -> MonitorMetricUnit {
        switch unit {
        case .percent: .percent
        case .seconds: .seconds
        case .volts: .volts
        case .amps: .amps
        case .hertz: .hertz
        case .watts: .watts
        case .voltAmps: .voltAmps
        case .celsius: .celsius
        }
    }
}
