import CryptoKit
import Foundation
import XCTest
@testable import UPSRuntime

final class ManagedOperationalRuntimeConfigurationTests: XCTestCase {
    func testExactNineKeyManifestAndCompleteModuleClosureAreAccepted() throws {
        let fixture = try RuntimeFixture(); defer { fixture.remove() }
        let validated = try fixture.configuration.validatedInterpreterAndModules()
        XCTAssertEqual(validated.python, fixture.python)
        XCTAssertEqual(validated.modules, fixture.directory)
        XCTAssertEqual(ManagedOperationalRuntimeConfiguration.moduleNames.count, 9)
    }

    func testExtraManifestKeyAndVersionBooleanAreRejected() throws {
        let fixture = try RuntimeFixture(); defer { fixture.remove() }
        var manifest = try fixture.readManifest()
        manifest["native_path"] = fixture.directory.appendingPathComponent("native").path
        try fixture.writeManifest(manifest)
        XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules())

        manifest = try fixture.validManifest()
        manifest["schema_version"] = true
        try fixture.writeManifest(manifest)
        XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(),
                             "JSON booleans cannot pass as integer schema versions")
    }

    func testProfileArchitectureMinimumAndNativeIdentityAreFixed() throws {
        let fixture = try RuntimeFixture(); defer { fixture.remove() }
        for (key, badValue) in [("profile", "other-profile"), ("architecture", "x86_64"),
                                ("minimum_macos", "14.0"), ("native_name", "other-native"),
                                ("native_sha256", String(repeating: "0", count: 64))] {
            var manifest = try fixture.validManifest()
            manifest[key] = badValue
            try fixture.writeManifest(manifest)
            XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(), key)
        }
    }

    func testMissingModuleChangedModuleAndChangedInterpreterFailClosed() throws {
        let fixture = try RuntimeFixture(); defer { fixture.remove() }
        try FileManager.default.removeItem(at: fixture.directory.appendingPathComponent("process_deadline.py"))
        XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(), "missing module")

        try fixture.writeAllModules()
        try Data("changed".utf8).write(to: fixture.directory.appendingPathComponent("continuous_protocol.py"))
        XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(), "module hash mismatch")

        try fixture.writeAllModules()
        try Data("changed python".utf8).write(to: fixture.python)
        XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules(), "interpreter hash mismatch")
    }

    func testPythonPathTraversalIsRejected() throws {
        let fixture = try RuntimeFixture(); defer { fixture.remove() }
        var manifest = try fixture.validManifest()
        manifest["python_path"] = "/tmp/../outside-python"
        try fixture.writeManifest(manifest)
        XCTAssertThrowsError(try fixture.configuration.validatedInterpreterAndModules())
    }
}

private struct RuntimeFixture {
    let container: URL
    let directory: URL
    let python: URL
    let manifestURL: URL
    let configuration: ManagedOperationalRuntimeConfiguration
    private let content = Data("synthetic inert managed runtime fixture".utf8)
    private var contentHash: String { SHA256.hash(data: content).map { String(format: "%02x", $0) }.joined() }

    init() throws {
        container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        directory = container.appendingPathComponent("ManagedOperationalRuntime", isDirectory: true)
        python = container.appendingPathComponent("fake-python")
        manifestURL = directory.appendingPathComponent("runtime.json")
        configuration = ManagedOperationalRuntimeConfiguration(manifestURL: manifestURL)
        try FileManager.default.createDirectory(at: container, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        try content.write(to: python)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: python.path)
        try writeAllModules()
        try writeManifest(validManifest())
    }

    func validManifest() -> [String: Any] {
        ["schema_version": 2, "profile": ManagedOperationalRuntimeConfiguration.profile,
         "python_path": python.path, "python_sha256": contentHash,
         "module_sha256": Dictionary(uniqueKeysWithValues: ManagedOperationalRuntimeConfiguration.moduleNames.map { ($0, contentHash) }),
         "native_name": ManagedOperationalRuntimeConfiguration.nativeName,
         "native_sha256": ManagedOperationalRuntimeConfiguration.nativeSHA256,
         "architecture": "arm64", "minimum_macos": "27.0"]
    }

    func readManifest() throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any])
    }

    func writeManifest(_ object: [String: Any]) throws {
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]).write(to: manifestURL)
    }

    func writeAllModules() throws {
        for name in ManagedOperationalRuntimeConfiguration.moduleNames {
            try content.write(to: directory.appendingPathComponent(name))
        }
    }

    func remove() { try? FileManager.default.removeItem(at: container) }
}
