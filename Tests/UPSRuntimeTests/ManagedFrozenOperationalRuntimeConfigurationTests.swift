import CryptoKit
import Darwin
import Foundation
import XCTest
@testable import UPSRuntime

final class ManagedFrozenOperationalRuntimeConfigurationTests: XCTestCase {
    func testPublicFrozenPinCannotEnableRuntime() {
        XCTAssertNil(FrozenOperationalReleasePins.manifestSHA256)
        XCTAssertThrowsError(try ManagedFrozenOperationalRuntimeConfiguration.bundled())
        XCTAssertNil(BundledOperationalReleasePins.manifestSHA256)
    }

    func testFrozenLayoutIsDistinctAndHasNineOperationalModules() {
        typealias F = ManagedFrozenOperationalRuntimeConfiguration
        typealias B = ManagedBundledOperationalRuntimeConfiguration
        XCTAssertNotEqual(F.profile, B.profile)
        XCTAssertNotEqual(F.manifestPath, B.manifestPath)
        XCTAssertEqual(F.moduleNames.count, 9)
        XCTAssertFalse(F.moduleNames.contains("managed_bundled_operational_entrypoint.py"))
        XCTAssertEqual(F.helperPath, "Helpers/UPSOperationalHelper.app/Contents/MacOS/UPSOperationalHelper")
    }

    func testPositiveLaunchUsesOnlyApplicationArguments() throws {
        let f = try FrozenFixture(); defer { f.remove() }
        let workspace = try ManagedSessionWorkspace.create(in: f.privateRoot)
        let id = UUID().uuidString.lowercased()
        let launch = try f.configuration.launch(workspace: workspace, launchID: id)
        XCTAssertEqual(launch.executableURL, f.contents.appendingPathComponent(FrozenFixture.F.helperPath))
        XCTAssertEqual(launch.arguments, ["--workspace", workspace.sessionDirectoryURL.path, "--launch-id", id,
                                          "--runtime-manifest-sha256", f.pin])
        XCTAssertFalse(launch.arguments.contains("-I"))
        XCTAssertFalse(launch.arguments.contains("-S"))
        XCTAssertFalse(launch.arguments.contains("-B"))
        XCTAssertFalse(launch.arguments.contains(where: { $0.hasSuffix(".py") }))
    }

    @MainActor
    func testBadBundlesRejectBeforeProcessFactory() throws {
        for fault in ["pin", "helper", "native", "module", "missing", "extra", "link", "profile", "duplicate"] {
            let f = try FrozenFixture(); defer { f.remove() }
            let fm = FileManager.default
            switch fault {
            case "pin": f.pin = String(repeating: "0", count: 64)
            case "helper": try Data("changed".utf8).write(to: f.url(FrozenFixture.F.helperPath))
            case "native": try Data("changed".utf8).write(to: f.url(FrozenFixture.B.nativePath))
            case "module":
                let module = try XCTUnwrap(FrozenFixture.F.moduleNames.sorted().first)
                try Data("changed".utf8).write(to: f.url(FrozenFixture.F.backendRoot + "/" + module))
            case "missing": try fm.removeItem(at: f.url(FrozenFixture.F.helperPath))
            case "extra": try Data("extra".utf8).write(to: f.url(FrozenFixture.F.backendRoot + "/extra.py"))
            case "link":
                let path = FrozenFixture.F.helperRoot + "/Contents/cross"
                let target = "../../../Resources/ManagedOperationalRuntime"
                try fm.createSymbolicLink(atPath: f.url(path).path, withDestinationPath: target)
                f.entries[path] = ["type": "symlink", "mode": "0777", "target": target,
                                   "resolved_target": FrozenFixture.F.backendRoot]
                try f.save()
            case "profile": f.manifest["profile"] = FrozenFixture.B.profile; try f.save()
            case "duplicate":
                let raw = try Data(contentsOf: f.url(FrozenFixture.F.manifestPath))
                let duplicate = Data("{\"schema_version\":1,".utf8) + Data(raw.dropFirst())
                try f.trust(duplicate)
            default: XCTFail("Unknown fault")
            }
            var factoryCalls = 0
            let controller = ManagedSyntheticSessionController(root: { f.privateRoot }, makeProcess: {
                factoryCalls += 1; return FrozenFakeProcess()
            })
            XCTAssertThrowsError(try controller.start(frozenOperationalConfiguration: f.configuration), fault)
            XCTAssertEqual(factoryCalls, 0, fault)
        }
    }
}

