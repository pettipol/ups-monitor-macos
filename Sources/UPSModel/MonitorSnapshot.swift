import Foundation

public enum MonitorProvider: String, Codable, Sendable {
    case apple
    case nut
}

public enum IdentityStability: String, Codable, Sendable {
    case sessionLocal
    case configured
}

public enum MonitorValidationError: Error, Equatable {
    case unsupportedSchemaVersion
    case invalidSource
    case invalidDate
    case invalidMetricCount
    case duplicateMetricID
    case invalidMetricValue
    case invalidMetricUnit
    case invalidStatus
}

public struct MonitorSource: Codable, Equatable, Sendable {
    public let provider: MonitorProvider
    public let id: String
    public let sessionID: String
    public let identityStability: IdentityStability

    public init(provider: MonitorProvider, id: String, sessionID: String, identityStability: IdentityStability) {
        self.provider = provider
        self.id = id
        self.sessionID = sessionID
        self.identityStability = identityStability
    }

    public func validate() throws {
        guard Self.validIdentifier(id), Self.validIdentifier(sessionID) else {
            throw MonitorValidationError.invalidSource
        }
    }

    private static func validIdentifier(_ value: String) -> Bool {
        guard (1...64).contains(value.utf8.count),
              let first = value.utf8.first,
              isAlphaNumeric(first) else { return false }
        return value.utf8.allSatisfy { isAlphaNumeric($0) || $0 == 46 || $0 == 95 || $0 == 45 }
    }

    private static func isAlphaNumeric(_ byte: UInt8) -> Bool {
        (48...57).contains(byte) || (65...90).contains(byte) || (97...122).contains(byte)
    }

    private enum CodingKeys: String, CodingKey { case provider, id, sessionID, identityStability }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        provider = try values.decode(MonitorProvider.self, forKey: .provider)
        id = try values.decode(String.self, forKey: .id)
        sessionID = try values.decode(String.self, forKey: .sessionID)
        identityStability = try values.decode(IdentityStability.self, forKey: .identityStability)
        do { try validate() } catch { throw DecodingError.dataCorruptedError(forKey: .id, in: values, debugDescription: "Invalid source identity") }
    }
}

public enum MonitorLineState: String, Codable, Sendable { case onLine, onBattery, unknown }
public enum MonitorStatusFlag: String, Codable, CaseIterable, Sendable {
    case lowBattery, highBattery, replaceBattery, outputOff, bypass, calibration, charging
    case discharging, overload, trim, boost, forcedShutdown, alarm, sourceOffline
}
public enum MonitorStatusQuality: String, Codable, Sendable { case available, unavailable, invalid, unqualified }
public enum MonitorBatteryHealth: String, Codable, Sendable { case good, fair, poor, unknown }

public struct MonitorStatus: Codable, Equatable, Sendable {
    public let lineState: MonitorLineState
    public let flags: Set<MonitorStatusFlag>
    public let quality: MonitorStatusQuality
    public let internalFailure: Bool?
    public let batteryHealth: MonitorBatteryHealth?
    public let isCharging: Bool?

    public init(
        lineState: MonitorLineState = .unknown,
        flags: Set<MonitorStatusFlag> = [],
        quality: MonitorStatusQuality,
        internalFailure: Bool? = nil,
        batteryHealth: MonitorBatteryHealth? = nil,
        isCharging: Bool? = nil
    ) {
        self.lineState = lineState
        self.flags = flags
        self.quality = quality
        self.internalFailure = internalFailure
        self.batteryHealth = batteryHealth
        self.isCharging = isCharging
    }
}

public enum MonitorMetricID: String, Codable, CaseIterable, Sendable {
    case batteryCharge, batteryRuntime, batteryTimeToFull, batteryVoltage, batteryVoltageNominal, batteryCurrent, batteryTemperature
    case inputVoltage, inputVoltageNominal, inputCurrent, inputCurrentNominal, inputFrequency, inputFrequencyNominal
    case inputRealPower, inputRealPowerNominal, inputApparentPower
    case outputVoltage, outputVoltageNominal, outputCurrent, outputCurrentNominal, outputFrequency, outputFrequencyNominal
    case upsLoad, upsRealPower, upsRealPowerNominal, upsApparentPower, upsApparentPowerNominal, upsTemperature
    case appleSourceCurrent, appleSourceTemperature

    public var allowedUnit: MonitorMetricUnit {
        switch self {
        case .batteryCharge, .upsLoad: .percent
        case .batteryRuntime, .batteryTimeToFull: .seconds
        case .batteryVoltage, .batteryVoltageNominal, .inputVoltage, .inputVoltageNominal,
             .outputVoltage, .outputVoltageNominal: .volts
        case .batteryCurrent, .inputCurrent, .inputCurrentNominal, .outputCurrent, .outputCurrentNominal,
             .appleSourceCurrent: .amps
        case .batteryTemperature, .upsTemperature, .appleSourceTemperature: .celsius
        case .inputFrequency, .inputFrequencyNominal, .outputFrequency, .outputFrequencyNominal: .hertz
        case .inputRealPower, .inputRealPowerNominal, .upsRealPower, .upsRealPowerNominal: .watts
        case .inputApparentPower, .upsApparentPower, .upsApparentPowerNominal: .voltAmps
        }
    }
}

