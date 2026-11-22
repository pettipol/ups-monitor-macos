import CryptoKit
import Darwin
import Foundation
import XCTest
@testable import UPSRuntime

final class ManagedNativeRuntimeTests: XCTestCase {
    @MainActor
    func testNativeReceiptRequiresMatchingProtocolAndSourceBeforeOwnershipCleanup() throws {
        for mismatch in ["protocol", "source"] {
            let fixture = try NativeFixture(); defer { fixture.remove() }
            let fake = NativeFakeProcess()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            _ = try controller.start(profile: .native) { _, launchID in fixture.fakeLaunch(launchID) }
            let receipt = fake.receipt(protocolName: mismatch == "protocol" ? "ups-monitor.managed-synthetic.v1" : "ups-monitor.managed-native.v1",
                                       sourceID: mismatch == "source" ? "synthetic-app-session" : "apcmicrolink-hidapi-continuous")
            fake.receive?(.finished(.init(returnCode: 0, receipt: receipt, outputWithinBounds: true)))
            XCTAssertEqual(controller.state, .unresolved, mismatch)
            XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path), mismatch)
        }
    }

    @MainActor
    func testNativeReceiptAloneRetainsMarkerAndExactReapedReceiptResolvesIt() throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        let fake = NativeFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(profile: .native) { _, launchID in fixture.fakeLaunch(launchID) }
        XCTAssertTrue(controller.message.contains("Native 120 s · unqualified"))
        let receipt = fake.receipt()
        fake.receive?(.receipt(receipt))
        XCTAssertEqual(controller.state, .starting)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        fake.receive?(.finished(.init(returnCode: 0, receipt: receipt, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .completed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertThrowsError(try controller.start(profile: .native) { _, id in fixture.fakeLaunch(id) })
    }

    @MainActor
    func testNativeStopWaitsForMatchingReceiptAndNeverStartsAnotherProcess() async throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        let fake = NativeFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(profile: .native) { _, launchID in fixture.fakeLaunch(launchID) }
        fake.completeOnStop = true
        let resolved = await controller.stopAndWait()
        XCTAssertTrue(resolved)
        XCTAssertGreaterThan(fake.stopRequests, 0)
        XCTAssertEqual(fake.starts, 1)
        XCTAssertEqual(controller.state, .stopped)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testSyntheticControllerRejectsNativeReceiptToo() throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        let fake = NativeFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try controller.start(profile: .synthetic) { _, id in fixture.fakeLaunch(id) }
        fake.receive?(.finished(.init(returnCode: 0, receipt: fake.receipt(), outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testInvalidNativeConfigurationCannotInvokeProcessAndAllowsQuit() async throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        let fake = NativeFakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        XCTAssertThrowsError(try controller.start(nativeConfiguration: .init(manifestURL: fixture.runtime.appendingPathComponent("missing.json"))))
        XCTAssertEqual(fake.starts, 0)
        XCTAssertFalse(controller.launchInvoked)
        let mayQuit = await controller.stopAndWait()
        XCTAssertTrue(mayQuit)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    func testNativeManifestIsClosedAndCannotRepinAnotherBinary() throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: fixture.runtime.appendingPathComponent("fake-python").path)
        try fixture.writeManifest(fixture.manifest)
        XCTAssertNoThrow(try fixture.configuration.validatedInterpreterAndModules())
        XCTAssertEqual(ManagedNativeRuntimeConfiguration.moduleNames.count, 5)
        XCTAssertFalse(ManagedNativeRuntimeConfiguration.moduleNames.contains("synthetic_continuous_stream.py"))
        for variant in ["extra", "profile", "version", "filename", "pin", "module", "relative-python", "parent-python"] {
            var manifest = fixture.manifest
            switch variant {
            case "extra": manifest["duration"] = 3600
            case "profile": manifest["profile"] = "daily"
            case "version": manifest["schema_version"] = 2
            case "filename": manifest["native_name"] = "../apcmicrolink-hidapi-continuous"
            case "pin": manifest["native_sha256"] = fixture.hash // Matches fake bytes, but never the admitted binary.
            case "module": manifest["module_sha256"] = ["unexpected.py": fixture.hash]
            case "parent-python": manifest["python_path"] = fixture.runtime.path + "/../runtime/fake-python"
            default: manifest["python_path"] = "relative-python"
            }
            try fixture.writeManifest(manifest)
            XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(), variant)
        }
    }

    func testInterpreterAndEveryModuleHashAreVerifiedWithoutNeedingNativeExecution() throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        try fixture.writeManifest(fixture.manifest)
        let python = fixture.runtime.appendingPathComponent("fake-python")
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: python.path)
        XCTAssertNoThrow(try fixture.configuration.validatedInterpreterAndModules())
        for name in ManagedNativeRuntimeConfiguration.moduleNames.union(["fake-python"]) {
            let file = fixture.runtime.appendingPathComponent(name)
            try Data("tampered".utf8).write(to: file)
            XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(), name)
            try Data("fixture, never executed".utf8).write(to: file)
        }
        XCTAssertNoThrow(try fixture.configuration.validatedInterpreterAndModules())
        let workspace = try ManagedSessionWorkspace.create(in: fixture.root)
        XCTAssertThrowsError(try fixture.configuration.launch(workspace: workspace, launchID: UUID().uuidString),
                             "Inert native bytes cannot satisfy the fixed executable native pin")
    }

    func testSharedFileChecksRejectTamperSymlinkNonregularOversizeAndMissingExecutableMode() throws {
        let fixture = try NativeFixture(); defer { fixture.remove() }
        let file = fixture.runtime.appendingPathComponent("check-file")
        try Data("first".utf8).write(to: file)
        XCTAssertEqual(try ManagedRuntimeFiles.digest(file), NativeFixture.digest(Data("first".utf8)))
        XCTAssertThrowsError(try ManagedRuntimeFiles.digest(file, requiresExecutable: true))
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: file.path)
        XCTAssertNoThrow(try ManagedRuntimeFiles.digest(file, requiresExecutable: true))
        try Data("tampered".utf8).write(to: file)
        XCTAssertNotEqual(try ManagedRuntimeFiles.digest(file), NativeFixture.digest(Data("first".utf8)))
        XCTAssertThrowsError(try ManagedRuntimeFiles.readFile(file, maximum: 3))
        XCTAssertThrowsError(try ManagedRuntimeFiles.digest(fixture.runtime))
        let link = fixture.runtime.appendingPathComponent("linked")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: file)
        XCTAssertThrowsError(try ManagedRuntimeFiles.readFile(link, maximum: 128))
        XCTAssertThrowsError(try ManagedRuntimeFiles.digest(link))
        let sparse = fixture.runtime.appendingPathComponent("oversized")
        XCTAssertTrue(FileManager.default.createFile(atPath: sparse.path, contents: Data([1])))
        let handle = try FileHandle(forWritingTo: sparse)
        try handle.truncate(atOffset: 2_097_153)
        XCTAssertThrowsError(try ManagedRuntimeFiles.digest(sparse, maximum: 2_097_152), "Native binary is bounded at 2 MiB")
        try handle.truncate(atOffset: 134_217_729); try handle.close()
        XCTAssertThrowsError(try ManagedRuntimeFiles.digest(sparse))
    }
}

