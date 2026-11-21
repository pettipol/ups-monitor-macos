import Foundation
import XCTest
import UPSModel
import UPSMonitorUI
@testable import UPSRuntime
import UPSWidgetBridge
import UPSWidgetData
@testable import UPSAppHost

final class ManagedFrozenOperationalAppTests: XCTestCase {
    @MainActor
    func testFrozenModeRequiresExplicitStartAndNeverEnumeratesProviders() async throws {
        let reads = FrozenAppReadCounter()
        var factories = 0
        let controller = ManagedSyntheticSessionController(makeProcess: {
            factories += 1
            return FrozenAppProcess()
        })
        let model = makeModel(arguments: ["app", "--managed-frozen-operational-session"],
                              controller: controller, reads: reads)
        await model.startIfNeeded()
        XCTAssertTrue(model.isManagedOperationalMode)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertFalse(model.isSyntheticMode)
        XCTAssertEqual(model.managedSessionTitle, "Operational session · unqualified · macOS 27+ arm64")
        XCTAssertEqual(model.managedSessionStartTitle, "Start operational session")
        XCTAssertEqual(model.syntheticModeTitle, "Operational session · unqualified · macOS 27+ arm64")
        XCTAssertFalse(controller.attempted)
        XCTAssertEqual(factories, 0)
        await model.useAppleBackend()
        await model.connectNUT()
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertTrue(model.energyEstimates.isEmpty)
        XCTAssertFalse(model.canExport)
        let count = await reads.count
        XCTAssertEqual(count, 0)
        let quit = await model.prepareToQuit()
        XCTAssertTrue(quit)
        XCTAssertEqual(factories, 0)
    }

