import CryptoKit
import Darwin
import Foundation
import XCTest
@testable import UPSRuntime

final class ManagedSyntheticSessionTests: XCTestCase {
    @MainActor
    func testTransportMarksAllSixPipeEndpointsCloseOnExec() throws {
        let pipes = [Pipe(), Pipe(), Pipe()]
        let handles = pipes.flatMap { [$0.fileHandleForReading, $0.fileHandleForWriting] }
        defer { for handle in handles { try? handle.close() } }
        for handle in handles { XCTAssertEqual(fcntl(handle.fileDescriptor, F_SETFD, 0), 0) }
        try ManagedSyntheticProcess.setCloseOnExec(handles)
        for handle in handles {
            XCTAssertNotEqual(fcntl(handle.fileDescriptor, F_GETFD) & FD_CLOEXEC, 0)
        }
    }

    @MainActor
    func testInvalidConfigurationNeverInvokesLaunchAndAllowsQuit() async throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        let missing = ManagedSyntheticRuntimeConfiguration(manifestURL: fixture.runtime.appendingPathComponent("missing.json"))
        XCTAssertThrowsError(try controller.start(configuration: missing))
        XCTAssertFalse(fake.started)
        XCTAssertFalse(controller.launchInvoked)
        let mayQuit = await controller.stopAndWait()
        XCTAssertTrue(mayQuit, "No Process.start invocation occurred")
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testSynchronousCompletionDuringStopCannotLoseWaiter() async throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(configuration: fixture.configuration)
        fake.synchronousStopReceipt = fake.receipt(reason: "cancelled", status: "cancelled", state: "failed")
        let resolved = await controller.stopAndWait()
        XCTAssertTrue(resolved)
        XCTAssertEqual(controller.state, .stopped)
    }

    @MainActor
    func testReceiptAloneDoesNotResolveDurableMarkerButReapAndEOFDo() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(configuration: fixture.configuration)
        let receipt = fake.receipt()
        fake.receive?(.receipt(receipt))
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertEqual(controller.state, .starting)
        fake.receive?(.finished(.init(returnCode: 0, receipt: receipt, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .completed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: controller.workspace!.sessionDirectoryURL.appendingPathComponent("resolved-owner.json").path))
        XCTAssertThrowsError(try controller.start(configuration: fixture.configuration), "A controller never retries")
    }

    @MainActor
    func testRestartCannotIgnorePendingMarkerAndDoesNotLaunchAnotherProcess() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let first = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { first })
        _ = try controller.start(configuration: fixture.configuration)
        let second = FakeProcess()
        let restarted = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { second })
        XCTAssertThrowsError(try restarted.start(configuration: fixture.configuration))
        XCTAssertFalse(second.started)
        XCTAssertEqual(restarted.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testStopUsesControlHandleAndPreservesCancelledReceipt() async throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(configuration: fixture.configuration)
        controller.markFeedReady()
        let wait = Task { await controller.stopAndWait() }
        await Task.yield()
        controller.requestStop()
        XCTAssertGreaterThan(fake.stopRequests, 0)
        let cancelled = fake.receipt(reason: "cancelled", status: "cancelled", state: "failed")
        fake.receive?(.finished(.init(returnCode: 0, receipt: cancelled, outputWithinBounds: true)))
        let didStop = await wait.value
        XCTAssertTrue(didStop)
        XCTAssertEqual(controller.state, .stopped)
    }

    @MainActor
    func testUnreapedReceiptCancelsQuitAndRetainsMarker() async throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(configuration: fixture.configuration)
        fake.receive?(.receipt(fake.receipt(reason: "child_unreaped", status: "unreaped", state: "failed", resolved: false)))
        XCTAssertEqual(controller.state, .unresolved)
        let canQuit = await controller.stopAndWait()
        XCTAssertFalse(canQuit)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testNonzeroExitFloodWrongLaunchAndPublicationFailureNeverClearMarker() throws {
        for failure in ["exit", "flood", "launch", "publication"] {
            let fixture = try Fixture(); defer { fixture.remove() }
            let fake = FakeProcess()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            _ = try controller.start(configuration: fixture.configuration)
            let data = fake.receipt(launch: failure == "launch" ? "wrong-launch" : nil,
                                    publicationError: failure == "publication" ? "publication_failed" : nil)
            fake.receive?(.finished(.init(returnCode: failure == "exit" ? 2 : 0, receipt: data,
                                          outputWithinBounds: failure != "flood")))
            XCTAssertEqual(controller.state, .unresolved, failure)
            XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path), failure)
        }
    }

    @MainActor
    func testLaunchErrorKeepsMarkerAndStopsFurtherAttempts() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess(); fake.failStart = true
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        XCTAssertThrowsError(try controller.start(configuration: fixture.configuration))
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertThrowsError(try controller.start(configuration: fixture.configuration))
    }

    func testManifestRequiresExactSevenModulesAndRejectsChangedCode() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let workspace = try ManagedSessionWorkspace.create(in: fixture.root)
        XCTAssertEqual(ManagedSyntheticRuntimeConfiguration.moduleNames.count, 7)
        _ = try fixture.configuration.launch(workspace: workspace, launchID: UUID().uuidString.lowercased())
        try Data("changed".utf8).write(to: fixture.runtime.appendingPathComponent("synthetic_continuous_stream.py"))
        XCTAssertThrowsError(try fixture.configuration.launch(workspace: workspace, launchID: UUID().uuidString.lowercased()))
    }
}

