import Foundation
import Testing
import UPSCore
import NUTData
import UPSModel

private let appleSource = MonitorSource(provider: .apple, id: "apple-ups-1", sessionID: "session-a", identityStability: .sessionLocal)
private let nutSource = MonitorSource(provider: .nut, id: "synthetic-ups", sessionID: "session-a", identityStability: .configured)

private func sampleSnapshot(source: MonitorSource = nutSource, at date: Date = Date(timeIntervalSince1970: 1_000)) -> MonitorSnapshot {
    MonitorSnapshot(source: source, capturedAt: date,
                    status: MonitorStatus(lineState: .unknown, quality: .unqualified),
                    metrics: [MonitorMetric(id: .upsLoad, value: 0, unit: .percent, quality: .available, provenance: .reported)])
}

@Test func snapshotJSONRoundTripsAndUsesTypedSchema() throws {
    let input = sampleSnapshot()
    let data = try JSONEncoder().encode(input)
    let output = try JSONDecoder().decode(MonitorSnapshot.self, from: data)
    #expect(output == input)
    #expect(output.schemaVersion == 1)
}

@Test func validationRejectsVersionDuplicatesUnitsNonFiniteAndQualityMismatch() throws {
    #expect(throws: MonitorValidationError.unsupportedSchemaVersion) { try MonitorSnapshot(schemaVersion: 2, source: nutSource, capturedAt: Date(), status: MonitorStatus(quality: .available), metrics: []).validate() }
    #expect(throws: MonitorValidationError.duplicateMetricID) {
        try MonitorSnapshot(source: nutSource, capturedAt: Date(), status: MonitorStatus(quality: .available), metrics: [
            MonitorMetric(id: .upsLoad, value: 0, unit: .percent, quality: .available, provenance: .reported),
            MonitorMetric(id: .upsLoad, value: 1, unit: .percent, quality: .available, provenance: .reported),
        ]).validate()
    }
    #expect(throws: MonitorValidationError.invalidMetricUnit) {
        try MonitorSnapshot(source: nutSource, capturedAt: Date(), status: MonitorStatus(quality: .available), metrics: [
            MonitorMetric(id: .upsRealPower, value: 4, unit: .voltAmps, quality: .available, provenance: .reported),
        ]).validate()
    }
    #expect(throws: MonitorValidationError.invalidMetricValue) {
        try MonitorSnapshot(source: nutSource, capturedAt: Date(), status: MonitorStatus(quality: .available), metrics: [
            MonitorMetric(id: .upsRealPower, value: .infinity, unit: .watts, quality: .available, provenance: .reported),
        ]).validate()
    }
    #expect(throws: MonitorValidationError.invalidMetricValue) {
        try MonitorSnapshot(source: nutSource, capturedAt: Date(), status: MonitorStatus(quality: .available), metrics: [
            MonitorMetric(id: .upsLoad, value: 0, unit: .percent, quality: .unavailable, provenance: .reported),
        ]).validate()
    }
}

@Test func validationRejectsInvalidSourceAndDate() throws {
    let invalidSource = MonitorSource(provider: .apple, id: "serial/id", sessionID: "session-a", identityStability: .sessionLocal)
    #expect(throws: MonitorValidationError.invalidSource) { try sampleSnapshot(source: invalidSource).validate() }
    #expect(throws: MonitorValidationError.invalidDate) {
        try MonitorSnapshot(source: nutSource, capturedAt: Date(timeIntervalSince1970: .infinity), status: MonitorStatus(quality: .unavailable), metrics: []).validate()
    }
}

@Test func customDecodingRejectsUnsupportedVersionAndDuplicateMetrics() throws {
    let encoder = JSONEncoder()
    let data = try encoder.encode(sampleSnapshot())
    var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    object["schemaVersion"] = 9
    let wrongVersion = try JSONSerialization.data(withJSONObject: object)
    #expect(throws: (any Error).self) { try JSONDecoder().decode(MonitorSnapshot.self, from: wrongVersion) }

    object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    let metrics = try #require(object["metrics"] as? [[String: Any]])
    object["metrics"] = [metrics[0], metrics[0]]
    let duplicate = try JSONSerialization.data(withJSONObject: object)
    #expect(throws: (any Error).self) { try JSONDecoder().decode(MonitorSnapshot.self, from: duplicate) }
}

