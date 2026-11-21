import Foundation
import XCTest
import UPSModel
import UPSMonitorUI
import UPSRuntime
import UPSWidgetBridge
import UPSWidgetData
@testable import UPSAppHost

@MainActor
final class ContinuousSessionHostTests: XCTestCase {
    private let date = Date(timeIntervalSince1970: 1_800_000_000)

    func testDefaultSessionFactoryFailsClosedAndKeepsAppleBackend() async {
        let apple = snapshot(provider: .apple, id: "apple")
        let clockDate = date
        let model = MonitorAppModel(read: { [apple] }, clock: { clockDate }, observesWorkspace: false,
                                    isPreview: false)
        await model.startIfNeeded()
        await waitUntil { model.selected == apple }
        model.supervisedSessionDirectoryURL = URL(fileURLWithPath: "/synthetic/session")
        await model.connectSupervisedSession()
        XCTAssertEqual(model.backend, .apple)
        XCTAssertEqual(model.selected, apple)
        XCTAssertEqual(model.supervisedSessionMessage, "Supervised session unavailable")
        await model.stop()
    }

    func testInjectedSessionUsesSelectedDirectoryAndDisablesTrialFeatures() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("continuous-session-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }

        let session = snapshot(provider: .nut, id: "trial")
        let factory = SessionFactoryProbe()
        let widgetParent = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: widgetParent) }
        let widgetStore = try WidgetSnapshotStore(directoryURL: widgetParent.appendingPathComponent("widget"), mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: widgetStore, reload: {})
        let clockDate = date
        let model = MonitorAppModel(read: { [] }, clock: { clockDate }, observesWorkspace: false,
                                    isPreview: false, widgetPublisher: publisher,
                                    supervisedSessionReadFactory: { url in
            await factory.record(url)
            return { [MonitorReading(snapshot: session, presentationName: "UPS · Trial")] }
        })
        await model.startIfNeeded()
        model.supervisedSessionDirectoryURL = directory
        await model.connectSupervisedSession()
        await waitUntil { model.selected == session }
        await waitUntil { model.readState == .ready }

        let receivedURL = await factory.receivedURL()
        let widget = try await widgetStore.read(now: clockDate)
        XCTAssertEqual(receivedURL, directory)
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.canExport)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertEqual(model.energyEstimates, [])
        XCTAssertEqual(model.presentationNamesBySourceKey[UPSMonitorFormatters.sourceKey(for: session)], "UPS · Trial")
        XCTAssertEqual(widget?.snapshot, session)
        XCTAssertEqual(widget?.presentationName, "UPS · Trial")
        XCTAssertEqual(widget?.acquisition, .active)
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.alerts.isEnabled)
        await model.stop()
    }

    func testExpiredInjectedSessionBecomesStaleWithoutAppleFallback() async {
        let appleCalls = SessionCallCounter()
        let clockDate = date
        let model = MonitorAppModel(read: { await appleCalls.increment(); return [] },
                                    clock: { clockDate }, observesWorkspace: false, isPreview: false,
                                    supervisedSessionReadFactory: { _ in { throw SessionReadFailure.eof } })
        await model.startIfNeeded()
        model.supervisedSessionDirectoryURL = URL(fileURLWithPath: "/synthetic/session")
        await model.connectSupervisedSession()
        model.refresh()
        await waitUntil { model.readState == .failed }
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertNil(model.selected)
        let count = await appleCalls.value
        try? await Task.sleep(for: .milliseconds(30))
        let afterFailureCount = await appleCalls.currentValue()
        XCTAssertEqual(afterFailureCount, count)
        await model.stop()
    }

    func testSyntheticLaunchUsesOnlyFeedAndPublishesStaleAfterFeedFailure() async throws {
        let feedDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: feedDirectory) }
        let widgetParent = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: widgetParent) }
        let widgetStore = try WidgetSnapshotStore(directoryURL: widgetParent.appendingPathComponent("widget"), mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: widgetStore, reload: {})
        let sample = snapshot(provider: .nut, id: "synthetic-feed")
        let feed = SessionFeed(sample: sample)
        let appleCalls = SessionCallCounter()
        let fixedDate = date
        let model = MonitorAppModel(
            read: { await appleCalls.increment(); return [] }, clock: { fixedDate },
            observesWorkspace: true, isPreview: false, widgetFixtureMode: .disabled,
            widgetPublisher: publisher,
            launchArguments: ["ups-monitor", "--synthetic-session-feed", feedDirectory.path],
            supervisedSessionReadFactory: { _ in { try await feed.read() } }
        )

        await model.startIfNeeded()
        await waitUntil { model.readState == .ready }
        let activeWidget = try await widgetStore.read(now: fixedDate)
        XCTAssertTrue(model.isSyntheticMode)
        XCTAssertEqual(model.syntheticModeTitle, "Synthetic session")
        XCTAssertEqual(model.selected, sample)
        XCTAssertEqual(activeWidget?.presentationName, "Simulated UPS · Trial")
        XCTAssertEqual(activeWidget?.acquisition, .active)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertEqual(model.energyEstimates, [])
        XCTAssertFalse(model.alerts.isEnabled)
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        await feed.failReads()
        model.refresh()
        await waitUntil { model.readState == .failed }

        let staleWidget = try await widgetStore.read(now: fixedDate)
        XCTAssertEqual(model.selected, sample, "The prior sample remains visible as stale after EOF")
        XCTAssertFalse(model.acquisitionSucceeded)
        XCTAssertEqual(staleWidget?.snapshot, sample)
        XCTAssertEqual(staleWidget?.presentationName, "Simulated UPS · Trial")
        XCTAssertEqual(staleWidget?.acquisition, .readFailed)
        let appleCount = await appleCalls.currentValue()
        XCTAssertEqual(appleCount, 0, "Synthetic session launch must bypass Apple power-source reads")
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.alerts.isEnabled)
        XCTAssertEqual(model.energyEstimates, [])
        await model.stop()
    }

    func testInvalidSessionLaunchArgumentsNeverFallBackToApple() async {
        let appleCalls = SessionCallCounter()
        let model = MonitorAppModel(
            read: { await appleCalls.increment(); return [] }, observesWorkspace: false,
            isPreview: false, launchArguments: ["ups-monitor", "--supervised-session-feed"],
            supervisedSessionReadFactory: { _ in await appleCalls.increment(); return { [] } }
        )
        await model.startIfNeeded()
        let count = await appleCalls.currentValue()
        XCTAssertEqual(count, 0)
        XCTAssertEqual(model.readState, .failed)
        XCTAssertEqual(model.operationMessage, "Session feed arguments invalid; monitoring disabled")
        await model.stop()
    }

    func testSupervisedLaunchStartsOnlySelectedFeed() async throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let sample = snapshot(provider: .nut, id: "supervised-feed")
        let appleCalls = SessionCallCounter()
        let factoryCalls = SessionFactoryProbe()
        let fixedDate = date
        let model = MonitorAppModel(
            read: { await appleCalls.increment(); return [] }, clock: { fixedDate },
            observesWorkspace: true, isPreview: false, widgetFixtureMode: .disabled,
            launchArguments: ["ups-monitor", "--supervised-session-feed", directory.path],
            supervisedSessionReadFactory: { url in
                await factoryCalls.record(url)
                return { [MonitorReading(snapshot: sample)] }
            }
        )
        await model.startIfNeeded()
        await waitUntil { model.readState == .ready }
        let appleCount = await appleCalls.currentValue()
        let openedDirectory = await factoryCalls.receivedURL()
        XCTAssertEqual(appleCount, 0)
        XCTAssertEqual(openedDirectory?.standardizedFileURL, directory.standardizedFileURL)
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertEqual(model.presentationNamesBySourceKey[UPSMonitorFormatters.sourceKey(for: sample)],
                       "Smart-UPS C 1500 · Trial")
        XCTAssertFalse(model.recordsHistory)
        XCTAssertEqual(model.energyEstimates, [])
        await model.stop()
    }

    func testSupervisedStartupBootstrapsPrivateWidgetStoreBeforeFactoryWithNilPublisher() async throws {
        let sessionDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: sessionDirectory) }
        let widgetParent = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: widgetParent) }
        let widgetDirectory = widgetParent.appendingPathComponent("fixture-store", isDirectory: true)
        let bootstrapCalls = LockedWidgetBootstrapCounter()
        let bootstrap = WidgetSharingBootstrap(directoryURL: {
            bootstrapCalls.increment()
            return widgetDirectory
        }, reload: {})
        let sample = snapshot(provider: .nut, id: "supervised-widget-startup")
        let appleCalls = SessionCallCounter()
        let factoryCalls = SessionFactoryProbe()
        let fixedDate = date
        let model = MonitorAppModel(
            read: { await appleCalls.increment(); return [] }, clock: { fixedDate },
            observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
            widgetSharingBootstrap: bootstrap,
            launchArguments: ["ups-monitor", "--supervised-session-feed", sessionDirectory.path],
            supervisedSessionReadFactory: { url in
                bootstrapCalls.recordDirectoryVisibleBeforeFactory(FileManager.default.fileExists(atPath: widgetDirectory.path))
                await factoryCalls.record(url)
                return { [MonitorReading(snapshot: sample)] }
            }
        )

        // The production publisher begins nil; only directory resolution/reload are substituted.
        await model.startIfNeeded()
        await model.startIfNeeded()
        await waitUntil { model.readState == .ready }
        let store = try WidgetSnapshotStore(directoryURL: widgetDirectory, mode: .readOnly)
        let widget = try await waitForWidget(store, acquisition: .active, now: fixedDate)
        let openedDirectory = await factoryCalls.receivedURL()
        XCTAssertEqual(bootstrapCalls.currentValue, 1)
        XCTAssertEqual(bootstrapCalls.directoryVisibleBeforeFactory, true)
        XCTAssertEqual(openedDirectory?.standardizedFileURL, sessionDirectory.standardizedFileURL)
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertEqual(model.selected, sample)
        XCTAssertEqual(widget?.acquisition, .active)
        XCTAssertEqual(widget?.snapshot, sample)
        XCTAssertEqual(widget?.snapshot?.capturedAt, sample.capturedAt)
        XCTAssertEqual(widget?.presentationName, "Smart-UPS C 1500 · Trial")
        let appleCount = await appleCalls.currentValue()
        XCTAssertEqual(appleCount, 0)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertEqual(model.energyEstimates, [])
        XCTAssertFalse(model.alerts.isEnabled)
        await model.stop()
    }

    func testFailedSupervisedBootstrapReplacesOldWidgetSnapshotWithReadFailedNil() async throws {
        let sessionDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: sessionDirectory) }
        let widgetParent = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: widgetParent) }
        let widgetDirectory = widgetParent.appendingPathComponent("fixture-store", isDirectory: true)
        let store = try WidgetSnapshotStore(directoryURL: widgetDirectory, mode: .readWrite)
        let oldDate = date.addingTimeInterval(-30)
        let old = MonitorSnapshot(
            source: MonitorSource(provider: .apple, id: "old-widget-snapshot", sessionID: "test-session",
                                  identityStability: .sessionLocal),
            capturedAt: oldDate, status: MonitorStatus(quality: .unavailable), metrics: []
        )
        let oldValue = WidgetSnapshot(publishedAt: oldDate, acquisition: .active, maximumAge: 10, snapshot: old)
        try await store.write(oldValue, now: date)
        let appleCalls = SessionCallCounter()
        let bootstrap = WidgetSharingBootstrap(directoryURL: { widgetDirectory }, reload: {})
        let fixedDate = date
        let model = MonitorAppModel(
            read: { await appleCalls.increment(); return [] }, clock: { fixedDate },
            observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
            widgetSharingBootstrap: bootstrap,
            launchArguments: ["ups-monitor", "--supervised-session-feed", sessionDirectory.path],
            supervisedSessionReadFactory: { _ in throw SessionReadFailure.eof }
        )

        await model.startIfNeeded()
        await waitUntil { model.readState == .failed }
        let widget = try await waitForWidget(store, acquisition: .readFailed, now: fixedDate)
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertNil(model.selected)
        XCTAssertFalse(model.acquisitionSucceeded)
        XCTAssertEqual(model.operationMessage, "Supervised session unavailable")
        XCTAssertEqual(widget?.acquisition, .readFailed)
        XCTAssertNil(widget?.snapshot, "Bootstrap failure must replace a prior snapshot with no data")
        XCTAssertNil(widget?.presentationName)
        XCTAssertEqual(widget?.publishedAt, fixedDate)
        let appleCount = await appleCalls.currentValue()
        XCTAssertEqual(appleCount, 0)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertEqual(model.energyEstimates, [])
        XCTAssertFalse(model.alerts.isEnabled)
        await model.stop()
    }

    func testSupervisedSessionRemainsVisibleWhenWidgetSharingCannotConfigure() async throws {
        let sessionDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: sessionDirectory) }
        let sample = snapshot(provider: .nut, id: "supervised-without-widget")
        let appleCalls = SessionCallCounter()
        let bootstrap = WidgetSharingBootstrap(directoryURL: { throw WidgetGroupError.notConfigured }, reload: {})
        let fixedDate = date
        let model = MonitorAppModel(
            read: { await appleCalls.increment(); return [] }, clock: { fixedDate },
            observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
            widgetSharingBootstrap: bootstrap,
            launchArguments: ["ups-monitor", "--supervised-session-feed", sessionDirectory.path],
            supervisedSessionReadFactory: { _ in { [MonitorReading(snapshot: sample)] } }
        )

        await model.startIfNeeded()
        await waitUntil { model.readState == .ready }
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertEqual(model.selected, sample)
        XCTAssertEqual(model.widgetMessage, "Widget sharing not configured")
        let appleCount = await appleCalls.currentValue()
        XCTAssertEqual(appleCount, 0)
        await model.stop()
    }

    private func waitForWidget(_ store: WidgetSnapshotStore, acquisition: WidgetAcquisition,
                               now: Date, file: StaticString = #filePath, line: UInt = #line) async throws -> WidgetSnapshot? {
        for _ in 0..<300 {
            if let value = try await store.read(now: now), value.acquisition == acquisition { return value }
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Expected widget acquisition \(acquisition) was not published", file: file, line: line)
        return try await store.read(now: now)
    }

    private func waitUntil(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<300 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Expected supervised-session state was not reached", file: file, line: line)
    }

    private func snapshot(provider: MonitorProvider, id: String) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: provider, id: id, sessionID: "test-session",
                                              identityStability: provider == .apple ? .sessionLocal : .configured),
                        capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
    }

    private func makeDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("continuous-host-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        return url
    }
}

private actor SessionFactoryProbe {
    private(set) var url: URL?
    func record(_ value: URL) { url = value }
    func receivedURL() -> URL? { url }
}

private actor SessionCallCounter {
    private(set) var value = 0
    func increment() { value += 1 }
    func currentValue() -> Int { value }
}

private final class LockedWidgetBootstrapCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    private var directoryVisible = false
    var currentValue: Int { lock.lock(); defer { lock.unlock() }; return count }
    var directoryVisibleBeforeFactory: Bool { lock.lock(); defer { lock.unlock() }; return directoryVisible }
    func increment() { lock.lock(); count += 1; lock.unlock() }
    func recordDirectoryVisibleBeforeFactory(_ value: Bool) {
        lock.lock(); directoryVisible = value; lock.unlock()
    }
}

private actor SessionFeed {
    let sample: MonitorSnapshot
    var fails = false
    init(sample: MonitorSnapshot) { self.sample = sample }
    func read() throws -> [MonitorReading] {
        if fails { throw SessionReadFailure.eof }
        return [MonitorReading(snapshot: sample)]
    }
    func failReads() { fails = true }
}

private enum SessionReadFailure: Error { case eof }