@MainActor private final class FakeProcess: ManagedSyntheticProcessHandle {
    var receive: (@MainActor (ManagedSyntheticProcessEvent) -> Void)?
    var started = false, failStart = false
    var stopRequests = 0
    var launchID = ""
    var synchronousStopReceipt: Data?
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        started = true; launchID = launch.arguments.last!; self.receive = receive
        if failStart { throw ManagedSyntheticError.ownership }
    }
    func requestStop() {
        stopRequests += 1
        if let synchronousStopReceipt {
            receive?(.finished(.init(returnCode: 0, receipt: synchronousStopReceipt, outputWithinBounds: true)))
        }
    }
    func receipt(reason: String = "duration_complete", status: String = "exited", state: String = "stopped",
                 resolved: Bool = true, launch: String? = nil, publicationError: String? = nil) -> Data {
        let capture: [String: Any] = ["state": state, "terminal_reason": reason,
            "source_id": "synthetic-app-session", "session_id": String(repeating: "a", count: 32),
            "started_at_unix_ms": 1, "published_at_unix_ms": 120_001, "sample_count": 24,
            "end_reason": reason == "duration_complete" ? reason as Any : NSNull(), "returncode": 0,
            "runner_status": status, "stdout_bytes": 128, "stderr_bytes": 0,
            "publication_error": publicationError as Any? ?? NSNull(), "tailer_quiesced": true]
        return try! JSONSerialization.data(withJSONObject: ["protocol": "ups-monitor.managed-synthetic.v1",
            "schema_version": 1, "launch_id": launch ?? launchID, "adapter": [
                "capture_result": capture, "control_reason": NSNull(), "adapter_error": NSNull(),
                "watcher_quiesced": true, "ownership_resolved": resolved]]) + Data([10])
    }
}

private struct Fixture {
    let container: URL, root: URL, runtime: URL
    var marker: URL { root.appendingPathComponent("active-owner.json") }
    var configuration: ManagedSyntheticRuntimeConfiguration { .init(manifestURL: runtime.appendingPathComponent("runtime.json")) }
    init() throws {
        container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        root = container.appendingPathComponent("sessions", isDirectory: true)
        runtime = container.appendingPathComponent("runtime", isDirectory: true)
        for directory in [container, root, runtime] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
        }
        let content = Data("synthetic fixture, never executed".utf8)
        let hash = SHA256.hash(data: content).map { String(format: "%02x", $0) }.joined()
        let python = runtime.appendingPathComponent("fake-python")
        try content.write(to: python)
        var pins: [String: String] = [:]
        for name in ManagedSyntheticRuntimeConfiguration.moduleNames {
            try content.write(to: runtime.appendingPathComponent(name)); pins[name] = hash
        }
        try JSONSerialization.data(withJSONObject: ["python_path": python.path, "python_sha256": hash,
                                                   "module_sha256": pins]).write(to: runtime.appendingPathComponent("runtime.json"))
    }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
