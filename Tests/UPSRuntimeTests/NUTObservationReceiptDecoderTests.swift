import CryptoKit
import Foundation
import XCTest
import NUTData
import UPSModel
@testable import UPSRuntime

final class NUTObservationReceiptDecoderTests: XCTestCase {
    private let stdout = Data(("Network UPS Tools 2.8.5.1 (development iteration after 2.8.5) - APC Microlink protocol driver 0.05\n" +
                               "Warning: This is an experimental driver.\nSome features may not function correctly.\n\n" +
                               "driver.name: full-nut-hidapi-fake\nups.status: OL\nbattery.charge: 76\nbattery.runtime: 590\n").utf8)
    private let stderr = Data("synthetic warning\n".utf8)
    private let pin = String(repeating: "a", count: 64)
    private let started = Date(timeIntervalSince1970: 1_800_000_000)
    private let finished = Date(timeIntervalSince1970: 1_800_000_002)
    private let now = Date(timeIntervalSince1970: 1_800_000_010)

    func testDecodesReceiptAndPassesRealBytesAndCallerOriginToAdapter() throws {
        let imported = try decode(receipt())
        XCTAssertFalse(imported.dataQualified)
        XCTAssertEqual(imported.origin, .archivedSupervisedDriverDump)
        XCTAssertEqual(imported.startedAt, started)
        XCTAssertEqual(imported.finishedAt, finished)
        XCTAssertEqual(imported.unqualifiedSnapshot.capturedAt, started)
        XCTAssertEqual(imported.unqualifiedSnapshot.status.lineState, .onLine)
        let metrics = Dictionary(uniqueKeysWithValues: imported.unqualifiedSnapshot.metrics.map { ($0.id, $0) })
        XCTAssertEqual(metrics[.batteryCharge]?.value, 76)
        XCTAssertEqual(metrics[.batteryRuntime]?.value, 590)
        XCTAssertEqual(metrics[.batteryRuntime]?.provenance, .estimated)
        XCTAssertNil(metrics[.upsRealPower]?.value)
    }

    func testRejectsMalformedSchemaAndStrictWireTypesAsInvalidReceipt() throws {
        let valid = try object(receipt())
        var cases: [Data] = [Data([0xff]), Data("{".utf8), Data(repeating: 0x61, count: 8_193)]
        var missing = valid
        missing.removeValue(forKey: "status")
        cases.append(try json(missing))
        var missingError = valid
        missingError.removeValue(forKey: "error")
        cases.append(try json(missingError))
        let legacyKeys: Set<String> = [
            "status", "trigger", "returncode", "stdout_bytes", "stderr_bytes",
            "data_qualified", "error",
        ]
        cases.append(try json(valid.filter { legacyKeys.contains($0.key) }))
        let utf8Receipt = try json(valid)
        cases.append(try encodedReceipt(utf8Receipt, encoding: .utf16LittleEndian, bom: [0xff, 0xfe]))
        cases.append(try encodedReceipt(utf8Receipt, encoding: .utf16BigEndian, bom: [0xfe, 0xff]))
        cases.append(try encodedReceipt(utf8Receipt, encoding: .utf32LittleEndian, bom: [0xff, 0xfe, 0x00, 0x00]))
        cases.append(try encodedReceipt(utf8Receipt, encoding: .utf32BigEndian, bom: [0x00, 0x00, 0xfe, 0xff]))
        cases.append(utf8Receipt + Data([0]))
        var extra = valid
        extra["unexpected"] = 1
        cases.append(try json(extra))
        for (key, value) in [
            ("schema_version", true as Any), ("status", 3 as Any), ("trigger", "unexpected" as Any),
            ("returncode", true as Any), ("stdout_bytes", "0" as Any), ("stderr_bytes", false as Any),
            ("maximum_output_bytes", 65.5 as Any), ("executable_sha256", 4 as Any),
            ("started_at_unix_seconds", true as Any), ("finished_at_unix_seconds", "1800000002" as Any),
            ("data_qualified", 0 as Any),
        ] {
            var changed = valid
            changed[key] = value
            cases.append(try json(changed))
        }
        for data in cases {
            XCTAssertThrowsError(try decode(data)) { error in
                XCTAssertEqual(error as? NUTObservationReceiptDecodeError, .invalidReceipt)
            }
        }
    }

