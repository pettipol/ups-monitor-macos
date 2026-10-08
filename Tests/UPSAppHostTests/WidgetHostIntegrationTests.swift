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
                                    widgetFixtureMode: .enabled,
                                    widgetPublisher: publisher)
        await model.startIfNeeded()
        model.refresh()
        await model.stop()
        let final = try await store.read(now: now)
        XCTAssertEqual(final, initial)
    }

    @MainActor
    func testWidgetFixtureUsesBuiltinReadAndPublishesOnlyToInjectedFixtureStore() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-fixture-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: store, reload: {})
        let injectedReadCalls = TestCallCounter()
        let nutFactoryCalls = TestCallCounter()
        let date = Date(timeIntervalSince1970: 500)
        let model = MonitorAppModel(
            read: { await injectedReadCalls.increment(); return [] },
            clock: { date }, observesWorkspace: true, isPreview: false,
            widgetFixtureMode: .enabled, widgetPublisher: publisher,
            nutReadFactory: { _ in
                await nutFactoryCalls.increment()
                return { [] }
            }
        )

        await model.startIfNeeded()
        for _ in 0..<200 where model.readState != .ready {
            try await Task.sleep(for: .milliseconds(10))
        }
        let active = try await store.read(now: date)
        let injectedReadCount = await injectedReadCalls.value
        let nutFactoryCallCount = await nutFactoryCalls.value

        XCTAssertEqual(model.readState, .ready)
        XCTAssertTrue(model.isWidgetFixture)
        XCTAssertEqual(model.syntheticModeTitle, "Synthetic widget test")
        XCTAssertEqual(active?.acquisition, .active)
        XCTAssertEqual(active?.snapshot?.source.id, "synthetic-widget-fixture")
        XCTAssertEqual(active?.snapshot?.source.sessionID, "synthetic-widget-session")
        XCTAssertEqual(active?.snapshot?.capturedAt, date)
        XCTAssertEqual(injectedReadCount, 0)
        XCTAssertEqual(nutFactoryCallCount, 0)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertNil(model.history)
        XCTAssertFalse(model.canExport)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertFalse(model.alerts.isEnabled)

        await model.setHistoryRecording(true)
        await model.openHistoryBrowser()
        await model.setAlertsEnabled(true)
        model.resetEnergy()
        model.refresh()
        let injectedReadCountAfterActions = await injectedReadCalls.value
        let nutFactoryCallCountAfterActions = await nutFactoryCalls.value

        XCTAssertFalse(model.recordsHistory)
        XCTAssertNil(model.historyBrowser)
        XCTAssertFalse(model.alerts.isEnabled)
        XCTAssertEqual(injectedReadCountAfterActions, 0)
        XCTAssertEqual(nutFactoryCallCountAfterActions, 0)

        await model.stop()
        let stopped = try await store.read(now: date)
        let injectedReadCountAfterStop = await injectedReadCalls.value
        XCTAssertEqual(stopped?.acquisition, .stopped)
        XCTAssertEqual(stopped?.snapshot?.source.id, "synthetic-widget-fixture")
        XCTAssertEqual(stopped?.snapshot?.capturedAt, date)
        XCTAssertEqual(injectedReadCountAfterStop, 0)
    }

    @MainActor
    func testInvalidFixtureModeFailsClosedWithoutSharingOrStartingReaders() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-invalid-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: store, reload: {})
        let injectedReadCalls = TestCallCounter()
        let date = Date(timeIntervalSince1970: 700)
        let model = MonitorAppModel(
            read: { await injectedReadCalls.increment(); return [] },
            clock: { date }, observesWorkspace: false, isPreview: false,
            widgetFixtureMode: .invalid, widgetPublisher: publisher
        )

        await model.startIfNeeded()
        let storedBeforeStop = try await store.read(now: date)
        let injectedReadCount = await injectedReadCalls.value

        XCTAssertTrue(model.isWidgetConfigurationInvalid)
        XCTAssertEqual(model.readState, .failed)
        XCTAssertTrue(model.operationMessage?.contains("configuration invalid") == true)
        XCTAssertEqual(model.syntheticModeTitle, "Synthetic preview · widget configuration invalid")
        XCTAssertNil(storedBeforeStop)
        XCTAssertEqual(injectedReadCount, 0)
        await model.stop()
        let storedAfterStop = try await store.read(now: date)
        XCTAssertNil(storedAfterStop)
    }
}

private actor TestCallCounter {
    private(set) var value = 0
    func increment() { value += 1 }
}