@Test func appleAdapterRequiresPresentExternalUPSAndKeepsSourceLocationFields() throws {
    let power = PowerSource(id: "ups-1", kind: .ups, isPresent: true, state: .batteryPower, isCharging: false,
                            charge: Metric(value: 0.4, unit: .ratio, quality: .available, provenance: .derived),
                            timeToEmpty: Metric(value: 120, unit: .seconds, quality: .available, provenance: .estimated),
                            timeToFullCharge: Metric(value: 360, unit: .seconds, quality: .available, provenance: .estimated),
                            batteryVoltage: Metric(value: 12, unit: .volts, quality: .available, provenance: .reported),
                            sourceCurrent: Metric(value: 1.2, unit: .amps, quality: .available, provenance: .reported),
                            sourceTemperature: Metric(value: 21, unit: .celsius, quality: .available, provenance: .reported),
                            internalFailure: nil, batteryHealth: nil)
    let apple = PowerSourceSnapshot(capturedAt: Date(timeIntervalSince1970: 1), availability: .available,
                                    discovery: DiscoveryCounts(ups: 1, internalBattery: 0, unknownType: 0), sources: [power])
    let result = try MonitorSnapshotAdapter.fromApple(apple, source: appleSource, powerSourceID: "ups-1")
    #expect(result.status.lineState == .onBattery)
    #expect(result.metrics.first(where: { $0.id == .batteryCharge })?.value == 40)
    #expect(result.metrics.first(where: { $0.id == .appleSourceCurrent })?.unit == .amps)
    #expect(result.metrics.first(where: { $0.id == .appleSourceTemperature })?.unit == .celsius)
    #expect(result.metrics.first(where: { $0.id == .batteryTimeToFull })?.value == 360)

    let internalPower = PowerSource(id: "ups-1", kind: .internalBattery, isPresent: true, state: .batteryPower, isCharging: nil,
                                    charge: power.charge, timeToEmpty: power.timeToEmpty, timeToFullCharge: power.timeToFullCharge,
                                    batteryVoltage: power.batteryVoltage, sourceCurrent: power.sourceCurrent,
                                    sourceTemperature: power.sourceTemperature, internalFailure: nil, batteryHealth: nil)
    let internalSnapshot = PowerSourceSnapshot(capturedAt: Date(), availability: .available,
                                               discovery: DiscoveryCounts(ups: 0, internalBattery: 1, unknownType: 0), sources: [internalPower])
    #expect(throws: MonitorAdapterError.sourceUnavailable) {
        try MonitorSnapshotAdapter.fromApple(internalSnapshot, source: appleSource, powerSourceID: "ups-1")
    }
}

@Test func nutAdapterPreservesStatusPowerUnitsNominalsAndProvenance() throws {
    let nut = NUTSnapshot(sourceID: "synthetic-ups", capturedAt: Date(timeIntervalSince1970: 2),
                          status: NUTStatus(lineState: .unknown, flags: [.overload], quality: .unqualified),
                          metrics: [
                            .upsLoad: NUTMetric(identifier: .upsLoad, value: 125, quality: .available),
                            .upsRealPower: NUTMetric(identifier: .upsRealPower, value: 500, quality: .available, provenance: .derivedByDriver),
                            .upsRealPowerNominal: NUTMetric(identifier: .upsRealPowerNominal, value: 600, quality: .available),
                            .upsApparentPower: NUTMetric(identifier: .upsApparentPower, value: 700, quality: .available),
                            .upsApparentPowerNominal: NUTMetric(identifier: .upsApparentPowerNominal, value: 800, quality: .available),
                            .batteryRuntime: NUTMetric(identifier: .batteryRuntime, value: 300, quality: .available, provenance: .estimated),
                          ])
    let result = try MonitorSnapshotAdapter.fromNUT(nut, source: nutSource)
    #expect(result.status.lineState == .unknown)
    #expect(result.status.quality == .unqualified)
    #expect(result.metrics.first(where: { $0.id == .upsLoad })?.value == 125)
    #expect(result.metrics.first(where: { $0.id == .upsRealPower })?.unit == .watts)
    #expect(result.metrics.first(where: { $0.id == .upsRealPowerNominal })?.value == 600)
    #expect(result.metrics.first(where: { $0.id == .upsApparentPower })?.unit == .voltAmps)
    #expect(result.metrics.first(where: { $0.id == .upsApparentPowerNominal })?.value == 800)
    #expect(result.metrics.first(where: { $0.id == .upsRealPower })?.provenance == .driverDerived)
    #expect(result.metrics.first(where: { $0.id == .batteryRuntime })?.provenance == .estimated)
    let wrongNUTSource = MonitorSource(provider: .nut, id: "other-ups", sessionID: "session-a", identityStability: .configured)
    #expect(throws: MonitorAdapterError.sourceMismatch) { try MonitorSnapshotAdapter.fromNUT(nut, source: wrongNUTSource) }
}

@Test func freshnessRejectsStaleFailedFutureAndInvalidPolicy() {
    let snapshot = sampleSnapshot(at: Date(timeIntervalSince1970: 100))
    let now = Date(timeIntervalSince1970: 110)
    #expect(evaluateFreshness(snapshot: snapshot, now: now, maximumAge: 10) == .fresh)
    #expect(evaluateFreshness(snapshot: snapshot, now: now, maximumAge: 9) == .stale)
    #expect(evaluateFreshness(snapshot: snapshot, now: now, maximumAge: 30, acquisitionSucceeded: false) == .stale)
    #expect(evaluateFreshness(snapshot: snapshot, now: Date(timeIntervalSince1970: 99), maximumAge: 30) == .stale)
    #expect(evaluateFreshness(snapshot: snapshot, now: now, maximumAge: -.infinity) == .stale)
}

@Test func encodedModelContainsNoBackendNamesOrHardwareIdentifiers() throws {
    let encoded = String(decoding: try JSONEncoder().encode(sampleSnapshot()), as: UTF8.self)
    #expect(!encoded.contains("ups.serial"))
    #expect(!encoded.contains("vendor"))
    #expect(!encoded.contains("deviceName"))
}
