import Foundation

public enum NUTMetricID: String, Codable, CaseIterable, Sendable {
    case batteryCharge
    case batteryRuntime
    case batteryVoltage
    case batteryVoltageNominal
    case batteryCurrent
    case batteryTemperature
    case inputVoltage
    case inputVoltageNominal
    case inputCurrent
    case inputCurrentNominal
    case inputFrequency
    case inputFrequencyNominal
    case inputRealPower
    case inputRealPowerNominal
    case inputApparentPower
    case outputVoltage
    case outputVoltageNominal
    case outputCurrent
    case outputCurrentNominal
    case outputFrequency
    case outputFrequencyNominal
    case upsLoad
    case upsRealPower
    case upsRealPowerNominal
    case upsApparentPower
    case upsApparentPowerNominal
    case upsTemperature

    public var unit: NUTMetricUnit {
        switch self {
        case .batteryCharge, .upsLoad: .percent
        case .batteryRuntime: .seconds
        case .batteryVoltage, .batteryVoltageNominal, .inputVoltage,
             .inputVoltageNominal, .outputVoltage, .outputVoltageNominal: .volts
        case .batteryCurrent, .inputCurrent, .inputCurrentNominal,
             .outputCurrent, .outputCurrentNominal: .amps
        case .batteryTemperature, .upsTemperature: .celsius
        case .inputFrequency, .inputFrequencyNominal,
             .outputFrequency, .outputFrequencyNominal: .hertz
        case .inputRealPower, .inputRealPowerNominal, .upsRealPower, .upsRealPowerNominal: .watts
        case .inputApparentPower, .upsApparentPower, .upsApparentPowerNominal: .voltAmps
        }
    }

    var nutVariable: String {
        switch self {
        case .batteryCharge: "battery.charge"
        case .batteryRuntime: "battery.runtime"
        case .batteryVoltage: "battery.voltage"
        case .batteryVoltageNominal: "battery.voltage.nominal"
        case .batteryCurrent: "battery.current"
        case .batteryTemperature: "battery.temperature"
        case .inputVoltage: "input.voltage"
        case .inputVoltageNominal: "input.voltage.nominal"
        case .inputCurrent: "input.current"
        case .inputCurrentNominal: "input.current.nominal"
        case .inputFrequency: "input.frequency"
        case .inputFrequencyNominal: "input.frequency.nominal"
        case .inputRealPower: "input.realpower"
        case .inputRealPowerNominal: "input.realpower.nominal"
        case .inputApparentPower: "input.power"
        case .outputVoltage: "output.voltage"
        case .outputVoltageNominal: "output.voltage.nominal"
        case .outputCurrent: "output.current"
        case .outputCurrentNominal: "output.current.nominal"
        case .outputFrequency: "output.frequency"
        case .outputFrequencyNominal: "output.frequency.nominal"
        case .upsLoad: "ups.load"
        case .upsRealPower: "ups.realpower"
        case .upsRealPowerNominal: "ups.realpower.nominal"
        case .upsApparentPower: "ups.power"
        case .upsApparentPowerNominal: "ups.power.nominal"
        case .upsTemperature: "ups.temperature"
        }
    }

    var percentRange: ClosedRange<Double>? {
        switch self {
        case .batteryCharge: 0...100
        default: nil
        }
    }

    var mustBeNonnegative: Bool {
        switch self {
        case .batteryRuntime, .batteryVoltage, .batteryVoltageNominal,
             .inputVoltage, .inputVoltageNominal, .inputFrequency,
             .inputFrequencyNominal, .inputRealPower, .inputRealPowerNominal,
             .inputApparentPower,
             .outputVoltage, .outputVoltageNominal, .outputFrequency,
             .outputFrequencyNominal, .upsRealPower, .upsRealPowerNominal,
             .upsApparentPower, .upsApparentPowerNominal, .upsLoad: true
        case .batteryCharge, .batteryCurrent, .batteryTemperature,
             .inputCurrent, .inputCurrentNominal, .outputCurrent, .outputCurrentNominal,
             .upsTemperature: false
        }
    }
}

public enum NUTMetricUnit: String, Codable, Sendable {
    case percent
    case seconds
    case volts
    case amps
    case hertz
    case watts
    case voltAmps
    case celsius
}

public enum NUTMetricQuality: String, Codable, Sendable {
    case available
    case unavailable
    case invalid
}

public enum NUTMetricProvenance: String, Codable, Sendable {
    /// Value was exported by the NUT server; this does not independently verify accuracy.
    case reported
    /// The NUT `battery.runtime` value is an estimate, not a directly measured duration.
    case estimated
    /// NUT's apcmicrolink driver derives this power value from its load percentage and nominal rating.
    case derivedByDriver
}

public struct NUTMetric: Codable, Equatable, Sendable {
    public let identifier: NUTMetricID
    public let value: Double?
    public let unit: NUTMetricUnit
    public let quality: NUTMetricQuality
    public let provenance: NUTMetricProvenance

    public init(identifier: NUTMetricID, value: Double?, quality: NUTMetricQuality, provenance: NUTMetricProvenance = .reported) {
        self.identifier = identifier
        self.value = value
        self.unit = identifier.unit
        self.quality = quality
        self.provenance = provenance
    }
}

public enum NUTLineState: String, Codable, Sendable {
    case onLine
    case onBattery
    case off
    case unknown
}

public enum NUTStatusFlag: String, Codable, CaseIterable, Sendable {
    case lowBattery
    case highBattery
    case replaceBattery
    case outputOff
    case bypass
    case calibration
    case charging
    case discharging
    case overload
    case trim
    case boost
    case forcedShutdown
    case alarm
}

public enum NUTStatusQuality: String, Codable, Sendable {
    case available
    case unavailable
    case invalid
    case unqualified
}

public struct NUTStatus: Codable, Equatable, Sendable {
    public let lineState: NUTLineState
    public let flags: Set<NUTStatusFlag>
    public let quality: NUTStatusQuality

    public init(lineState: NUTLineState, flags: Set<NUTStatusFlag>, quality: NUTStatusQuality) {
        self.lineState = lineState
        self.flags = flags
        self.quality = quality
    }
}

public enum NUTSnapshotProvider: String, Codable, Sendable {
    case upscOutput
}

public struct NUTSnapshot: Codable, Equatable, Sendable {
    /// Caller-assigned opaque identifier. The decoder never infers identity from UPS output.
    public let sourceID: String
    public let provider: NUTSnapshotProvider
    public let capturedAt: Date
    public let status: NUTStatus
    public let metrics: [NUTMetricID: NUTMetric]

    public init(sourceID: String, capturedAt: Date, status: NUTStatus, metrics: [NUTMetricID: NUTMetric]) {
        self.sourceID = sourceID
        self.provider = .upscOutput
        self.capturedAt = capturedAt
        self.status = status
        self.metrics = metrics
    }
}
