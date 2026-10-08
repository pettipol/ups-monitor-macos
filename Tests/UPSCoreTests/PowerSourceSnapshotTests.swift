import Foundation
import Testing
import UPSCore

@Test func capabilityCountsOnlyIncludeAvailableMetrics() {
    let sources = [
        PowerSource(id: "ups-1", kind: .ups, isPresent: true, state: .batteryPower, isCharging: false,
                    charge: Metric(value: 0.5, unit: .ratio, quality: .available, provenance: .derived),
                    timeToEmpty: Metric(value: nil, unit: .seconds, quality: .calculating, provenance: .estimated),
                    timeToFullCharge: Metric(value: nil, unit: .seconds, quality: .unavailable, provenance: .estimated),
                    batteryVoltage: Metric(value: nil, unit: .volts, quality: .unavailable, provenance: .reported),
                    sourceCurrent: Metric(value: nil, unit: .amps, quality: .unavailable, provenance: .reported),
                    sourceTemperature: Metric(value: nil, unit: .celsius, quality: .unavailable, provenance: .reported),
                    internalFailure: nil, batteryHealth: nil),
        PowerSource(id: "ups-2", kind: .ups, isPresent: true, state: .unknown, isCharging: nil,
                    charge: Metric(value: nil, unit: .ratio, quality: .invalid, provenance: .derived),
                    timeToEmpty: Metric(value: nil, unit: .seconds, quality: .unavailable, provenance: .estimated),
                    timeToFullCharge: Metric(value: nil, unit: .seconds, quality: .unavailable, provenance: .estimated),
                    batteryVoltage: Metric(value: 12, unit: .volts, quality: .available, provenance: .reported),
                    sourceCurrent: Metric(value: nil, unit: .amps, quality: .unavailable, provenance: .reported),
                    sourceTemperature: Metric(value: nil, unit: .celsius, quality: .unavailable, provenance: .reported),
                    internalFailure: nil, batteryHealth: nil),
    ]

    let counts = CapabilityCounts(sources: sources)
    #expect(counts.charge == 1)
    #expect(counts.timeToEmpty == 0)
    #expect(counts.timeToFullCharge == 0)
    #expect(counts.batteryVoltage == 1)
    #expect(counts.sourceCurrent == 0)
    #expect(counts.sourceTemperature == 0)
}
