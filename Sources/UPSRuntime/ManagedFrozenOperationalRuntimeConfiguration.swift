import Foundation

/// Frozen helper admission; no runtime-supplied production pin or system Python fallback.
public struct ManagedFrozenOperationalRuntimeConfiguration: Sendable {
    public static let profile = "apc-smc1500i-operational-frozen-v1"
    public static let helperRoot = "Helpers/UPSOperationalHelper.app"
    public static let helperPath = helperRoot + "/Contents/MacOS/UPSOperationalHelper"
    public static let backendRoot = ManagedBundledOperationalRuntimeConfiguration.backendRoot
    public static let manifestPath = backendRoot + "/frozen-runtime-bundle.json"
    public static let inventoryPath = backendRoot + "/frozen-runtime-tree.json"
    public static let moduleNames = ManagedBundledOperationalRuntimeConfiguration.moduleNames
        .subtracting(["managed_bundled_operational_entrypoint.py"])
    private let contentsURL: URL
    private let expectedManifestSHA256: String
    private let hostAdmissionForTesting: Bool?

    public static func bundled(bundle: Bundle = .main) throws -> Self {
        guard let pin = FrozenOperationalReleasePins.manifestSHA256,
              ManagedRuntimeFiles.validHash(pin) else { throw ManagedSyntheticError.configuration }
        return Self(contentsURL: try ManagedBundledOperationalRuntimeConfiguration.bundleContentsURL(bundle),
                    expectedManifestSHA256: pin)
    }

    init(contentsURL: URL, expectedManifestSHA256: String, hostAdmissionForTesting: Bool? = nil) {
        self.contentsURL = contentsURL
        self.expectedManifestSHA256 = expectedManifestSHA256
        self.hostAdmissionForTesting = hostAdmissionForTesting
    }

    public func launch(workspace: ManagedSessionWorkspace, launchID: String) throws -> ManagedSyntheticLaunch {
        #if arch(arm64)
        let hostSupported = ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 27
        #else
        let hostSupported = false
        #endif
        guard UUID(uuidString: launchID)?.uuidString.lowercased() == launchID,
              hostAdmissionForTesting ?? hostSupported else { throw ManagedSyntheticError.configuration }
        try validatedBundle()
        return ManagedSyntheticLaunch(executableURL: contentsURL.appendingPathComponent(Self.helperPath), arguments: [
            "--workspace", workspace.sessionDirectoryURL.path, "--launch-id", launchID,
            "--runtime-manifest-sha256", expectedManifestSHA256,
        ])
    }

    func validatedBundle() throws {
        typealias C = ManagedFrozenOperationalRuntimeConfiguration
        typealias B = ManagedBundledOperationalRuntimeConfiguration
        guard ManagedRuntimeFiles.validHash(expectedManifestSHA256) else { throw ManagedSyntheticError.configuration }
        let files = try BundledFiles(contents: contentsURL); defer { files.close() }
        let raw = try files.read(C.manifestPath, maximum: 32768)
        guard BundledFiles.sha(raw) == expectedManifestSHA256 else { throw ManagedSyntheticError.configuration }
        let manifest = try BundledJSON.object(raw)
        try BundledFiles.keys(manifest, ["schema_version", "profile", "architecture", "minimum_macos", "python", "backend", "native", "closure", "upstream"])
        guard BundledFiles.integer(manifest["schema_version"], maximum: 1) == 1,
              manifest["profile"] as? String == C.profile, manifest["architecture"] as? String == "arm64",
              manifest["minimum_macos"] as? String == "27.0",
              let python = manifest["python"] as? [String: Any], let backend = manifest["backend"] as? [String: Any],
              let native = manifest["native"] as? [String: Any], let closure = manifest["closure"] as? [String: Any],
              let upstream = manifest["upstream"] as? [String: Any] else { throw ManagedSyntheticError.configuration }
        try BundledFiles.keys(python, ["root", "executable", "sha256"])
        try BundledFiles.keys(backend, ["root", "module_sha256"])
        try BundledFiles.keys(native, ["path", "name", "sha256", "bytes"])
        try BundledFiles.keys(closure, ["path", "sha256", "entries"])
        try BundledFiles.keys(upstream, ["archive_sha256", "metadata_sha256"])
        guard python["root"] as? String == C.helperRoot, python["executable"] as? String == C.helperPath,
              backend["root"] as? String == C.backendRoot, native["path"] as? String == B.nativePath,
              native["name"] as? String == B.nativeName, closure["path"] as? String == C.inventoryPath,
              let helperHash = python["sha256"] as? String, ManagedRuntimeFiles.validHash(helperHash),
              let nativeHash = native["sha256"] as? String, ManagedRuntimeFiles.validHash(nativeHash),
              let nativeBytes = BundledFiles.integer(native["bytes"], maximum: 2097152), nativeBytes > 0,
              let inventoryHash = closure["sha256"] as? String, ManagedRuntimeFiles.validHash(inventoryHash),
              let count = BundledFiles.integer(closure["entries"], maximum: 20000), count > 0,
              let hashes = backend["module_sha256"] as? [String: String], Set(hashes.keys) == C.moduleNames,
              hashes.values.allSatisfy(ManagedRuntimeFiles.validHash),
              let archive = upstream["archive_sha256"] as? String, ManagedRuntimeFiles.validHash(archive),
              let metadata = upstream["metadata_sha256"] as? String, ManagedRuntimeFiles.validHash(metadata)
        else { throw ManagedSyntheticError.configuration }
        let inventoryRaw = try files.read(C.inventoryPath, maximum: 16 * 1048576)
        guard BundledFiles.sha(inventoryRaw) == inventoryHash else { throw ManagedSyntheticError.configuration }
        let inventory = try BundledJSON.object(inventoryRaw)
        try BundledFiles.keys(inventory, ["schema_version", "entries"])
        guard BundledFiles.integer(inventory["schema_version"], maximum: 1) == 1,
              let entries = inventory["entries"] as? [String: [String: Any]], entries.count == count
        else { throw ManagedSyntheticError.configuration }
        try files.verifyClosure(entries, roots: [C.helperRoot, C.backendRoot], nativePath: B.nativePath,
                                controls: [C.manifestPath, C.inventoryPath], parents: ["Helpers", "Resources", "MacOS"],
                                sameRootLinks: true)
        func pinned(_ path: String, _ hash: String, size: Int? = nil, executable: Bool = false) throws {
            guard let row = entries[path], row["type"] as? String == "file", row["sha256"] as? String == hash,
                  (!executable || row["mode"] as? String == "0755" && (BundledFiles.integer(row["bytes"], maximum: 128 * 1048576) ?? 0) > 0),
                  (size == nil || BundledFiles.integer(row["bytes"], maximum: 128 * 1048576) == size)
            else { throw ManagedSyntheticError.configuration }
        }
        try pinned(C.helperPath, helperHash, executable: true)
        try pinned(B.nativePath, nativeHash, size: nativeBytes, executable: true)
        for (name, hash) in hashes { try pinned(C.backendRoot + "/" + name, hash) }
        guard try files.read(C.manifestPath, maximum: 32768) == raw,
              try files.read(C.inventoryPath, maximum: 16 * 1048576) == inventoryRaw else { throw ManagedSyntheticError.configuration }
        try files.verifyNamedRoot()
    }
}