@MainActor private final class NativeFakeProcess: ManagedSyntheticProcessHandle {
    var receive: (@MainActor (ManagedSyntheticProcessEvent) -> Void)?
    var launchID = "", starts = 0, stopRequests = 0
    var completeOnStop = false
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        starts += 1; launchID = launch.arguments.last!; self.receive = receive
    }
    func requestStop() {
        stopRequests += 1
        if completeOnStop {
            receive?(.finished(.init(returnCode: 0, receipt: receipt(cancelled: true), outputWithinBounds: true)))
        }
    }
    func receipt(protocolName: String = "ups-monitor.managed-native.v1", sourceID: String = "apcmicrolink-hidapi-continuous",
                 cancelled: Bool = false) -> Data {
        let capture: [String: Any] = ["state": cancelled ? "failed" : "stopped", "terminal_reason": cancelled ? "cancelled" : "duration_complete",
            "source_id": sourceID, "session_id": String(repeating: "a", count: 32),
            "started_at_unix_ms": 1, "published_at_unix_ms": 120_001, "sample_count": 24,
            "end_reason": cancelled ? NSNull() : "duration_complete" as Any, "returncode": 0,
            "runner_status": cancelled ? "cancelled" : "exited", "stdout_bytes": 128, "stderr_bytes": 0,
            "publication_error": NSNull(), "tailer_quiesced": true]
        return try! JSONSerialization.data(withJSONObject: ["protocol": protocolName, "schema_version": 1,
            "launch_id": launchID, "adapter": ["capture_result": capture, "control_reason": NSNull(),
                "adapter_error": NSNull(), "watcher_quiesced": true, "ownership_resolved": true]]) + Data([10])
    }
}

private struct NativeFixture {
    let container: URL, root: URL, runtime: URL
    let hash = NativeFixture.digest(Data("fixture, never executed".utf8))
    var marker: URL { root.appendingPathComponent("active-owner.json") }
    var configuration: ManagedNativeRuntimeConfiguration { .init(manifestURL: runtime.appendingPathComponent("runtime.json")) }
    var manifest: [String: Any] { ["schema_version": 1, "profile": "apc-smc1500i-120s-v1",
        "python_path": runtime.appendingPathComponent("fake-python").path, "python_sha256": hash,
        "module_sha256": Dictionary(uniqueKeysWithValues: ManagedNativeRuntimeConfiguration.moduleNames.map { ($0, hash) }),
        "native_name": ManagedNativeRuntimeConfiguration.nativeName, "native_sha256": ManagedNativeRuntimeConfiguration.nativeSHA256] }
    init() throws {
        container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        root = container.appendingPathComponent("sessions", isDirectory: true)
        runtime = container.appendingPathComponent("runtime", isDirectory: true)
        for directory in [container, root, runtime] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        }
        let files = ManagedNativeRuntimeConfiguration.moduleNames.union(["fake-python", ManagedNativeRuntimeConfiguration.nativeName])
        for name in files {
            try Data("fixture, never executed".utf8).write(to: runtime.appendingPathComponent(name))
        }
    }
    func fakeLaunch(_ launchID: String) -> ManagedSyntheticLaunch { .init(executableURL: runtime.appendingPathComponent("fake-python"), arguments: [launchID]) }
    func writeManifest(_ value: [String: Any]) throws { try JSONSerialization.data(withJSONObject: value).write(to: runtime.appendingPathComponent("runtime.json")) }
    static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
