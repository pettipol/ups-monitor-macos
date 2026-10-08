import Foundation
import SQLite3
import XCTest
import UPSModel
@testable import UPSHistory

final class HistoryBoundaryRegressionTests: XCTestCase {
    func testNumericCSVRetainsNegativeNumber() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let sample = snapshot(at: 1_000, value: -1.25)
        try await store.append(sample, now: sample.capturedAt)
        let csv = String(decoding: try await store.export(query(for: sample), format: .csv), as: UTF8.self)
        XCTAssertTrue(csv.contains("\"inputCurrent\",\"-1.25\",\"amps\""), "Typed numeric cells must remain importable as numbers")
        XCTAssertFalse(csv.contains("'-1.25"))
        try await store.close()
    }

    func testRetentionFailureRollsBackInsertion() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory, retention: HistoryRetention(maximumAge: 10, maximumRows: 100))
        let first = snapshot(at: 1_000)
        try await store.append(first, now: first.capturedAt)
        try executeSQL(in: directory, "CREATE TRIGGER reject_delete BEFORE DELETE ON samples BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        do {
            try await store.append(snapshot(at: 1_020), now: Date(timeIntervalSince1970: 1_020))
            XCTFail("The synthetic retention failure must be reported")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .databaseUnavailable)
        }
        let records = try await store.query(HistoryQuery(start: Date(timeIntervalSince1970: 990), end: Date(timeIntervalSince1970: 1_030), source: first.source))
        XCTAssertEqual(records, [first], "A failed append must not leave its new row behind")
        try await store.close()
    }

    func testSemanticallyEqualFlagOrderIsIdempotent() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let sample = snapshot(at: 1_000, flags: [.alarm, .outputOff])
        try await store.append(sample, now: sample.capturedAt)
        // The same valid Set has no array ordering contract in persisted JSON.
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(sample)) as? [String: Any])
        var status = try XCTUnwrap(object["status"] as? [String: Any])
        let flags = try XCTUnwrap(status["flags"] as? [String])
        status["flags"] = Array(flags.reversed())
        object["status"] = status
        let payload = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        let hex = payload.map { String(format: "%02x", $0) }.joined()
        try executeSQL(in: directory, "UPDATE samples SET payload=x'\(hex)'")
        do {
            try await store.append(sample, now: sample.capturedAt)
        } catch {
            XCTFail("Equal decoded snapshots must be idempotent regardless of JSON Set order: \(error)")
        }
        try await store.close()
    }

    func testUnexpectedSchemaObjectRefusesReopenWithoutChangingBytes() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        try await store.close()
        try executeSQL(in: directory, "CREATE TRIGGER unexpected AFTER INSERT ON samples BEGIN DELETE FROM samples; END")
        let path = directory.appendingPathComponent("history.sqlite3")
        let before = try Data(contentsOf: path)
        do {
            let reopened = try UPSHistoryStore(directoryURL: directory)
            try await reopened.close()
            XCTFail("An additional trigger is not the known application schema")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .incompatibleSchema)
        }
        XCTAssertEqual(try Data(contentsOf: path), before)
    }

    func testFutureSampleCannotPurgeExistingHistory() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory, retention: HistoryRetention(maximumAge: 10, maximumRows: 100))
        let first = snapshot(at: 1_000)
        try await store.append(first, now: first.capturedAt)
        do {
            try await store.append(snapshot(at: 1_000_000), now: first.capturedAt.addingTimeInterval(1))
            XCTFail("Future capture time must not control pruning")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .invalidSnapshot)
        }
        let records = try await store.query(query(for: first))
        XCTAssertEqual(records, [first])
        try await store.close()
    }

    func testExplicitClockRejectsExpiredReplayAndPrunesWithoutNewSample() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory, retention: HistoryRetention(maximumAge: 10, maximumRows: 100))
        let first = snapshot(at: 1_000)
        try await store.append(first, now: first.capturedAt)
        do {
            try await store.append(snapshot(at: 999), now: Date(timeIntervalSince1970: 1_020))
            XCTFail("An old replay must not bypass age policy")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .outsideRetentionWindow)
        }
        let unchanged = try await store.query(query(for: first))
        XCTAssertEqual(unchanged, [first], "Rejected records must not prune existing data as a side effect")
        try await store.prune(now: Date(timeIntervalSince1970: 1_020))
        let pruned = try await store.query(query(for: first))
        XCTAssertTrue(pruned.isEmpty)
        try await store.close()
    }

    func testOversizedStoredPayloadIsRejected() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let sample = snapshot(at: 1_000)
        try await store.append(sample, now: sample.capturedAt)
        // JSON whitespace is legal: successful decoding alone is not a size guard.
        var payload = try JSONEncoder().encode(sample)
        payload.append(Data(repeating: 0x20, count: 70_000))
        let hex = payload.map { String(format: "%02x", $0) }.joined()
        try executeSQL(in: directory, "UPDATE samples SET payload=x'\(hex)'")
        do {
            _ = try await store.query(query(for: sample))
            XCTFail("Stored payload must be bounded before allocation/decode")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .corruptRecord)
        }
        try await store.close()
    }

    func testCSVPreservesSubmillisecondCaptureIdentity() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let sample = snapshot(at: 1_800_000_000.000123)
        try await store.append(sample, now: sample.capturedAt)
        let csv = String(decoding: try await store.export(query(for: sample), format: .csv), as: UTF8.self)
        XCTAssertTrue(csv.split(separator: "\n")[0].contains("captured_at_reference_seconds"))
        XCTAssertTrue(csv.contains("\"\(sample.capturedAt.timeIntervalSinceReferenceDate)\""), "Human-readable milliseconds alone lose capture precision")
        try await store.close()
    }

    private func snapshot(at seconds: TimeInterval, value: Double = 1, flags: Set<MonitorStatusFlag> = []) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: .nut, id: "fixture", sessionID: "session", identityStability: .configured), capturedAt: Date(timeIntervalSince1970: seconds), status: MonitorStatus(lineState: .unknown, flags: flags, quality: .available), metrics: [MonitorMetric(id: .inputCurrent, value: value, unit: .amps, quality: .available, provenance: .reported)])
    }

    private func query(for snapshot: MonitorSnapshot) throws -> HistoryQuery {
        try HistoryQuery(start: snapshot.capturedAt, end: snapshot.capturedAt, source: snapshot.source)
    }

    private func temporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("UPSHistoryBoundary-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        return directory
    }

    private func executeSQL(in directory: URL, _ sql: String) throws {
        var handle: OpaquePointer?
        guard sqlite3_open(directory.appendingPathComponent("history.sqlite3").path, &handle) == SQLITE_OK, let handle else {
            if let handle { sqlite3_close(handle) }
            throw HistoryError.databaseUnavailable
        }
        defer { sqlite3_close(handle) }
        guard sqlite3_exec(handle, sql, nil, nil, nil) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
    }
}
