import Foundation
import XCTest
import UPSHistory
import UPSModel
@testable import UPSAppHost

@MainActor
final class HistoryBrowserTests: XCTestCase {
    func testOldSessionPagingExportsOnlyDisplayedRecordsAndSupportsBack() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let records = (0..<5).map { sample(id: "old", offset: Double($0)) }
        for record in records { try await store.append(record, now: records.last!.capturedAt) }
        let browser = HistoryBrowserModel(store: store, pageSize: 2)
        await browser.refresh()
        XCTAssertEqual(browser.page?.records, Array(records.prefix(2)))
        XCTAssertTrue(browser.canGoForward)
        await browser.nextPage()
        XCTAssertEqual(browser.pageNumber, 2)
        XCTAssertEqual(browser.page?.records, Array(records[2...3]))
        let exported = try JSONDecoder().decode([MonitorSnapshot].self, from: browser.exportData(.json))
        XCTAssertEqual(exported, Array(records[2...3]))
        await browser.nextPage()
        XCTAssertEqual(browser.page?.records, [records[4]])
        XCTAssertFalse(browser.canGoForward)
        await browser.previousPage()
        XCTAssertEqual(browser.page?.records, Array(records[2...3]))
        await browser.selectRange(.session)
        XCTAssertEqual(browser.pageNumber, 1)
        XCTAssertEqual(browser.page?.records, Array(records.prefix(2)))
        browser.close()
        XCTAssertThrowsError(try browser.exportData(.json))
        try await store.close()
    }

    func testOpeningBrowserLeavesRecordingAndLiveSelectionUnchanged() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let old = sample(id: "stored", offset: 0)
        let live = sample(id: "live", offset: 5)
        let store = try UPSHistoryStore(directoryURL: directory)
        try await store.append(old, now: live.capturedAt)
        try await store.close()
        let model = MonitorAppModel(read: { [live] }, clock: { live.capturedAt }, historyDirectoryURL: directory,
                                    observesWorkspace: false, isPreview: false)
        await model.startIfNeeded()
        for _ in 0..<200 where model.selected != live { try await Task.sleep(for: .milliseconds(10)) }
        let selection = model.selectedSourceKey
        await model.openHistoryBrowser()
        let browser = try XCTUnwrap(model.historyBrowser)
        XCTAssertEqual(browser.selectedSession?.source, old.source)
        XCTAssertEqual(browser.page?.records, [old])
        XCTAssertFalse(model.recordsHistory)
        XCTAssertEqual(model.selected, live)
        XCTAssertEqual(model.selectedSourceKey, selection)
        await model.stop()
        XCTAssertNil(model.historyBrowser)
        XCTAssertFalse(browser.canExport)
    }

    func testSessionDeleteAndClearKeepCatalogAndPageConsistent() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let first = sample(id: "first", offset: 0)
        let second = sample(id: "second", offset: 1)
        try await store.append(first, now: second.capturedAt)
        try await store.append(second, now: second.capturedAt)
        let browser = HistoryBrowserModel(store: store)
        await browser.refresh()
        XCTAssertEqual(browser.sessions.count, 2)
        await browser.selectSession(HistoryBrowserModel.key(first.source))
        await browser.deleteSelectedSession()
        XCTAssertEqual(browser.sessions.map(\.source), [second.source])
        XCTAssertEqual(browser.page?.records, [second])
        await browser.clearAllHistory()
        XCTAssertEqual(browser.sessions, [])
        XCTAssertNil(browser.selectedSession)
        XCTAssertNil(browser.page)
        XCTAssertFalse(browser.canExport)
        XCTAssertFalse(browser.canGoBack)
        XCTAssertFalse(browser.canGoForward)
        XCTAssertFalse(browser.isLoading)
        try await store.close()
    }

    func testClosedBrowserRejectsNewRequestsAndMutations() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try UPSHistoryStore(directoryURL: directory)
        let record = sample(id: "source", offset: 0)
        try await store.append(record, now: record.capturedAt)
        let browser = HistoryBrowserModel(store: store)
        await browser.refresh()
        browser.close()
        await browser.clearAllHistory()
        await browser.deleteSelectedSession()
        await browser.refresh()
        await browser.nextPage()
        let catalog = try await store.sessions()
        XCTAssertEqual(catalog.sessions.count, 1)
        XCTAssertFalse(browser.isLoading)
        XCTAssertFalse(browser.canGoForward)
        try await store.close()
    }

    private func sample(id: String, offset: TimeInterval) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: .nut, id: id, sessionID: "synthetic-session", identityStability: .configured),
                        capturedAt: Date(timeIntervalSince1970: 40_000.123456 + offset),
                        status: MonitorStatus(quality: .unavailable),
                        metrics: [MonitorMetric(id: .upsRealPower, value: offset, unit: .watts,
                                                quality: .available, provenance: .driverDerived)])
    }
    private func temporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("history-browser-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        return directory
    }
}