@MainActor private final class FrozenFakeProcess: ManagedSyntheticProcessHandle {
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        XCTFail("A rejected preflight must not start a process")
    }
    func requestStop() {}
}

private final class FrozenFixture {
    typealias F = ManagedFrozenOperationalRuntimeConfiguration
    typealias B = ManagedBundledOperationalRuntimeConfiguration
    let container: URL
    let contents: URL
    let privateRoot: URL
    var entries: [String: [String: Any]] = [:]
    var manifest: [String: Any] = [:]
    var pin = ""
    var configuration: F { F(contentsURL: contents, expectedManifestSHA256: pin, hostAdmissionForTesting: true) }
    init() throws {
        let tmp = FileManager.default.temporaryDirectory.path
        guard let canonical = tmp.withCString({ realpath($0, nil) }) else { throw ManagedSyntheticError.configuration }
        let base = URL(fileURLWithPath: String(cString: canonical), isDirectory: true); free(canonical)
        container = base.appendingPathComponent(UUID().uuidString)
        contents = container.appendingPathComponent("移動 App with spaces.app/Contents", isDirectory: true)
        privateRoot = container.appendingPathComponent("private", isDirectory: true)
        let fm = FileManager.default
        try fm.createDirectory(at: contents, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o755])
        try fm.createDirectory(at: privateRoot, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: privateRoot.path)
        try file(F.helperPath, Data("inert helper".utf8), mode: 0o755)
        try file(B.nativePath, Data("inert native".utf8), mode: 0o755)
        try file(F.helperRoot + "/Contents/Frameworks/inert.dat", Data("inert".utf8))
        var pins: [String: String] = [:]
        for name in F.moduleNames {
            let data = Data(("# synthetic " + name).utf8)
            try file(F.backendRoot + "/" + name, data); pins[name] = hash(data)
        }
        manifest = ["schema_version": 1, "profile": F.profile, "architecture": "arm64", "minimum_macos": "27.0",
            "python": ["root": F.helperRoot, "executable": F.helperPath, "sha256": entries[F.helperPath]!["sha256"]!],
            "backend": ["root": F.backendRoot, "module_sha256": pins],
            "native": ["path": B.nativePath, "name": B.nativeName, "sha256": entries[B.nativePath]!["sha256"]!,
                       "bytes": entries[B.nativePath]!["bytes"]!],
            "closure": ["path": F.inventoryPath, "sha256": "", "entries": 0],
            "upstream": ["archive_sha256": String(repeating: "a", count: 64), "metadata_sha256": String(repeating: "b", count: 64)]]
        try save()
    }
    func url(_ path: String) -> URL { contents.appendingPathComponent(path) }
    func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    func file(_ name: String, _ data: Data, mode: Int = 0o644) throws {
        let parts = name.split(separator: "/").map(String.init)
        for length in 1..<parts.count {
            let parent = parts.prefix(length).joined(separator: "/")
            try FileManager.default.createDirectory(at: url(parent), withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o755])
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url(parent).path)
            if parent == F.helperRoot || parent.hasPrefix(F.helperRoot + "/") ||
               parent == F.backendRoot || parent.hasPrefix(F.backendRoot + "/") {
                entries[parent] = ["type": "directory", "mode": "0755"]
            }
        }
        try data.write(to: url(name)); try FileManager.default.setAttributes([.posixPermissions: mode], ofItemAtPath: url(name).path)
        entries[name] = ["type": "file", "mode": String(format: "%04o", mode), "bytes": data.count, "sha256": hash(data)]
    }
    func save() throws {
        let inventory = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "entries": entries], options: .sortedKeys)
        try inventory.write(to: url(F.inventoryPath))
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: url(F.inventoryPath).path)
        manifest["closure"] = ["path": F.inventoryPath, "sha256": hash(inventory), "entries": entries.count]
        try trust(JSONSerialization.data(withJSONObject: manifest, options: .sortedKeys))
    }
    func trust(_ raw: Data) throws {
        try raw.write(to: url(F.manifestPath))
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: url(F.manifestPath).path)
        pin = hash(raw)
    }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
