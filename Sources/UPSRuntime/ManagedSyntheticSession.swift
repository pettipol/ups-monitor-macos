import CryptoKit
import Darwin
import Foundation
import Observation

public enum ManagedSyntheticError: Error, Sendable { case configuration, ownership, receipt }

public struct ManagedSyntheticLaunch: Sendable {
    public let executableURL: URL
    public let arguments: [String]
}

/// Developer-owned bundle configuration, never a UI path or environment override.
public struct ManagedSyntheticRuntimeConfiguration: Sendable {
    public static let moduleNames: Set<String> = [
        "managed_synthetic_entrypoint.py", "app_controlled_capture.py", "continuous_capture.py",
        "continuous_protocol.py", "process_deadline.py", "synthetic_continuous_feed.py",
        "synthetic_continuous_stream.py",
    ]
    public let manifestURL: URL

    public init(manifestURL: URL) { self.manifestURL = manifestURL }

    public static func bundled(bundle: Bundle = .main) throws -> Self {
        guard let resources = bundle.resourceURL else { throw ManagedSyntheticError.configuration }
        return Self(manifestURL: resources.appendingPathComponent("ManagedSyntheticRuntime/runtime.json"))
    }

    public func launch(workspace: ManagedSessionWorkspace, launchID: String) throws -> ManagedSyntheticLaunch {
        struct Manifest: Decodable { let python_path: String; let python_sha256: String; let module_sha256: [String: String] }
        let data = try ManagedRuntimeFiles.readFile(manifestURL, maximum: 16_384)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["python_path", "python_sha256", "module_sha256"] else {
            throw ManagedSyntheticError.configuration
        }
        let manifest = try JSONDecoder().decode(Manifest.self, from: data)
        guard manifest.python_path.hasPrefix("/"), !manifest.python_path.contains("\0"),
              ManagedRuntimeFiles.validHash(manifest.python_sha256), Set(manifest.module_sha256.keys) == Self.moduleNames else {
            throw ManagedSyntheticError.configuration
        }
        let python = URL(fileURLWithPath: manifest.python_path)
        guard try ManagedRuntimeFiles.digest(python) == manifest.python_sha256 else { throw ManagedSyntheticError.configuration }
        let modules = manifestURL.deletingLastPathComponent()
        for (name, expected) in manifest.module_sha256 {
            guard ManagedRuntimeFiles.validHash(expected),
                  SHA256.hash(data: try ManagedRuntimeFiles.readFile(modules.appendingPathComponent(name), maximum: 2_097_152))
                    .map({ String(format: "%02x", $0) }).joined() == expected else {
                throw ManagedSyntheticError.configuration
            }
        }
        return ManagedSyntheticLaunch(executableURL: python, arguments: [
            "-I", "-S", "-B", modules.appendingPathComponent("managed_synthetic_entrypoint.py").path,
            "--workspace", workspace.sessionDirectoryURL.path, "--launch-id", launchID,
        ])
    }

}

