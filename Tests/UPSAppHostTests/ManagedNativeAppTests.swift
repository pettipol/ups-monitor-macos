import Foundation
import XCTest
import UPSModel
@testable import UPSRuntime
@testable import UPSAppHost

final class ManagedNativeAppTests: XCTestCase {
    @MainActor
    func testNativeModeIsExplicitUnqualifiedAndNeverAutoStartsOrFallsBackToApple() async throws {
        let fixture = try NativeAppFixture(); defer { fixture.remove() }
        let fake = NativeAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let reads = NativeAppReadCounter()
        let model = MonitorAppModel(read: { await reads.increment(); return [] }, observesWorkspace: false, isPreview: false,
                                    widgetFixtureMode: .disabled,
                                    widgetSharingBootstrap: fixture.noWidget, alerts: UPSAlertController(delivery: NativeNoAlertDelivery()),
                                    launchArguments: ["app", "--managed-native-session"],
                                    managedSyntheticController: controller,
                                    managedNativeConfiguration: .init(manifestURL: fixture.root.appendingPathComponent("missing.json")))
        await model.startIfNeeded()
        XCTAssertTrue(model.isManagedNativeMode)
        XCTAssertTrue(model.isManagedMode)
        XCTAssertFalse(model.isSyntheticMode)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertEqual(model.readState, .stopped)
        XCTAssertTrue(model.managedSessionMessage.contains("Native 120 s · unqualified"))
        XCTAssertFalse(controller.attempted)
        XCTAssertEqual(fake.starts, 0)
        await model.startManagedSession()
        await model.useAppleBackend()
        await model.connectNUT()
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertTrue(model.energyEstimates.isEmpty)
        XCTAssertFalse(model.canExport)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertEqual(fake.starts, 0)
        let count = await reads.count
        XCTAssertEqual(count, 0)
        let mayQuit = await model.prepareToQuit()
        XCTAssertTrue(mayQuit, "A validation failure before launch does not create process ownership")
    }

    @MainActor
    func testNativeFlagRejectsEveryCombinedLaunchModeBeforeAnyStart() async throws {
        let fixture = try NativeAppFixture(); defer { fixture.remove() }
        for extra in [["--managed-synthetic-session"], ["--synthetic-preview"], ["--supervised-session-feed", "/unused"],
                      ["--synthetic-session-feed", "/unused"], ["--managed-native-session"], ["--unknown"]] {
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { NativeAppFakeProcess() })
            let reads = NativeAppReadCounter()
            let model = MonitorAppModel(read: { await reads.increment(); return [] }, observesWorkspace: false, isPreview: false,
                                        widgetFixtureMode: .disabled, widgetSharingBootstrap: fixture.noWidget, alerts: UPSAlertController(delivery: NativeNoAlertDelivery()),
                                        launchArguments: ["app", "--managed-native-session"] + extra,
                                        managedSyntheticController: controller)
            await model.startIfNeeded()
            XCTAssertEqual(model.readState, .failed, extra.joined(separator: " "))
            XCTAssertFalse(controller.attempted)
            let count = await reads.count
            XCTAssertEqual(count, 0)
        }
    }

    @MainActor
    func testNativeQuitUsesSharedOwnedStopAndMatchingCleanup() async throws {
        let fixture = try NativeAppFixture(); defer { fixture.remove() }
        let fake = NativeAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(profile: .native) { _, launchID in fixture.launch(launchID) }
        fake.completeOnStop = true
        let model = MonitorAppModel(observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
                                    widgetSharingBootstrap: fixture.noWidget, alerts: UPSAlertController(delivery: NativeNoAlertDelivery()),
                                    launchArguments: ["app", "--managed-native-session"], managedSyntheticController: controller)
        await model.startIfNeeded()
        let mayQuit = await model.prepareToQuit()
        XCTAssertTrue(mayQuit)
        XCTAssertGreaterThan(fake.stopRequests, 0)
        XCTAssertEqual(fake.starts, 1)
        XCTAssertEqual(controller.state, .stopped)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testWrongProfileReceiptCancelsNativeQuitAndRetainsOwnership() async throws {
        let fixture = try NativeAppFixture(); defer { fixture.remove() }
        let fake = NativeAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(profile: .native) { _, launchID in fixture.launch(launchID) }
        fake.completeOnStop = true; fake.wrongProtocol = true
        let model = MonitorAppModel(observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
                                    widgetSharingBootstrap: fixture.noWidget, alerts: UPSAlertController(delivery: NativeNoAlertDelivery()),
                                    launchArguments: ["app", "--managed-native-session"], managedSyntheticController: controller)
        await model.startIfNeeded()
        let mayQuit = await model.prepareToQuit()
        XCTAssertFalse(mayQuit)
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
    }
}

@MainActor private final class NativeAppFakeProcess: ManagedSyntheticProcessHandle {
    var receive: (@MainActor (ManagedSyntheticProcessEvent) -> Void)?
    var launchID = "", starts = 0, stopRequests = 0
    var completeOnStop = false, wrongProtocol = false
    private var finished = false
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        starts += 1; launchID = launch.arguments.last!; self.receive = receive
    }
    func requestStop() {
        stopRequests += 1
        guard completeOnStop, !finished else { return }
        finished = true
        let capture: [String: Any] = ["state": "failed", "terminal_reason": "cancelled", "source_id": "apcmicrolink-hidapi-continuous",
            "session_id": String(repeating: "a", count: 32), "started_at_unix_ms": 1, "published_at_unix_ms": 2,
            "sample_count": 0, "end_reason": NSNull(), "returncode": 0, "runner_status": "cancelled",
            "stdout_bytes": 0, "stderr_bytes": 0, "publication_error": NSNull(), "tailer_quiesced": true]
        let receipt = try! JSONSerialization.data(withJSONObject: ["protocol": wrongProtocol ? "ups-monitor.managed-synthetic.v1" : "ups-monitor.managed-native.v1",
            "schema_version": 1, "launch_id": launchID, "adapter": ["capture_result": capture, "control_reason": "app_stop",
                "adapter_error": NSNull(), "watcher_quiesced": true, "ownership_resolved": true]]) + Data([10])
        receive?(.finished(.init(returnCode: 0, receipt: receipt, outputWithinBounds: true)))
    }
}

private actor NativeAppReadCounter {
    private(set) var count = 0
    func increment() { count += 1 }
}

private struct NativeAppFixture {
    let container: URL, root: URL
    var marker: URL { root.appendingPathComponent("active-owner.json") }
    var noWidget: WidgetSharingBootstrap { .init(directoryURL: { throw ManagedSyntheticError.configuration }, reload: {}) }
    init() throws {
        container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        root = container.appendingPathComponent("sessions", isDirectory: true)
        for directory in [container, root] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        }
    }
    func launch(_ launchID: String) -> ManagedSyntheticLaunch { .init(executableURL: root.appendingPathComponent("never-executed"), arguments: [launchID]) }
    func remove() { try? FileManager.default.removeItem(at: container) }
}

@MainActor private final class NativeNoAlertDelivery: UPSAlertDelivery {
    func requestAuthorization() async throws -> Bool { false }
    func isAuthorized() async -> Bool { false }
    func submit(_ event: UPSAlertEvent) async throws {}
    func clear() async {}
}
