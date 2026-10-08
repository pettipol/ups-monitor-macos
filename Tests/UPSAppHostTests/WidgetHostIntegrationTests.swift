import Foundation
import XCTest
import UPSModel
import UPSWidgetData
import UPSWidgetBridge
@testable import UPSAppHost

final class WidgetHostIntegrationTests: XCTestCase {
    @MainActor
    func testWidgetSharingIsSeparateFromHistoryAndStopPublishesStaleState() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-host-widget-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: store, reload: {})
        let date = Date(timeIntervalSince1970: 200)
        let sample = MonitorSnapshot(source: MonitorSource(provider: .apple, id: "synthetic", sessionID: "session", identityStability: .sessionLocal),
                                     capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
        let model = MonitorAppModel(read: { [sample] }, clock: { date }, observesWorkspace: false,
                                    isPreview: false, widgetPublisher: publisher)
        await model.startIfNeeded()
        for _ in 0..<200 where model.readState != .ready { try await Task.sleep(for: .milliseconds(10)) }
        let active = try await store.read(now: date)
        XCTAssertEqual(active?.snapshot, sample)
        XCTAssertEqual(active?.acquisition, .active)
        XCTAssertFalse(model.recordsHistory)
        await model.stop()
        let stopped = try await store.read(now: date)
        XCTAssertEqual(stopped?.acquisition, .stopped)
        XCTAssertEqual(stopped?.snapshot?.capturedAt, date)
        XCTAssertEqual(stopped?.isStale(at: date), true)
    }

    @MainActor
    func testSyntheticPreviewCannotOverwriteInjectedSharedStore() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-preview-widget-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
        let now = Date(timeIntervalSince1970: 200)
        let initial = WidgetSnapshot(publishedAt: now, acquisition: .noSources, maximumAge: 10, snapshot: nil)
        try await store.write(initial, now: now)
        let publisher = WidgetSnapshotPublisher(store: store, reload: {})
        let model = MonitorAppModel(clock: { now }, observesWorkspace: false, isPreview: true,
                                    widgetPublisher: publisher)
        await model.startIfNeeded()
        model.refresh()
        await model.stop()
        let final = try await store.read(now: now)
        XCTAssertEqual(final, initial)
    }
}
