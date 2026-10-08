import Foundation
import Testing
import UPSCore
@testable import ApplePowerSource

@Test func normalizesUPSChargeTimeAndVoltage() {
    let source = PowerSourceNormalizer.normalize([
        "Type": "UPS",
        "Is Present": true,
        "Power Source State": "Battery Power",
        "Is Charging": false,
        "Current Capacity": 75,
        "Max Capacity": 100,
        "Time to Empty": 12,
        "Voltage": 12_600,
    ], id: "ups-1")

    #expect(source.kind == .ups)
    #expect(source.charge.value == 0.75)
    #expect(source.charge.unit == .ratio)
    #expect(source.timeToEmpty.value == 720)
    #expect(source.timeToEmpty.unit == .seconds)
    #expect(source.batteryVoltage.value == 12.6)
    #expect(source.batteryVoltage.unit == .volts)
    #expect(source.charge.provenance == .derived)
    #expect(source.timeToEmpty.provenance == .estimated)
    #expect(source.batteryVoltage.provenance == .reported)
}

@Test func distinguishesInternalBatteryAndDoesNotPromoteItToUPS() {
    let source = PowerSourceNormalizer.normalize(["Type": "InternalBattery"], id: "source-1")
    #expect(source.kind == .internalBattery)
    #expect(source.charge.quality == .unavailable)
    #expect(source.timeToEmpty.quality == .unavailable)
}

@Test func missingAndSentinelValuesRemainUnavailableOrCalculating() {
    let missing = PowerSourceNormalizer.normalize(["Type": "UPS"], id: "ups-1")
    #expect(missing.charge.value == nil)
    #expect(missing.charge.quality == .unavailable)
    #expect(missing.batteryVoltage.value == nil)
    #expect(missing.batteryVoltage.quality == .unavailable)

    let calculating = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Power Source State": "Battery Power", "Is Charging": false,
        "Time to Empty": -1,
    ], id: "ups-1")
    #expect(calculating.timeToEmpty.value == nil)
    #expect(calculating.timeToEmpty.quality == .calculating)
}

@Test func rejectsInvalidCapacityAndTimeValues() {
    let invalidCapacity = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Current Capacity": 101, "Max Capacity": 100,
    ], id: "ups-1")
    #expect(invalidCapacity.charge.value == nil)
    #expect(invalidCapacity.charge.quality == .invalid)

    let invalidTime = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Power Source State": "Battery Power", "Is Charging": false,
        "Time to Empty": -2,
    ], id: "ups-1")
    #expect(invalidTime.timeToEmpty.value == nil)
    #expect(invalidTime.timeToEmpty.quality == .invalid)
}

@Test func ignoresBatteryTimeOutsideDocumentedContextAndRejectsBooleanNumericFields() {
    let source = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Power Source State": "AC Power", "Is Charging": true,
        "Time to Empty": 20, "Current Capacity": true, "Max Capacity": 100,
    ], id: "ups-1")
    #expect(source.timeToEmpty.quality == .unavailable)
    #expect(source.charge.quality == .invalid)
}

@Test func filtersTypesExplicitlyAndKeepsUnknownTypeSafe() {
    let battery = PowerSourceNormalizer.normalize(["Type": "InternalBattery"], id: "source-1")
    let unknown = PowerSourceNormalizer.normalize(["Type": "Unexpected"], id: "source-2")
    #expect(battery.kind == .internalBattery)
    #expect(unknown.kind == .unknown)
}

@Test func normalizesSourceCurrentWithSignAndTemperatureInCelsius() {
    let source = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Current": -1_250, "Temperature": -5,
    ], id: "ups-1")

    #expect(source.sourceCurrent.value == -1.25)
    #expect(source.sourceCurrent.unit == .amps)
    #expect(source.sourceCurrent.provenance == .reported)
    #expect(source.sourceTemperature.value == -5)
    #expect(source.sourceTemperature.unit == .celsius)
    #expect(source.sourceTemperature.provenance == .reported)
}

@Test func timeToFullChargeRequiresChargingAndHandlesSentinel() {
    let charging = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Power Source State": "AC Power", "Is Charging": true,
        "Time to Full Charge": 15, "Time to Empty": 30,
    ], id: "ups-1")
    #expect(charging.timeToFullCharge.value == 900)
    #expect(charging.timeToFullCharge.unit == .seconds)
    #expect(charging.timeToFullCharge.provenance == .estimated)
    #expect(charging.timeToEmpty.quality == .unavailable)

    let calculating = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Is Charging": true, "Time to Full Charge": -1,
    ], id: "ups-1")
    #expect(calculating.timeToFullCharge.quality == .calculating)
    #expect(calculating.timeToFullCharge.value == nil)

    let notCharging = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Is Charging": false, "Time to Full Charge": 1,
    ], id: "ups-1")
    #expect(notCharging.timeToFullCharge.quality == .unavailable)
}

