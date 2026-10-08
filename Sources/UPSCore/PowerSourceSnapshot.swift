import Foundation

public enum PowerSourceKind: String, Codable, Sendable {
    case ups
    case internalBattery
    case unknown
}

public enum PowerSourceState: String, Codable, Sendable {
    case acPower
    case batteryPower
    case offLine
    case unknown
}

public enum MetricQuality: String, Codable, Sendable {
    case available
    case unavailable
    case invalid
    case calculating
}

public enum MetricUnit: String, Codable, Sendable {
    case ratio
    case seconds
    case volts
    case amps
    case celsius
}

public enum MetricProvenance: String, Codable, Sendable {
    case reported
    case derived
    case estimated
}

public enum BatteryHealth: String, Codable, Sendable {
    case good
    case fair
    case poor
    case unknown
}

public struct Metric: Codable, Equatable, Sendable {
    public let value: Double?
    public let unit: MetricUnit
    public let quality: MetricQuality
    public let provenance: MetricProvenance

    public init(value: Double?, unit: MetricUnit, quality: MetricQuality, provenance: MetricProvenance) {
        self.value = value
        self.unit = unit
        self.quality = quality
        self.provenance = provenance
    }
}

public struct PowerSource: Codable, Equatable, Sendable {
    /// A caller-generated ordinal identifier, never an IOKit device identifier.
    public let id: String
    public let kind: PowerSourceKind
    public let isPresent: Bool?
    public let state: PowerSourceState
    public let isCharging: Bool?
    public let charge: Metric
    public let timeToEmpty: Metric
    public let timeToFullCharge: Metric
    public let batteryVoltage: Metric
    public let sourceCurrent: Metric
    public let sourceTemperature: Metric
    public let internalFailure: Bool?
    public let batteryHealth: BatteryHealth?

    public init(
        id: String,
        kind: PowerSourceKind,
        isPresent: Bool?,
        state: PowerSourceState,
        isCharging: Bool?,
        charge: Metric,
        timeToEmpty: Metric,
        timeToFullCharge: Metric,
        batteryVoltage: Metric,
        sourceCurrent: Metric,
        sourceTemperature: Metric,
        internalFailure: Bool?,
        batteryHealth: BatteryHealth?
    ) {
        self.id = id
        self.kind = kind
        self.isPresent = isPresent
        self.state = state
        self.isCharging = isCharging
        self.charge = charge
        self.timeToEmpty = timeToEmpty
        self.timeToFullCharge = timeToFullCharge
        self.batteryVoltage = batteryVoltage
        self.sourceCurrent = sourceCurrent
        self.sourceTemperature = sourceTemperature
        self.internalFailure = internalFailure
        self.batteryHealth = batteryHealth
    }
}

public struct CapabilityCounts: Codable, Equatable, Sendable {
    public let charge: Int
    public let timeToEmpty: Int
    public let timeToFullCharge: Int
    public let batteryVoltage: Int
    public let sourceCurrent: Int
    public let sourceTemperature: Int
    public let internalFailure: Int
    public let batteryHealth: Int

    public init(sources: [PowerSource]) {
        charge = sources.filter { $0.charge.quality == .available }.count
        timeToEmpty = sources.filter { $0.timeToEmpty.quality == .available }.count
        timeToFullCharge = sources.filter { $0.timeToFullCharge.quality == .available }.count
        batteryVoltage = sources.filter { $0.batteryVoltage.quality == .available }.count
        sourceCurrent = sources.filter { $0.sourceCurrent.quality == .available }.count
        sourceTemperature = sources.filter { $0.sourceTemperature.quality == .available }.count
        internalFailure = sources.filter { $0.internalFailure != nil }.count
        batteryHealth = sources.filter { $0.batteryHealth != nil && $0.batteryHealth != .unknown }.count
    }
}

public struct DiscoveryCounts: Codable, Equatable, Sendable {
    public let ups: Int
    public let internalBattery: Int
    public let unknownType: Int
    public let upsAbsent: Int
    public let upsPresenceUnknown: Int

    public init(ups: Int, internalBattery: Int, unknownType: Int, upsAbsent: Int = 0, upsPresenceUnknown: Int = 0) {
        self.ups = ups
        self.internalBattery = internalBattery
        self.unknownType = unknownType
        self.upsAbsent = upsAbsent
        self.upsPresenceUnknown = upsPresenceUnknown
    }
}

public enum SnapshotAvailability: String, Codable, Sendable {
    case available
    case unavailable
}

public enum SnapshotProvider: String, Codable, Sendable {
    case appleIOPowerSources
}

public struct PowerSourceSnapshot: Codable, Equatable, Sendable {
    public let capturedAt: Date
    public let provider: SnapshotProvider
    public let availability: SnapshotAvailability
    public let discovery: DiscoveryCounts
    public let capabilities: CapabilityCounts
    public let sources: [PowerSource]

    public init(
        capturedAt: Date,
        provider: SnapshotProvider = .appleIOPowerSources,
        availability: SnapshotAvailability,
        discovery: DiscoveryCounts,
        sources: [PowerSource]
    ) {
        self.capturedAt = capturedAt
        self.provider = provider
        self.availability = availability
        self.discovery = discovery
        capabilities = CapabilityCounts(sources: sources)
        self.sources = sources
    }
}
