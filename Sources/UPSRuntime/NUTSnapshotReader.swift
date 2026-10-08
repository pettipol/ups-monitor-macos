import CryptoKit
import Darwin
import Foundation
import NUTClient
import NUTData
import UPSModel

public enum NUTSnapshotReaderError: Error, Equatable, Sendable {
    case invalidExpectedSHA256
    case invalidIdentity
    case unsafeExecutable
    case executableTooLarge
    case executableChanged
    case digestMismatch
    case cancelled
    case readInProgress
    case readFailed
    case invalidSnapshot
}

/// Reads one explicitly configured NUT source after verifying the configured executable bytes.
public actor NUTSnapshotReader {
    private static let maximumExecutableBytes: Int64 = 64 * 1024 * 1024

    private let configuration: UPSCClientConfiguration
    private let expectedSHA256: String
    private let source: MonitorSource
    private let snapshotRead: @Sendable () async throws -> NUTSnapshot
    private var readInProgress = false

    public init(
        configuration: UPSCClientConfiguration,
        expectedSHA256: String,
        sessionID: String = UUID().uuidString.lowercased()
    ) throws {
        guard Self.isValidSHA256(expectedSHA256) else {
            throw NUTSnapshotReaderError.invalidExpectedSHA256
        }
        let source = try Self.makeSource(configuration: configuration, sessionID: sessionID)

        self.configuration = configuration
        self.expectedSHA256 = expectedSHA256.lowercased()
        self.source = source
        self.snapshotRead = {
            try await UPSCClient(configuration: configuration).readSnapshot()
        }
    }

    init(
        configuration: UPSCClientConfiguration,
        expectedSHA256: String,
        sessionID: String,
        snapshotRead: @escaping @Sendable () async throws -> NUTSnapshot
    ) throws {
        guard Self.isValidSHA256(expectedSHA256) else {
            throw NUTSnapshotReaderError.invalidExpectedSHA256
        }
        let source = try Self.makeSource(configuration: configuration, sessionID: sessionID)

        self.configuration = configuration
        self.expectedSHA256 = expectedSHA256.lowercased()
        self.source = source
        self.snapshotRead = snapshotRead
    }

    /// Verifies the executable without launching it.
    public func validateExecutable() async throws {
        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
        let digest = try Self.hashExecutable(at: configuration.executableURL)
        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
        guard digest == expectedSHA256 else { throw NUTSnapshotReaderError.digestMismatch }
    }

    /// Performs one bounded UPSCClient read and returns its validated model snapshot.
    public func read() async throws -> [MonitorSnapshot] {
        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
        guard !readInProgress else { throw NUTSnapshotReaderError.readInProgress }
        readInProgress = true
        defer { readInProgress = false }

        try await validateExecutable()
        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }

        let nutSnapshot: NUTSnapshot
        do {
            nutSnapshot = try await snapshotRead()
        } catch let error as UPSCClientError {
            switch error {
            case .cancelled: throw NUTSnapshotReaderError.cancelled
            case .readInProgress: throw NUTSnapshotReaderError.readInProgress
            default: throw NUTSnapshotReaderError.readFailed
            }
        } catch is CancellationError {
            throw NUTSnapshotReaderError.cancelled
        } catch {
            throw NUTSnapshotReaderError.readFailed
        }

        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
        do {
            let snapshot = try MonitorSnapshotAdapter.fromNUT(nutSnapshot, source: source)
            try snapshot.validate()
            return [snapshot]
        } catch {
            throw NUTSnapshotReaderError.invalidSnapshot
        }
    }

    private static func isValidSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 70) || ($0 >= 97 && $0 <= 102)
        }
    }

    private static func makeSource(
        configuration: UPSCClientConfiguration,
        sessionID: String
    ) throws -> MonitorSource {
        let source = MonitorSource(
            provider: .nut,
            id: configuration.sourceID,
            sessionID: sessionID,
            identityStability: .configured
        )
        do {
            try source.validate()
            return source
        } catch {
            throw NUTSnapshotReaderError.invalidIdentity
        }
    }

    private static func hashExecutable(at url: URL) throws -> String {
        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw NUTSnapshotReaderError.unsafeExecutable }
        defer { _ = close(descriptor) }

        var before = stat()
        guard fstat(descriptor, &before) == 0 else { throw NUTSnapshotReaderError.unsafeExecutable }
        try validateMetadata(before)

        var hasher = SHA256()
        var totalBytes: Int64 = 0
        var buffer = [UInt8](repeating: 0, count: 64 * 1024)
        while true {
            guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
            let count = buffer.withUnsafeMutableBytes { bytes in
                Darwin.read(descriptor, bytes.baseAddress, bytes.count)
            }
            if count == 0 { break }
            if count < 0 {
                if errno == EINTR { continue }
                throw NUTSnapshotReaderError.unsafeExecutable
            }
            totalBytes += Int64(count)
            guard totalBytes <= maximumExecutableBytes else {
                throw NUTSnapshotReaderError.executableTooLarge
            }
            hasher.update(data: Data(buffer.prefix(count)))
        }

        var after = stat()
        guard fstat(descriptor, &after) == 0 else { throw NUTSnapshotReaderError.executableChanged }
        try validateMetadata(after)
        guard metadataUnchanged(before, after), totalBytes == Int64(before.st_size) else {
            throw NUTSnapshotReaderError.executableChanged
        }
        guard !Task.isCancelled else { throw NUTSnapshotReaderError.cancelled }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func validateMetadata(_ info: stat) throws {
        guard (info.st_mode & S_IFMT) == S_IFREG,
              info.st_uid == getuid(),
              (info.st_mode & 0o6022) == 0,
              (info.st_mode & 0o111) != 0,
              info.st_nlink == 1,
              info.st_size >= 0 else {
            throw NUTSnapshotReaderError.unsafeExecutable
        }
        guard info.st_size <= maximumExecutableBytes else {
            throw NUTSnapshotReaderError.executableTooLarge
        }
    }

    private static func metadataUnchanged(_ lhs: stat, _ rhs: stat) -> Bool {
        lhs.st_dev == rhs.st_dev &&
        lhs.st_ino == rhs.st_ino &&
        lhs.st_uid == rhs.st_uid &&
        lhs.st_mode == rhs.st_mode &&
        lhs.st_nlink == rhs.st_nlink &&
        lhs.st_size == rhs.st_size &&
        lhs.st_mtimespec.tv_sec == rhs.st_mtimespec.tv_sec &&
        lhs.st_mtimespec.tv_nsec == rhs.st_mtimespec.tv_nsec &&
        lhs.st_ctimespec.tv_sec == rhs.st_ctimespec.tv_sec &&
        lhs.st_ctimespec.tv_nsec == rhs.st_ctimespec.tv_nsec
    }
}
