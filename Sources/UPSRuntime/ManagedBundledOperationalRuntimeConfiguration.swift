import CoreFoundation
import CryptoKit
import Darwin
import Foundation

/// A distinct, disabled-by-default package admission. Legacy runtime v2 is unchanged.
public struct ManagedBundledOperationalRuntimeConfiguration: Sendable {
    public static let profile = "apc-smc1500i-operational-bundled-v1"
    public static let pythonRoot = "Resources/PythonRuntime"
    public static let pythonPath = pythonRoot + "/install/bin/python3.15"
    public static let backendRoot = "Resources/ManagedOperationalRuntime"
    public static let entryPath = backendRoot + "/managed_bundled_operational_entrypoint.py"
    public static let nativeName = "apcmicrolink-hidapi-operational"
    public static let nativePath = "MacOS/" + nativeName
    public static let manifestPath = backendRoot + "/runtime-bundle.json"
    public static let inventoryPath = backendRoot + "/runtime-tree.json"
    public static let moduleNames: Set<String> = [
        "managed_operational_entrypoint.py", "managed_bundled_operational_entrypoint.py",
        "app_controlled_operational.py", "operational_capture.py", "operational_publication.py",
        "continuous_capture.py", "continuous_protocol.py", "process_deadline.py",
        "bounded_stream_dispatch.py", "cleanup_diagnostics.py",
    ]
    private let contentsURL: URL
    private let expectedManifestSHA256: String
    private let hostAdmissionForTesting: Bool?

    /// Production never accepts an expected pin from a runtime file or user input.
    public static func bundled(bundle: Bundle = .main) throws -> Self {
        guard let pin = BundledOperationalReleasePins.manifestSHA256,
              ManagedRuntimeFiles.validHash(pin) else { throw ManagedSyntheticError.configuration }
        return Self(contentsURL: try bundleContentsURL(bundle),
                    expectedManifestSHA256: pin)
    }

    /// Shared path-only fixture seam; it cannot supply or enable a release pin.
    static func bundleContentsURL(_ bundle: Bundle) throws -> URL {
        let url = bundle.bundleURL.appendingPathComponent("Contents", isDirectory: true)
        let input = url.path
        guard url.isFileURL, input.hasPrefix("/"), !input.contains("\0") else {
            throw ManagedSyntheticError.configuration
        }
        // Foundation spells physical /private/tmp and /private/var as their
        // standard macOS aliases. Expand only those verified system roots.
        var candidate = input
        for (alias, target) in [("/tmp", "private/tmp"), ("/var", "private/var")] {
            if input.hasPrefix(alias + "/") {
                var info = stat()
                var bytes = [CChar](repeating: 0, count: 64)
                let count = alias.withCString { readlink($0, &bytes, bytes.count) }
                guard alias.withCString({ lstat($0, &info) }) == 0,
                      info.st_mode & S_IFMT == S_IFLNK, count > 0, count < bytes.count,
                      String(bytes: bytes.prefix(count).map { UInt8(bitPattern: $0) }, encoding: .utf8) == target else {
                    throw ManagedSyntheticError.configuration
                }
                candidate = "/private" + input
                break
            }
        }
        guard let physical = input.withCString({ realpath($0, nil) }) else {
            throw ManagedSyntheticError.configuration
        }
        defer { free(physical) }
        // Never adopt the resolution of an arbitrary app/parent/Contents link.
        guard String(cString: physical) == candidate else { throw ManagedSyntheticError.configuration }
        return URL(fileURLWithPath: candidate, isDirectory: true)
    }