    @MainActor
    func testWidgetFixtureFrozenSessionUsesOperationalReaderAndPublishesSyntheticPresentation() async throws {
        let parent = FileManager.default.temporaryDirectory
            .resolvingSymlinksInPath().appendingPathComponent("frozen-widget-fixture-" + UUID().uuidString,
                                                              isDirectory: true)
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: parent) }

        let widgetDirectory = parent.appendingPathComponent("widget-fixture", isDirectory: true)
        let widgetStore = try WidgetSnapshotStore(directoryURL: widgetDirectory, mode: .readWrite)
        let publisher = WidgetSnapshotPublisher(store: widgetStore, reload: {})
        let sessionRoot = parent.appendingPathComponent("sessions", isDirectory: true)
        try FileManager.default.createDirectory(at: sessionRoot, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])

        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let first = frozenSnapshot(at: now, charge: 41)
        let second = frozenSnapshot(at: now, charge: 42)
        let feed = FrozenOperationalFeed(readings: [first, second])
        let counters = FrozenFixtureReaderCounters()
        let process = FrozenFixtureOperationalProcess()
        let controller = ManagedSyntheticSessionController(root: { sessionRoot }, makeProcess: { process })
        let model = MonitorAppModel(
            read: { await counters.appleRead(); return [] }, clock: { now },
            observesWorkspace: false, isPreview: false, widgetFixtureMode: .enabled,
            widgetPublisher: publisher,
            launchArguments: ["app", "--managed-frozen-operational-session"],
            managedSyntheticController: controller,
            operationalSessionReadFactory: { directory in
                await counters.operationalFactory(directory)
                return { await feed.read() }
            },
            operationalStart: { target in
                try target.start(profile: .operational) { _, launchID in
                    ManagedSyntheticLaunch(executableURL: parent.appendingPathComponent("never-executed"),
                                           arguments: ["inert-test-fixture", launchID])
                }
            },
            nutReadFactory: { _ in await counters.nutRead(); return { [] } }
        )

        XCTAssertTrue(model.isWidgetFixture)
        XCTAssertTrue(model.isManagedOperationalMode)
        XCTAssertEqual(model.managedSessionTitle, "Synthetic frozen operational candidate · Unqualified")
        XCTAssertEqual(model.managedSessionStartTitle, "Start synthetic frozen operational session")
        XCTAssertEqual(model.syntheticModeTitle, "Synthetic frozen operational candidate · Unqualified")
        await model.startIfNeeded()
        XCTAssertFalse(controller.attempted, "The managed mode must remain explicit-start even with widget fixtures enabled")
        let readsBeforeStart = await counters.snapshot()
        XCTAssertEqual(readsBeforeStart.apple, 0)
        XCTAssertEqual(readsBeforeStart.nut, 0)

        await model.startManagedSession()
        await waitForWidget(widgetStore, charge: 41, now: now)
        await waitForWidget(widgetStore, charge: 42, now: now)

        let factoryState = await counters.snapshot()
        XCTAssertEqual(factoryState.apple, 0, "The Apple reader must not be selected in frozen operational mode")
        XCTAssertEqual(factoryState.nut, 0, "The built-in NUT reader must not be selected in frozen operational mode")
        XCTAssertEqual(factoryState.operationalFactory, 1)
        XCTAssertEqual(factoryState.directory?.deletingLastPathComponent().deletingLastPathComponent(), sessionRoot)
        XCTAssertEqual(model.selected, second)
        XCTAssertEqual(model.presentationNamesBySourceKey[UPSMonitorFormatters.sourceKey(for: second)],
                       "Synthetic frozen operational candidate · Unqualified")

        let beforeStop = try await widgetStore.read(now: now)
        XCTAssertEqual(beforeStop?.acquisition, .active)
        XCTAssertEqual(beforeStop?.snapshot, second)
        XCTAssertEqual(beforeStop?.presentationName, "Synthetic frozen operational candidate · Unqualified")
        let mayQuit = await model.prepareToQuit()
        XCTAssertTrue(mayQuit)
        let afterStop = try await widgetStore.read(now: now)
        XCTAssertEqual(afterStop?.acquisition, .stopped)
        XCTAssertEqual(afterStop?.snapshot, second, "Stop must publish a stale state while retaining the last fixture capture")
        XCTAssertEqual(afterStop?.isStale(at: now), true)
        XCTAssertEqual(afterStop?.presentationName, "Synthetic frozen operational candidate · Unqualified")
        XCTAssertEqual(controller.state, .stopped)
        XCTAssertEqual(process.stopRequests, 1)
    }

    @MainActor
    func testPublicNilPinFailsStartWithoutProcessOrFallback() async throws {
        let reads = FrozenAppReadCounter()
        var factories = 0
        let controller = ManagedSyntheticSessionController(makeProcess: {
            factories += 1
            return FrozenAppProcess()
        })
        let model = makeModel(arguments: ["app", "--managed-frozen-operational-session"],
                              controller: controller, reads: reads)
        await model.startIfNeeded()
        await model.startManagedSession()
        XCTAssertEqual(model.readState, .failed)
        XCTAssertEqual(factories, 0)
        XCTAssertFalse(controller.launchInvoked)
        let count = await reads.count
        XCTAssertEqual(count, 0)
        let quit = await model.prepareToQuit()
        XCTAssertTrue(quit)
    }

    @MainActor
    func testFrozenFlagRejectsMixedRepeatedAndUnknownArguments() async {
        for suffix in [["--managed-frozen-operational-session"], ["--managed-bundled-operational-session"],
                       ["--managed-operational-session"], ["--managed-native-session"],
                       ["--synthetic-preview"], ["--unknown"]] {
            let reads = FrozenAppReadCounter()
            var factories = 0
            let controller = ManagedSyntheticSessionController(makeProcess: {
                factories += 1
                return FrozenAppProcess()
            })
            let model = makeModel(arguments: ["app", "--managed-frozen-operational-session"] + suffix,
                                  controller: controller, reads: reads)
            await model.startIfNeeded()
            await model.startManagedSession()
            XCTAssertEqual(model.readState, .failed)
            XCTAssertFalse(controller.attempted)
            XCTAssertEqual(factories, 0)
            let count = await reads.count
            XCTAssertEqual(count, 0)
        }
    }

    @MainActor
    private func makeModel(arguments: [String], controller: ManagedSyntheticSessionController,
                           reads: FrozenAppReadCounter) -> MonitorAppModel {
        MonitorAppModel(read: { await reads.increment(); return [] },
            observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
            widgetSharingBootstrap: .init(directoryURL: { throw ManagedSyntheticError.configuration }, reload: {}),
            launchArguments: arguments, managedSyntheticController: controller,
            operationalSessionReadFactory: { _ in await reads.increment(); return { [] } },
            nutReadFactory: { _ in await reads.increment(); return { [] } },
            supervisedSessionReadFactory: { _ in await reads.increment(); return { [] } })
    }
}

