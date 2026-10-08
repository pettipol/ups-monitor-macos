import Foundation
import Testing
import NUTData

private func decodeSemanticFixture(_ json: String) throws -> NUTSnapshot {
    try UPSCJSONDecoder().decode(Data(json.utf8), sourceID: "synthetic-ups",
                                 capturedAt: Date(timeIntervalSince1970: 0))
}

@Test func overloadDoesNotInvalidateLoadAboveOneHundredPercent() throws {
    let snapshot = try decodeSemanticFixture(#"{"ups.status":"OL OVER","ups.load":"125.5"}"#)
    #expect(snapshot.metrics[.upsLoad]?.value == 125.5)
    #expect(snapshot.metrics[.upsLoad]?.quality == .available)
    #expect(snapshot.status.flags.contains(.overload))
}

@Test func mainsPresenceAndOutputOffAreIndependentStates() throws {
    let snapshot = try decodeSemanticFixture(#"{"ups.status":"OL OFF"}"#)
    #expect(snapshot.status.lineState == .onLine)
    #expect(snapshot.status.flags.map(\.rawValue).contains("outputOff"))
}

@Test func documentedHighBatteryFlagDoesNotHideMainsPresence() throws {
    let snapshot = try decodeSemanticFixture(#"{"ups.status":"OL HB"}"#)
    #expect(snapshot.status.lineState == .onLine)
    #expect(snapshot.status.flags.map(\.rawValue).contains("highBattery"))
}

@Test func runtimeRemainsAnEstimateInTheNormalizedSchema() throws {
    let snapshot = try decodeSemanticFixture(#"{"battery.runtime":"1200"}"#)
    #expect(snapshot.metrics[.batteryRuntime]?.provenance.rawValue == "estimated")
}

@Test func conflictingLineStatesAreNotReportedAsValidStatus() throws {
    let snapshot = try decodeSemanticFixture(#"{"ups.status":"OL OB"}"#)
    #expect(snapshot.status.lineState == .unknown)
    #expect(snapshot.status.quality == .invalid)
}

@Test func emptyOrMetadataOnlyReadsCannotReplaceALastGoodSnapshot() throws {
    #expect(throws: (any Error).self) {
        try UPSCTextDecoder().decode("\n\r\n", sourceID: "synthetic-ups", capturedAt: Date())
    }
    #expect(throws: (any Error).self) {
        try decodeSemanticFixture(#"{"driver.name":"apcmicrolink","ups.serial":"SYNTHETIC_SECRET"}"#)
    }
}