/// Shared bounded, no-follow file validation for both closed runtime profiles.
enum ManagedRuntimeFiles {
    static func validHash(_ value: String) -> Bool {
        value.count == 64 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    static func digest(_ url: URL, maximum: Int = 134_217_728, requiresExecutable: Bool = false) throws -> String {
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        guard descriptor >= 0 else { throw ManagedSyntheticError.configuration }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_size > 0, info.st_size <= maximum,
              !requiresExecutable || info.st_mode & 0o111 != 0 else { throw ManagedSyntheticError.configuration }
        var digest = SHA256()
        var remaining = Int(info.st_size)
        while remaining > 0 {
            guard let block = try handle.read(upToCount: min(65_536, remaining)), !block.isEmpty else {
                throw ManagedSyntheticError.configuration
            }
            digest.update(data: block); remaining -= block.count
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }
    static func readFile(_ url: URL, maximum: Int) throws -> Data {
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        guard descriptor >= 0 else { throw ManagedSyntheticError.configuration }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_size > 0, info.st_size <= maximum,
              let data = try handle.read(upToCount: maximum), data.count == Int(info.st_size) else {
            throw ManagedSyntheticError.configuration
        }
        return data
    }
}

/// The open directory/file identities remain pinned until a receipt and reap prove resolution.
final class ManagedSyntheticOwner {
    private final class Descriptors {
        let root: Int32, session: Int32, marker: Int32
        init(_ root: Int32, _ session: Int32, _ marker: Int32) { self.root = root; self.session = session; self.marker = marker }
        deinit { _ = close(marker); _ = close(session); _ = close(root) }
    }
    private let descriptors: Descriptors
    private var rootFD: Int32 { descriptors.root }
    private var sessionFD: Int32 { descriptors.session }
    private var markerFD: Int32 { descriptors.marker }
    private let rootURL: URL
    private let sessionName: String
    private let name = "active-owner.json"

    init(root: URL, workspace: ManagedSessionWorkspace, launchID: String) throws {
        rootURL = root
        let rootFD = open(root.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard rootFD >= 0 else { throw ManagedSyntheticError.ownership }
        sessionName = workspace.sessionDirectoryURL.lastPathComponent
        let sessionFD = openat(rootFD, sessionName, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard sessionFD >= 0 else { _ = close(rootFD); throw ManagedSyntheticError.ownership }
        let markerFD = openat(rootFD, "active-owner.json", O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard markerFD >= 0 else {
            _ = close(sessionFD); _ = close(rootFD); throw ManagedSyntheticError.ownership
        }
        descriptors = Descriptors(rootFD, sessionFD, markerFD)
        do {
            let data = try JSONSerialization.data(withJSONObject: ["schema_version": 1,
                "launch_id": launchID, "session": sessionName, "state": "pending"])
            try data.withUnsafeBytes { bytes in
                var offset = 0
                while offset < bytes.count {
                    let written = Darwin.write(markerFD, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                    guard written > 0 else { throw ManagedSyntheticError.ownership }
                    offset += written
                }
            }
            guard fsync(markerFD) == 0, fsync(rootFD) == 0, secureMarker() else {
                throw ManagedSyntheticError.ownership
            }
        } catch {
            throw error // The marker is deliberately retained on every failure.
        }
    }

    func resolve() throws {
        guard secureMarker(), renameatx_np(rootFD, name, sessionFD, "resolved-owner.json", UInt32(RENAME_EXCL)) == 0,
              fsync(sessionFD) == 0, fsync(rootFD) == 0 else { throw ManagedSyntheticError.ownership }
    }

    func archiveManagedReceipt(_ data: Data) throws {
        guard !data.isEmpty, data.count <= 65_536 else { throw ManagedSyntheticError.receipt }
        try writeSessionFileAtomically(data, temporary: "managed-receipt.tmp", final: "managed-receipt.json",
                                       maximumBytes: 65_536)
    }

    func writeManagedReceiptStatus(_ state: String, launchID: String,
                                   byteCount: Int, sha256: String) throws {
        guard ["valid", "invalid", "absent"].contains(state),
              launchID.count == 36, byteCount >= 0,
              sha256.count == 64, sha256.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
            throw ManagedSyntheticError.receipt
        }
        let value: [String: Any] = ["schema_version": 1, "launch_id": launchID,
                                    "state": state, "byte_count": byteCount, "sha256": sha256]
        var data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        data.append(10)
        guard data.count <= 1_024 else { throw ManagedSyntheticError.receipt }
        try writeSessionFileAtomically(data, temporary: "managed-receipt-status.tmp",
                                       final: "managed-receipt-status.json", maximumBytes: 1_024)
    }

    private func writeSessionFileAtomically(_ data: Data, temporary: String, final: String,
                                            maximumBytes: Int) throws {
        guard !data.isEmpty, data.count <= maximumBytes, secureMarker() else {
            throw ManagedSyntheticError.ownership
        }
        let descriptor = temporary.withCString {
            openat(sessionFD, $0, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        }
        guard descriptor >= 0 else { throw ManagedSyntheticError.ownership }
        defer { _ = Darwin.close(descriptor) }
        guard secureSessionFile(descriptor, name: temporary, maximumBytes: maximumBytes,
                                expectedBytes: 0) else {
            throw ManagedSyntheticError.ownership
        }
        let writeSucceeded = data.withUnsafeBytes { bytes -> Bool in
            guard let base = bytes.baseAddress else { return false }
            var offset = 0
            while offset < bytes.count {
                let count = Darwin.write(descriptor, base.advanced(by: offset), bytes.count - offset)
                guard count > 0 else { return false }
                offset += count
            }
            return true
        }
        guard writeSucceeded, fsync(descriptor) == 0,
              secureMarker(), secureSessionFile(descriptor, name: temporary, maximumBytes: maximumBytes,
                                                expectedBytes: data.count),
              renameatx_np(sessionFD, temporary, sessionFD, final, UInt32(RENAME_EXCL)) == 0,
              fsync(sessionFD) == 0, secureMarker(),
              secureSessionFile(descriptor, name: final, maximumBytes: maximumBytes,
                                expectedBytes: data.count) else {
            throw ManagedSyntheticError.ownership
        }
    }

    private func secureSessionFile(_ descriptor: Int32, name: String,
                                   maximumBytes: Int, expectedBytes: Int) -> Bool {
        var opened = stat(), named = stat(), session = stat(), sessionNamed = stat()
        let result = name.withCString { fstatat(sessionFD, $0, &named, AT_SYMLINK_NOFOLLOW) }
        guard fstat(descriptor, &opened) == 0, result == 0,
              fstat(sessionFD, &session) == 0,
              fstatat(rootFD, sessionName, &sessionNamed, AT_SYMLINK_NOFOLLOW) == 0,
              session.st_dev == sessionNamed.st_dev, session.st_ino == sessionNamed.st_ino,
              session.st_mode & S_IFMT == S_IFDIR, session.st_mode & 0o7777 == 0o700,
              session.st_uid == getuid(),
              opened.st_dev == named.st_dev, opened.st_ino == named.st_ino,
              opened.st_mode & S_IFMT == S_IFREG, opened.st_mode & 0o7777 == 0o600,
              opened.st_uid == getuid(), opened.st_nlink == 1,
              opened.st_size == off_t(expectedBytes), opened.st_size <= off_t(maximumBytes),
              Self.emptyACL(sessionFD), Self.emptyACL(descriptor) else { return false }
        return true
    }

    private func secureMarker() -> Bool {
        var opened = stat(), named = stat(), root = stat(), rootNamed = stat(), session = stat(), sessionNamed = stat()
        guard fstat(markerFD, &opened) == 0, fstatat(rootFD, name, &named, AT_SYMLINK_NOFOLLOW) == 0,
              fstat(rootFD, &root) == 0, lstat(rootURL.path, &rootNamed) == 0,
              root.st_dev == rootNamed.st_dev, root.st_ino == rootNamed.st_ino,
              root.st_mode & 0o7777 == 0o700, root.st_uid == getuid(),
              fstat(sessionFD, &session) == 0, fstatat(rootFD, sessionName, &sessionNamed, AT_SYMLINK_NOFOLLOW) == 0,
              session.st_dev == sessionNamed.st_dev, session.st_ino == sessionNamed.st_ino,
              session.st_mode & 0o7777 == 0o700, session.st_uid == getuid(),
              opened.st_dev == named.st_dev, opened.st_ino == named.st_ino,
              opened.st_mode & S_IFMT == S_IFREG, opened.st_mode & 0o7777 == 0o600,
              opened.st_uid == getuid(), opened.st_nlink == 1 else { return false }
        return [rootFD, sessionFD, markerFD].allSatisfy(Self.emptyACL)
    }
    private static func emptyACL(_ descriptor: Int32) -> Bool {
        errno = 0
        guard let acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED) else { return errno == ENOENT }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        var entry: acl_entry_t?
        guard acl_valid(acl) == 0 else { return false }
        errno = 0
        return acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry) == -1 && errno == EINVAL
    }
}

enum ManagedRuntimeProfile: Sendable {
    case synthetic, native, operational
    var receiptProtocol: String {
        switch self {
        case .synthetic: "ups-monitor.managed-synthetic.v1"
        case .native: "ups-monitor.managed-native.v1"
        case .operational: "ups-monitor.managed-operational.v2"
        }
    }
    var sourceID: String {
        switch self {
        case .synthetic: "synthetic-app-session"
        case .native: "apcmicrolink-hidapi-continuous"
        case .operational: "apcmicrolink-hidapi-operational"
        }
    }
    var caption: String {
        switch self {
        case .synthetic: "Synthetic · unqualified"
        case .native: "Native 120 s · unqualified"
        case .operational: "Operational · unqualified"
        }
    }
}

private struct ManagedReceiptSummary {
    let captureState: String
    let terminalReason: String
    let adapterError: String?
    let operational: Bool
}

struct ManagedSyntheticReceipt: Decodable {
    struct Capture: Decodable {
        let state: String; let terminal_reason: String; let source_id: String; let session_id: String
        let runner_status: String; let returncode: Int?; let tailer_quiesced: Bool
        let publication_error: String?; let sample_count: Int; let stdout_bytes: Int; let stderr_bytes: Int
        let started_at_unix_ms: Int64; let published_at_unix_ms: Int64; let end_reason: String?
    }
    struct Adapter: Decodable {
        let capture_result: Capture?; let control_reason: String?; let adapter_error: String?
        let watcher_quiesced: Bool; let ownership_resolved: Bool
    }
    let `protocol`: String; let schema_version: Int; let launch_id: String; let adapter: Adapter

    static func decode(_ data: Data, launchID: String, profile: ManagedRuntimeProfile = .synthetic) throws -> Self {
        guard data.count <= 65_536, data.last == 10,
              data.dropLast().contains(10) == false,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["protocol", "schema_version", "launch_id", "adapter"],
              let adapter = object["adapter"] as? [String: Any],
              Set(adapter.keys) == ["capture_result", "control_reason", "adapter_error", "watcher_quiesced", "ownership_resolved"] else {
            throw ManagedSyntheticError.receipt
        }
        if let capture = adapter["capture_result"] as? [String: Any] {
            guard Set(capture.keys) == ["state", "terminal_reason", "source_id", "session_id",
                "started_at_unix_ms", "published_at_unix_ms", "sample_count", "end_reason", "returncode",
                "runner_status", "stdout_bytes", "stderr_bytes", "publication_error", "tailer_quiesced"] else {
                throw ManagedSyntheticError.receipt
            }
        }
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.protocol == profile.receiptProtocol, value.schema_version == 1,
              value.launch_id == launchID else { throw ManagedSyntheticError.receipt }
        return value
    }
    var provesCleanup: Bool { provesCleanup(profile: .synthetic) }
    func provesCleanup(profile: ManagedRuntimeProfile) -> Bool {
        guard adapter.ownership_resolved, adapter.watcher_quiesced, adapter.adapter_error == nil,
              let capture = adapter.capture_result, capture.tailer_quiesced, capture.publication_error == nil,
              capture.source_id == profile.sourceID, (0...24).contains(capture.sample_count),
              capture.session_id.count == 32, capture.session_id.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              capture.started_at_unix_ms > 0, capture.published_at_unix_ms >= capture.started_at_unix_ms,
              capture.stdout_bytes >= 0, capture.stderr_bytes >= 0,
              capture.stdout_bytes <= 1_048_576 - capture.stderr_bytes else { return false }
        let reasonAllowed = ["cancelled", "device_lost", "session_lost", "guard_error", "output_error",
            "protocol_error", "capture_limit", "deadline", "child_failed", "io_error"].contains(capture.terminal_reason)
        let stateAllowed = capture.state == "stopped"
            ? capture.terminal_reason == "duration_complete" && capture.runner_status == "exited"
                && capture.returncode == 0 && capture.end_reason == "duration_complete" && capture.sample_count > 0
            : capture.state == "failed" && reasonAllowed
        return stateAllowed && ["exited", "cancelled", "timed_out", "output_limit", "output_incomplete"].contains(capture.runner_status)
            && (capture.returncode != nil || capture.runner_status == "cancelled")
    }
}

public enum ManagedSyntheticSessionState: String, Sendable {
    case idle, starting, active, stopping, completed, stopped, failed, unresolved
}

public enum ManagedReceiptArchiveState: String, Sendable {
    case notRequested, pending, valid, invalid, absent, writeFailed
}

@Observable @MainActor
public final class ManagedSyntheticSessionController {
    public private(set) var state: ManagedSyntheticSessionState = .idle
    public private(set) var receiptArchiveState: ManagedReceiptArchiveState = .notRequested
    public private(set) var workspace: ManagedSessionWorkspace?
    public private(set) var attempted = false
    public private(set) var launchInvoked = false
    public var message: String { "\(profile.caption) · \(state.rawValue)" }
    public var canStop: Bool { state == .starting || state == .active || state == .stopping }
    @ObservationIgnored private let root: () throws -> URL
    @ObservationIgnored private let makeProcess: () -> any ManagedSyntheticProcessHandle
    @ObservationIgnored private var profile: ManagedRuntimeProfile = .synthetic
    @ObservationIgnored private var process: (any ManagedSyntheticProcessHandle)?
    @ObservationIgnored private var owner: ManagedSyntheticOwner?
    @ObservationIgnored private var launchID = ""
    @ObservationIgnored private var cleanupProved = false
    @ObservationIgnored private var finishedReceived = false
    @ObservationIgnored private var waiters: [CheckedContinuation<Bool, Never>] = []

    public init(root: @escaping () throws -> URL = { try ManagedSessionRoot.resolve() },
                makeProcess: @escaping () -> any ManagedSyntheticProcessHandle = { ManagedSyntheticProcess() }) {
        self.root = root; self.makeProcess = makeProcess
    }
    public func start(configuration: ManagedSyntheticRuntimeConfiguration) throws -> URL {
        try start(profile: .synthetic) { try configuration.launch(workspace: $0, launchID: $1) }
    }
    public func start(nativeConfiguration: ManagedNativeRuntimeConfiguration) throws -> URL {
        try start(profile: .native) { try nativeConfiguration.launch(workspace: $0, launchID: $1) }
    }
    public func start(operationalConfiguration: ManagedOperationalRuntimeConfiguration) throws -> URL {
        try start(profile: .operational) { try operationalConfiguration.launch(workspace: $0, launchID: $1) }
    }
    public func start(bundledOperationalConfiguration: ManagedBundledOperationalRuntimeConfiguration) throws -> URL {
        try start(profile: .operational) { try bundledOperationalConfiguration.launch(workspace: $0, launchID: $1) }
    }
    public func start(frozenOperationalConfiguration: ManagedFrozenOperationalRuntimeConfiguration) throws -> URL {
        try start(profile: .operational) { try frozenOperationalConfiguration.launch(workspace: $0, launchID: $1) }
    }
    // Internal injection seam for lifecycle tests; public starts always validate their fixed configuration.
    func start(profile: ManagedRuntimeProfile,
               launch: (ManagedSessionWorkspace, String) throws -> ManagedSyntheticLaunch) throws -> URL {
        guard !attempted else { throw ManagedSyntheticError.ownership }
        self.profile = profile
        if case .operational = profile { receiptArchiveState = .pending }
        else { receiptArchiveState = .notRequested }
        attempted = true; state = .starting
        do {
            let root = try root()
            let workspace = try ManagedSessionWorkspace.create(in: root)
            self.workspace = workspace
            launchID = UUID().uuidString.lowercased()
            let launch = try launch(workspace, launchID)
            owner = try ManagedSyntheticOwner(root: root, workspace: workspace, launchID: launchID)
            let process = makeProcess()
            self.process = process // Retain even when launch throws ambiguously.
            launchInvoked = true
            try process.start(launch) { [weak self] event in self?.receive(event) }
            return workspace.feedDirectoryURL
        } catch {
            state = .unresolved
            finishWaiters(false)
            throw error
        }
    }
    public func markFeedReady() { if state == .starting { state = .active } }
    public func requestStop() {
        guard canStop else { return }
        state = .stopping; process?.requestStop()
    }
    public func stopAndWait() async -> Bool {
        if !attempted || !launchInvoked || cleanupProved { return true }
        if state == .unresolved { return false }
        return await withCheckedContinuation {
            waiters.append($0) // A process handle may report completion synchronously.
            requestStop()
        }
    }
    private func receive(_ event: ManagedSyntheticProcessEvent) {
        guard !cleanupProved else { return } // Both EOFs and reap already fixed the final evidence.
        switch event {
        case let .receipt(data):
            guard (try? decodeReceipt(data)) != nil else {
                state = .unresolved; process?.requestStop(); finishWaiters(false); return
            }
            // A resolved receipt alone is insufficient: wait for reap and both EOFs.
        case .fault:
            state = .unresolved; process?.requestStop(); finishWaiters(false)
        case let .finished(exit):
            if case .operational = profile {
                guard !finishedReceived else { return }
                finishedReceived = true
                if !archiveOperationalReceipt(exit) {
                    state = .unresolved
                    finishWaiters(false)
                    return
                }
            }
            guard exit.returnCode == 0, exit.outputWithinBounds,
                  let receipt = try? decodeReceipt(exit.receipt),
                  state != .unresolved else {
                state = .unresolved; finishWaiters(false); return
            }
            do {
                try owner?.resolve()
                guard owner != nil else { throw ManagedSyntheticError.ownership }
                cleanupProved = true
                if receipt.adapterError != nil { state = .failed }
                else if receipt.operational && receipt.captureState == "stopped" && receipt.terminalReason == "cancelled" { state = .stopped }
                else if receipt.captureState == "stopped" && receipt.terminalReason == "duration_complete" { state = .completed }
                else if !receipt.operational && receipt.captureState == "failed" && receipt.terminalReason == "cancelled" { state = .stopped }
                else { state = .failed }
                finishWaiters(true)
            } catch { state = .unresolved; finishWaiters(false) }
        }
    }

    private func archiveOperationalReceipt(_ exit: ManagedSyntheticProcessExit) -> Bool {
        let data = exit.receipt
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let receiptIsValid: Bool
        if exit.outputWithinBounds, !data.isEmpty, data.count <= 65_536,
           (try? ManagedOperationalReceipt.decode(data, launchID: launchID)) != nil {
            receiptIsValid = true
        } else {
            receiptIsValid = false
        }
        let archivedState: String
        if data.isEmpty && exit.outputWithinBounds {
            archivedState = "absent"
        } else {
            archivedState = receiptIsValid ? "valid" : "invalid"
        }
        do {
            guard let owner else { throw ManagedSyntheticError.ownership }
            if receiptIsValid { try owner.archiveManagedReceipt(data) }
            try owner.writeManagedReceiptStatus(archivedState, launchID: launchID,
                                                byteCount: data.count, sha256: digest)
            switch archivedState {
            case "valid": receiptArchiveState = .valid
            case "invalid": receiptArchiveState = .invalid
            default: receiptArchiveState = .absent
            }
            return receiptIsValid
        } catch {
            receiptArchiveState = .writeFailed
            return false
        }
    }

    private func decodeReceipt(_ data: Data) throws -> ManagedReceiptSummary {
        if case .operational = profile {
            let receipt = try ManagedOperationalReceipt.decode(data, launchID: launchID)
            guard receipt.provesCleanup,
                  let state = receipt.captureState,
                  let reason = receipt.captureTerminalReason else { throw ManagedSyntheticError.receipt }
            return ManagedReceiptSummary(captureState: state, terminalReason: reason,
                                         adapterError: receipt.adapter.adapter_error, operational: true)
        }
        let receipt = try ManagedSyntheticReceipt.decode(data, launchID: launchID, profile: profile)
        guard receipt.provesCleanup(profile: profile), let capture = receipt.adapter.capture_result else {
            throw ManagedSyntheticError.receipt
        }
        return ManagedReceiptSummary(captureState: capture.state,
                                     terminalReason: capture.terminal_reason, adapterError: nil, operational: false)
    }
    private func finishWaiters(_ result: Bool) {
        let pending = waiters; waiters.removeAll()
        for waiter in pending { waiter.resume(returning: result) }
    }
}