    /// Internal fixture/build seam; not a UI parameter or a public initializer.
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
              hostAdmissionForTesting ?? hostSupported else {
            throw ManagedSyntheticError.configuration
        }
        let binding = try validatedBundle()
        return ManagedSyntheticLaunch(executableURL: binding.python, arguments: [
            "-I", "-S", "-B", contentsURL.appendingPathComponent(Self.entryPath).path,
            "--workspace", workspace.sessionDirectoryURL.path, "--launch-id", launchID,
            "--runtime-manifest-sha256", expectedManifestSHA256,
        ])
    }

    struct Binding {
        let python: URL
        let modules: URL
        let native: URL
        let nativeSHA256: String
    }

    func validatedBundle() throws -> Binding {
        typealias C = ManagedBundledOperationalRuntimeConfiguration
        guard ManagedRuntimeFiles.validHash(expectedManifestSHA256) else { throw ManagedSyntheticError.configuration }
        let files = try BundledFiles(contents: contentsURL)
        defer { files.close() }
        let manifestBytes = try files.read(C.manifestPath, maximum: 32768)
        guard BundledFiles.sha(manifestBytes) == expectedManifestSHA256 else { throw ManagedSyntheticError.configuration }
        let manifest = try BundledJSON.object(manifestBytes)
        try BundledFiles.keys(manifest, ["schema_version", "profile", "architecture", "minimum_macos",
                                         "python", "backend", "native", "closure", "upstream"])
        guard BundledFiles.integer(manifest["schema_version"], maximum: 1) == 1,
              manifest["profile"] as? String == C.profile, manifest["architecture"] as? String == "arm64",
              manifest["minimum_macos"] as? String == "27.0",
              let python = manifest["python"] as? [String: Any],
              let backend = manifest["backend"] as? [String: Any],
              let native = manifest["native"] as? [String: Any],
              let closure = manifest["closure"] as? [String: Any],
              let upstream = manifest["upstream"] as? [String: Any] else { throw ManagedSyntheticError.configuration }
        try BundledFiles.keys(python, ["root", "executable", "sha256"])
        try BundledFiles.keys(backend, ["root", "entrypoint", "module_sha256"])
        try BundledFiles.keys(native, ["path", "name", "sha256", "bytes"])
        try BundledFiles.keys(closure, ["path", "sha256", "entries"])
        try BundledFiles.keys(upstream, ["archive_sha256", "metadata_sha256"])
        guard python["root"] as? String == C.pythonRoot, python["executable"] as? String == C.pythonPath,
              backend["root"] as? String == C.backendRoot, backend["entrypoint"] as? String == C.entryPath,
              native["path"] as? String == C.nativePath, native["name"] as? String == C.nativeName,
              closure["path"] as? String == C.inventoryPath,
              let pythonHash = python["sha256"] as? String, ManagedRuntimeFiles.validHash(pythonHash),
              let nativeHash = native["sha256"] as? String, ManagedRuntimeFiles.validHash(nativeHash),
              let nativeBytes = BundledFiles.integer(native["bytes"], maximum: 2097152), nativeBytes > 0,
              let inventoryHash = closure["sha256"] as? String, ManagedRuntimeFiles.validHash(inventoryHash),
              let entryCount = BundledFiles.integer(closure["entries"], maximum: 20000), entryCount > 0,
              let moduleHashes = backend["module_sha256"] as? [String: String],
              Set(moduleHashes.keys) == C.moduleNames, moduleHashes.values.allSatisfy(ManagedRuntimeFiles.validHash),
              let archiveHash = upstream["archive_sha256"] as? String, ManagedRuntimeFiles.validHash(archiveHash),
              let metadataHash = upstream["metadata_sha256"] as? String, ManagedRuntimeFiles.validHash(metadataHash)
        else { throw ManagedSyntheticError.configuration }
        let inventoryBytes = try files.read(C.inventoryPath, maximum: 16 * 1048576)
        guard BundledFiles.sha(inventoryBytes) == inventoryHash else { throw ManagedSyntheticError.configuration }
        let inventory = try BundledJSON.object(inventoryBytes)
        try BundledFiles.keys(inventory, ["schema_version", "entries"])
        guard BundledFiles.integer(inventory["schema_version"], maximum: 1) == 1,
              let entries = inventory["entries"] as? [String: [String: Any]], entries.count == entryCount
        else { throw ManagedSyntheticError.configuration }
        try files.verifyClosure(entries)
        func pinned(_ path: String, _ hash: String, size: Int? = nil, executable: Bool = false) throws {
            guard let row = entries[path], row["type"] as? String == "file", row["sha256"] as? String == hash,
                  (!executable || row["mode"] as? String == "0755" &&
                    (BundledFiles.integer(row["bytes"], maximum: 128 * 1048576) ?? 0) > 0),
                  (size == nil || BundledFiles.integer(row["bytes"], maximum: 128 * 1048576) == size)
            else { throw ManagedSyntheticError.configuration }
        }
        try pinned(C.pythonPath, pythonHash, executable: true)
        try pinned(C.nativePath, nativeHash, size: nativeBytes, executable: true)
        for (name, hash) in moduleHashes { try pinned(C.backendRoot + "/" + name, hash) }
        // Recheck control files and the named root after the full payload pass.
        guard try files.read(C.manifestPath, maximum: 32768) == manifestBytes,
              try files.read(C.inventoryPath, maximum: 16 * 1048576) == inventoryBytes else {
            throw ManagedSyntheticError.configuration
        }
        try files.verifyNamedRoot()
        return Binding(python: contentsURL.appendingPathComponent(C.pythonPath),
                       modules: contentsURL.appendingPathComponent(C.backendRoot),
                       native: contentsURL.appendingPathComponent(C.nativePath), nativeSHA256: nativeHash)
    }
}

