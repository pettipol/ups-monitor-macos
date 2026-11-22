import Foundation
import XCTest
@testable import UPSRuntime
@testable import UPSAppHost

final class ManagedBundledOperationalAppTests: XCTestCase {
    @MainActor
    func testBundledFlagSelectsIdleUnqualifiedModeWithoutAutomaticStartOrProvider() async throws {
        let fixture = try BundledAppFixture(); defer { fixture.remove() }
        let fake = BundledAppProcess()
        let reads = BundledAppReadCounter()
        var factories = 0
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: {
            factories += 1; return fake
        })
        let model = makeBundledModel(fixture, controller: controller, reads: reads,
                                    arguments: ["app", "--managed-bundled-operational-session"])
        await model.startIfNeeded()
        XCTAssertTrue(model.isManagedOperationalMode)
        XCTAssertTrue(model.isManagedMode)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertFalse(model.isManagedNativeMode)
        XCTAssertFalse(model.isManagedSyntheticMode)
        XCTAssertFalse(model.isSyntheticMode)
        XCTAssertFalse(controller.attempted)
        XCTAssertEqual(factories, 0)
        XCTAssertEqual(fake.starts, 0)
        XCTAssertTrue(model.managedSessionTitle.contains("unqualified"))
        await model.useAppleBackend()
        await model.connectNUT()
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertTrue(model.energyEstimates.isEmpty)
        XCTAssertFalse(model.canExport)
        XCTAssertFalse(model.canExportEnergy)
        let count = await reads.count
        XCTAssertEqual(count, 0, "mode selection must not enumerate live providers")
        let quit = await model.prepareToQuit()
        XCTAssertTrue(quit)
        XCTAssertEqual(fake.starts, 0)
    }

    @MainActor
    func testUnadmittedBundledStartCreatesNoProcessAndDoesNotFallback() async throws {
        let fixture = try BundledAppFixture(); defer { fixture.remove() }
        let fake = BundledAppProcess()
        let reads = BundledAppReadCounter()
        var factories = 0
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: {
            factories += 1; return fake
        })
        let model = makeBundledModel(fixture, controller: controller, reads: reads,
                                    arguments: ["app", "--managed-bundled-operational-session"])
        await model.startIfNeeded()
        await model.startManagedSession()
        XCTAssertEqual(model.readState, .failed)
        XCTAssertEqual(factories, 0)
        XCTAssertEqual(fake.starts, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.root.appendingPathComponent("active-owner.json").path))
        let count = await reads.count
        XCTAssertEqual(count, 0, "rejection must not switch to Apple/NUT or another managed runtime")
        let quit = await model.prepareToQuit()
        XCTAssertTrue(quit)
        XCTAssertEqual(fake.starts, 0)
    }

    @MainActor
    func testBundledFlagRejectsRepeatedMixedAndUnknownAccompanyingArguments() async throws {
        let fixture = try BundledAppFixture(); defer { fixture.remove() }
        for suffix in [["--managed-bundled-operational-session"], ["--managed-operational-session"],
                       ["--managed-native-session"], ["--synthetic-preview"], ["--unknown"]] {
            let fake = BundledAppProcess()
            let reads = BundledAppReadCounter()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            let arguments = ["app", "--managed-bundled-operational-session"] + suffix
            let model = makeBundledModel(fixture, controller: controller, reads: reads, arguments: arguments)
            await model.startIfNeeded()
            await model.startManagedSession()
            XCTAssertEqual(model.readState, .failed, arguments.joined(separator: " "))
            XCTAssertFalse(controller.attempted)
            XCTAssertEqual(fake.starts, 0)
            let count = await reads.count
            XCTAssertEqual(count, 0)
        }
    }

    @MainActor
    func testLegacyOperationalFlagStillSelectsItsOriginalIdleProfile() async throws {
        let fixture = try BundledAppFixture(); defer { fixture.remove() }
        let fake = BundledAppProcess()
        let reads = BundledAppReadCounter()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let model = makeBundledModel(fixture, controller: controller, reads: reads,
                                    arguments: ["app", "--managed-operational-session"])
        await model.startIfNeeded()
        XCTAssertTrue(model.isManagedOperationalMode)
        XCTAssertFalse(controller.attempted)
        XCTAssertEqual(fake.starts, 0)
        XCTAssertFalse(model.recordsHistory)
        let count = await reads.count
        XCTAssertEqual(count, 0)
    }
}

@MainActor
private func makeBundledModel(_ fixture: BundledAppFixture, controller: ManagedSyntheticSessionController,
                              reads: BundledAppReadCounter, arguments: [String]) -> MonitorAppModel {
    MonitorAppModel(read: { await reads.increment(); return [] },
        observesWorkspace: false, isPreview: false, widgetFixtureMode: .disabled,
        widgetSharingBootstrap: .init(directoryURL: { throw ManagedSyntheticError.configuration }, reload: {}),
        launchArguments: arguments, managedSyntheticController: controller,
        operationalSessionReadFactory: { _ in await reads.increment(); return { [] } },
        nutReadFactory: { _ in await reads.increment(); return { [] } },
        supervisedSessionReadFactory: { _ in await reads.increment(); return { [] } })
}

@MainActor private final class BundledAppProcess: ManagedSyntheticProcessHandle {
    var starts = 0
    var stops = 0
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        starts += 1
    }
    func requestStop() { stops += 1 }
}

private actor BundledAppReadCounter {
    private(set) var count = 0
    func increment() { count += 1 }
}

private struct BundledAppFixture {
    let container: URL
    let root: URL
    init() throws {
        container = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        root = container.appendingPathComponent("sessions")
        for directory in [container, root] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
        }
    }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
