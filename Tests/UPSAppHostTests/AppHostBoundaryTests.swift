import Foundation
import XCTest
import UPSHistory
import UPSModel
@testable import UPSAppHost

final class AppHostBoundaryTests: XCTestCase {
    @MainActor
    func testSyntheticPreviewNeverReadsOrCreatesHistory() async throws {
        let parent = try makePrivateDirectory()
        defer { try? FileManager.default.removeItem(at: parent) }
        let directory = parent.appendingPathComponent("preview-history")
        let counter = HostReadCounter()
        let model = MonitorAppModel(read: { await counter.read() }, historyDirectoryURL: directory,
                                    observesWorkspace: false, isPreview: true)
        await model.startIfNeeded()
        await model.setHistoryRecording(true)
        model.refresh()
        await model.stop()
        let count = await counter.count
        XCTAssertEqual(count, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.canExport)
    }

    @MainActor
    func testHistoryIsOptInAndRecordedSnapshotSurvivesStop() async throws {
        let parent = try makePrivateDirectory()
        defer { try? FileManager.default.removeItem(at: parent) }
        let directory = parent.appendingPathComponent("history")
        let date = Date(timeIntervalSince1970: 20_000)
        let source = MonitorSource(provider: .nut, id: "synthetic", sessionID: "session", identityStability: .configured)
        let snapshot = MonitorSnapshot(source: source, capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
        let model = MonitorAppModel(read: { [snapshot] }, clock: { date }, historyDirectoryURL: directory,
                                    observesWorkspace: false, isPreview: false)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        await model.setHistoryRecording(true)
        await model.startIfNeeded()
        for _ in 0..<200 where model.history?.isEmpty != false {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(model.history, [snapshot])
        XCTAssertTrue(model.canExport)
        await model.stop()
        model.refresh()
        await model.setHistoryRecording(true)
        await model.startIfNeeded()
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.canExport)
        XCTAssertEqual(model.readState, .stopped)
        let reopened = try UPSHistoryStore(directoryURL: directory)
        let query = try HistoryQuery(start: date.addingTimeInterval(-1), end: date, source: source)
        let records = try await reopened.query(query)
        XCTAssertEqual(records, [snapshot])
        try await reopened.close()
    }

    @MainActor
    func testQueuedRefreshCannotReadAfterTerminalStop() async throws {
        let counter = HostReadCounter()
        let model = MonitorAppModel(read: { await counter.read() }, observesWorkspace: false, isPreview: false)
        await model.startIfNeeded()
        model.refresh()
        await model.stop()
        let count = await counter.count
        for _ in 0..<5 { model.refresh() }
        try await Task.sleep(for: .milliseconds(50))
        let finalCount = await counter.count
        XCTAssertEqual(finalCount, count)
        XCTAssertEqual(model.readState, .stopped)
    }

    private func makePrivateDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ups-host-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false,
                                               attributes: [.posixPermissions: 0o700])
        return url
    }
}

private actor HostReadCounter {
    var count = 0
    func read() -> [MonitorSnapshot] { count += 1; return [] }
}