/// Minimal strict JSON pass: no arrays exist in this closed schema; duplicate keys fail.
struct BundledJSON {
    var bytes: [UInt8]
    var index = 0
    static func object(_ data: Data) throws -> [String: Any] {
        var parser = Self(bytes: Array(data))
        try parser.value(depth: 0)
        parser.space()
        guard parser.index == parser.bytes.count,
              let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ManagedSyntheticError.configuration
        }
        return result
    }
    mutating func space() { while index < bytes.count && [9, 10, 13, 32].contains(bytes[index]) { index += 1 } }
    mutating func string() throws -> String {
        let start = index
        guard index < bytes.count && bytes[index] == 34 else { throw ManagedSyntheticError.configuration }
        index += 1
        while index < bytes.count {
            let byte = bytes[index]; index += 1
            if byte == 34 {
                guard let result = try JSONSerialization.jsonObject(with: Data(bytes[start..<index]),
                    options: .fragmentsAllowed) as? String else { throw ManagedSyntheticError.configuration }
                return result
            }
            if byte == 92 {
                guard index < bytes.count else { throw ManagedSyntheticError.configuration }
                index += 1
            }
        }
        throw ManagedSyntheticError.configuration
    }
    mutating func value(depth: Int) throws {
        space()
        guard depth <= 32 && index < bytes.count else { throw ManagedSyntheticError.configuration }
        if bytes[index] == 123 {
            index += 1; space()
            var keys = Set<String>()
            if index < bytes.count && bytes[index] == 125 { index += 1; return }
            while true {
                space(); let key = try string()
                guard keys.insert(key).inserted else { throw ManagedSyntheticError.configuration }
                space()
                guard index < bytes.count && bytes[index] == 58 else { throw ManagedSyntheticError.configuration }
                index += 1; try value(depth: depth + 1); space()
                guard index < bytes.count else { throw ManagedSyntheticError.configuration }
                let delimiter = bytes[index]; index += 1
                if delimiter == 125 { return }
                guard delimiter == 44 else { throw ManagedSyntheticError.configuration }
            }
        }
        if bytes[index] == 34 { _ = try string(); return }
        if bytes[index] == 91 { throw ManagedSyntheticError.configuration }
        let start = index
        while index < bytes.count && ![9, 10, 13, 32, 44, 125].contains(bytes[index]) { index += 1 }
        guard index > start else { throw ManagedSyntheticError.configuration }
        let token = Data(bytes[start..<index])
        _ = try JSONSerialization.jsonObject(with: token, options: .fragmentsAllowed)
    }
}

