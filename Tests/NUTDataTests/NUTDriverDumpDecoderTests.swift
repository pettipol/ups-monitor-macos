import Foundation
import XCTest
@testable import NUTData

final class NUTDriverDumpDecoderTests: XCTestCase {
    private let capturedAt = Date(timeIntervalSince1970: 1_800_000_000)
    private let preamble = "Network UPS Tools 2.8.5.1 (development iteration after 2.8.5) - APC Microlink protocol driver 0.05\nWarning: This is an experimental driver.\nSome features may not function correctly.\n\n"

    func testCompleteSyntheticDumpPreservesProviderMetricsAndProvenance() throws {
        let snapshot = try decode("battery.charge: 76\nbattery.runtime: 590\nups.status: \ndriver.name: apcmicrolink-hidapi-observe\nups.load: 20\nups.realpower: 65.5\nups.power: 82.4\nups.realpower.nominal: 500\nups.power.nominal: 500\n")

        XCTAssertEqual(snapshot.sourceID, "synthetic-ups")
        XCTAssertEqual(snapshot.capturedAt, capturedAt)
        XCTAssertEqual(snapshot.provider, .driverDumpOutput)
        XCTAssertEqual(snapshot.status.lineState, .unknown)
        XCTAssertEqual(snapshot.status.quality, .unavailable)
        XCTAssertEqual(metric(.batteryCharge, in: snapshot).value, 76)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot).value, 590)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot).provenance, .estimated)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot).value, 65.5)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot).unit, .watts)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot).provenance, .derivedByDriver)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot).value, 82.4)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot).unit, .voltAmps)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot).provenance, .derivedByDriver)
        XCTAssertEqual(metric(.batteryCurrent, in: snapshot).quality, .unavailable)
        XCTAssertNil(metric(.batteryCurrent, in: snapshot).value)
        XCTAssertFalse(String(describing: snapshot).contains("apcmicrolink-hidapi-observe"))
    }

    func testSecondSupportedAliasGetsSameMicrolinkSemantics() throws {
        let snapshot = try decode("ups.status: OL\ndriver.name: full-nut-hidapi-fake\nups.realpower: 40\n")
        XCTAssertEqual(snapshot.provider, .driverDumpOutput)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot).provenance, .derivedByDriver)
    }

    func testMetadataOnlyDumpIsRejectedAndLegacyProviderDefaultsToUpsc() throws {
        assertDumpError("driver.name: apcmicrolink-hidapi-observe\nups.status: \n", equals: .noUsableTelemetry)

        let legacy = try UPSCTextDecoder().decode("battery.charge: 50\n", sourceID: "legacy", capturedAt: capturedAt)
        XCTAssertEqual(legacy.provider, .upscOutput)
    }

    func testHorizontalWhitespaceStatusIsUnavailableOnlyForDriverDump() throws {
        let snapshot = try decode("driver.name: apcmicrolink-hidapi-observe\nups.status: \t \nbattery.charge: 50\n")
        XCTAssertEqual(snapshot.status.lineState, .unknown)
        XCTAssertEqual(snapshot.status.quality, .unavailable)
    }

    func testPinnedPreambleAndBodyFramingAreStrict() {
        assertDumpError(preamble.replacingOccurrences(of: "2.8.5.1", with: "2.8.5.2") + "battery.charge: 50\ndriver.name: apcmicrolink-hidapi-observe\n", equals: .invalidDriverDump)
        assertDumpError(preamble + "Warning: unexpected\nbattery.charge: 50\ndriver.name: apcmicrolink-hidapi-observe\n", equals: .invalidDriverDump)
        assertDumpError(preamble + "battery.charge: 50\ndriver.name: apcmicrolink-hidapi-observe", equals: .invalidDriverDump)
        assertDumpError(preamble, equals: .invalidDriverDump)
    }

    func testDuplicateFieldsEmptyStatusAndDriverNamesAreRejected() {
        assertDumpError(validBody + "battery.charge: 76\n", equals: .duplicateField(.batteryCharge))
        assertDumpError("ups.status: \nups.status: OL\ndriver.name: apcmicrolink-hidapi-observe\nbattery.charge: 76\n", equals: .duplicateStatus)
        assertDumpError("driver.name: apcmicrolink-hidapi-observe\ndriver.name: full-nut-hidapi-fake\nbattery.charge: 76\n", equals: .duplicateDriverName)
        assertDumpError("battery.charge: 76\n", equals: .invalidDriverDump)
        assertDumpError("driver.name: unsupported\nbattery.charge: 76\n", equals: .invalidDriverDump)
    }

    func testEmptyUpscStatusRemainsInvalid() {
        XCTAssertThrowsError(try UPSCTextDecoder().decode("ups.status: \nbattery.charge: 76\n", sourceID: "legacy", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .invalidStatus)
        }
    }

    func testNumericInvalidityAndInputBoundsUseExistingDecoderRules() throws {
        let snapshot = try decode("driver.name: apcmicrolink-hidapi-observe\nups.status: OL\nbattery.charge: 101\nbattery.runtime: -1\nups.realpower: NaN\n")
        XCTAssertEqual(metric(.batteryCharge, in: snapshot).quality, .invalid)
        XCTAssertNil(metric(.batteryCharge, in: snapshot).value)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot).quality, .invalid)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot).quality, .invalid)

        XCTAssertThrowsError(try decode("driver.name: apcmicrolink-hidapi-observe\nbattery.charge: 101\nbattery.runtime: -1\nups.realpower: NaN\n")) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .noUsableTelemetry)
        }

        XCTAssertThrowsError(try NUTDriverDumpDecoder().decode(Data(repeating: 32, count: UPSCTextDecoder.maximumInputBytes + 1), sourceID: "synthetic-ups", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .inputTooLarge)
        }
        XCTAssertThrowsError(try NUTDriverDumpDecoder().decode(Data([0xFF]), sourceID: "synthetic-ups", capturedAt: capturedAt)) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, .invalidUTF8)
        }
        assertDumpError("driver.name: apcmicrolink-hidapi-observe\n" + String(repeating: "x", count: UPSCTextDecoder.maximumLineBytes + 1) + "\n", equals: .lineTooLong)
    }

    func testWholeDumpLineLimitIncludesPinnedPreamble() throws {
        let atLimitBody = "driver.name: apcmicrolink-hidapi-observe\nbattery.charge: 50\n" + String(repeating: "\n", count: 505)
        let atLimit = try decode(atLimitBody)
        XCTAssertEqual(metric(.batteryCharge, in: atLimit).value, 50)

        assertDumpError(atLimitBody + "\n", equals: .tooManyLines)
    }

    private var validBody: String {
        "driver.name: apcmicrolink-hidapi-observe\nbattery.charge: 76\n"
    }

    private func decode(_ body: String) throws -> NUTSnapshot {
        try NUTDriverDumpDecoder().decode(Data((preamble + body).utf8), sourceID: "synthetic-ups", capturedAt: capturedAt)
    }

    private func metric(_ id: NUTMetricID, in snapshot: NUTSnapshot) -> NUTMetric {
        guard let value = snapshot.metrics[id] else {
            XCTFail("Missing metric \(id)")
            return NUTMetric(identifier: id, value: nil, quality: .invalid)
        }
        return value
    }

    private func assertDumpError(_ text: String, equals expected: UPSCTextDecodeError,
                                 file: StaticString = #filePath, line: UInt = #line) {
        let dump = text.hasPrefix("Network UPS Tools ") ? text : preamble + text
        XCTAssertThrowsError(try NUTDriverDumpDecoder().decode(Data(dump.utf8), sourceID: "synthetic-ups", capturedAt: capturedAt), file: file, line: line) {
            XCTAssertEqual($0 as? UPSCTextDecodeError, expected, file: file, line: line)
        }
    }
}
