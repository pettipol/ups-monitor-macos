import Darwin
import Foundation

public enum ManagedSessionWorkspaceError: Error, Equatable, Sendable {
    case unsafeRoot
    case creationFailed
}

/// Creates a private, fresh directory tree for one managed monitoring session.
/// The caller is responsible for choosing the application-support root.
public struct ManagedSessionWorkspace: Sendable {
    public let sessionDirectoryURL: URL
    public let feedDirectoryURL: URL
    public let captureDirectoryURL: URL

    private static let directoryMode: mode_t = 0o700

    public static func create(in privateRootURL: URL) throws -> Self {
        guard privateRootURL.isFileURL, !privateRootURL.path.contains("\0") else {
            throw ManagedSessionWorkspaceError.unsafeRoot
        }
        let rootURL = privateRootURL.standardizedFileURL
        let rootName = rootURL.lastPathComponent
        guard !rootName.isEmpty, !rootName.contains("\0"),
              rootName != "/", rootName != ".", rootName != ".." else {
            throw ManagedSessionWorkspaceError.unsafeRoot
        }

        let parentFD = open(rootURL.deletingLastPathComponent().path,
                            O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parentFD >= 0 else { throw ManagedSessionWorkspaceError.unsafeRoot }
        defer { _ = Darwin.close(parentFD) }

        let rootFD = rootName.withCString {
            openat(parentFD, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard rootFD >= 0 else { throw ManagedSessionWorkspaceError.unsafeRoot }
        defer { _ = Darwin.close(rootFD) }
        guard isPrivateRoot(rootFD), namedEntryMatches(rootName, in: parentFD, descriptor: rootFD) else {
            throw ManagedSessionWorkspaceError.unsafeRoot
        }

        let sessionName = "session-\(UUID().uuidString.lowercased())"
        guard sessionName.withCString({ mkdirat(rootFD, $0, directoryMode) }) == 0 else {
            throw ManagedSessionWorkspaceError.creationFailed
        }

        var sessionFD: Int32 = -1
        var feedFD: Int32 = -1
        var captureFD: Int32 = -1
        defer {
            // Partial directories are intentionally left in place on failure.
            // Automatic name-based cleanup could remove a same-owner replacement.
            if captureFD >= 0 { _ = Darwin.close(captureFD) }
            if feedFD >= 0 { _ = Darwin.close(feedFD) }
            if sessionFD >= 0 { _ = Darwin.close(sessionFD) }
        }

        sessionFD = sessionName.withCString {
            openat(rootFD, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard sessionFD >= 0, isPrivateDirectory(sessionFD),
              namedEntryMatches(sessionName, in: rootFD, descriptor: sessionFD) else {
            throw ManagedSessionWorkspaceError.creationFailed
        }

        guard "feed".withCString({ mkdirat(sessionFD, $0, directoryMode) }) == 0 else {
            throw ManagedSessionWorkspaceError.creationFailed
        }
        feedFD = "feed".withCString {
            openat(sessionFD, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard feedFD >= 0, isPrivateDirectory(feedFD),
              namedEntryMatches("feed", in: sessionFD, descriptor: feedFD) else {
            throw ManagedSessionWorkspaceError.creationFailed
        }

        guard "capture".withCString({ mkdirat(sessionFD, $0, directoryMode) }) == 0 else {
            throw ManagedSessionWorkspaceError.creationFailed
        }
        captureFD = "capture".withCString {
            openat(sessionFD, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        }
        guard captureFD >= 0, isPrivateDirectory(captureFD),
              namedEntryMatches("capture", in: sessionFD, descriptor: captureFD),
              isPrivateRoot(rootFD),
              namedEntryMatches(rootName, in: parentFD, descriptor: rootFD),
              isPrivateDirectory(sessionFD), namedEntryMatches(sessionName, in: rootFD, descriptor: sessionFD),
              isPrivateDirectory(feedFD), namedEntryMatches("feed", in: sessionFD, descriptor: feedFD) else {
            throw ManagedSessionWorkspaceError.creationFailed
        }

        let sessionURL = rootURL.appendingPathComponent(sessionName, isDirectory: true)
        return Self(
            sessionDirectoryURL: sessionURL,
            feedDirectoryURL: sessionURL.appendingPathComponent("feed", isDirectory: true),
            captureDirectoryURL: sessionURL.appendingPathComponent("capture", isDirectory: true)
        )
    }

    private static func isPrivateRoot(_ descriptor: Int32) -> Bool {
        var info = stat()
        return fstat(descriptor, &info) == 0
            && (info.st_mode & S_IFMT) == S_IFDIR
            && (info.st_mode & 0o7777) == directoryMode
            && info.st_uid == getuid()
            && hasEmptyExtendedACL(descriptor)
    }

    private static func isPrivateDirectory(_ descriptor: Int32) -> Bool {
        isPrivateRoot(descriptor)
    }

    private static func namedEntryMatches(_ name: String, in parent: Int32, descriptor: Int32) -> Bool {
        var opened = stat()
        var named = stat()
        let result = name.withCString { fstatat(parent, $0, &named, AT_SYMLINK_NOFOLLOW) }
        return fstat(descriptor, &opened) == 0 && result == 0
            && (named.st_mode & S_IFMT) == S_IFDIR
            && sameIdentity(opened, named)
    }

    private static func sameIdentity(_ lhs: stat, _ rhs: stat) -> Bool {
        lhs.st_dev == rhs.st_dev && lhs.st_ino == rhs.st_ino
            && lhs.st_uid == rhs.st_uid && (lhs.st_mode & S_IFMT) == (rhs.st_mode & S_IFMT)
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
