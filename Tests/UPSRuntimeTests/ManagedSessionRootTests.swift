import Darwin
import Foundation
import XCTest
import UPSRuntime

final class ManagedSessionRootTests: XCTestCase {
    func testCreatesPrivateRootAndIsIdempotentWithoutChangingHistory() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }

        let first = try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)
        XCTAssertEqual(first, fixture.base.appendingPathComponent("UPSMonitorMac/ManagedSessions", isDirectory: true))
        XCTAssertEqual(permissions(at: fixture.appDirectory), 0o700)
        XCTAssertEqual(permissions(at: first), 0o700)

        let history = fixture.appDirectory.appendingPathComponent("History", isDirectory: true)
        try FileManager.default.createDirectory(at: history, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: history.path)
        let sentinel = history.appendingPathComponent("history.fixture")
        try Data("preserve".utf8).write(to: sentinel)

        XCTAssertEqual(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base), first)
        XCTAssertEqual(try Data(contentsOf: sentinel), Data("preserve".utf8))
    }

    func testRejectsMissingApplicationSupport() throws {
        let fixture = try Fixture(createBase: false)
        defer { fixture.remove() }

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeApplicationSupport)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.base.path))
    }

    func testRejectsFileApplicationSupport() throws {
        let fixture = try Fixture(createBase: false)
        defer { fixture.remove() }
        try Data("base".utf8).write(to: fixture.base)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fixture.base.path)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeApplicationSupport)
        }
        XCTAssertEqual(try Data(contentsOf: fixture.base), Data("base".utf8))
        XCTAssertEqual(permissions(at: fixture.base), 0o600)
    }

    func testRejectsSymlinkApplicationSupportWithoutTouchingTarget() throws {
        let fixture = try Fixture(createBase: false)
        defer { fixture.remove() }
        let target = fixture.container.appendingPathComponent("base-target", isDirectory: true)
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: target.path)
        try FileManager.default.createSymbolicLink(atPath: fixture.base.path, withDestinationPath: "base-target")

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeApplicationSupport)
        }
        XCTAssertEqual(permissions(at: target), 0o755)
        XCTAssertEqual(try children(of: target), [])
    }

    func testRejectsNULInBasePathWithoutChangingTheRealBase() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let nulBase = URL(fileURLWithPath: fixture.base.path + "\0suffix", isDirectory: true)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: nulBase)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeApplicationSupport)
        }
        XCTAssertEqual(permissions(at: fixture.base), 0o755)
        XCTAssertEqual(try children(of: fixture.base), [])
    }

    func testRejectsGroupWritableParentWithoutChangingApplicationSupport() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try FileManager.default.setAttributes([.posixPermissions: 0o770], ofItemAtPath: fixture.container.path)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeApplicationSupport)
        }
        XCTAssertEqual(permissions(at: fixture.container), 0o770)
        XCTAssertEqual(permissions(at: fixture.base), 0o755)
        XCTAssertEqual(try children(of: fixture.base), [])
    }

    func testRejectsExistingAppDirectoryWithUnsafePermissionsWithoutChangingIt() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try FileManager.default.createDirectory(at: fixture.appDirectory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o750], ofItemAtPath: fixture.appDirectory.path)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeManagedRoot)
        }
        XCTAssertEqual(permissions(at: fixture.appDirectory), 0o750)
        XCTAssertEqual(try children(of: fixture.appDirectory), [])
    }

    func testRejectsAppDirectorySymlinkWithoutTouchingTarget() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let target = fixture.container.appendingPathComponent("app-target", isDirectory: true)
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: target.path)
        try FileManager.default.createSymbolicLink(atPath: fixture.appDirectory.path, withDestinationPath: "app-target")

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeManagedRoot)
        }
        XCTAssertEqual(permissions(at: target), 0o700)
        XCTAssertEqual(try children(of: target), [])
    }

    func testRejectsExistingSessionsDirectoryWithUnsafePermissionsWithoutChangingIt() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try FileManager.default.createDirectory(at: fixture.appDirectory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: fixture.appDirectory.path)
        try FileManager.default.createDirectory(at: fixture.sessionsDirectory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o750], ofItemAtPath: fixture.sessionsDirectory.path)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeManagedRoot)
        }
        XCTAssertEqual(permissions(at: fixture.appDirectory), 0o700)
        XCTAssertEqual(permissions(at: fixture.sessionsDirectory), 0o750)
        XCTAssertEqual(try children(of: fixture.appDirectory), ["ManagedSessions"])
    }

    func testAcceptsBaseWithDenyDeleteACLAndPreservesIt() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try Self.setExtendedACL(at: fixture.base, denyDelete: true)
        let originalMode = permissions(at: fixture.base)

        let resolved = try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)

        XCTAssertEqual(resolved, fixture.sessionsDirectory)
        XCTAssertEqual(permissions(at: fixture.base), originalMode)
        XCTAssertTrue(Self.hasACLTag(ACL_EXTENDED_DENY, at: fixture.base))
        XCTAssertEqual(permissions(at: resolved), 0o700)
    }

    func testRejectsBaseWithAllowACLWithoutChangingIt() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try Self.setExtendedACL(at: fixture.base)
        let originalMode = permissions(at: fixture.base)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeApplicationSupport)
        }
        XCTAssertEqual(permissions(at: fixture.base), originalMode)
        XCTAssertTrue(Self.hasACLTag(ACL_EXTENDED_ALLOW, at: fixture.base))
        XCTAssertEqual(try children(of: fixture.base), [])
    }

    func testRejectsSessionsDirectoryWithExtendedACLWithoutRemovingIt() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try FileManager.default.createDirectory(at: fixture.appDirectory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: fixture.appDirectory.path)
        try FileManager.default.createDirectory(at: fixture.sessionsDirectory, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: fixture.sessionsDirectory.path)
        try Self.setExtendedACL(at: fixture.sessionsDirectory)

        XCTAssertThrowsError(try ManagedSessionRoot.resolve(applicationSupportURL: fixture.base)) { error in
            XCTAssertEqual(error as? ManagedSessionRootError, .unsafeManagedRoot)
        }
        XCTAssertEqual(permissions(at: fixture.sessionsDirectory), 0o700)
        XCTAssertTrue(Self.hasExtendedACL(at: fixture.sessionsDirectory))
    }

    private func permissions(at url: URL) -> Int? {
        (try? FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber)?.intValue
    }

    private func children(of url: URL) throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: url.path).sorted()
    }

    private static func setExtendedACL(at url: URL, denyDelete: Bool = false) throws {
        var acl = acl_init(1)
        guard acl != nil else { throw POSIXError(.ENOMEM) }
        defer { if let acl { _ = acl_free(UnsafeMutableRawPointer(acl)) } }
        var entry: acl_entry_t?
        guard acl_create_entry(&acl, &entry) == 0, let entry,
              acl_set_tag_type(entry, denyDelete ? ACL_EXTENDED_DENY : ACL_EXTENDED_ALLOW) == 0 else {
            throw POSIXError(.EINVAL)
        }
        var qualifier = UUID().uuid
        let qualifierResult = withUnsafePointer(to: &qualifier) { acl_set_qualifier(entry, $0) }
        var permissions: acl_permset_t?
        guard qualifierResult == 0,
              acl_get_permset(entry, &permissions) == 0,
              acl_add_perm(permissions, denyDelete ? ACL_DELETE : ACL_READ_DATA) == 0,
              let acl else { throw POSIXError(.EINVAL) }
        let descriptor = url.path.withCString { open($0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
        guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        defer { _ = Darwin.close(descriptor) }
        guard acl_set_fd_np(descriptor, acl, ACL_TYPE_EXTENDED) == 0 else {
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
    }

    private static func hasExtendedACL(at url: URL) -> Bool {
        let descriptor = url.path.withCString { open($0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
        guard descriptor >= 0 else { return false }
        defer { _ = Darwin.close(descriptor) }
        errno = 0
        guard let acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED) else { return false }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        var entry: acl_entry_t?
        return acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry) == 0
    }

    private static func hasACLTag(_ expectedTag: acl_tag_t, at url: URL) -> Bool {
        let descriptor = url.path.withCString { open($0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
        guard descriptor >= 0 else { return false }
        defer { _ = Darwin.close(descriptor) }
        errno = 0
        guard let acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED) else { return false }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        var entry: acl_entry_t?
        guard acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry) == 0, let entry else { return false }
        var tag = ACL_UNDEFINED_TAG
        return acl_get_tag_type(entry, &tag) == 0 && tag == expectedTag
    }

    private struct Fixture {
        let container: URL
        let base: URL
        var appDirectory: URL { base.appendingPathComponent("UPSMonitorMac", isDirectory: true) }
        var sessionsDirectory: URL { appDirectory.appendingPathComponent("ManagedSessions", isDirectory: true) }

        init(createBase: Bool = true) throws {
            container = FileManager.default.temporaryDirectory
                .appendingPathComponent("managed-session-root-\(UUID().uuidString)", isDirectory: true)
            base = container.appendingPathComponent("Application Support", isDirectory: true)
            try FileManager.default.createDirectory(at: container, withIntermediateDirectories: false)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: container.path)
            if createBase {
                try FileManager.default.createDirectory(at: base, withIntermediateDirectories: false)
                try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: base.path)
            }
        }

        func remove() {
            let descriptor = base.path.withCString {
                open($0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            }
            if descriptor >= 0 {
                var emptyACL = acl_init(0)
                if let emptyACL {
                    _ = acl_set_fd_np(descriptor, emptyACL, ACL_TYPE_EXTENDED)
                    _ = acl_free(UnsafeMutableRawPointer(emptyACL))
                }
                _ = Darwin.close(descriptor)
            }
            try? FileManager.default.removeItem(at: container)
        }
    }
}