    func testRequiresNullErrorFalseQualificationAndKnownVersion() throws {
        let valid = try object(receipt())
        for (key, value) in [("error", "failed" as Any), ("data_qualified", true as Any), ("schema_version", 2 as Any)] {
            var changed = valid
            changed[key] = value
            XCTAssertThrowsError(try decode(json(changed))) { error in
                XCTAssertEqual(error as? NUTObservationReceiptDecodeError, .invalidReceipt)
            }
        }
    }

    func testMetadataIntegrityAndSuccessGateErrorsComeFromAdapter() throws {
        let valid = try object(receipt())
        var cases: [(String, Any, NUTObservationImportError)] = [
            ("stdout_bytes", stdout.count + 1, .invalidByteCounts),
            ("maximum_output_bytes", 1, .invalidOutputLimit),
            ("stdout_sha256", String(repeating: "0", count: 64), .invalidDigest),
            ("executable_sha256", String(repeating: "b", count: 64), .executablePinMismatch),
            ("status", "timed_out", .unsuccessfulProcess),
            ("trigger", "timeout", .unsuccessfulProcess),
            ("returncode", NSNull(), .unsuccessfulProcess),
        ]
        cases.append(("started_at_unix_seconds", 1_800_000_003, .invalidDates))
        for (key, value, expected) in cases {
            var changed = valid
            changed[key] = value
            XCTAssertThrowsError(try decode(json(changed))) { error in
                XCTAssertEqual(error as? NUTObservationImportError, expected)
            }
        }
        var future = valid
        future["finished_at_unix_seconds"] = 1_800_000_011
        XCTAssertThrowsError(try decode(json(future))) { error in
            XCTAssertEqual(error as? NUTObservationImportError, .invalidDates)
        }
    }

    func testDumpFailureIsAdapterInvalidDump() throws {
        let invalidDump = Data("not a NUT driver dump\n".utf8)
        let receipt = try json(makeReceipt(stdoutData: invalidDump, stderrData: Data()))
        XCTAssertThrowsError(try decode(receipt, stdoutData: invalidDump, stderrData: Data())) { error in
            XCTAssertEqual(error as? NUTObservationImportError, .invalidDump)
        }
    }

    func testMetadataOnlyReceiptReachesAdapterDumpGate() throws {
        let empty = Data()
        let receipt = try json(makeReceipt(stdoutData: empty, stderrData: empty))
        XCTAssertThrowsError(try decode(receipt, stdoutData: empty, stderrData: empty)) { error in
            XCTAssertEqual(error as? NUTObservationImportError, .invalidDump)
        }
    }

    private func decode(_ data: Data, stdoutData: Data? = nil, stderrData: Data? = nil) throws -> ImportedNUTObservation {
        try NUTObservationReceiptDecoder().decode(
            data, stdout: stdoutData ?? stdout, stderr: stderrData ?? stderr,
            origin: .archivedSupervisedDriverDump,
            source: MonitorSource(provider: .nut, id: "synthetic", sessionID: "session", identityStability: .configured),
            expectedExecutableSHA256: pin, now: now
        )
    }

    private func receipt() throws -> Data { try json(makeReceipt()) }

    private func makeReceipt(stdoutData: Data? = nil, stderrData: Data? = nil) -> [String: Any] {
        let out = stdoutData ?? stdout
        let err = stderrData ?? stderr
        return [
            "schema_version": 1, "status": "exited", "trigger": "completed", "returncode": 0,
            "stdout_bytes": out.count, "stderr_bytes": err.count, "maximum_output_bytes": 65_536,
            "executable_sha256": pin, "stdout_sha256": hash(out), "stderr_sha256": hash(err),
            "started_at_unix_seconds": started.timeIntervalSince1970,
            "finished_at_unix_seconds": finished.timeIntervalSince1970,
            "data_qualified": false, "error": NSNull(),
        ]
    }

    private func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func object(_ data: Data) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func json(_ value: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    }

    private func encodedReceipt(_ utf8: Data, encoding: String.Encoding, bom: [UInt8]) throws -> Data {
        let text = try XCTUnwrap(String(data: utf8, encoding: .utf8))
        let encoded = try XCTUnwrap(text.data(using: encoding))
        return Data(bom) + encoded
    }
}
