import Darwin
import Foundation
import UPSModel

public enum WidgetStoreMode: Sendable, Equatable {
    case readOnly
    case readWrite
}

public enum WidgetStoreError: Error, Equatable {
    case invalidRequest
    case invalidSnapshot
    case unsafeLocation
    case payloadTooLarge
    case readOnly
    case ioFailure
}

public actor WidgetSnapshotStore {
    private static let fileName = "snapshot.json"
    private static let maximumPayloadBytes = 64 * 1024
    private let directoryDescriptor: Int32
    private let mode: WidgetStoreMode
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(directoryURL: URL, mode: WidgetStoreMode) throws {
        guard directoryURL.isFileURL else { throw WidgetStoreError.unsafeLocation }
        let directory = directoryURL.standardizedFileURL
        let name = directory.lastPathComponent
        guard !name.isEmpty, name != "/", name != ".", name != ".." else {
            throw WidgetStoreError.unsafeLocation
        }
        let parentPath = directory.deletingLastPathComponent().path
        let parentDescriptor = open(parentPath, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parentDescriptor >= 0, Self.isTrustedParent(parentDescriptor) else {
            if parentDescriptor >= 0 { _ = Darwin.close(parentDescriptor) }
            throw WidgetStoreError.unsafeLocation
        }
        defer { _ = Darwin.close(parentDescriptor) }

        var created = false
        if mode == .readWrite {
            let result = name.withCString { mkdirat(parentDescriptor, $0, mode_t(0o700)) }
            if result == 0 {
                created = true
            } else if errno != EEXIST {
                throw WidgetStoreError.unsafeLocation
            }
        }

        let descriptor = name.withCString {
            openat(parentDescriptor, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard descriptor >= 0 else { throw WidgetStoreError.unsafeLocation }
        if created, fchmod(descriptor, mode_t(0o700)) != 0 {
            _ = Darwin.close(descriptor)
            throw WidgetStoreError.unsafeLocation
        }
        guard Self.isPrivateDirectory(descriptor) else {
            _ = Darwin.close(descriptor)
            throw WidgetStoreError.unsafeLocation
        }

        directoryDescriptor = descriptor
        self.mode = mode
        encoder = Self.makeEncoder()
        decoder = Self.makeDecoder()
    }

    deinit {
        _ = Darwin.close(directoryDescriptor)
    }

    public func read(now: Date) throws -> WidgetSnapshot? {
        guard Self.isFinite(now) else { throw WidgetStoreError.invalidRequest }
        guard Self.isPrivateDirectory(directoryDescriptor) else { throw WidgetStoreError.unsafeLocation }
        let descriptor = Self.openExistingTarget(directoryDescriptor)
        guard descriptor >= 0 else {
            if errno == ENOENT { return nil }
            throw WidgetStoreError.unsafeLocation
        }
        defer { _ = Darwin.close(descriptor) }

        let data = try Self.readBoundedFile(descriptor)
        guard Self.isPrivateDirectory(directoryDescriptor) else { throw WidgetStoreError.unsafeLocation }
        let value: WidgetSnapshot
        do {
            value = try decoder.decode(WidgetSnapshot.self, from: data)
            try value.validate()
        } catch {
            throw WidgetStoreError.invalidSnapshot
        }
        guard value.publishedAt <= now else { throw WidgetStoreError.invalidSnapshot }
        return value
    }

    public func write(_ value: WidgetSnapshot, now: Date) throws {
        guard mode == .readWrite else { throw WidgetStoreError.readOnly }
        guard Self.isFinite(now) else { throw WidgetStoreError.invalidRequest }
        do { try value.validate() } catch { throw WidgetStoreError.invalidSnapshot }
        guard value.publishedAt <= now else { throw WidgetStoreError.invalidSnapshot }

        let data: Data
        do { data = try encoder.encode(value) } catch { throw WidgetStoreError.invalidSnapshot }
        guard data.count <= Self.maximumPayloadBytes else { throw WidgetStoreError.payloadTooLarge }
        guard Self.isPrivateDirectory(directoryDescriptor) else { throw WidgetStoreError.unsafeLocation }

        let existing = Self.openExistingTarget(directoryDescriptor)
        if existing >= 0 {
            defer { _ = Darwin.close(existing) }
            guard Self.isPrivateRegularFile(existing) else { throw WidgetStoreError.unsafeLocation }
        } else if errno != ENOENT {
            throw WidgetStoreError.unsafeLocation
        }

        let temporaryName = ".widget-snapshot-\(UUID().uuidString.lowercased()).tmp"
        let temporaryDescriptor = temporaryName.withCString {
            openat(directoryDescriptor, $0, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        }
        guard temporaryDescriptor >= 0 else { throw WidgetStoreError.ioFailure }
        var installed = false
        defer {
            _ = Darwin.close(temporaryDescriptor)
            if !installed {
                _ = temporaryName.withCString { unlinkat(directoryDescriptor, $0, 0) }
            }
        }
        guard fchmod(temporaryDescriptor, mode_t(0o600)) == 0,
              Self.isPrivateRegularFile(temporaryDescriptor),
              Self.isPrivateDirectory(directoryDescriptor) else {
            throw WidgetStoreError.unsafeLocation
        }
        try Self.writeAll(data, to: temporaryDescriptor)
        guard fsync(temporaryDescriptor) == 0 else { throw WidgetStoreError.ioFailure }
        guard Self.isPrivateDirectory(directoryDescriptor) else { throw WidgetStoreError.unsafeLocation }

        let renameResult = temporaryName.withCString { temporary in
            Self.fileName.withCString { destination in
                renameat(directoryDescriptor, temporary, directoryDescriptor, destination)
            }
        }
        guard renameResult == 0 else { throw WidgetStoreError.ioFailure }
        installed = true
    }

    private static func openExistingTarget(_ directoryDescriptor: Int32) -> Int32 {
        fileName.withCString {
            openat(directoryDescriptor, $0, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        }
    }

    private static func isPrivateDirectory(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && (info.st_mode & 0o7777) == 0o700
            && info.st_uid == getuid()
    }

    private static func isTrustedParent(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && info.st_uid == getuid()
            && (info.st_mode & 0o022) == 0
    }

    private static func isPrivateRegularFile(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFREG
            && (info.st_mode & 0o7777) == 0o600
            && info.st_uid == getuid()
            && info.st_nlink == 1
    }

    private static func readBoundedFile(_ descriptor: Int32) throws -> Data {
        var before = stat()
        guard fstat(descriptor, &before) == 0, isPrivateRegularFile(descriptor) else {
            throw WidgetStoreError.unsafeLocation
        }
        guard before.st_size >= 0 else { throw WidgetStoreError.invalidSnapshot }
        guard before.st_size <= off_t(maximumPayloadBytes) else { throw WidgetStoreError.payloadTooLarge }

        var data = Data()
        data.reserveCapacity(Int(before.st_size))
        var buffer = [UInt8](repeating: 0, count: 4096)
        while true {
            let requested = min(buffer.count, maximumPayloadBytes + 1 - data.count)
            let count = buffer.withUnsafeMutableBytes { bytes in
                Darwin.read(descriptor, bytes.baseAddress, requested)
            }
            if count == 0 { break }
            if count < 0 {
                if errno == EINTR { continue }
                throw WidgetStoreError.ioFailure
            }
            guard data.count + count <= maximumPayloadBytes else { throw WidgetStoreError.payloadTooLarge }
            data.append(contentsOf: buffer.prefix(count))
        }

        var after = stat()
        guard fstat(descriptor, &after) == 0,
              Self.isPrivateRegularFile(descriptor),
              before.st_dev == after.st_dev, before.st_ino == after.st_ino else {
            throw WidgetStoreError.unsafeLocation
        }
        return data
    }

    private static func writeAll(_ data: Data, to descriptor: Int32) throws {
        try data.withUnsafeBytes { bytes in
            guard let baseAddress = bytes.baseAddress else { throw WidgetStoreError.ioFailure }
            var offset = 0
            while offset < bytes.count {
                let count = Darwin.write(descriptor, baseAddress.advanced(by: offset), bytes.count - offset)
                if count < 0 {
                    if errno == EINTR { continue }
                    throw WidgetStoreError.ioFailure
                }
                guard count > 0 else { throw WidgetStoreError.ioFailure }
                offset += count
            }
        }
    }

    private static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .deferredToDate
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }

    private static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .deferredToDate
        return decoder
    }

    private static func isFinite(_ date: Date) -> Bool {
        date.timeIntervalSince1970.isFinite
    }
}
