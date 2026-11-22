import Darwin
import Foundation
import XCTest
import UPSRuntime

final class ManagedSessionWorkspaceTests: XCTestCase {
    func testCreatesPrivateSessionAndEmptyChildren() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }

        let workspace = try ManagedSessionWorkspace.create(in: fixture.root)

        XCTAssertTrue(workspace.sessionDirectoryURL.lastPathComponent.hasPrefix("session-"))
        XCTAssertEqual(permissions(at: workspace.sessionDirectoryURL), 0o700)
        XCTAssertEqual(permissions(at: workspace.feedDirectoryURL), 0o700)
        XCTAssertEqual(permissions(at: workspace.captureDirectoryURL), 0o700)
        XCTAssertTrue(isDirectory(workspace.sessionDirectoryURL))
        XCTAssertTrue(isDirectory(workspace.feedDirectoryURL))
        XCTAssertTrue(isDirectory(workspace.captureDirectoryURL))
        XCTAssertEqual(try children(of: workspace.sessionDirectoryURL), ["capture", "feed"])
        XCTAssertEqual(try children(of: workspace.feedDirectoryURL), [])
        XCTAssertEqual(try children(of: workspace.captureDirectoryURL), [])
    }

    func testEachCreationUsesANewSessionDirectory() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }

        let first = try ManagedSessionWorkspace.create(in: fixture.root)
        let second = try ManagedSessionWorkspace.create(in: fixture.root)

        XCTAssertNotEqual(first.sessionDirectoryURL, second.sessionDirectoryURL)
        XCTAssertNotEqual(first.sessionDirectoryURL.lastPathComponent, second.sessionDirectoryURL.lastPathComponent)
        XCTAssertEqual(try children(of: fixture.root).count, 2)
    }

    func testRejectsMissingRootWithoutCreatingIt() throws {
        let fixture = try Fixture(createRoot: false)
        defer { fixture.remove() }

        XCTAssertThrowsError(try ManagedSessionWorkspace.create(in: fixture.root)) { error in
            XCTAssertEqual(error as? ManagedSessionWorkspaceError, .unsafeRoot)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.root.path))
        XCTAssertEqual(try children(of: fixture.container), [])
    }

    func testRejectsRootPathContainingNULWithoutChangingTheRealRoot() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let nulRoot = URL(fileURLWithPath: fixture.root.path + "\0suffix", isDirectory: true)

        XCTAssertThrowsError(try ManagedSessionWorkspace.create(in: nulRoot)) { error in
            XCTAssertEqual(error as? ManagedSessionWorkspaceError, .unsafeRoot)
        }
        XCTAssertEqual(permissions(at: fixture.root), 0o700)
        XCTAssertEqual(try children(of: fixture.root), [])
    }

    func testRejectsRootWithNonPrivatePermissionsWithoutChangingIt() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try FileManager.default.setAttributes([.posixPermissions: 0o750], ofItemAtPath: fixture.root.path)

        XCTAssertThrowsError(try ManagedSessionWorkspace.create(in: fixture.root)) { error in
            XCTAssertEqual(error as? ManagedSessionWorkspaceError, .unsafeRoot)
        }
        XCTAssertEqual(permissions(at: fixture.root), 0o750)
        XCTAssertEqual(try children(of: fixture.root), [])
    }

    func testRejectsRegularFileAsRootWithoutChangingIt() throws {
        let fixture = try Fixture(createRoot: false)
        defer { fixture.remove() }
        try Data("fixture".utf8).write(to: fixture.root)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fixture.root.path)

        XCTAssertThrowsError(try ManagedSessionWorkspace.create(in: fixture.root)) { error in
            XCTAssertEqual(error as? ManagedSessionWorkspaceError, .unsafeRoot)
        }
        XCTAssertEqual(try Data(contentsOf: fixture.root), Data("fixture".utf8))
        XCTAssertEqual(permissions(at: fixture.root), 0o600)
    }

    func testRejectsSymlinkRootWithoutTouchingTarget() throws {
        let fixture = try Fixture(createRoot: false)
        defer { fixture.remove() }
        let target = fixture.container.appendingPathComponent("target", isDirectory: true)
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: false)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: target.path)
        try FileManager.default.createSymbolicLink(atPath: fixture.root.path, withDestinationPath: "target")

        XCTAssertThrowsError(try ManagedSessionWorkspace.create(in: fixture.root)) { error in
            XCTAssertEqual(error as? ManagedSessionWorkspaceError, .unsafeRoot)
        }
        XCTAssertEqual(permissions(at: target), 0o700)
        XCTAssertEqual(try children(of: target), [])
        XCTAssertTrue(try FileManager.default.destinationOfSymbolicLink(atPath: fixture.root.path) == "target")
    }

    func testRejectsRootWithExtendedACLWithoutChangingItsContentsOrMode() throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try Self.setExtendedACL(at: fixture.root)

        XCTAssertThrowsError(try ManagedSessionWorkspace.create(in: fixture.root)) { error in
            XCTAssertEqual(error as? ManagedSessionWorkspaceError, .unsafeRoot)
        }
        XCTAssertEqual(permissions(at: fixture.root), 0o700)
        XCTAssertEqual(try children(of: fixture.root), [])
        XCTAssertTrue(Self.hasExtendedACL(at: fixture.root))
    }

    private func permissions(at url: URL) -> Int? {
        (try? FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber)?.intValue
    }

    private func isDirectory(_ url: URL) -> Bool {
        (try? FileManager.default.attributesOfItem(atPath: url.path)[.type] as? FileAttributeType) == .typeDirectory
    }

    private func children(of url: URL) throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: url.path).sorted()
    }

    private static func setExtendedACL(at url: URL) throws {
        var acl = acl_init(1)
        guard acl != nil else { throw POSIXError(.ENOMEM) }
        defer { if let acl { _ = acl_free(UnsafeMutableRawPointer(acl)) } }
        var entry: acl_entry_t?
        guard acl_create_entry(&acl, &entry) == 0, let entry else { throw POSIXError(.EINVAL) }
        guard acl_set_tag_type(entry, ACL_EXTENDED_ALLOW) == 0 else { throw POSIXError(.EINVAL) }
        var qualifier = UUID().uuid
        let qualifierResult = withUnsafePointer(to: &qualifier) { acl_set_qualifier(entry, $0) }
        var permissions: acl_permset_t?
        guard qualifierResult == 0,
              acl_get_permset(entry, &permissions) == 0,
              acl_add_perm(permissions, ACL_READ_DATA) == 0,
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

    private struct Fixture {
        let container: URL
        let root: URL

        init(createRoot: Bool = true) throws {
            container = FileManager.default.temporaryDirectory
                .appendingPathComponent("managed-session-workspace-\(UUID().uuidString)", isDirectory: true)
            root = container.appendingPathComponent("private", isDirectory: true)
            try FileManager.default.createDirectory(at: container, withIntermediateDirectories: false)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: container.path)
            if createRoot {
                try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
                try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root.path)
            }
        }

        func remove() { try? FileManager.default.removeItem(at: container) }
    }
}
