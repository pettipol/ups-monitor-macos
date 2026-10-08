import Foundation
import Testing
import UPSCore
@testable import ApplePowerSource

@Test func snapshotExportsOnlyWhitelistedTelemetry() throws {
    let snapshot = PowerSourceNormalizer.snapshot(from: [[
        "Type": "UPS",
        "Is Present": true,
        "Is Charging": true,
        "Power Source State": "AC Power",
        "Current Capacity": 90,
        "Max Capacity": 100,
        "Voltage": 24_000,
        "Current": -750,
        "Temperature": 22,
        "Time to Full Charge": 15,
        "Internal Failure": false,
        "BatteryHealth": "Good",
        "Name": "SYNTHETIC_PRIVATE_NAME",
        "Hardware Serial Number": "SYNTHETIC_SERIAL_DO_NOT_EXPORT",
        "Power Source ID": 987_654,
        "Vendor Specific Data": "SYNTHETIC_PRIVATE_VENDOR_DATA",
        "Unexpected Future Field": "SYNTHETIC_SECRET",
    ]], capturedAt: Date(timeIntervalSince1970: 0))

    let encoded = try JSONEncoder().encode(snapshot)
    let text = String(decoding: encoded, as: UTF8.self)
    #expect(!text.contains("SYNTHETIC_"))
    #expect(!text.contains("987654"))

    let object = try #require(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
    #expect(Set(object.keys) == Set(["capturedAt", "provider", "availability", "discovery", "capabilities", "sources"]))
    let capabilities = try #require(object["capabilities"] as? [String: Int])
    #expect(Set(capabilities.keys) == Set([
        "charge", "timeToEmpty", "timeToFullCharge", "batteryVoltage", "sourceCurrent",
        "sourceTemperature", "internalFailure", "batteryHealth",
    ]))
    #expect(capabilities["timeToFullCharge"] == 1)
    #expect(capabilities["sourceCurrent"] == 1)
    #expect(capabilities["sourceTemperature"] == 1)
    #expect(capabilities["internalFailure"] == 1)
    #expect(capabilities["batteryHealth"] == 1)
    let sources = try #require(object["sources"] as? [[String: Any]])
    let source = try #require(sources.first)
    #expect(source["id"] as? String == "ups-1")
    #expect(Set(source.keys) == Set([
        "id", "kind", "isPresent", "state", "isCharging", "charge", "timeToEmpty", "timeToFullCharge",
        "batteryVoltage", "sourceCurrent", "sourceTemperature", "internalFailure", "batteryHealth",
    ]))
    let current = try #require(source["sourceCurrent"] as? [String: Any])
    #expect(Set(current.keys) == Set(["value", "unit", "quality", "provenance"]))
    #expect(current["value"] as? Double == -0.75)
    #expect(current["unit"] as? String == "amps")
    #expect(source["batteryHealth"] as? String == "good")
    #expect(snapshot.sources.count == 1)
}

@Test func internalBatteryNameCannotImpersonateUPS() {
    let snapshot = PowerSourceNormalizer.snapshot(from: [[
        "Type": "InternalBattery",
        "Name": "UPS Back-UPS SYNTHETIC",
        "Is Present": true,
        "Current Capacity": 100,
        "Max Capacity": 100,
    ]])
    #expect(snapshot.sources.isEmpty)
    #expect(snapshot.discovery.internalBattery == 1)
    #expect(snapshot.discovery.ups == 0)
}
