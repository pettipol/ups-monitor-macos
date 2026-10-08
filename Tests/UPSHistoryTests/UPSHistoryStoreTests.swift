import Foundation
import SQLite3
import XCTest
import UPSModel
@testable import UPSHistory

final class UPSHistoryStoreTests: XCTestCase {
    func testRoundTripReopenDuplicateAndConflict() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = try snapshot(at: Date(timeIntervalSince1970: 1_800_000_000), charge: 0)
        let store = try UPSHistoryStore(directoryURL: directory)
        try await store.append(first, now: first.capturedAt)
        try await store.append(first, now: first.capturedAt)
        try await store.close()

        let reopened = try UPSHistoryStore(directoryURL: directory)
        let query = try HistoryQuery(start: first.capturedAt, end: first.capturedAt, source: first.source)
        let reopenedRecords = try await reopened.query(query)
        XCTAssertEqual(reopenedRecords, [first])
        let conflict = try snapshot(at: first.capturedAt, charge: 1)
        do {
            try await reopened.append(conflict, now: conflict.capturedAt)
            XCTFail("A conflicting sample at the same source and time must fail")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .conflictingSample)
        }
    }

    func testOrderingFiltersRowCapRetentionAndDeletion() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let retention = try HistoryRetention(maximumAge: 10_000, maximumRows: 2)
        let store = try UPSHistoryStore(directoryURL: directory, retention: retention)
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        let other = MonitorSource(provider: .nut, id: "ups-b", sessionID: "session-b", identityStability: .configured)
        try await store.append(try snapshot(at: t0, charge: 10), now: t0)
        try await store.append(try snapshot(at: t0.addingTimeInterval(1), charge: 20), now: t0.addingTimeInterval(1))
        try await store.append(try snapshot(at: t0.addingTimeInterval(2), charge: 30), now: t0.addingTimeInterval(2))
        try await store.append(try snapshot(at: t0.addingTimeInterval(3), charge: 40, source: other), now: t0.addingTimeInterval(3))

        let sourceQuery = try HistoryQuery(start: t0, end: t0.addingTimeInterval(10), source: source, limit: 1)
        let results = try await store.query(sourceQuery)
        XCTAssertEqual(results.map(\.metrics[0].value), [30])
        let removed = try await store.delete(source: other)
        XCTAssertEqual(removed, 1)
        let cleared = try await store.clear()
        XCTAssertEqual(cleared, 1)
        let empty = try await store.query(sourceQuery)
        XCTAssertTrue(empty.isEmpty)
        let emptyCSV = String(decoding: try await store.export(sourceQuery, format: .csv), as: UTF8.self)
        XCTAssertEqual(emptyCSV.split(separator: "\n").count, 1)
    }

    func testExportsKeepZeroMissingStatusOnlyAndGuardFormulaCells() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let source = MonitorSource(provider: .nut, id: "ups-1", sessionID: "s1", identityStability: .sessionLocal)
        let statusOnly = MonitorSnapshot(source: source, capturedAt: Date(timeIntervalSince1970: 1_800_000_000),
                                         status: MonitorStatus(lineState: .unknown, flags: [.alarm], quality: .unavailable,
                                                               internalFailure: false, batteryHealth: .unknown, isCharging: false), metrics: [])
        try await store.append(statusOnly, now: statusOnly.capturedAt)
        let zeroSnapshot = try snapshot(at: statusOnly.capturedAt.addingTimeInterval(1), charge: 0, source: source)
        try await store.append(zeroSnapshot, now: zeroSnapshot.capturedAt)
        let missing = MonitorMetric(id: .batteryVoltage, value: nil, unit: .volts, quality: .unavailable, provenance: .reported)
        let negative = MonitorMetric(id: .inputCurrent, value: -1, unit: .amps, quality: .available, provenance: .reported)
        let missingSnapshot = MonitorSnapshot(source: source, capturedAt: statusOnly.capturedAt.addingTimeInterval(2),
                                              status: MonitorStatus(quality: .available), metrics: [missing, negative])
        try await store.append(missingSnapshot, now: missingSnapshot.capturedAt)
        let query = try HistoryQuery(start: statusOnly.capturedAt, end: statusOnly.capturedAt.addingTimeInterval(3), source: source)
        let json = String(decoding: try await store.export(query, format: .json), as: UTF8.self)
        let csv = String(decoding: try await store.export(query, format: .csv), as: UTF8.self)
        XCTAssertTrue(json.contains("\"value\":0"))
        XCTAssertTrue(csv.contains("status_flag"))
        XCTAssertTrue(csv.contains("alarm"))
        XCTAssertTrue(csv.contains("\"0.0\""))
        XCTAssertTrue(csv.contains("\"\",\"volts\",\"unavailable\",\"reported\""))
        XCTAssertTrue(csv.contains("\"unknown\""))
        XCTAssertTrue(csv.contains("\"internal_failure\",\"false\""))
        XCTAssertTrue(csv.contains("\"battery_health\",\"unknown\""))
        XCTAssertTrue(csv.contains("\"is_charging\",\"false\""))
        XCTAssertTrue(csv.contains("\"-1.0\""))
    }

    func testRejectsSymlinkAndUnknownDatabaseWithoutChangingTarget() throws {
        let parent = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: parent) }
        let directory = parent.appendingPathComponent("store", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        let sentinel = parent.appendingPathComponent("sentinel")
        let original = Data("private sentinel".utf8)
        try original.write(to: sentinel)
        try FileManager.default.createSymbolicLink(at: directory.appendingPathComponent("history.sqlite3"), withDestinationURL: sentinel)
        XCTAssertThrowsError(try UPSHistoryStore(directoryURL: directory)) { error in
            XCTAssertEqual(error as? HistoryError, .unsafeLocation)
        }
        XCTAssertEqual(try Data(contentsOf: sentinel), original)

        let unknownDirectory = parent.appendingPathComponent("unknown", isDirectory: true)
        try FileManager.default.createDirectory(at: unknownDirectory, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        let unknownDB = unknownDirectory.appendingPathComponent("history.sqlite3")
        let unknownBytes = Data("not an app database".utf8)
        try unknownBytes.write(to: unknownDB)
        XCTAssertThrowsError(try UPSHistoryStore(directoryURL: unknownDirectory))
        XCTAssertEqual(try Data(contentsOf: unknownDB), unknownBytes)
    }

    func testRejectsFutureSchemaAndCorruptRows() async throws {
        let futureDirectory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: futureDirectory) }
        let store = try UPSHistoryStore(directoryURL: futureDirectory)
        try await store.close()
        try executeSQL(in: futureDirectory, "PRAGMA user_version=2")
        XCTAssertThrowsError(try UPSHistoryStore(directoryURL: futureDirectory)) { error in
            XCTAssertEqual(error as? HistoryError, .incompatibleSchema)
        }

        let corruptDirectory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: corruptDirectory) }
        let corruptStore = try UPSHistoryStore(directoryURL: corruptDirectory)
        let record = try snapshot(at: Date(timeIntervalSince1970: 1_800_000_000), charge: 55)
        try await corruptStore.append(record, now: record.capturedAt)
        try await corruptStore.close()
        try executeSQL(in: corruptDirectory, "UPDATE samples SET payload=x'6e6f742d6a736f6e'")
        let reopened = try UPSHistoryStore(directoryURL: corruptDirectory)
        let query = try HistoryQuery(start: record.capturedAt, end: record.capturedAt, source: record.source)
        do {
            _ = try await reopened.query(query)
            XCTFail("Corrupt payloads must not be returned")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .corruptRecord)
        }
    }

    func testRejectsNonPrivateDirectoryAndRedactsSQLiteFailure() async throws {
        let parent = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: parent) }
        let looseDirectory = parent.appendingPathComponent("loose", isDirectory: true)
        try FileManager.default.createDirectory(at: looseDirectory, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o755])
        XCTAssertThrowsError(try UPSHistoryStore(directoryURL: looseDirectory)) { error in
            XCTAssertEqual(error as? HistoryError, .unsafeLocation)
        }

        let directory = parent.appendingPathComponent("triggered", isDirectory: true)
        let store = try UPSHistoryStore(directoryURL: directory)
        try executeSQL(in: directory, "CREATE TRIGGER reject_sample BEFORE INSERT ON samples BEGIN SELECT RAISE(ABORT, 'sensitive local path'); END")
        do {
            let record = try snapshot(at: Date(timeIntervalSince1970: 1_800_000_000), charge: 42)
            try await store.append(record, now: record.capturedAt)
            XCTFail("The synthetic SQLite trigger should reject the insert")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .databaseUnavailable)
            XCTAssertFalse(String(describing: error).contains("sensitive local path"))
        }
    }

    private var source: MonitorSource {
        MonitorSource(provider: .nut, id: "ups-1", sessionID: "session-1", identityStability: .configured)
    }

    private func snapshot(at date: Date, charge: Double, source: MonitorSource? = nil) throws -> MonitorSnapshot {
        let metric = MonitorMetric(id: .batteryCharge, value: charge, unit: .percent, quality: .available, provenance: .reported)
        let value = MonitorSnapshot(source: source ?? self.source, capturedAt: date,
                                    status: MonitorStatus(lineState: .onLine, quality: .available), metrics: [metric])
        try value.validate()
        return value
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("UPSHistoryTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        return url
    }

    private func executeSQL(in directory: URL, _ sql: String) throws {
        let databaseURL = directory.appendingPathComponent("history.sqlite3")
        var database: OpaquePointer?
        guard sqlite3_open(databaseURL.path, &database) == SQLITE_OK, let database else {
            if let database { sqlite3_close(database) }
            throw HistoryError.databaseUnavailable
        }
        defer { sqlite3_close(database) }
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw HistoryError.databaseUnavailable
        }
    }
}