final class BundledFiles {
    typealias C = ManagedBundledOperationalRuntimeConfiguration
    let contents: URL
    let root: Int32
    let rootDevice: dev_t
    let rootInode: ino_t
    private var closed = false
    init(contents: URL) throws {
        guard contents.isFileURL, contents.lastPathComponent == "Contents",
              !contents.path.utf8.contains(0) else { throw ManagedSyntheticError.configuration }
        // Foundation can preserve system aliases such as /var on macOS. Require
        // the caller's spelling to be the POSIX canonical path before the
        // descriptor walk; never adopt a path by following its aliases.
        guard let canonical = contents.path.withCString({ realpath($0, nil) }) else {
            throw ManagedSyntheticError.configuration
        }
        defer { free(canonical) }
        guard String(cString: canonical) == contents.path else { throw ManagedSyntheticError.configuration }
        self.contents = contents
        var fd = Darwin.open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        guard fd >= 0 else { throw ManagedSyntheticError.configuration }
        do {
            for part in contents.path.split(separator: "/") {
                let next = String(part).withCString { openat(fd, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
                guard next >= 0 else { throw ManagedSyntheticError.configuration }
                Darwin.close(fd); fd = next
            }
            var info = stat()
            guard fstat(fd, &info) == 0 && info.st_mode & 0o022 == 0 else { throw ManagedSyntheticError.configuration }
            root = fd; rootDevice = info.st_dev; rootInode = info.st_ino
        } catch { Darwin.close(fd); throw error }
    }
    func close() { if !closed { Darwin.close(root); closed = true } }
    deinit { close() }
    static func keys(_ object: [String: Any], _ expected: Set<String>) throws {
        guard Set(object.keys) == expected else { throw ManagedSyntheticError.configuration }
    }
    static func integer(_ value: Any?, maximum: Int) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: number.objCType)),
              number.int64Value >= 0, number.uint64Value <= UInt64(maximum) else { return nil }
        return number.intValue
    }
    static func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func path(_ value: String) throws -> [String] {
        let parts = value.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard !value.isEmpty && value.utf8.count <= 4096 && parts.count <= 64,
              value.utf8.allSatisfy({ $0 >= 32 && $0 < 127 }),
              !value.contains("\\"), !parts.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else {
            throw ManagedSyntheticError.configuration
        }
        return parts
    }
    func descriptor(_ path: String, directory: Bool = false) throws -> Int32 {
        let parts = try Self.path(path)
        var current = dup(root)
        guard current >= 0 else { throw ManagedSyntheticError.configuration }
        do {
            for (index, part) in parts.enumerated() {
                let isDirectory = directory || index < parts.count - 1
                let flags = O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK | (isDirectory ? O_DIRECTORY : 0)
                let next = part.withCString { openat(current, $0, flags) }
                guard next >= 0 else { throw ManagedSyntheticError.configuration }
                Darwin.close(current); current = next
                var info = stat()
                guard fstat(current, &info) == 0 && info.st_mode & 0o022 == 0 else { throw ManagedSyntheticError.configuration }
            }
            return current
        } catch { Darwin.close(current); throw error }
    }
    private func stamp(_ s: stat) -> [Int64] {
        [Int64(s.st_dev), Int64(s.st_ino), Int64(s.st_size), Int64(s.st_mode),
         Int64(s.st_mtimespec.tv_sec), Int64(s.st_mtimespec.tv_nsec),
         Int64(s.st_ctimespec.tv_sec), Int64(s.st_ctimespec.tv_nsec)]
    }
    func read(_ path: String, maximum: Int) throws -> Data {
        let fd = try descriptor(path); let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat(), after = stat()
        guard fstat(fd, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_nlink == 1, before.st_mode & 0o7000 == 0,
              before.st_size >= 0 && before.st_size <= maximum else { throw ManagedSyntheticError.configuration }
        var data = Data()
        var left = Int(before.st_size)
        while left > 0 {
            guard let block = try handle.read(upToCount: min(65536, left)), !block.isEmpty else {
                throw ManagedSyntheticError.configuration
            }
            data.append(block); left -= block.count
        }
        guard (try handle.read(upToCount: 1) ?? Data()).isEmpty, fstat(fd, &after) == 0,
              stamp(before) == stamp(after) else { throw ManagedSyntheticError.configuration }
        let named = try descriptor(path); defer { Darwin.close(named) }
        var current = stat()
        guard fstat(named, &current) == 0 && stamp(current) == stamp(before) else { throw ManagedSyntheticError.configuration }
        return data
    }
    func verifyNamedRoot() throws {
        let check = try BundledFiles(contents: contents); defer { check.close() }
        guard check.rootDevice == rootDevice && check.rootInode == rootInode else { throw ManagedSyntheticError.configuration }
    }
    func verifyClosure(_ entries: [String: [String: Any]],
                       roots: [String] = [C.pythonRoot, C.backendRoot],
                       nativePath: String = C.nativePath,
                       controls: Set<String> = [C.manifestPath, C.inventoryPath],
                       parents: Set<String> = ["Resources", "MacOS"],
                       sameRootLinks: Bool = false) throws {
        var aliases = Set<String>(); var total = 0
        for (name, row) in entries {
            _ = try Self.path(name)
            guard aliases.insert(name.lowercased()).inserted,
                  !controls.contains(name),
                  roots.contains(where: { name == $0 || name.hasPrefix($0 + "/") }) || name == nativePath,
                  let type = row["type"] as? String, let mode = row["mode"] as? String else {
                throw ManagedSyntheticError.configuration
            }
            switch type {
            case "directory": try Self.keys(row, ["type", "mode"])
                guard mode == "0755" else { throw ManagedSyntheticError.configuration }
            case "file": try Self.keys(row, ["type", "mode", "bytes", "sha256"])
                guard ["0644", "0755"].contains(mode),
                      let size = Self.integer(row["bytes"], maximum: 128 * 1048576),
                      let hash = row["sha256"] as? String, ManagedRuntimeFiles.validHash(hash) else {
                    throw ManagedSyntheticError.configuration
                }
                total += size
            case "symlink": try Self.keys(row, ["type", "mode", "target", "resolved_target"])
                guard mode == "0777", row["target"] is String, row["resolved_target"] is String else {
                    throw ManagedSyntheticError.configuration
                }
            default: throw ManagedSyntheticError.configuration
            }
        }
        guard total <= 1073741824, roots.allSatisfy({ entries[$0]?["type"] as? String == "directory" })
        else { throw ManagedSyntheticError.configuration }
        for name in entries.keys {
            let parts = try Self.path(name)
            if parts.count > 1 {
                for length in 1..<parts.count {
                    let parent = parts.prefix(length).joined(separator: "/")
                    guard parents.contains(parent) || entries[parent]?["type"] as? String == "directory"
                    else { throw ManagedSyntheticError.configuration }
                }
            }
        }
        for (name, row) in entries where row["type"] as? String == "symlink" {
            guard let target = row["target"] as? String, let expected = row["resolved_target"] as? String,
                  try resolve(name, target: target, entries: entries, parents: parents) == expected,
                  !sameRootLinks || roots.contains(where: { name.hasPrefix($0 + "/") && expected.hasPrefix($0 + "/") })
            else { throw ManagedSyntheticError.configuration }
        }
        var found = Set<String>()
        for prefix in roots {
            let fd = try descriptor(prefix, directory: true)
            do { try visit(fd, prefix: prefix, entries: entries, found: &found, controls: controls); Darwin.close(fd) }
            catch { Darwin.close(fd); throw error }
        }
        try verifyNode(nativePath, entries: entries); found.insert(nativePath)
        guard found == Set(entries.keys) else { throw ManagedSyntheticError.configuration }
    }
    private func joined(_ name: String, target: String, suffix: ArraySlice<String> = []) throws -> String {
        guard !target.isEmpty && !target.hasPrefix("/"), !target.contains("\\"),
              target.utf8.count <= 4096 && target.utf8.allSatisfy({ $0 >= 32 && $0 < 127 }) else {
            throw ManagedSyntheticError.configuration
        }
        var parts = Array(try Self.path(name).dropLast())
        for part in target.split(separator: "/", omittingEmptySubsequences: false).map(String.init) + Array(suffix) {
            if part.isEmpty || part == "." { continue }
            if part == ".." {
                guard !parts.isEmpty else { throw ManagedSyntheticError.configuration }
                parts.removeLast()
            } else { parts.append(part) }
        }
        let result = parts.joined(separator: "/"); _ = try Self.path(result); return result
    }
    private func resolve(_ name: String, target: String, entries: [String: [String: Any]], parents: Set<String>) throws -> String {
        var current = try joined(name, target: target); var seen: Set<String> = [name]
        while true {
            let parts = try Self.path(current); var changed = false
            for length in 1...parts.count {
                let prefix = parts.prefix(length).joined(separator: "/")
                if parents.contains(prefix) { continue }
                guard let row = entries[prefix], let type = row["type"] as? String else { throw ManagedSyntheticError.configuration }
                if type == "symlink" {
                    guard seen.insert(prefix).inserted, let next = row["target"] as? String else { throw ManagedSyntheticError.configuration }
                    current = try joined(prefix, target: next, suffix: parts.dropFirst(length)); changed = true; break
                }
                guard length == parts.count || type == "directory" else { throw ManagedSyntheticError.configuration }
            }
            if !changed { return current }
        }
    }
    private func verifyNode(_ name: String, entries: [String: [String: Any]]) throws {
        guard let row = entries[name], let type = row["type"] as? String, let mode = row["mode"] as? String,
              let expectedMode = UInt16(mode, radix: 8) else { throw ManagedSyntheticError.configuration }
        let parts = try Self.path(name); let leaf = parts.last!
        let parent: Int32
        if parts.count == 1 { parent = dup(root) }
        else { parent = try descriptor(parts.dropLast().joined(separator: "/"), directory: true) }
        defer { Darwin.close(parent) }
        var info = stat()
        guard leaf.withCString({ fstatat(parent, $0, &info, AT_SYMLINK_NOFOLLOW) }) == 0,
              info.st_mode & 0o7777 == expectedMode else { throw ManagedSyntheticError.configuration }
        if type == "directory" {
            guard info.st_mode & S_IFMT == S_IFDIR else { throw ManagedSyntheticError.configuration }
        } else if type == "symlink" {
            guard info.st_mode & S_IFMT == S_IFLNK && info.st_nlink == 1 else { throw ManagedSyntheticError.configuration }
            var buffer = [CChar](repeating: 0, count: 4098)
            let count = leaf.withCString { readlinkat(parent, $0, &buffer, buffer.count - 1) }
            guard count > 0 && count < buffer.count - 1,
                  String(bytes: buffer.prefix(count).map { UInt8(bitPattern: $0) }, encoding: .utf8) == row["target"] as? String
            else { throw ManagedSyntheticError.configuration }
        } else {
            guard info.st_mode & S_IFMT == S_IFREG,
                  let size = Self.integer(row["bytes"], maximum: 128 * 1048576), info.st_size == size,
                  let hash = row["sha256"] as? String,
                  try Self.sha(read(name, maximum: 128 * 1048576)) == hash else { throw ManagedSyntheticError.configuration }
        }
    }
    private func visit(_ fd: Int32, prefix: String, entries: [String: [String: Any]], found: inout Set<String>, controls: Set<String>) throws {
        try verifyNode(prefix, entries: entries); found.insert(prefix)
        let copied = dup(fd)
        guard copied >= 0 else { throw ManagedSyntheticError.configuration }
        guard let directory = fdopendir(copied) else { Darwin.close(copied); throw ManagedSyntheticError.configuration }
        defer { closedir(directory) }
        errno = 0
        while let item = readdir(directory) {
            let name = withUnsafePointer(to: &item.pointee.d_name) { pointer in
                pointer.withMemoryRebound(to: CChar.self, capacity: Int(MAXNAMLEN) + 1) { String(cString: $0) }
            }
            if name == "." || name == ".." { continue }
            let path = prefix + "/" + name
            if controls.contains(path) { continue }
            try verifyNode(path, entries: entries); found.insert(path)
            if entries[path]?["type"] as? String == "directory" {
                let child = name.withCString { openat(fd, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
                guard child >= 0 else { throw ManagedSyntheticError.configuration }
                do { try visit(child, prefix: path, entries: entries, found: &found, controls: controls); Darwin.close(child) }
                catch { Darwin.close(child); throw error }
            }
            errno = 0
        }
        guard errno == 0 else { throw ManagedSyntheticError.configuration }
    }
}