@Test func typedBooleanFailuresAndHealthAllowlistAreSafe() {
    let malformed = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Is Charging": "true", "Internal Failure": "false",
        "BatteryHealth": "Synthetic Future Health Value",
    ], id: "ups-1")
    #expect(malformed.isCharging == nil)
    #expect(malformed.internalFailure == nil)
    #expect(malformed.batteryHealth == .unknown)

    let known: [(String, BatteryHealth)] = [
        ("Good", .good), ("Fair", .fair), ("Poor", .poor),
    ]
    for (raw, expected) in known {
        let source = PowerSourceNormalizer.normalize(["Type": "UPS", "BatteryHealth": raw], id: "ups-1")
        #expect(source.batteryHealth == expected)
    }
}

@Test func internalFailureAcceptsOnlyCFBoolean() {
    let failed = PowerSourceNormalizer.normalize(["Type": "UPS", "Internal Failure": true], id: "ups-1")
    let healthy = PowerSourceNormalizer.normalize(["Type": "UPS", "Internal Failure": false], id: "ups-1")
    #expect(failed.internalFailure == true)
    #expect(healthy.internalFailure == false)
}

@Test func snapshotFiltersToPresentUPSAndCountsOtherAndAbsentSources() {
    let snapshot = PowerSourceNormalizer.snapshot(from: [
        ["Type": "UPS", "Is Present": true, "Current Capacity": 50, "Max Capacity": 100],
        ["Type": "UPS", "Is Present": false, "Current Capacity": 100, "Max Capacity": 100],
        ["Type": "InternalBattery", "Is Present": true],
        ["Type": "FutureSource", "Is Present": true],
        ["Type": "UPS"],
    ], capturedAt: Date(timeIntervalSince1970: 0))

    #expect(snapshot.provider == .appleIOPowerSources)
    #expect(snapshot.discovery.ups == 3)
    #expect(snapshot.discovery.upsAbsent == 1)
    #expect(snapshot.discovery.upsPresenceUnknown == 1)
    #expect(snapshot.discovery.internalBattery == 1)
    #expect(snapshot.discovery.unknownType == 1)
    #expect(snapshot.sources.count == 1)
    #expect(snapshot.sources[0].id == "ups-1")
    #expect(snapshot.capabilities.charge == 1)
}

@Test func snapshotWithNoUPSHasNoSourcesOrCapabilities() {
    let snapshot = PowerSourceNormalizer.snapshot(from: [["Type": "InternalBattery", "Is Present": true]])
    #expect(snapshot.sources.isEmpty)
    #expect(snapshot.discovery.ups == 0)
    #expect(snapshot.discovery.internalBattery == 1)
    #expect(snapshot.capabilities.charge == 0)
    #expect(snapshot.capabilities.batteryVoltage == 0)
}

@Test func rejectsMalformedAndOutOfInt32NumericValues() {
    let malformedInputs: [Any] = [
        NSNumber(value: Double.nan),
        NSNumber(value: Double.infinity),
        NSNumber(value: 1.5),
        NSNumber(value: Int64(Int32.max) + 1),
        NSNumber(value: Int64(Int32.min) - 1),
        NSNumber(value: true),
    ]

    for value in malformedInputs {
        let capacity = PowerSourceNormalizer.normalize([
            "Type": "UPS", "Current Capacity": value, "Max Capacity": 100,
        ], id: "ups-1")
        #expect(capacity.charge.quality == .invalid)

        let voltage = PowerSourceNormalizer.normalize(["Type": "UPS", "Voltage": value], id: "ups-1")
        #expect(voltage.batteryVoltage.quality == .invalid)

        let current = PowerSourceNormalizer.normalize(["Type": "UPS", "Current": value], id: "ups-1")
        #expect(current.sourceCurrent.quality == .invalid)

        let temperature = PowerSourceNormalizer.normalize(["Type": "UPS", "Temperature": value], id: "ups-1")
        #expect(temperature.sourceTemperature.quality == .invalid)
    }
}

@Test func invalidCapacitiesAndMalformedVoltageAreNotMissing() {
    let zeroMaximum = PowerSourceNormalizer.normalize([
        "Type": "UPS", "Current Capacity": 0, "Max Capacity": 0,
    ], id: "ups-1")
    #expect(zeroMaximum.charge.quality == .invalid)

    let malformedVoltage = PowerSourceNormalizer.normalize(["Type": "UPS", "Voltage": "unknown"], id: "ups-1")
    #expect(malformedVoltage.batteryVoltage.quality == .invalid)
}

@Test func suppressesRuntimeEstimateWhileChargingOrOnAC() {
    for values: [String: Any] in [
        ["Type": "UPS", "Power Source State": "Battery Power", "Is Charging": true, "Time to Empty": 30],
        ["Type": "UPS", "Power Source State": "AC Power", "Is Charging": false, "Time to Empty": 30],
    ] {
        #expect(PowerSourceNormalizer.normalize(values, id: "ups-1").timeToEmpty.quality == .unavailable)
    }
}
