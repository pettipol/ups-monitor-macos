import Foundation
import Testing
import UPSCore
import NUTData
import UPSModel

private let nativeIdentity = MonitorSource(provider: .apple, id: "fixture-native", sessionID: "session-1", identityStability: .sessionLocal)
private let nutIdentity = MonitorSource(provider: .nut, id: "fixture-nut", sessionID: "session-1", identityStability: .configured)

private func nativeFixture(chargeUnit: MetricUnit = .ratio, state: PowerSourceState = .acPower) -> PowerSourceSnapshot {
    let absent = Metric(value: nil, unit: .seconds, quality: .unavailable, provenance: .estimated)
    let source = PowerSource(
        id: "ordinal-1", kind: .ups, isPresent: true, state: state, isCharging: true,
        charge: Metric(value: 0.8, unit: chargeUnit, quality: .available, provenance: .derived),
        timeToEmpty: absent,
        timeToFullCharge: Metric(value: 600, unit: .seconds, quality: .available, provenance: .estimated),
        batteryVoltage: Metric(value: 24, unit: .volts, quality: .available, provenance: .reported),
        sourceCurrent: Metric(value: 0, unit: .amps, quality: .available, provenance: .reported),
        sourceTemperature: Metric(value: 25, unit: .celsius, quality: .available, provenance: .reported),
        internalFailure: true, batteryHealth: .poor
    )
    return PowerSourceSnapshot(capturedAt: Date(timeIntervalSince1970: 1000), availability: .available,
        discovery: DiscoveryCounts(ups: 1, internalBattery: 0, unknownType: 0), sources: [source])
}

@Test func sharedModelDoesNotDiscardNativeHealthFailureOrChargingTime() throws {
    let sample = try MonitorSnapshotAdapter.fromApple(nativeFixture(), source: nativeIdentity, powerSourceID: "ordinal-1")
    #expect(sample.metrics.first(where: { $0.id.rawValue == "batteryTimeToFull" })?.value == 600)
    let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(sample)) as? [String: Any])
    let status = try #require(object["status"] as? [String: Any])
    #expect(status["internalFailure"] as? Bool == true)
    #expect(status["batteryHealth"] as? String == "poor")
    #expect(status["isCharging"] as? Bool == true)
}

@Test func appleMappingCannotRelabelAnIncorrectInputUnit() {
    #expect(throws: (any Error).self) {
        try MonitorSnapshotAdapter.fromApple(nativeFixture(chargeUnit: .volts), source: nativeIdentity, powerSourceID: "ordinal-1")
    }
}

@Test func nutMappingRejectsDictionaryKeyAndMetricIdentityDisagreement() {
    let snapshot = NUTSnapshot(sourceID: nutIdentity.id, capturedAt: Date(timeIntervalSince1970: 1000),
        status: NUTStatus(lineState: .onLine, flags: [], quality: .available),
        metrics: [.inputVoltage: NUTMetric(identifier: .batteryVoltage, value: 230, quality: .available)])
    #expect(throws: (any Error).self) {
        try MonitorSnapshotAdapter.fromNUT(snapshot, source: nutIdentity)
    }
}

@Test func outputOffDoesNotInventAnInputLineState() throws {
    let snapshot = NUTSnapshot(sourceID: nutIdentity.id, capturedAt: Date(timeIntervalSince1970: 1000),
        status: NUTStatus(lineState: .off, flags: [], quality: .available), metrics: [:])
    let result = try MonitorSnapshotAdapter.fromNUT(snapshot, source: nutIdentity)
    #expect(result.status.lineState == .unknown)
    #expect(result.status.flags.contains(.outputOff))
}

@Test func nativeOfflineIsNotAnAssertionThatTheOutputIsSwitchedOff() throws {
    let result = try MonitorSnapshotAdapter.fromApple(nativeFixture(state: .offLine), source: nativeIdentity, powerSourceID: "ordinal-1")
    #expect(result.status.lineState == .unknown)
    #expect(result.status.flags.contains(where: { $0.rawValue == "sourceOffline" }))
    #expect(!result.status.flags.contains(.outputOff))
}

@Test func invalidStatusCannotCarryAQualifiedMainsState() {
    let sample = MonitorSnapshot(source: nutIdentity, capturedAt: Date(timeIntervalSince1970: 1000),
        status: MonitorStatus(lineState: .onLine, quality: .invalid), metrics: [])
    #expect(throws: (any Error).self) { try sample.validate() }
}

@Test func sharedSchemaCannotEncodeAnAmbiguousOffMainsState() {
    #expect(MonitorLineState(rawValue: "off") == nil)
}
