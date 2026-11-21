import Foundation
import XCTest
@testable import UPSRuntime
@testable import UPSAppHost

final class ManagedOperationalAppTests: XCTestCase {
    @MainActor
    func testOperationalFlagIsExplicitUnqualifiedAndDoesNotAutoStartOrFallback() async throws {
        let fixture = try AppFixture(); defer { fixture.remove() }
        let fake = OperationalAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let reads = AppReadCounter()
        let model = makeModel(fixture: fixture, controller: controller, fake: fake,
                              arguments: ["app", "--managed-operational-session"],
                              operationalRead: { _ in await reads.increment(); return { [] } })

        await model.startIfNeeded()
        XCTAssertTrue(model.isManagedOperationalMode)
        XCTAssertTrue(model.isManagedMode)
        XCTAssertFalse(model.isSyntheticMode)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertEqual(model.backend, .supervisedSession)
        XCTAssertFalse(controller.attempted)
        XCTAssertEqual(fake.starts, 0)
        XCTAssertTrue(model.managedSessionTitle.contains("unqualified"))
        XCTAssertTrue(model.managedSessionTitle.contains("macOS 27+ arm64"))
        await model.useAppleBackend()
        await model.connectNUT()
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertTrue(model.energyEstimates.isEmpty)
        XCTAssertFalse(model.canExport)
        XCTAssertFalse(model.canExportEnergy)
        let readCount = await reads.count
        XCTAssertEqual(readCount, 0)
        let quit = await model.prepareToQuit()
        XCTAssertTrue(quit)
        XCTAssertEqual(fake.starts, 0)
        XCTAssertTrue(model.energyEstimates.isEmpty,
                      "Quit must not repopulate energy estimates for a supervised operational session")
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.canExportEnergy)
    }

    @MainActor
    func testFlagRejectsCombinedOrRepeatedArgumentsBeforeAnyStart() async throws {
        let fixture = try AppFixture(); defer { fixture.remove() }
        for arguments in [["app", "--managed-operational-session", "--synthetic-preview"],
                          ["app", "--managed-operational-session", "--managed-operational-session"],
                          ["app", "--managed-operational-session", "--managed-native-session"],
                          ["app", "--managed-operational-session", "--unknown"]] {
            let fake = OperationalAppFakeProcess()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            let model = makeModel(fixture: fixture, controller: controller, fake: fake, arguments: arguments)
            await model.startIfNeeded()
            XCTAssertEqual(model.readState, .failed, arguments.joined(separator: " "))
            XCTAssertFalse(controller.attempted)
            XCTAssertEqual(fake.starts, 0)
        }
    }

    @MainActor
    func testOperationalStartupMayCrossTenSecondsAndQuitUsesOwnedStop() async throws {
        let fixture = try AppFixture(); defer { fixture.remove() }
        let timeline = StartupTimeline()
        let fake = OperationalAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let reads = AppReadCounter()
        let model = makeModel(fixture: fixture, controller: controller, fake: fake,
                              arguments: ["app", "--managed-operational-session"],
                              clock: { timeline.now },
                              sleep: { _ in timeline.advance(by: 0.05) },
                              operationalRead: { _ in
                                  await reads.increment()
                                  guard timeline.now >= 11 else { throw ManagedSyntheticError.configuration }
                                  return { [] }
                              })

        await model.startManagedSession()
        XCTAssertGreaterThanOrEqual(timeline.now, 11)
        XCTAssertEqual(controller.state, .active)
        XCTAssertEqual(fake.starts, 1)
        XCTAssertTrue(model.operationMessage?.contains("history, energy estimates and alerts are disabled") == true)
        let quit = await model.prepareToQuit()
        XCTAssertTrue(quit)
        XCTAssertTrue(model.energyEstimates.isEmpty,
                      "Quit must leave energy estimates disabled for a supervised operational session")
        XCTAssertFalse(model.recordsHistory)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertGreaterThan(fake.stopRequests, 0)
        XCTAssertEqual(controller.state, .stopped)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testStopDuringStartupAfterTenSecondsSettlesAndDoesNotKeepPolling() async throws {
        let fixture = try AppFixture(); defer { fixture.remove() }
        let timeline = StartupTimeline()
        let fake = OperationalAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let reads = AppReadCounter()
        let model = makeModel(fixture: fixture, controller: controller, fake: fake,
                              arguments: ["app", "--managed-operational-session"],
                              clock: { timeline.now },
                              sleep: { _ in
                                  timeline.advance(by: 0.05)
                                  if timeline.now >= 10.5 { await timeline.stopOnce() }
                              },
                              operationalRead: { _ in await reads.increment(); throw ManagedSyntheticError.configuration })
        timeline.installStop { await model.stopManagedSession() }

        await model.startManagedSession()
        XCTAssertGreaterThanOrEqual(timeline.now, 10.5)
        XCTAssertLessThan(timeline.now, 40)
        XCTAssertGreaterThan(fake.stopRequests, 0)
        XCTAssertEqual(controller.state, .stopped)
        let callsAfterStop = await reads.count
        XCTAssertLessThan(callsAfterStop, 250)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testResolvedFailedOperationalCaptureRemainsFailedInAppProjection() async throws {
        let fixture = try AppFixture(); defer { fixture.remove() }
        let fake = OperationalAppFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let model = makeModel(fixture: fixture, controller: controller, fake: fake,
                              arguments: ["app", "--managed-operational-session"],
                              operationalRead: { _ in { [] } })
        await model.startManagedSession()
        XCTAssertEqual(controller.state, .active)
        fake.failOnStop = true

        let mayQuit = await model.prepareToQuit()
        XCTAssertTrue(mayQuit, "Settled cleanup permits Quit while the captured result remains failed")
        XCTAssertEqual(controller.state, .failed)
        XCTAssertEqual(model.readState, .failed)
        XCTAssertTrue(model.operationMessage?.contains("capture failed") == true)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }
}

@MainActor
private func makeModel(fixture: AppFixture, controller: ManagedSyntheticSessionController,
                       fake: OperationalAppFakeProcess, arguments: [String],
                       clock: @escaping @Sendable () -> TimeInterval = { 0 },
                       sleep: @escaping @Sendable (Duration) async throws -> Void = { _ in },
                       operationalRead: @escaping @Sendable (URL) async throws -> MonitorCoordinator.ReadWithPresentation = { _ in { [] } }) -> MonitorAppModel {
    MonitorAppModel(observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
                    widgetSharingBootstrap: fixture.noWidget,
                    launchArguments: arguments,
                    managedSyntheticController: controller,
                    operationalSessionReadFactory: operationalRead,
                    startupClock: clock, startupSleep: sleep,
                    operationalStart: { target in
                        try target.start(profile: .operational) { _, launchID in
                            ManagedSyntheticLaunch(executableURL: fixture.root.appendingPathComponent("never-executed"),
                                                   arguments: ["inert-fixture", launchID])
                        }
                    })
}

@MainActor
private final class OperationalAppFakeProcess: ManagedSyntheticProcessHandle {
    var receive: (@MainActor (ManagedSyntheticProcessEvent) -> Void)?
    var launchID = ""
    var starts = 0
    var stopRequests = 0
    var failOnStop = false
    private var finished = false

    func start(_ launch: ManagedSyntheticLaunch,
               receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        starts += 1
        launchID = launch.arguments.last ?? ""
        self.receive = receive
    }

    func requestStop() {
        stopRequests += 1
        guard !finished else { return }
        finished = true
        let runner: [String: Any] = [
            "trigger": "cancelled", "returncode": 0, "stdout_bytes": 0, "stderr_bytes": 0,
            "stdout_sha256": String(repeating: "a", count: 64), "stderr_sha256": String(repeating: "b", count: 64),
            "leader_reaped": true, "group_absent": true, "stdout_eof": true, "stderr_eof": true,
            "consumer_quiesced": true,
        ]
        let state = failOnStop ? "failed" : "stopped"
        let capture: [String: Any] = [
            "schema_version": 2, "protocol": "ups-monitor.continuous.v2", "state": state,
            "terminal_reason": failOnStop ? "io_error" : "cancelled",
            "first_error": failOnStop ? "terminal_publication_failed" as Any : NSNull(),
            "publication_error": failOnStop ? "terminal_publication_failed" as Any : NSNull(),
            "source_id": "apcmicrolink-hidapi-operational", "session_id": String(repeating: "a", count: 32),
            "started_at_unix_ms": 1_000,
            "published_at_unix_ms": failOnStop ? NSNull() as Any : 2_000 as Any, "sample_count": 1,
            "end_reason": failOnStop ? NSNull() as Any : "cancelled" as Any,
            "runner_result": runner, "consumer_quiesced": true,
            "publisher_quiesced": true, "publisher_closed": true, "terminal_published": !failOnStop,
            "ownership_resolved": true,
        ]
        let adapter: [String: Any] = ["capture_result": capture, "control_reason": "stop",
                                      "adapter_error": NSNull(), "watcher_quiesced": true,
                                      "ownership_resolved": true]
        let envelope: [String: Any] = ["protocol": "ups-monitor.managed-operational.v2", "schema_version": 2,
                                       "launch_id": launchID, "adapter": adapter]
        let data = (try? JSONSerialization.data(withJSONObject: envelope)).map { $0 + Data([10]) } ?? Data()
        receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
    }
}

private actor AppReadCounter {
    private(set) var count = 0
    func increment() { count += 1 }
}

private final class StartupTimeline: @unchecked Sendable {
    private let lock = NSLock()
    private var value: TimeInterval = 0
    private var didStop = false
    private var stop: (@MainActor () async -> Void)?
    var now: TimeInterval { lock.lock(); defer { lock.unlock() }; return value }
    func advance(by amount: TimeInterval) { lock.lock(); value += amount; lock.unlock() }
    func installStop(_ closure: @escaping @MainActor () async -> Void) { lock.lock(); stop = closure; lock.unlock() }
    @MainActor func stopOnce() async {
        await takeStopIfNeeded()?()
    }

    private func takeStopIfNeeded() -> (@MainActor () async -> Void)? {
        lock.lock(); defer { lock.unlock() }
        guard !didStop else { return nil }
        didStop = true
        return stop
    }
}

private struct AppFixture {
    let container: URL
    let root: URL
    var marker: URL { root.appendingPathComponent("active-owner.json") }
    var noWidget: WidgetSharingBootstrap {
        .init(directoryURL: { throw ManagedSyntheticError.configuration }, reload: {})
    }
    init() throws {
        container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        root = container.appendingPathComponent("sessions", isDirectory: true)
        for directory in [container, root] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
        }
    }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
