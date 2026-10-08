import Foundation
import XCTest
@testable import NUTData

final class UPSCDecoderTests: XCTestCase {
    private let capturedAt = Date(timeIntervalSince1970: 1_800_000_000)

    func testJSONMapsWhitelistWithUnitsAndCallerIdentity() throws {
        let data = Data(#"{"ups.status":"OL CHRG","battery.charge":"85.5","battery.runtime":"1200","battery.voltage":"24.2","battery.voltage.nominal":"24","input.voltage":"230","input.frequency":"50.0","output.voltage":"229.8","output.current":"1.2","ups.load":"20","ups.realpower":"100","ups.power":"120","ups.temperature":"31.5","ups.serial":"must-not-escape","experimental.output.energy":"42"}"#.utf8)

        let snapshot = try UPSCJSONDecoder().decode(data, sourceID: "nut-source-2", capturedAt: capturedAt)

        XCTAssertEqual(snapshot.sourceID, "nut-source-2")
        XCTAssertEqual(snapshot.capturedAt, capturedAt)
        XCTAssertEqual(snapshot.provider, .upscOutput)
        XCTAssertEqual(snapshot.status.lineState, .onLine)
        XCTAssertEqual(snapshot.status.flags, [.charging])
        XCTAssertEqual(metric(.batteryCharge, in: snapshot).value, 85.5)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot).unit, .seconds)
        XCTAssertEqual(metric(.inputVoltage, in: snapshot).unit, .volts)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot).unit, .watts)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot).unit, .voltAmps)
        XCTAssertEqual(metric(.upsTemperature, in: snapshot).unit, .celsius)
        XCTAssertEqual(snapshot.metrics.count, NUTMetricID.allCases.count)
        XCTAssertNil(snapshot.metrics[.batteryCurrent]?.value)
        XCTAssertEqual(metric(.upsTemperature, in: snapshot).quality, .available)
        XCTAssertFalse(String(describing: snapshot).contains("must-not-escape"))
        XCTAssertFalse(String(describing: snapshot).contains("experimental.output.energy"))
    }

    func testMissingInvalidAndOutOfRangeHaveDifferentQuality() throws {
        let data = Data(#"{"battery.charge":"101","battery.runtime":"-1","ups.load":"NaN","input.voltage":"230.0"}"#.utf8)
        let snapshot = try UPSCJSONDecoder().decode(data, sourceID: "ups-1", capturedAt: capturedAt)

        XCTAssertEqual(metric(.batteryCharge, in: snapshot).quality, .invalid)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot).quality, .invalid)
        XCTAssertEqual(metric(.upsLoad, in: snapshot).quality, .invalid)
        XCTAssertEqual(metric(.inputVoltage, in: snapshot).quality, .available)
        XCTAssertEqual(metric(.inputCurrent, in: snapshot).quality, .unavailable)
        XCTAssertNil(metric(.inputCurrent, in: snapshot).value)
    }

    func testPowerIsNeverInferredFromLoadAndMicrolinkPowerIsDriverDerived() throws {
        let ordinary = try UPSCJSONDecoder().decode(
            Data(#"{"ups.load":"25","ups.realpower.nominal":"300","ups.power.nominal":"500"}"#.utf8),
            sourceID: "ordinary", capturedAt: capturedAt
        )
        XCTAssertEqual(metric(.upsLoad, in: ordinary).value, 25)
        XCTAssertEqual(metric(.upsRealPower, in: ordinary).quality, .unavailable)
        XCTAssertEqual(metric(.upsApparentPower, in: ordinary).quality, .unavailable)
        XCTAssertEqual(metric(.upsRealPower, in: ordinary).provenance, .reported)

        let microlink = try UPSCJSONDecoder().decode(
            Data(#"{"driver.name":"apcmicrolink","ups.realpower":"65.5","ups.power":"82.4","ups.realpower.nominal":"500","ups.power.nominal":"500"}"#.utf8),
            sourceID: "microlink", capturedAt: capturedAt
        )
        XCTAssertEqual(metric(.upsRealPower, in: microlink).value, 65.5)
        XCTAssertEqual(metric(.upsRealPower, in: microlink).provenance, .derivedByDriver)
        XCTAssertEqual(metric(.upsApparentPower, in: microlink).unit, .voltAmps)
        XCTAssertEqual(metric(.upsApparentPower, in: microlink).provenance, .derivedByDriver)
        XCTAssertFalse(String(describing: microlink).contains("apcmicrolink"))

        let runtime = try UPSCJSONDecoder().decode(
            Data(#"{"battery.runtime":"1200"}"#.utf8), sourceID: "runtime", capturedAt: capturedAt
        )
        XCTAssertEqual(metric(.batteryRuntime, in: runtime).provenance, .estimated)
    }

    func testStatusUnknownAndContradictoryInputsStayUnknown() throws {
        let unknownToken = try UPSCJSONDecoder().decode(
            Data(#"{"ups.status":"OL VENDORFLAG"}"#.utf8), sourceID: "source", capturedAt: capturedAt
        )
        XCTAssertEqual(unknownToken.status.quality, .unqualified)
        XCTAssertEqual(unknownToken.status.lineState, .unknown)

        let contradictory = try UPSCJSONDecoder().decode(
            Data(#"{"ups.status":"OL OB LB"}"#.utf8), sourceID: "source", capturedAt: capturedAt
        )
        XCTAssertEqual(contradictory.status.lineState, .unknown)
        XCTAssertEqual(contradictory.status.flags, [.lowBattery])
        XCTAssertEqual(contradictory.status.quality, .invalid)

        let mainsAndOutputOff = try UPSCJSONDecoder().decode(
            Data(#"{"ups.status":"OL OFF"}"#.utf8), sourceID: "source", capturedAt: capturedAt
        )
        XCTAssertEqual(mainsAndOutputOff.status.lineState, .onLine)
        XCTAssertTrue(mainsAndOutputOff.status.flags.contains(.outputOff))

        let highBattery = try UPSCJSONDecoder().decode(
            Data(#"{"ups.status":"OL HB"}"#.utf8), sourceID: "source", capturedAt: capturedAt
        )
        XCTAssertEqual(highBattery.status.lineState, .onLine)
        XCTAssertTrue(highBattery.status.flags.contains(.highBattery))

        let absent = try UPSCJSONDecoder().decode(Data(#"{"battery.charge":"50"}"#.utf8), sourceID: "source", capturedAt: capturedAt)
        XCTAssertEqual(absent.status.quality, .unavailable)
        XCTAssertEqual(absent.status.lineState, .unknown)
    }

    func testJSONRejectsMalformedEmptyErrorAndNonStringPayloads() {
        assertJSONError(#"[]"#, equals: .invalidJSON)
        assertJSONError(#"{}"#, equals: .emptyJSON)
        assertJSONError(#"{"error":"connection refused"}"#, equals: .invalidJSON)
        assertJSONError(#"{"battery.charge":90}"#, equals: .nonStringJSONValue)
        assertJSONError("not json", equals: .invalidJSON)
    }

    func testJSONBoundsAndCallerSourceID() throws {
        XCTAssertThrowsError(try UPSCJSONDecoder().decode(Data(repeating: 0x20, count: UPSCTextDecoder.maximumInputBytes + 1), sourceID: "id", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .inputTooLarge)
        }
        XCTAssertThrowsError(try UPSCJSONDecoder().decode(Data(#"{"battery.charge":"50"}"#.utf8), sourceID: "real ups@host", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .invalidSourceID)
        }
        XCTAssertThrowsError(try UPSCJSONDecoder().decode(Data(#"{"battery.charge":"50"}"#.utf8), sourceID: "id", capturedAt: Date(timeIntervalSince1970: .infinity))) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .invalidCaptureTime)
        }
    }

    func testTextFallbackHandlesCRLFAndRejectsDuplicateOrScientificNumber() throws {
        let decoder = UPSCTextDecoder()
        let snapshot = try decoder.decode("ups.status: OB LB\r\nbattery.runtime: 1200\r\nbattery.charge: 70\r\n", sourceID: "text-1", capturedAt: capturedAt)
        XCTAssertEqual(snapshot.status.lineState, .onBattery)
        XCTAssertEqual(snapshot.status.flags, [.lowBattery])
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot).value, 1200)

        XCTAssertThrowsError(try decoder.decode("battery.charge: 80\nbattery.charge: 80\n", sourceID: "id", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .duplicateField(.batteryCharge))
        }
        let scientific = try decoder.decode("battery.runtime: 1e3\nbattery.charge: 50\n", sourceID: "id", capturedAt: capturedAt)
        XCTAssertEqual(metric(.batteryRuntime, in: scientific).quality, .invalid)
    }

    func testTextFallbackRejectsDuplicateStatusAndMalformedInput() {
        let decoder = UPSCTextDecoder()
        XCTAssertThrowsError(try decoder.decode("ups.status: OL\nups.status: OB\n", sourceID: "id", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .duplicateStatus)
        }
        XCTAssertThrowsError(try decoder.decode("driver.name: apcmicrolink\ndriver.name: other\n", sourceID: "id", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .duplicateDriverName)
        }
        XCTAssertThrowsError(try decoder.decode("battery.charge 50\n", sourceID: "id", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .malformedLine(line: 1))
        }
        XCTAssertThrowsError(try decoder.decode(Data([0xFF]), sourceID: "id", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .invalidUTF8)
        }
    }

    private func metric(_ id: NUTMetricID, in snapshot: NUTSnapshot) -> NUTMetric {
        guard let value = snapshot.metrics[id] else {
            XCTFail("Missing metric \(id)")
            return NUTMetric(identifier: id, value: nil, quality: .invalid)
        }
        return value
    }

    private func assertJSONError(_ json: String, equals expected: UPSCTextDecodeError, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertThrowsError(try UPSCJSONDecoder().decode(Data(json.utf8), sourceID: "id", capturedAt: capturedAt), file: file, line: line) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, expected, file: file, line: line)
        }
    }
}