@MainActor private final class FrozenAppProcess: ManagedSyntheticProcessHandle {
    func start(_ launch: ManagedSyntheticLaunch,
               receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        XCTFail("unadmitted frozen runtime must not launch")
    }
    func requestStop() { XCTFail("unadmitted frozen runtime has no process to stop") }
}

private actor FrozenAppReadCounter {
    private(set) var count = 0
    func increment() { count += 1 }
}

@MainActor
private func waitForWidget(_ store: WidgetSnapshotStore, charge: Double, now: Date,
                           file: StaticString = #filePath, line: UInt = #line) async {
    for _ in 0..<900 {
        if let value = try? await store.read(now: now),
           value.acquisition == .active,
           value.snapshot?.metrics.first(where: { $0.id == .batteryCharge })?.value == charge { return }
        try? await Task.sleep(for: .milliseconds(10))
    }
    XCTFail("Expected frozen operational widget charge \(charge)", file: file, line: line)
}

private func frozenSnapshot(at date: Date, charge: Double) -> MonitorSnapshot {
    let source = MonitorSource(provider: .nut, id: "frozen-operational-fixture", sessionID: "fixture-session",
                               identityStability: .configured)
    let metric = MonitorMetric(id: .batteryCharge, value: charge, unit: .percent,
                               quality: .available, provenance: .reported)
    return MonitorSnapshot(source: source, capturedAt: date,
                           status: MonitorStatus(lineState: .onLine, quality: .available), metrics: [metric])
}

private actor FrozenOperationalFeed {
    private let readings: [MonitorSnapshot]
    private var index = 0
    init(readings: [MonitorSnapshot]) { self.readings = readings }
    func read() -> [MonitorReading] {
        let snapshot = readings[min(index, readings.count - 1)]
        index += 1
        return [MonitorReading(snapshot: snapshot)]
    }
}

private actor FrozenFixtureReaderCounters {
    private(set) var apple = 0
    private(set) var nut = 0
    private(set) var operationalFactory = 0
    private(set) var directory: URL?
    func appleRead() { apple += 1 }
    func nutRead() { nut += 1 }
    func operationalFactory(_ value: URL) { operationalFactory += 1; directory = value }
    func snapshot() -> (apple: Int, nut: Int, operationalFactory: Int, directory: URL?) {
        (apple, nut, operationalFactory, directory)
    }
}

@MainActor
private final class FrozenFixtureOperationalProcess: ManagedSyntheticProcessHandle {
    private var receive: (@MainActor (ManagedSyntheticProcessEvent) -> Void)?
    private var launchID = ""
    private(set) var stopRequests = 0

    func start(_ launch: ManagedSyntheticLaunch,
               receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        launchID = launch.arguments.last ?? ""
        self.receive = receive
    }

    func requestStop() {
        stopRequests += 1
        let runner: [String: Any] = [
            "trigger": "cancelled", "returncode": 0, "stdout_bytes": 0, "stderr_bytes": 0,
            "stdout_sha256": String(repeating: "a", count: 64), "stderr_sha256": String(repeating: "b", count: 64),
            "leader_reaped": true, "group_absent": true, "stdout_eof": true, "stderr_eof": true,
            "consumer_quiesced": true,
        ]
        let capture: [String: Any] = [
            "schema_version": 2, "protocol": "ups-monitor.continuous.v2", "state": "stopped",
            "terminal_reason": "cancelled", "first_error": NSNull(), "publication_error": NSNull(),
            "source_id": "apcmicrolink-hidapi-operational", "session_id": String(repeating: "a", count: 32),
            "started_at_unix_ms": 1_000, "published_at_unix_ms": 2_000, "sample_count": 2,
            "end_reason": "cancelled", "runner_result": runner, "consumer_quiesced": true,
            "publisher_quiesced": true, "publisher_closed": true, "terminal_published": true,
            "ownership_resolved": true,
        ]
        let adapter: [String: Any] = ["capture_result": capture, "control_reason": "stop",
                                      "adapter_error": NSNull(), "watcher_quiesced": true,
                                      "ownership_resolved": true]
        let receipt: [String: Any] = ["protocol": "ups-monitor.managed-operational.v2", "schema_version": 2,
                                      "launch_id": launchID, "adapter": adapter]
        let data = (try? JSONSerialization.data(withJSONObject: receipt)).map { $0 + Data([10]) } ?? Data()
        receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
    }
}