public enum MonitorMetricUnit: String, Codable, Sendable { case percent, seconds, volts, amps, hertz, watts, voltAmps, celsius }
public enum MonitorMetricQuality: String, Codable, Sendable { case available, unavailable, invalid, calculating }
public enum MonitorMetricProvenance: String, Codable, Sendable { case reported, derived, estimated, driverDerived }

public struct MonitorMetric: Codable, Equatable, Sendable {
    public let id: MonitorMetricID
    public let value: Double?
    public let unit: MonitorMetricUnit
    public let quality: MonitorMetricQuality
    public let provenance: MonitorMetricProvenance

    public init(id: MonitorMetricID, value: Double?, unit: MonitorMetricUnit, quality: MonitorMetricQuality, provenance: MonitorMetricProvenance) {
        self.id = id
        self.value = value
        self.unit = unit
        self.quality = quality
        self.provenance = provenance
    }

    private enum CodingKeys: String, CodingKey { case id, value, unit, quality, provenance }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(MonitorMetricID.self, forKey: .id)
        value = try values.decodeIfPresent(Double.self, forKey: .value)
        unit = try values.decode(MonitorMetricUnit.self, forKey: .unit)
        quality = try values.decode(MonitorMetricQuality.self, forKey: .quality)
        provenance = try values.decode(MonitorMetricProvenance.self, forKey: .provenance)
    }
}

public struct MonitorSnapshot: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let source: MonitorSource
    public let capturedAt: Date
    public let status: MonitorStatus
    public let metrics: [MonitorMetric]

    public init(schemaVersion: Int = 1, source: MonitorSource, capturedAt: Date, status: MonitorStatus, metrics: [MonitorMetric]) {
        self.schemaVersion = schemaVersion
        self.source = source
        self.capturedAt = capturedAt
        self.status = status
        self.metrics = metrics
    }

    public func validate() throws {
        guard schemaVersion == 1 else { throw MonitorValidationError.unsupportedSchemaVersion }
        try source.validate()
        if source.provider == .apple && source.identityStability != .sessionLocal {
            throw MonitorValidationError.invalidSource
        }
        guard capturedAt.timeIntervalSince1970.isFinite else { throw MonitorValidationError.invalidDate }
        if status.quality != .available && status.lineState != .unknown {
            throw MonitorValidationError.invalidStatus
        }
        guard metrics.count <= 64 else { throw MonitorValidationError.invalidMetricCount }
        var seen = Set<MonitorMetricID>()
        for metric in metrics {
            guard seen.insert(metric.id).inserted else { throw MonitorValidationError.duplicateMetricID }
            guard metric.unit == metric.id.allowedUnit else { throw MonitorValidationError.invalidMetricUnit }
            switch metric.quality {
            case .available:
                guard let value = metric.value, value.isFinite else { throw MonitorValidationError.invalidMetricValue }
                if metric.id == .batteryCharge && !(0...100).contains(value) {
                    throw MonitorValidationError.invalidMetricValue
                }
                if metric.id.requiresNonnegativeValue && value < 0 { throw MonitorValidationError.invalidMetricValue }
            case .unavailable, .invalid, .calculating:
                guard metric.value == nil else { throw MonitorValidationError.invalidMetricValue }
            }
        }
    }

    private enum CodingKeys: String, CodingKey { case schemaVersion, source, capturedAt, status, metrics }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        source = try values.decode(MonitorSource.self, forKey: .source)
        capturedAt = try values.decode(Date.self, forKey: .capturedAt)
        status = try values.decode(MonitorStatus.self, forKey: .status)
        metrics = try values.decode([MonitorMetric].self, forKey: .metrics)
        do { try validate() } catch { throw DecodingError.dataCorruptedError(forKey: .metrics, in: values, debugDescription: "Invalid monitor snapshot") }
    }
}

private extension MonitorMetricID {
    var requiresNonnegativeValue: Bool {
        switch self {
        case .batteryRuntime, .batteryTimeToFull, .batteryVoltage, .batteryVoltageNominal,
             .inputVoltage, .inputVoltageNominal, .inputFrequency, .inputFrequencyNominal,
             .inputRealPower, .inputRealPowerNominal, .inputApparentPower,
             .outputVoltage, .outputVoltageNominal, .outputFrequency, .outputFrequencyNominal,
             .upsLoad, .upsRealPower, .upsRealPowerNominal, .upsApparentPower, .upsApparentPowerNominal:
            true
        case .batteryCharge, .batteryCurrent, .batteryTemperature, .inputCurrent, .inputCurrentNominal,
             .outputCurrent, .outputCurrentNominal, .upsTemperature, .appleSourceCurrent, .appleSourceTemperature:
            false
        }
    }
}

public enum SnapshotFreshness: Equatable, Sendable { case fresh, stale }

public func evaluateFreshness(
    snapshot: MonitorSnapshot,
    now: Date,
    maximumAge: TimeInterval,
    acquisitionSucceeded: Bool = true
) -> SnapshotFreshness {
    guard acquisitionSucceeded, maximumAge.isFinite, maximumAge >= 0,
          now.timeIntervalSince1970.isFinite, snapshot.capturedAt.timeIntervalSince1970.isFinite else { return .stale }
    let age = now.timeIntervalSince(snapshot.capturedAt)
    guard age.isFinite, age >= 0, age <= maximumAge else { return .stale }
    return .fresh
}
