import Foundation
import XCTest
import UPSHistory
import UPSModel
import UPSMonitorUI
import UPSRuntime
import UPSWidgetBridge
import UPSWidgetData
@testable import UPSAppHost

@MainActor
final class PresentationNameHostTests: XCTestCase {
    private let date = Date(timeIntervalSince1970: 45_000)

    func testPresentationNameFollowsSelectionAndStaleCacheButNotHistoryExports() async throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let historyURL = directory.appendingPathComponent("history")
        let widgetStore = try WidgetSnapshotStore(directoryURL: directory.appendingPathComponent("widget"), mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: widgetStore, reload: {})
        let first = snapshot(id: "a")
        let second = snapshot(id: "b")
        let readings = [MonitorReading(snapshot: first, presentationName: "Synthetic Alpha"),
                        MonitorReading(snapshot: second, presentationName: "Synthetic Beta")]
        let model = MonitorAppModel(readWithPresentation: { readings }, clock: { first.capturedAt },
                                    historyDirectoryURL: historyURL, observesWorkspace: false,
                                    isPreview: false, widgetFixtureMode: .disabled, widgetPublisher: publisher)
        await model.setHistoryRecording(true)
        await model.startIfNeeded()
        await waitUntil { model.history == [first] }
        XCTAssertEqual(model.presentationNamesBySourceKey[UPSMonitorFormatters.sourceKey(for: first)], "Synthetic Alpha")
        await waitForWidget(widgetStore, snapshot: first, name: "Synthetic Alpha")

        model.select(UPSMonitorFormatters.sourceKey(for: second))
        await waitUntil { model.history == [second] }
        await waitForWidget(widgetStore, snapshot: second, name: "Synthetic Beta")
        await model.stop()
        let stopped = try await widgetStore.read(now: date)
        XCTAssertEqual(stopped?.presentationName, "Synthetic Beta")
        XCTAssertEqual(stopped?.snapshot, second)
        XCTAssertEqual(stopped?.acquisition, .stopped)

        let history = try UPSHistoryStore(directoryURL: historyURL)
        let query = try HistoryQuery(start: date, end: date, source: second.source)
        for format in [HistoryExportFormat.json, .csv] {
            let data = try await history.export(query, format: format)
            let text = try XCTUnwrap(String(data: data, encoding: .utf8))
            XCTAssertFalse(text.contains("Synthetic Beta"), "Display names must not enter history exports")
            XCTAssertFalse(text.contains("presentationName"))
        }
        let records = try await history.query(query)
        XCTAssertEqual(records, [second])
        try await history.close()
    }

    func testPresentationNamesClearWhenChangingBackend() async throws {
        let apple = snapshot(id: "apple")
        let nut = snapshot(id: "nut", provider: .nut)
        let model = MonitorAppModel(readWithPresentation: { [MonitorReading(snapshot: apple, presentationName: "Synthetic Apple UPS")] },
                                    clock: { apple.capturedAt }, observesWorkspace: false, isPreview: false,
                                    widgetFixtureMode: .disabled, nutReadFactory: { _ in { [nut] } })
        await model.startIfNeeded()
        await waitUntil { model.selected == apple }
        XCTAssertEqual(model.presentationNamesBySourceKey.count, 1)
        model.connectionDraft = NUTConnectionDraft(executablePath: "/synthetic/upsc",
                                                  expectedSHA256: String(repeating: "a", count: 64),
                                                  upsName: "fixture", completionQualified: true)
        await model.connectNUT()
        model.refresh()
        await waitUntil { model.selected == nut }
        XCTAssertEqual(model.presentationNamesBySourceKey, [:])
        await model.useAppleBackend()
        model.refresh()
        await waitUntil { model.selected == apple }
        XCTAssertEqual(model.presentationNamesBySourceKey[UPSMonitorFormatters.sourceKey(for: apple)], "Synthetic Apple UPS")
        await model.stop()
    }

    func testPresentationNamesClearWhenSourcesDisappear() async throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try WidgetSnapshotStore(directoryURL: directory.appendingPathComponent("widget"), mode: .readWrite)
        let sample = snapshot(id: "a")
        let feed = PresentationNameFeed([MonitorReading(snapshot: sample, presentationName: "Synthetic Name")])
        let model = MonitorAppModel(readWithPresentation: { await feed.read() }, clock: { sample.capturedAt },
                                    observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
                                    widgetPublisher: WidgetSnapshotPublisher(store: store, reload: {}))
        await model.startIfNeeded()
        await waitUntil { model.selected == sample }
        await feed.replace([])
        model.refresh()
        await waitUntil { model.readState == .noSources }
        XCTAssertEqual(model.presentationNamesBySourceKey, [:])
        await model.stop()
        let value = try await store.read(now: date)
        XCTAssertNil(value?.snapshot)
        XCTAssertNil(value?.presentationName)
    }

    func testPresentationReaderNeverRunsInSyntheticModes() async {
        for mode in ["preview", "fixture", "invalid"] {
            let calls = PresentationNameCallCounter()
            let date = date
            let model = MonitorAppModel(readWithPresentation: { await calls.increment(); return [] },
                                        clock: { date }, observesWorkspace: false,
                                        isPreview: mode == "preview",
                                        widgetFixtureMode: mode == "invalid" ? .invalid : .enabled)
            await model.startIfNeeded()
            if mode == "fixture" { await waitUntil { model.readState == .ready } }
            XCTAssertEqual(model.presentationNamesBySourceKey, [:])
            await model.stop()
            let count = await calls.value
            XCTAssertEqual(count, 0)
        }
    }

    private func snapshot(id: String, provider: MonitorProvider = .apple) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: provider, id: id, sessionID: "synthetic-session",
                                              identityStability: provider == .apple ? .sessionLocal : .configured),
                        capturedAt: date, status: MonitorStatus(lineState: .onLine, quality: .available), metrics: [])
    }

    private func makeDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-name-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                               attributes: [.posixPermissions: 0o700])
        return directory
    }

    private func waitUntil(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<300 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Expected synthetic host state was not reached", file: file, line: line)
    }

    private func waitForWidget(_ store: WidgetSnapshotStore, snapshot: MonitorSnapshot, name: String,
                               file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<300 {
            if let value = try? await store.read(now: date), value.snapshot == snapshot,
               value.presentationName == name { return }
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Widget cache did not receive the matching snapshot and name", file: file, line: line)
    }
}

private actor PresentationNameFeed {
    private var readings: [MonitorReading]
    init(_ readings: [MonitorReading]) { self.readings = readings }
    func read() -> [MonitorReading] { readings }
    func replace(_ readings: [MonitorReading]) { self.readings = readings }
}

private actor PresentationNameCallCounter {
    private(set) var value = 0
    func increment() { value += 1 }
}
