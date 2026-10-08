import Foundation
import SQLite3
import XCTest
import UPSModel
@testable import UPSHistory

final class HistoryBrowsingTests: XCTestCase {
    func testSessionSummariesAreBoundedOrderedAndValidated() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let t0 = Date(timeIntervalSince1970: 1_800_000_000.1234)
        let sourceA = source(id: "ups-a", session: "session-a")
        let sourceB = source(id: "ups-b", session: "session-b")
        try await store.append(snapshot(source: sourceA, at: t0), now: t0)
        try await store.append(snapshot(source: sourceA, at: t0.addingTimeInterval(1.2345)), now: t0.addingTimeInterval(1.2345))
        try await store.append(snapshot(source: sourceB, at: t0.addingTimeInterval(2.3456)), now: t0.addingTimeInterval(2.3456))

        let page = try await store.sessions(limit: 1)
        XCTAssertTrue(page.hasMore)
        XCTAssertEqual(page.sessions.count, 1)
        XCTAssertEqual(page.sessions[0].source, sourceB)
        XCTAssertEqual(page.sessions[0].firstCapturedAt, page.sessions[0].lastCapturedAt)
        XCTAssertEqual(page.sessions[0].sampleCount, 1)
        let all = try await store.sessions(limit: 2)
        XCTAssertFalse(all.hasMore)
        XCTAssertEqual(all.sessions.map(\.source), [sourceB, sourceA])
        XCTAssertEqual(all.sessions[1].sampleCount, 2)
        XCTAssertEqual(all.sessions[1].lastCapturedAt, t0.addingTimeInterval(1.2345))
        do {
            _ = try await store.sessions(limit: 0)
            XCTFail("Invalid session limits must be rejected")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .invalidRequest)
        }
    }

    func testPagesKeepInclusiveBoundariesAndSubsecondCursorIdentity() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000.1234)
        let second = start.addingTimeInterval(0.0007)
        let third = start.addingTimeInterval(0.0014)
        for date in [start, second, third] {
            try await store.append(snapshot(source: source, at: date), now: date)
        }
        let query = try HistoryQuery(start: start, end: third, source: source, limit: 2)

        let firstPage = try await store.queryPage(query)
        XCTAssertEqual(firstPage.records.map(\.capturedAt), [start, second])
        XCTAssertTrue(firstPage.hasMore)
        XCTAssertEqual(firstPage.nextAfter, second)
        let secondPage = try await store.queryPage(query, after: firstPage.nextAfter)
        XCTAssertEqual(secondPage.records.map(\.capturedAt), [third])
        XCTAssertFalse(secondPage.hasMore)
        XCTAssertNil(secondPage.nextAfter)

        let exactBoundary = try HistoryQuery(start: second, end: second, source: source, limit: 1)
        let boundaryPage = try await store.queryPage(exactBoundary)
        XCTAssertEqual(boundaryPage.records.map(\.capturedAt), [second])
    }

    func testPageExportsEncodeExactlyTheProvidedValidatedRecords() async throws {
        let source = source(id: "ups-a", session: "session-a")
        let first = snapshot(source: source, at: Date(timeIntervalSince1970: 1_800_000_000.125))
        let second = snapshot(source: source, at: Date(timeIntervalSince1970: 1_800_000_001.875))
        let records = [first, second]
        let json = try UPSHistoryStore.encodeExport(records, format: .json)
        let csv = String(decoding: try UPSHistoryStore.encodeExport(records, format: .csv), as: UTF8.self)
        let decoded = try JSONDecoder().decode([MonitorSnapshot].self, from: json)
        XCTAssertEqual(decoded, records)
        XCTAssertTrue(csv.contains(String(first.capturedAt.timeIntervalSinceReferenceDate)))
        XCTAssertTrue(csv.contains(String(second.capturedAt.timeIntervalSinceReferenceDate)))
        XCTAssertEqual(csv.components(separatedBy: "\n").filter { $0.contains(",\"metric\",\"batteryCharge\",") }.count, 2)
    }

    func testPageRejectsInvalidAndOutOfRangeCursors() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        let query = try HistoryQuery(start: start, end: start.addingTimeInterval(10), source: source)
        for cursor in [start.addingTimeInterval(-1), query.end.addingTimeInterval(1), Date(timeIntervalSince1970: 1e20)] {
            do {
                _ = try await store.queryPage(query, after: cursor)
                XCTFail("Out-of-range cursor must be rejected")
            } catch let error as HistoryError {
                XCTAssertEqual(error, .invalidRequest)
            }
        }
        do {
            _ = try await store.queryPage(query, after: Date(timeIntervalSince1970: .nan))
            XCTFail("Non-finite cursor must be rejected")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .invalidRequest)
        }
    }

    func testSessionListingRejectsCorruptRepresentativePayload() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let source = source(id: "ups-a", session: "session-a")
        let record = snapshot(source: source, at: Date(timeIntervalSince1970: 1_800_000_000))
        try await store.append(record, now: record.capturedAt)
        try await store.close()
        try executeSQL(in: directory, "UPDATE samples SET payload=x'6e6f742d6a736f6e'")
        let reopened = try UPSHistoryStore(directoryURL: directory)
        do {
            _ = try await reopened.sessions()
            XCTFail("Session representatives must be decoded and validated")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .corruptRecord)
        }
    }

    func testPageValidatesCorruptLookaheadAndRejectsInvalidSourceOrClosedStore() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let source = source(id: "ups-a", session: "session-a")
        let first = Date(timeIntervalSince1970: 1_800_000_000)
        let second = first.addingTimeInterval(1)
        try await store.append(snapshot(source: source, at: first), now: first)
        try await store.append(snapshot(source: source, at: second), now: second)
        try await store.close()
        try executeSQL(in: directory, "UPDATE samples SET payload=x'6e6f742d6a736f6e' WHERE captured_us=(SELECT MAX(captured_us) FROM samples)")
        let reopened = try UPSHistoryStore(directoryURL: directory)
        let query = try HistoryQuery(start: first, end: second, source: source, limit: 1)
        do {
            _ = try await reopened.queryPage(query)
            XCTFail("A corrupt lookahead row must not be hidden by pagination")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .corruptRecord)
        }

        let invalidSource = MonitorSource(provider: .nut, id: "bad id", sessionID: "session-a", identityStability: .configured)
        let invalidQuery = try HistoryQuery(start: first, end: second, source: invalidSource)
        do {
            _ = try await reopened.queryPage(invalidQuery)
            XCTFail("Invalid source identities must be rejected")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .invalidRequest)
        }
        try await reopened.close()
        do {
            _ = try await reopened.sessions()
            XCTFail("A closed store must reject browsing")
        } catch let error as HistoryError {
            XCTAssertEqual(error, .databaseUnavailable)
        }
    }

    private func source(id: String, session: String) -> MonitorSource {
        MonitorSource(provider: .nut, id: id, sessionID: session, identityStability: .configured)
    }

    private func snapshot(source: MonitorSource, at date: Date) -> MonitorSnapshot {
        MonitorSnapshot(source: source, capturedAt: date,
                        status: MonitorStatus(lineState: .onLine, quality: .available),
                        metrics: [MonitorMetric(id: .batteryCharge, value: 42, unit: .percent,
                                                quality: .available, provenance: .reported)])
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("UPSHistoryBrowsingTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        return url
    }

    private func executeSQL(in directory: URL, _ sql: String) throws {
        var database: OpaquePointer?
        let path = directory.appendingPathComponent("history.sqlite3").path
        guard sqlite3_open(path, &database) == SQLITE_OK, let database else {
            if let database { sqlite3_close(database) }
            throw HistoryError.databaseUnavailable
        }
        defer { sqlite3_close(database) }
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw HistoryError.databaseUnavailable
        }
    }
}
