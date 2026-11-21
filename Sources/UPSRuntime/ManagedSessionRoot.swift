import Darwin
import Foundation

public enum ManagedSessionRootError: Error, Equatable, Sendable {
    case unsafeApplicationSupport
    case unsafeManagedRoot
    case creationFailed
}

/// Resolves the private root used for managed monitoring sessions.
public enum ManagedSessionRoot {
    private static let appDirectoryName = "UPSMonitorMac"
    private static let sessionsDirectoryName = "ManagedSessions"
    private static let privateMode: mode_t = 0o700

    public static func resolve(applicationSupportURL: URL? = nil) throws -> URL {
        let baseURL: URL
        if let applicationSupportURL {
            baseURL = applicationSupportURL
        } else {
            do {
                baseURL = try FileManager.default.url(
                    for: .applicationSupportDirectory,
                    in: .userDomainMask,
                    appropriateFor: nil,
                    create: false
                )
            } catch {
                throw ManagedSessionRootError.unsafeApplicationSupport
            }
        }
        guard baseURL.isFileURL, !baseURL.path.contains("\0") else {
            throw ManagedSessionRootError.unsafeApplicationSupport
        }

        let normalizedBase = baseURL.standardizedFileURL
        let baseName = normalizedBase.lastPathComponent
        guard !baseName.isEmpty, baseName != "/", baseName != ".", baseName != "..",
              !baseName.contains("\0") else {
            throw ManagedSessionRootError.unsafeApplicationSupport
        }

        let parentFD = open(normalizedBase.deletingLastPathComponent().path,
                            O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parentFD >= 0 else { throw ManagedSessionRootError.unsafeApplicationSupport }
        defer { _ = Darwin.close(parentFD) }
        guard isTrustedParent(parentFD) else { throw ManagedSessionRootError.unsafeApplicationSupport }

        let baseFD = baseName.withCString {
            openat(parentFD, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard baseFD >= 0 else { throw ManagedSessionRootError.unsafeApplicationSupport }
        defer { _ = Darwin.close(baseFD) }
        guard isApplicationSupport(baseFD), namedDirectoryMatches(baseName, in: parentFD, descriptor: baseFD) else {
            throw ManagedSessionRootError.unsafeApplicationSupport
        }

        let appFD = try openOrCreatePrivateDirectory(appDirectoryName, parent: baseFD)
        defer { _ = Darwin.close(appFD) }
        let sessionsFD = try openOrCreatePrivateDirectory(sessionsDirectoryName, parent: appFD)
        defer { _ = Darwin.close(sessionsFD) }

        guard isTrustedParent(parentFD), namedDirectoryMatches(baseName, in: parentFD, descriptor: baseFD),
              isApplicationSupport(baseFD),
              isPrivateDirectory(appFD), namedDirectoryMatches(appDirectoryName, in: baseFD, descriptor: appFD),
              isPrivateDirectory(sessionsFD),
              namedDirectoryMatches(sessionsDirectoryName, in: appFD, descriptor: sessionsFD) else {
            throw ManagedSessionRootError.unsafeManagedRoot
        }

        return normalizedBase
            .appendingPathComponent(appDirectoryName, isDirectory: true)
            .appendingPathComponent(sessionsDirectoryName, isDirectory: true)
    }

    private static func openOrCreatePrivateDirectory(_ name: String, parent: Int32) throws -> Int32 {
        guard !name.isEmpty, !name.contains("\0") else { throw ManagedSessionRootError.unsafeManagedRoot }

        var named = stat()
        let namedResult = name.withCString { fstatat(parent, $0, &named, AT_SYMLINK_NOFOLLOW) }
        if namedResult != 0 {
            guard errno == ENOENT else { throw ManagedSessionRootError.unsafeManagedRoot }
            let createResult = name.withCString { mkdirat(parent, $0, privateMode) }
            guard createResult == 0 else { throw ManagedSessionRootError.creationFailed }
        }

        let descriptor = name.withCString {
            openat(parent, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard descriptor >= 0 else { throw ManagedSessionRootError.unsafeManagedRoot }
        guard isPrivateDirectory(descriptor), namedDirectoryMatches(name, in: parent, descriptor: descriptor) else {
            _ = Darwin.close(descriptor)
            throw ManagedSessionRootError.unsafeManagedRoot
        }
        return descriptor
    }

    private static func isTrustedParent(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && info.st_uid == getuid()
            && info.st_mode & 0o022 == 0
    }

    private static func isApplicationSupport(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && info.st_uid == getuid()
            && info.st_mode & 0o022 == 0
            && hasSafeApplicationSupportACL(descriptor)
    }

    private static func isPrivateDirectory(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && (info.st_mode & 0o7777) == privateMode
            && info.st_uid == getuid()
            && hasEmptyExtendedACL(descriptor)
    }

    private static func hasSafeApplicationSupportACL(_ descriptor: Int32) -> Bool {
        errno = 0
        guard let acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED) else { return errno == ENOENT }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        guard acl_valid(acl) == 0 else { return false }

        var entry: acl_entry_t?
        errno = 0
        var result = acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry)
        if result == -1 { return errno == EINVAL }
        while result == 0 {
            guard let currentEntry = entry else { return false }
            var tag = ACL_UNDEFINED_TAG
            guard acl_get_tag_type(currentEntry, &tag) == 0, tag == ACL_EXTENDED_DENY else { return false }
            errno = 0
            result = acl_get_entry(acl, Int32(ACL_NEXT_ENTRY.rawValue), &entry)
        }
        return errno == EINVAL
    }

    private static func namedDirectoryMatches(_ name: String, in parent: Int32, descriptor: Int32) -> Bool {
        var opened = stat()
        var named = stat()
        let result = name.withCString { fstatat(parent, $0, &named, AT_SYMLINK_NOFOLLOW) }
        return fstat(descriptor, &opened) == 0 && result == 0
            && (named.st_mode & S_IFMT) == S_IFDIR
            && opened.st_dev == named.st_dev
            && opened.st_ino == named.st_ino
            && opened.st_uid == named.st_uid
    }

    private static func hasEmptyExtendedACL(_ descriptor: Int32) -> Bool {
        errno = 0
        guard let acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED) else { return errno == ENOENT }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        guard acl_valid(acl) == 0 else { return false }
        var entry: acl_entry_t?
        errno = 0
        return acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry) == -1 && errno == EINVAL
    }
}
