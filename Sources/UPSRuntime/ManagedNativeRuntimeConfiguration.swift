import CryptoKit
import Foundation

/// Host-local developer-owned configuration for the fixed H07 120-second capture.
/// The UI cannot supply commands, a duration, a native filename or identity overrides.
public struct ManagedNativeRuntimeConfiguration: Sendable {
    public static let moduleNames: Set<String> = [
        "managed_native_entrypoint.py", "app_controlled_capture.py", "continuous_capture.py",
        "continuous_protocol.py", "process_deadline.py",
    ]
    public static let nativeName = "apcmicrolink-hidapi-continuous"
    public static let nativeSHA256 = "2dae6874c8cb99469a9def4a9f584898e815656d87b93dcc6fd67dba5b7d6183"
    public let manifestURL: URL

    public init(manifestURL: URL) { self.manifestURL = manifestURL }

    public static func bundled(bundle: Bundle = .main) throws -> Self {
        guard let resources = bundle.resourceURL else { throw ManagedSyntheticError.configuration }
        return Self(manifestURL: resources.appendingPathComponent("ManagedNativeRuntime/runtime.json"))
    }

    public func launch(workspace: ManagedSessionWorkspace, launchID: String) throws -> ManagedSyntheticLaunch {
        guard UUID(uuidString: launchID) != nil else { throw ManagedSyntheticError.configuration }
        let (python, modules) = try validatedInterpreterAndModules()
        guard try ManagedRuntimeFiles.digest(modules.appendingPathComponent(Self.nativeName), maximum: 2_097_152, requiresExecutable: true)
                == Self.nativeSHA256 else { throw ManagedSyntheticError.configuration }
        return ManagedSyntheticLaunch(executableURL: python, arguments: [
            "-I", "-S", "-B", modules.appendingPathComponent("managed_native_entrypoint.py").path,
            "--workspace", workspace.sessionDirectoryURL.path, "--launch-id", launchID,
        ])
    }

    // Separate validation phase permits inert Python/module fixtures without repinning the native binary.
    func validatedInterpreterAndModules() throws -> (python: URL, modules: URL) {
        struct Manifest: Decodable {
            let schema_version: Int
            let profile: String
            let python_path: String
            let python_sha256: String
            let module_sha256: [String: String]
            let native_name: String
            let native_sha256: String
        }
        let data = try ManagedRuntimeFiles.readFile(manifestURL, maximum: 16_384)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["schema_version", "profile", "python_path", "python_sha256",
                                   "module_sha256", "native_name", "native_sha256"] else {
            throw ManagedSyntheticError.configuration
        }
        let manifest = try JSONDecoder().decode(Manifest.self, from: data)
        guard manifest.schema_version == 1, manifest.profile == "apc-smc1500i-120s-v1",
              manifest.python_path.hasPrefix("/"), !manifest.python_path.contains("\0"),
              !manifest.python_path.components(separatedBy: "/").contains(".."),
              ManagedRuntimeFiles.validHash(manifest.python_sha256),
              Set(manifest.module_sha256.keys) == Self.moduleNames,
              manifest.native_name == Self.nativeName, manifest.native_sha256 == Self.nativeSHA256 else { throw ManagedSyntheticError.configuration }
        let python = URL(fileURLWithPath: manifest.python_path)
        guard try ManagedRuntimeFiles.digest(python, requiresExecutable: true) == manifest.python_sha256 else {
            throw ManagedSyntheticError.configuration
        }
        let modules = manifestURL.deletingLastPathComponent()
        for (name, expected) in manifest.module_sha256 {
            guard ManagedRuntimeFiles.validHash(expected),
                  SHA256.hash(data: try ManagedRuntimeFiles.readFile(modules.appendingPathComponent(name), maximum: 2_097_152))
                    .map({ String(format: "%02x", $0) }).joined() == expected else {
                throw ManagedSyntheticError.configuration
            }
        }
        return (python, modules)
    }
}
