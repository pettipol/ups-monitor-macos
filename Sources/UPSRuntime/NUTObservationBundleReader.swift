import Darwin
import Foundation
import UPSModel

public enum NUTObservationBundleReaderError: Error, Equatable, Sendable {
    case unsafeBundle
    case payloadTooLarge
    case ioFailure
}

public struct NUTObservationBundleReader: Sendable {
    private static let receiptName = "receipt.json"
    private static let stdoutName = "stdout.bin"
    private static let stderrName = "stderr.bin"
    private static let receiptLimit = 8_192
    private static let stdoutLimit = 65_536
    private static let captureLimit = 1_048_576

    public init() {}

    public func read(
        sessionDirectoryURL: URL,
        origin: NUTObservationOrigin,
        source: MonitorSource,
        expectedExecutableSHA256: String,
        now: Date
    ) throws -> ImportedNUTObservation {
        guard sessionDirectoryURL.isFileURL else { throw NUTObservationBundleReaderError.unsafeBundle }
        let directory = sessionDirectoryURL.standardizedFileURL
        let name = directory.lastPathComponent
        guard !name.isEmpty, name != "/", name != ".", name != ".." else {
            throw NUTObservationBundleReaderError.unsafeBundle
        }

        let parent = open(directory.deletingLastPathComponent().path,
                          O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parent >= 0 else { throw NUTObservationBundleReaderError.unsafeBundle }
        defer { _ = Darwin.close(parent) }
        guard Self.isTrustedParent(parent) else { throw NUTObservationBundleReaderError.unsafeBundle }

        let session = name.withCString {
            openat(parent, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard session >= 0 else { throw NUTObservationBundleReaderError.unsafeBundle }
        defer { _ = Darwin.close(session) }
        guard Self.isPrivateDirectory(session) else { throw NUTObservationBundleReaderError.unsafeBundle }

        let specs: [(String, Int)] = [
            (Self.receiptName, Self.receiptLimit),
            (Self.stdoutName, Self.stdoutLimit),
            (Self.stderrName, Self.captureLimit),
        ]
        var descriptors: [Int32] = []
        defer { descriptors.forEach { _ = Darwin.close($0) } }
        for (fileName, _) in specs {
            let descriptor = fileName.withCString {
                openat(session, $0, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            }
            guard descriptor >= 0 else { throw NUTObservationBundleReaderError.unsafeBundle }
            descriptors.append(descriptor)
        }

        let initial = try zip(specs, descriptors).map { spec, descriptor in
            try Self.metadata(descriptor, name: spec.0, directory: session)
        }
        guard initial[0].st_size <= off_t(Self.receiptLimit) else {
            throw NUTObservationBundleReaderError.payloadTooLarge
        }
        guard initial[1].st_size <= off_t(Self.stdoutLimit),
              initial[2].st_size <= off_t(Self.captureLimit) - initial[1].st_size else {
            throw NUTObservationBundleReaderError.payloadTooLarge
        }
        let receipt = try Self.readBounded(descriptors[0], name: specs[0].0, directory: session,
                                           limit: Self.receiptLimit, initial: initial[0])
        let stdout = try Self.readBounded(descriptors[1], name: specs[1].0, directory: session,
                                          limit: Self.stdoutLimit, initial: initial[1])
        let stderr = try Self.readBounded(descriptors[2], name: specs[2].0, directory: session,
                                          limit: Self.captureLimit - stdout.count, initial: initial[2])

        guard Self.isTrustedParent(parent), Self.isPrivateDirectory(session) else {
            throw NUTObservationBundleReaderError.unsafeBundle
        }
        for index in specs.indices {
            let final = try Self.metadata(descriptors[index], name: specs[index].0, directory: session)
            guard Self.same(initial[index], final) else { throw NUTObservationBundleReaderError.unsafeBundle }
        }
        guard stderr.count <= Self.captureLimit - stdout.count else {
            throw NUTObservationBundleReaderError.payloadTooLarge
        }

        return try NUTObservationReceiptDecoder().decode(
            receipt, stdout: stdout, stderr: stderr, origin: origin, source: source,
            expectedExecutableSHA256: expectedExecutableSHA256, now: now
        )
    }

    private static func isTrustedParent(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && info.st_uid == getuid()
            && (info.st_mode & 0o022) == 0
            && hasEmptyExtendedACL(descriptor)
    }

    private static func isPrivateDirectory(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && (info.st_mode & 0o7777) == 0o700
            && info.st_uid == getuid()
            && hasEmptyExtendedACL(descriptor)
    }

    private static func hasEmptyExtendedACL(_ descriptor: Int32) -> Bool {
        errno = 0
        guard let acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED) else {
            let retrievalError = errno
            // Darwin reports an absent extended ACL as ENOENT, even on an open descriptor.
            return retrievalError == ENOENT
        }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        guard acl_valid(acl) == 0 else { return false }
        var entry: acl_entry_t?
        errno = 0
        // Darwin returns 0 for an entry, and -1/EINVAL at the end of a valid ACL.
        return acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry) == -1 && errno == EINVAL
    }

    private static func metadata(_ descriptor: Int32, name: String, directory: Int32) throws -> stat {
        var opened = stat()
        var named = stat()
        let result = name.withCString { fstatat(directory, $0, &named, AT_SYMLINK_NOFOLLOW) }
        guard fstat(descriptor, &opened) == 0, result == 0,
              isPrivateRegularFile(opened), hasEmptyExtendedACL(descriptor), same(opened, named) else {
            throw NUTObservationBundleReaderError.unsafeBundle
        }
        guard opened.st_size >= 0 else { throw NUTObservationBundleReaderError.unsafeBundle }
        return opened
    }

    private static func isPrivateRegularFile(_ info: stat) -> Bool {
        (info.st_mode & S_IFMT) == S_IFREG
            && (info.st_mode & 0o7777) == 0o600
            && info.st_uid == getuid()
            && info.st_nlink == 1
    }

    private static func same(_ lhs: stat, _ rhs: stat) -> Bool {
        lhs.st_dev == rhs.st_dev && lhs.st_ino == rhs.st_ino
            && lhs.st_mode == rhs.st_mode && lhs.st_uid == rhs.st_uid
            && lhs.st_gid == rhs.st_gid && lhs.st_nlink == rhs.st_nlink
            && lhs.st_size == rhs.st_size
            && lhs.st_mtimespec.tv_sec == rhs.st_mtimespec.tv_sec
            && lhs.st_mtimespec.tv_nsec == rhs.st_mtimespec.tv_nsec
            && lhs.st_ctimespec.tv_sec == rhs.st_ctimespec.tv_sec
            && lhs.st_ctimespec.tv_nsec == rhs.st_ctimespec.tv_nsec
    }

    private static func readBounded(_ descriptor: Int32, name: String, directory: Int32,
                                    limit: Int, initial: stat) throws -> Data {
        guard initial.st_size <= off_t(limit) else { throw NUTObservationBundleReaderError.payloadTooLarge }
        var data = Data()
        data.reserveCapacity(Int(initial.st_size))
        var buffer = [UInt8](repeating: 0, count: 8_192)
        while true {
            let request = min(buffer.count, limit + 1 - data.count)
            let count = buffer.withUnsafeMutableBytes { bytes in
                Darwin.read(descriptor, bytes.baseAddress, request)
            }
            if count == 0 { break }
            if count < 0 {
                if errno == EINTR { continue }
                throw NUTObservationBundleReaderError.ioFailure
            }
            guard data.count + count <= limit else { throw NUTObservationBundleReaderError.payloadTooLarge }
            data.append(contentsOf: buffer.prefix(count))
        }
        var after = stat()
        var named = stat()
        let namedResult = name.withCString { fstatat(directory, $0, &named, AT_SYMLINK_NOFOLLOW) }
        guard fstat(descriptor, &after) == 0, namedResult == 0,
              isPrivateRegularFile(after), hasEmptyExtendedACL(descriptor),
              same(initial, after), same(after, named),
              data.count == Int(initial.st_size) else {
            throw NUTObservationBundleReaderError.unsafeBundle
        }
        return data
    }
}
