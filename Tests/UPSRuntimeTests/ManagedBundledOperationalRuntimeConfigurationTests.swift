import CryptoKit
import Darwin
import Foundation
import XCTest
@testable import UPSRuntime

final class ManagedBundledOperationalRuntimeConfigurationTests: XCTestCase {
    func testCompleteClosureAcceptsUnicodeAndSpacesInOuterAppOnly() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        let binding = try fixture.configuration.validatedBundle()
        XCTAssertEqual(binding.python, fixture.contents.appendingPathComponent(BundledFixture.C.pythonPath))
        XCTAssertEqual(binding.native, fixture.contents.appendingPathComponent(BundledFixture.C.nativePath))
        XCTAssertEqual(BundledFixture.C.moduleNames.count, 10)
    }

    func testPublicDefaultCannotAdoptAFileOrEnvironmentPin() {
        XCTAssertNil(BundledOperationalReleasePins.manifestSHA256)
        XCTAssertThrowsError(try ManagedBundledOperationalRuntimeConfiguration.bundled())
    }

    func testRealBundleSystemAliasesReachTheSameStrictContentsReader() throws {
        var rejectedOldTransformation = false
        var observedAliasPrefixes = Set<String>()
        var tempBuffer = [CChar](repeating: 0, count: 4096)
        let requiredCount = tempBuffer.withUnsafeMutableBufferPointer {
            confstr(_CS_DARWIN_USER_TEMP_DIR, $0.baseAddress, $0.count)
        }
        guard requiredCount > 1, requiredCount <= tempBuffer.count,
              tempBuffer[requiredCount - 1] == 0 else {
            XCTFail("confstr must return a complete Darwin user temporary directory")
            return
        }
        let tempBytes = tempBuffer[..<(requiredCount - 1)].map { UInt8(bitPattern: $0) }
        guard tempBytes.allSatisfy({ $0 != 0 }),
              let userTemporaryPath = String(bytes: tempBytes, encoding: .utf8),
              userTemporaryPath.hasPrefix("/var/") || userTemporaryPath.hasPrefix("/private/var/") else {
            XCTFail("confstr must return the Darwin user temporary directory under /var or /private/var")
            return
        }
        let temporaryRoots = [URL(fileURLWithPath: "/private/tmp", isDirectory: true),
                              URL(fileURLWithPath: userTemporaryPath, isDirectory: true)]
        for temporaryRoot in temporaryRoots {
            let fixture = try BundledFixture(temporaryRoot: temporaryRoot); defer { fixture.remove() }
            _ = try fixture.configuration.validatedBundle()
            let bundle = try fixture.makeBundle()
            let oldContents = bundle.bundleURL.appendingPathComponent("Contents", isDirectory: true)
            XCTAssertNotEqual(oldContents.path, fixture.contents.path)
            let aliasPrefix = ["/tmp/", "/var/"].first { oldContents.path.hasPrefix($0) }
            XCTAssertNotNil(aliasPrefix, "Record the actual system alias returned by Bundle")
            if let aliasPrefix { observedAliasPrefixes.insert(aliasPrefix) }
            // Reproduce the old production transformation with an existing
            // strict initializer, rather than an undefined new helper.
            XCTAssertThrowsError(try BundledFixture.C(contentsURL: oldContents,
                expectedManifestSHA256: fixture.pin).validatedBundle())
            rejectedOldTransformation = true
            let contents = try BundledFixture.C.bundleContentsURL(bundle)
            XCTAssertEqual(contents.path, fixture.contents.path)
            let configuration = BundledFixture.C(contentsURL: contents, expectedManifestSHA256: fixture.pin)
            _ = try configuration.validatedBundle()
            // A real Bundle is the input to the production path helper. Its
            // public release factory still cannot adopt a fixture's file pin.
            XCTAssertThrowsError(try BundledFixture.C.bundled(bundle: bundle))
        }
        XCTAssertTrue(rejectedOldTransformation, "Real Bundle must reproduce the macOS system-alias regression")
        XCTAssertEqual(observedAliasPrefixes, Set(["/tmp/", "/var/"]))
    }

    func testRealBundleRejectsUnexpectedAppParentAndContentsAliases() throws {
        for fault in ["app", "parent", "contents"] {
            let fixture = try BundledFixture(); defer { fixture.remove() }
            let bundle = try fixture.makeBundle()
            let contents = try BundledFixture.C.bundleContentsURL(bundle)
            _ = try BundledFixture.C(contentsURL: contents, expectedManifestSHA256: fixture.pin).validatedBundle()
            let app = fixture.contents.deletingLastPathComponent()
            if fault == "app" {
                let moved = fixture.container.appendingPathComponent("moved.app")
                try FileManager.default.moveItem(at: app, to: moved)
                try FileManager.default.createSymbolicLink(at: app, withDestinationURL: moved)
            } else if fault == "parent" {
                let moved = fixture.container.appendingPathExtension("moved")
                try FileManager.default.moveItem(at: fixture.container, to: moved)
                defer { try? FileManager.default.removeItem(at: moved) }
                try FileManager.default.createSymbolicLink(at: fixture.container, withDestinationURL: moved)
                XCTAssertThrowsError(try BundledFixture.C.bundleContentsURL(bundle), fault)
                XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
                continue
            } else {
                let moved = app.appendingPathComponent("OtherContents", isDirectory: true)
                try FileManager.default.moveItem(at: fixture.contents, to: moved)
                try FileManager.default.createSymbolicLink(at: fixture.contents, withDestinationURL: moved)
            }
            XCTAssertThrowsError(try BundledFixture.C.bundleContentsURL(bundle), fault)
            XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
        }
    }

    func testPOSIXSystemAliasAndOuterSymlinkAreRejected() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        _ = try fixture.configuration.validatedBundle()
        let alias = fixture.container.appendingPathComponent("app-alias")
        try FileManager.default.createSymbolicLink(at: alias,
            withDestinationURL: fixture.contents.deletingLastPathComponent())
        let aliased = ManagedBundledOperationalRuntimeConfiguration(
            contentsURL: alias.appendingPathComponent("Contents", isDirectory: true),
            expectedManifestSHA256: fixture.pin)
        XCTAssertThrowsError(try aliased.validatedBundle())

        // macOS system aliases remain invalid even when Foundation considers
        // their spelling resolved. The matching canonical fixture passed above.
        let canonical = fixture.contents.path
        var checkedSystemAlias = false
        for (physical, logical) in [("/private/var/", "/var/"), ("/private/tmp/", "/tmp/")] {
            if canonical.hasPrefix(physical) {
                let path = logical + String(canonical.dropFirst(physical.count))
                let configuration = ManagedBundledOperationalRuntimeConfiguration(
                    contentsURL: URL(fileURLWithPath: path, isDirectory: true),
                    expectedManifestSHA256: fixture.pin)
                XCTAssertThrowsError(try configuration.validatedBundle(), path)
                checkedSystemAlias = true
            }
        }
        XCTAssertTrue(checkedSystemAlias, "Synthetic test temporary root must exercise a macOS system alias")
    }

    func testWrongCompiledRootRejectsEvenOtherwiseValidManifest() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        _ = try fixture.configuration.validatedBundle()
        let configuration = ManagedBundledOperationalRuntimeConfiguration(contentsURL: fixture.contents,
            expectedManifestSHA256: String(repeating: "0", count: 64))
        XCTAssertThrowsError(try configuration.validatedBundle())
    }

    func testBooleanFloatDuplicateAndExtraManifestFieldsAreRejected() throws {
        for fault in ["boolean", "float", "duplicate", "extra", "legacy"] {
            let fixture = try BundledFixture(); defer { fixture.remove() }
            _ = try fixture.configuration.validatedBundle()
            if fault == "boolean" { fixture.manifest["schema_version"] = true }
            if fault == "extra" { fixture.manifest["python_path"] = "/unadmitted/python" }
            if fault == "legacy" { fixture.manifest["schema_version"] = 2 }
            try fixture.save()
            if fault == "float" || fault == "duplicate" {
                let raw = try String(contentsOf: fixture.manifestURL, encoding: .utf8)
                let replacement = fault == "float" ? "\"schema_version\":1.0" : "\"schema_version\":1,\"schema_version\":1"
                try fixture.trustManifest(Data(raw.replacingOccurrences(of: "\"schema_version\":1", with: replacement).utf8))
            }
            XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
        }
    }

    func testMissingChangedExtraAndWritableModuleFailClosed() throws {
        for fault in ["missing", "changed", "extra", "mode"] {
            let fixture = try BundledFixture(); defer { fixture.remove() }
            _ = try fixture.configuration.validatedBundle()
            let path = fixture.contents.appendingPathComponent(BundledFixture.C.backendRoot + "/process_deadline.py")
            if fault == "missing" { try FileManager.default.removeItem(at: path) }
            if fault == "changed" { try Data("changed".utf8).write(to: path) }
            if fault == "extra" { try Data("extra".utf8).write(to: path.deletingLastPathComponent().appendingPathComponent("unadmitted.py")) }
            if fault == "mode" { try FileManager.default.setAttributes([.posixPermissions: 0o664], ofItemAtPath: path.path) }
            XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
        }
    }

    func testRolePathsModuleClosureAndNativeSizeAreFixed() throws {
        for fault in ["python", "native", "modules", "count", "native-size"] {
            let fixture = try BundledFixture(); defer { fixture.remove() }
            _ = try fixture.configuration.validatedBundle()
            if fault == "python" { try fixture.change("python", "executable", "/tmp/python") }
            if fault == "native" { try fixture.change("native", "path", "MacOS/other") }
            if fault == "modules" {
                var backend = fixture.manifest["backend"] as! [String: Any]
                var modules = backend["module_sha256"] as! [String: String]
                modules["extra.py"] = String(repeating: "a", count: 64)
                backend["module_sha256"] = modules; fixture.manifest["backend"] = backend
            }
            if fault == "native-size" { try fixture.change("native", "bytes", true) }
            try fixture.save()
            if fault == "count" {
                try fixture.change("closure", "entries", true)
                try fixture.trustManifest(JSONSerialization.data(withJSONObject: fixture.manifest, options: .sortedKeys))
            }
            XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
        }
    }

    func testInternalRelativeSymlinkWithPinnedTargetIsAccepted() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        _ = try fixture.configuration.validatedBundle()
        try fixture.link(BundledFixture.C.pythonRoot + "/install/bin/python3", target: "python3.15", resolved: BundledFixture.C.pythonPath)
        try fixture.save()
        _ = try fixture.configuration.validatedBundle()
    }

    func testExternalMissingCyclicAndAlteredSymlinksAreRejected() throws {
        for fault in ["external", "missing", "cycle", "changed"] {
            let fixture = try BundledFixture(); defer { fixture.remove() }
            _ = try fixture.configuration.validatedBundle()
            let path = BundledFixture.C.pythonRoot + "/install/bin/alias"
            if fault == "cycle" {
                try fixture.link(path, target: "other", resolved: BundledFixture.C.pythonPath)
                try fixture.link(BundledFixture.C.pythonRoot + "/install/bin/other", target: "alias", resolved: BundledFixture.C.pythonPath)
            } else {
                let target = fault == "external" ? "/outside" : (fault == "missing" ? "missing" : "python3.15")
                try fixture.link(path, target: target, resolved: BundledFixture.C.pythonPath)
            }
            try fixture.save()
            if fault == "changed" {
                try FileManager.default.removeItem(at: fixture.contents.appendingPathComponent(path))
                try FileManager.default.createSymbolicLink(atPath: fixture.contents.appendingPathComponent(path).path,
                    withDestinationPath: "missing")
            }
            XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
        }
    }

    func testCaseUnicodeAliasesAndSymlinkedParentsAreRejected() throws {
        for fault in ["case", "unicode", "parent"] {
            let fixture = try BundledFixture(); defer { fixture.remove() }
            _ = try fixture.configuration.validatedBundle()
            if fault == "parent" {
                let bin = fixture.contents.appendingPathComponent(BundledFixture.C.pythonRoot + "/install/bin")
                try FileManager.default.moveItem(at: bin, to: bin.deletingLastPathComponent().appendingPathComponent("other-bin"))
                try FileManager.default.createSymbolicLink(atPath: bin.path, withDestinationPath: "other-bin")
            } else {
                let path = fault == "case" ? BundledFixture.C.pythonPath.uppercased() : BundledFixture.C.pythonRoot + "/café.py"
                fixture.entries[path] = fixture.entries[BundledFixture.C.pythonPath]
                try fixture.save()
            }
            XCTAssertThrowsError(try fixture.configuration.validatedBundle(), fault)
        }
    }

    func testRegularHardlinkAliasIsNotAnAdmittedSymlink() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        _ = try fixture.configuration.validatedBundle()
        try FileManager.default.linkItem(at: fixture.contents.appendingPathComponent(BundledFixture.C.pythonPath),
                                        to: fixture.container.appendingPathComponent("outside-hardlink"))
        XCTAssertThrowsError(try fixture.configuration.validatedBundle())
    }

    @MainActor
    func testNewControllerOverloadProducesOnlyFixedLaunchAndUsesExistingStop() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        let root = fixture.container.appendingPathComponent("sessions")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        let fake = BundledInertProcess()
        let controller = ManagedSyntheticSessionController(root: { root }, makeProcess: { fake })
        _ = try controller.start(bundledOperationalConfiguration: fixture.configuration)
        XCTAssertEqual(fake.starts, 1)
        let launch = try XCTUnwrap(fake.launch)
        XCTAssertEqual(launch.executableURL, fixture.contents.appendingPathComponent(BundledFixture.C.pythonPath))
        XCTAssertEqual(Array(launch.arguments.prefix(3)), ["-I", "-S", "-B"])
        XCTAssertEqual(Array(launch.arguments.suffix(2)), ["--runtime-manifest-sha256", fixture.pin])
        XCTAssertFalse(launch.arguments.contains("--native"))
        XCTAssertEqual(controller.state, .starting)
        XCTAssertEqual(controller.receiptArchiveState, .pending)
        controller.requestStop()
        XCTAssertEqual(fake.stops, 1)
    }

    @MainActor
    func testFailedPreflightConstructsNoProcessAndCannotFallback() throws {
        let fixture = try BundledFixture(); defer { fixture.remove() }
        _ = try fixture.configuration.validatedBundle()
        let root = fixture.container.appendingPathComponent("sessions")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        var factories = 0
        let controller = ManagedSyntheticSessionController(root: { root }, makeProcess: {
            factories += 1; return BundledInertProcess()
        })
        let invalid = ManagedBundledOperationalRuntimeConfiguration(contentsURL: fixture.contents,
            expectedManifestSHA256: String(repeating: "0", count: 64), hostAdmissionForTesting: true)
        XCTAssertThrowsError(try controller.start(bundledOperationalConfiguration: invalid))
        XCTAssertEqual(factories, 0)
        XCTAssertEqual(controller.state, .unresolved)
    }
}

