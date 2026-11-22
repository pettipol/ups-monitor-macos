import CoreFoundation
import CryptoKit
import Foundation

/// Fixed, host-local admission for the disabled managed operational v2 candidate.
/// UI arguments cannot select its Python, modules, native identity, or argv.
public struct ManagedOperationalRuntimeConfiguration: Sendable {
    public static let profile = "apc-smc1500i-operational-v2"
    public static let nativeName = "apcmicrolink-hidapi-operational"
    public static let nativeSHA256 = "d754eaa71ef19dad5532ddabfd507f084ec6848ef2642718b1cb575657f43cfc"
    public static let sourceID = "apcmicrolink-hidapi-operational"
    public static let moduleNames: Set<String> = [
        "managed_operational_entrypoint.py", "app_controlled_operational.py", "operational_capture.py",
        "operational_publication.py", "continuous_capture.py", "continuous_protocol.py",
        "process_deadline.py", "bounded_stream_dispatch.py",
        "cleanup_diagnostics.py",
    ]

    public let manifestURL: URL

    public init(manifestURL: URL) { self.manifestURL = manifestURL }

    public static func bundled(bundle: Bundle = .main) throws -> Self {
        guard let resources = bundle.resourceURL else { throw ManagedSyntheticError.configuration }
        return Self(manifestURL: resources.appendingPathComponent("ManagedOperationalRuntime/runtime.json"))
    }

    public func launch(workspace: ManagedSessionWorkspace, launchID: String) throws -> ManagedSyntheticLaunch {
        guard UUID(uuidString: launchID)?.uuidString.lowercased() == launchID,
              Self.hostIsSupported else { throw ManagedSyntheticError.configuration }
        let (python, modules) = try validatedInterpreterAndModules()
        let native = modules.appendingPathComponent(Self.nativeName, isDirectory: false)
        guard try ManagedRuntimeFiles.digest(native, maximum: 2_097_152, requiresExecutable: true)
                == Self.nativeSHA256 else { throw ManagedSyntheticError.configuration }
        return ManagedSyntheticLaunch(executableURL: python, arguments: [
            "-I", "-S", "-B", modules.appendingPathComponent("managed_operational_entrypoint.py").path,
            "--workspace", workspace.sessionDirectoryURL.path, "--launch-id", launchID,
        ])
    }

    /// Internal validation seam keeps tests inert; public launch always checks the pinned native too.
    func validatedInterpreterAndModules() throws -> (python: URL, modules: URL) {
        let data = try ManagedRuntimeFiles.readFile(manifestURL, maximum: 16_384)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["schema_version", "profile", "python_path", "python_sha256",
                                   "module_sha256", "native_name", "native_sha256", "architecture", "minimum_macos"],
              Self.integer(object["schema_version"], equals: 2),
              let profile = object["profile"] as? String, profile == Self.profile,
              let pythonPath = object["python_path"] as? String, pythonPath.hasPrefix("/"),
              !pythonPath.contains("\0"), !pythonPath.split(separator: "/").contains(".."),
              let pythonHash = object["python_sha256"] as? String, ManagedRuntimeFiles.validHash(pythonHash),
              let moduleHashes = object["module_sha256"] as? [String: String],
              Set(moduleHashes.keys) == Self.moduleNames,
              moduleHashes.values.allSatisfy(ManagedRuntimeFiles.validHash),
              let nativeName = object["native_name"] as? String, nativeName == Self.nativeName,
              let nativeHash = object["native_sha256"] as? String, nativeHash == Self.nativeSHA256,
              let architecture = object["architecture"] as? String, architecture == "arm64",
              let minimum = object["minimum_macos"] as? String, minimum == "27.0" else {
            throw ManagedSyntheticError.configuration
        }

        let python = URL(fileURLWithPath: pythonPath)
        guard try ManagedRuntimeFiles.digest(python, maximum: 134_217_728, requiresExecutable: true) == pythonHash else {
            throw ManagedSyntheticError.configuration
        }
        let modules = manifestURL.deletingLastPathComponent()
        for name in Self.moduleNames {
            guard let expected = moduleHashes[name],
                  try ManagedRuntimeFiles.digest(modules.appendingPathComponent(name), maximum: 2_097_152)
                    == expected else { throw ManagedSyntheticError.configuration }
        }
        return (python, modules)
    }

    private static var hostIsSupported: Bool {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        guard version.majorVersion >= 27 else { return false }
        #if arch(arm64)
        return true
        #else
        return false
        #endif
    }

    private static func integer(_ value: Any?, equals expected: Int64) -> Bool {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: number.objCType)) else {
            return false
        }
        return number.int64Value == expected
    }
}
