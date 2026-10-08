import Foundation
import CoreFoundation
import UPSCore

public enum PowerSourceNormalizer {
    public static func normalize(_ values: [String: Any], id: String) -> PowerSource {
        let kind = sourceKind(values["Type"] as? String)
        let state: PowerSourceState
        switch values["Power Source State"] as? String {
        case "AC Power": state = .acPower
        case "Battery Power": state = .batteryPower
        case "Off Line": state = .offLine
        default: state = .unknown
        }

        let charging = boolean(values["Is Charging"])
        let isPresent = boolean(values["Is Present"])
        let charge = normalizedCharge(
            current: integer(values, key: "Current Capacity"),
            maximum: integer(values, key: "Max Capacity")
        )
        let timeToEmpty = normalizedTime(
            integer(values, key: "Time to Empty"),
            validContext: state == .batteryPower && charging == false,
            provenance: .estimated
        )
        let timeToFullCharge = normalizedTime(
            integer(values, key: "Time to Full Charge"),
            validContext: charging == true,
            provenance: .estimated
        )
        let batteryVoltage = normalizedBatteryVoltage(integer(values, key: "Voltage"))
        let sourceCurrent = normalizedSourceCurrent(integer(values, key: "Current"))
        let sourceTemperature = normalizedSourceTemperature(integer(values, key: "Temperature"))
        let internalFailure = boolean(values["Internal Failure"])
        let batteryHealth = health(values["BatteryHealth"])

        return PowerSource(
            id: id,
            kind: kind,
            isPresent: isPresent,
            state: state,
            isCharging: charging,
            charge: charge,
            timeToEmpty: timeToEmpty,
            timeToFullCharge: timeToFullCharge,
            batteryVoltage: batteryVoltage,
            sourceCurrent: sourceCurrent,
            sourceTemperature: sourceTemperature,
            internalFailure: internalFailure,
            batteryHealth: batteryHealth
        )
    }

    public static func snapshot(
        from descriptions: [[String: Any]],
        capturedAt: Date = Date(),
        availability: SnapshotAvailability = .available
    ) -> PowerSourceSnapshot {
        var currentUPS: [PowerSource] = []
        var upsCount = 0
        var internalBatteryCount = 0
        var unknownTypeCount = 0
        var absentUPSCount = 0
        var unknownPresenceCount = 0

        for description in descriptions {
            switch sourceKind(description["Type"] as? String) {
            case .ups:
                upsCount += 1
                let source = normalize(description, id: "ups-\(currentUPS.count + 1)")
                switch source.isPresent {
                case true: currentUPS.append(source)
                case false: absentUPSCount += 1
                case nil: unknownPresenceCount += 1
                }
            case .internalBattery:
                internalBatteryCount += 1
            case .unknown:
                unknownTypeCount += 1
            }
        }

        return PowerSourceSnapshot(
            capturedAt: capturedAt,
            availability: availability,
            discovery: DiscoveryCounts(
                ups: upsCount,
                internalBattery: internalBatteryCount,
                unknownType: unknownTypeCount,
                upsAbsent: absentUPSCount,
                upsPresenceUnknown: unknownPresenceCount
            ),
            sources: currentUPS
        )
    }

    private enum IntegerInput {
        case absent
        case valid(Int32)
        case malformed
    }

    private static func sourceKind(_ type: String?) -> PowerSourceKind {
        switch type {
        case "UPS": return .ups
        case "InternalBattery": return .internalBattery
        default: return .unknown
        }
    }

    private static func normalizedCharge(current: IntegerInput, maximum: IntegerInput) -> Metric {
        let provenance = MetricProvenance.derived
        guard case let .valid(currentValue) = current,
              case let .valid(maximumValue) = maximum else {
            if isMalformed(current) || isMalformed(maximum) { return invalid(.ratio, provenance) }
            return unavailable(.ratio, provenance)
        }
        guard currentValue >= 0, maximumValue > 0, currentValue <= maximumValue else {
            return invalid(.ratio, provenance)
        }
        return Metric(value: Double(currentValue) / Double(maximumValue), unit: .ratio, quality: .available, provenance: provenance)
    }

    private static func normalizedTime(
        _ input: IntegerInput,
        validContext: Bool,
        provenance: MetricProvenance
    ) -> Metric {
        guard validContext else { return unavailable(.seconds, provenance) }
        switch input {
        case .absent: return unavailable(.seconds, provenance)
        case .malformed: return invalid(.seconds, provenance)
        case let .valid(minutes):
            if minutes == -1 {
                return Metric(value: nil, unit: .seconds, quality: .calculating, provenance: provenance)
            }
            guard minutes >= 0 else { return invalid(.seconds, provenance) }
            return Metric(value: Double(minutes) * 60, unit: .seconds, quality: .available, provenance: provenance)
        }
    }

    private static func normalizedBatteryVoltage(_ input: IntegerInput) -> Metric {
        let provenance = MetricProvenance.reported
        switch input {
        case .absent: return unavailable(.volts, provenance)
        case .malformed: return invalid(.volts, provenance)
        case let .valid(millivolts):
            guard millivolts > 0 else { return invalid(.volts, provenance) }
            return Metric(value: Double(millivolts) / 1_000, unit: .volts, quality: .available, provenance: provenance)
        }
    }

    private static func normalizedSourceCurrent(_ input: IntegerInput) -> Metric {
        switch input {
        case .absent: return unavailable(.amps, .reported)
        case .malformed: return invalid(.amps, .reported)
        case let .valid(milliamps):
            return Metric(value: Double(milliamps) / 1_000, unit: .amps, quality: .available, provenance: .reported)
        }
    }

    private static func normalizedSourceTemperature(_ input: IntegerInput) -> Metric {
        switch input {
        case .absent: return unavailable(.celsius, .reported)
        case .malformed: return invalid(.celsius, .reported)
        case let .valid(celsius):
            return Metric(value: Double(celsius), unit: .celsius, quality: .available, provenance: .reported)
        }
    }

    private static func health(_ value: Any?) -> BatteryHealth? {
        guard let value else { return nil }
        switch value as? String {
        case "Good": return .good
        case "Fair": return .fair
        case "Poor": return .poor
        default: return .unknown
        }
    }

    private static func integer(_ values: [String: Any], key: String) -> IntegerInput {
        guard let value = values[key] else { return .absent }
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return .malformed }
        let doubleValue = number.doubleValue
        guard doubleValue.isFinite,
              doubleValue.rounded(.towardZero) == doubleValue,
              doubleValue >= Double(Int32.min),
              doubleValue <= Double(Int32.max) else { return .malformed }
        return .valid(Int32(doubleValue))
    }

    private static func boolean(_ value: Any?) -> Bool? {
        guard let value, let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    private static func isMalformed(_ input: IntegerInput) -> Bool {
        if case .malformed = input { return true }
        return false
    }

    private static func unavailable(_ unit: MetricUnit, _ provenance: MetricProvenance) -> Metric {
        Metric(value: nil, unit: unit, quality: .unavailable, provenance: provenance)
    }

    private static func invalid(_ unit: MetricUnit, _ provenance: MetricProvenance) -> Metric {
        Metric(value: nil, unit: unit, quality: .invalid, provenance: provenance)
    }
}