@MainActor private final class BundledInertProcess: ManagedSyntheticProcessHandle {
    var starts = 0
    var stops = 0
    var launch: ManagedSyntheticLaunch?
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        starts += 1; self.launch = launch
    }
    func requestStop() { stops += 1 }
}

private final class BundledFixture {
    typealias C = ManagedBundledOperationalRuntimeConfiguration
    let container: URL
    let contents: URL
    var entries: [String: [String: Any]] = [:]
    var manifest: [String: Any] = [:]
    var pin = ""
    var manifestURL: URL { contents.appendingPathComponent(C.manifestPath) }
    var configuration: C { C(contentsURL: contents, expectedManifestSHA256: pin, hostAdmissionForTesting: true) }
    init(temporaryRoot: URL = FileManager.default.temporaryDirectory) throws {
        let temporaryPath = temporaryRoot.path
        guard let canonical = temporaryPath.withCString({ realpath($0, nil) }) else {
            throw ManagedSyntheticError.configuration
        }
        let temporaryRoot = URL(fileURLWithPath: String(cString: canonical), isDirectory: true)
        free(canonical)
        container = temporaryRoot.appendingPathComponent(UUID().uuidString)
        contents = container.appendingPathComponent("移動 App with spaces.app/Contents", isDirectory: true)
        try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o755])
        try file(C.pythonPath, data: Data("inert python; never executed".utf8), mode: 0o755)
        try file(C.nativePath, data: Data("inert native; never executed".utf8), mode: 0o755)
        try file(C.pythonRoot + "/install/lib/python3.15/os.py", data: Data("# inert stdlib\n".utf8))
        var moduleHashes: [String: String] = [:]
        for name in C.moduleNames {
            let data = Data(("# synthetic " + name + "\n").utf8)
            try file(C.backendRoot + "/" + name, data: data)
            moduleHashes[name] = hash(data)
        }
        manifest = ["schema_version": 1, "profile": C.profile, "architecture": "arm64", "minimum_macos": "27.0",
            "python": ["root": C.pythonRoot, "executable": C.pythonPath, "sha256": entries[C.pythonPath]!["sha256"]!],
            "backend": ["root": C.backendRoot, "entrypoint": C.entryPath, "module_sha256": moduleHashes],
            "native": ["path": C.nativePath, "name": C.nativeName, "sha256": entries[C.nativePath]!["sha256"]!,
                       "bytes": entries[C.nativePath]!["bytes"]!],
            "closure": ["path": C.inventoryPath, "sha256": "", "entries": 0],
            "upstream": ["archive_sha256": String(repeating: "a", count: 64), "metadata_sha256": String(repeating: "b", count: 64)]]
        try save()
    }
    func makeBundle() throws -> Bundle {
        let info: [String: Any] = ["CFBundleIdentifier": "org.openupsmonitor.tests.bundle." + UUID().uuidString.lowercased(),
            "CFBundleName": "Synthetic Bundle", "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
            "CFBundleExecutable": C.nativeName]
        let url = contents.appendingPathComponent("Info.plist")
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: url.path)
        return try XCTUnwrap(Bundle(url: contents.deletingLastPathComponent()))
    }
    func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    func parents(_ name: String) throws {
        let parts = name.split(separator: "/").map(String.init)
        for length in 1..<parts.count {
            let path = parts.prefix(length).joined(separator: "/")
            let url = contents.appendingPathComponent(path, isDirectory: true)
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o755])
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
            if path.hasPrefix(C.pythonRoot) || path.hasPrefix(C.backendRoot) {
                entries[path] = ["type": "directory", "mode": "0755"]
            }
        }
    }
    func file(_ name: String, data: Data, mode: Int = 0o644) throws {
        try parents(name)
        let url = contents.appendingPathComponent(name)
        try data.write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: mode], ofItemAtPath: url.path)
        entries[name] = ["type": "file", "mode": String(format: "%04o", mode), "bytes": data.count, "sha256": hash(data)]
    }
    func link(_ name: String, target: String, resolved: String) throws {
        try parents(name)
        let url = contents.appendingPathComponent(name)
        try FileManager.default.createSymbolicLink(atPath: url.path, withDestinationPath: target)
        guard lchmod(url.path, 0o777) == 0 else { throw ManagedSyntheticError.configuration }
        entries[name] = ["type": "symlink", "mode": "0777", "target": target, "resolved_target": resolved]
    }
    func change(_ object: String, _ key: String, _ value: Any) throws {
        var row = try XCTUnwrap(manifest[object] as? [String: Any])
        row[key] = value; manifest[object] = row
    }
    func save() throws {
        let inventory = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "entries": entries], options: .sortedKeys)
        let inventoryURL = contents.appendingPathComponent(C.inventoryPath)
        try inventory.write(to: inventoryURL)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: inventoryURL.path)
        try change("closure", "sha256", hash(inventory))
        try change("closure", "entries", entries.count)
        try trustManifest(JSONSerialization.data(withJSONObject: manifest, options: .sortedKeys))
    }
    func trustManifest(_ data: Data) throws {
        try data.write(to: manifestURL)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: manifestURL.path)
        pin = hash(data)
    }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
