import Foundation
import CryptoKit
import XCTest
import UPSRuntime
@testable import UPSAppHost

final class ManagedSyntheticAppTests: XCTestCase {
    @MainActor
    func testFaultBeforeFirstFeedProjectsFailedInsteadOfLoading() async throws {
        let container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let root = container.appendingPathComponent("sessions", isDirectory: true)
        let runtime = container.appendingPathComponent("runtime", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: container) }
        for directory in [container, root, runtime] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
        }
        let data = Data("synthetic fixture, never executed".utf8)
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let python = runtime.appendingPathComponent("fake-python")
        try data.write(to: python)
        var pins: [String: String] = [:]
        for name in ManagedSyntheticRuntimeConfiguration.moduleNames {
            try data.write(to: runtime.appendingPathComponent(name)); pins[name] = digest
        }
        let manifest = runtime.appendingPathComponent("runtime.json")
        try JSONSerialization.data(withJSONObject: ["python_path": python.path, "python_sha256": digest,
                                                   "module_sha256": pins]).write(to: manifest)
        let controller = ManagedSyntheticSessionController(root: { root }, makeProcess: { ImmediateManagedFault() })
        let reads = ManagedAppleReadCounter()
        let model = MonitorAppModel(observesWorkspace: false, isPreview: false,
                                    widgetSharingBootstrap: WidgetSharingBootstrap(directoryURL: { throw ManagedSyntheticError.configuration }, reload: {}),
                                    launchArguments: ["app", "--managed-synthetic-session"],
                                    managedSyntheticController: controller,
                                    managedSyntheticConfiguration: .init(manifestURL: manifest),
                                    supervisedSessionReadFactory: { _ in await reads.increment(); return { [] } })
        await model.startIfNeeded()
        await model.startManagedSyntheticSession()
        XCTAssertEqual(model.readState, .failed)
        XCTAssertEqual(controller.state, .unresolved)
        let readCount = await reads.count
        XCTAssertEqual(readCount, 0)
        XCTAssertTrue(model.operationMessage?.contains("unresolved") == true)
        let mayQuit = await model.prepareToQuit()
        XCTAssertFalse(mayQuit)
    }

    @MainActor
    func testManagedModeNeverInvokesAppleReadBeforeStartOrAfterConfigurationFailure() async throws {
        let container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let root = container.appendingPathComponent("sessions", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: container) }
        for directory in [container, root] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
        }
        let controller = ManagedSyntheticSessionController(root: { root }, makeProcess: { ImmediateManagedFault() })
        let reads = ManagedAppleReadCounter()
        let model = MonitorAppModel(read: { await reads.increment(); return [] },
                                    observesWorkspace: false, isPreview: false,
                                    widgetSharingBootstrap: WidgetSharingBootstrap(directoryURL: { throw ManagedSyntheticError.configuration }, reload: {}),
                                    launchArguments: ["app", "--managed-synthetic-session"],
                                    managedSyntheticController: controller,
                                    managedSyntheticConfiguration: .init(manifestURL: root.appendingPathComponent("missing-runtime.json")))
        await model.startIfNeeded()
        XCTAssertTrue(model.isManagedSyntheticMode)
        XCTAssertTrue(model.isSyntheticMode)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertEqual(model.backend, .supervisedSession)
        await model.startManagedSyntheticSession()
        await model.useAppleBackend()
        await model.setHistoryRecording(true)
        await model.setAlertsEnabled(true)
        XCTAssertTrue(model.isSyntheticMode)
        XCTAssertTrue(model.isSupervisedSession)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertTrue(model.energyEstimates.isEmpty)
        XCTAssertFalse(model.canExport)
        XCTAssertFalse(model.canExportEnergy)
        let count = await reads.count
        XCTAssertEqual(count, 0)
        XCTAssertEqual(model.managedSyntheticSession.state, .unresolved)
        let mayQuit = await model.prepareToQuit()
        XCTAssertTrue(mayQuit, "Configuration failure before launch must allow Quit")
    }

    @MainActor
    func testManagedFlagCannotBeCombinedWithExternalFeedOrPreview() async {
        for arguments in [["app", "--managed-synthetic-session", "--synthetic-preview"],
                          ["app", "--managed-synthetic-session", "--synthetic-session-feed", "/synthetic-feed"]] {
            let model = MonitorAppModel(observesWorkspace: false, isPreview: false, launchArguments: arguments)
            await model.startIfNeeded()
            XCTAssertEqual(model.readState, .failed)
            XCTAssertFalse(model.managedSyntheticSession.attempted)
        }
    }
}

@MainActor private final class ImmediateManagedFault: ManagedSyntheticProcessHandle {
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        receive(.fault)
    }
    func requestStop() {}
}

private actor ManagedAppleReadCounter {
    private(set) var count = 0
    func increment() { count += 1 }
}
