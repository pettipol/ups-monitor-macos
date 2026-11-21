import CryptoKit
import Darwin
import Foundation
import XCTest
import UPSModel
@testable import UPSRuntime

final class NUTObservationBundleReaderTests: XCTestCase {
    private let stdout = Data(("Network UPS Tools 2.8.5.1 (development iteration after 2.8.5) - APC Microlink protocol driver 0.05\n" +
                               "Warning: This is an experimental driver.\nSome features may not function correctly.\n\n" +
                               "driver.name: full-nut-hidapi-fake\nups.status: OL\nbattery.charge: 76\nbattery.runtime: 590\n").utf8)
    private let stderr = Data("synthetic warning\n".utf8)
    private let pin = String(repeating: "a", count: 64)
    private let started = Date(timeIntervalSince1970: 1_800_000_000)
    private let finished = Date(timeIntervalSince1970: 1_800_000_002)
    private let now = Date(timeIntervalSince1970: 1_800_000_010)

    func testImportsValidBundleWithoutRenewingOriginalDates() throws {
        let fixture = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished)
        let result = try reader().read(sessionDirectoryURL: fixture.sessionURL, origin: .archivedSupervisedDriverDump,
                                       source: source(), expectedExecutableSHA256: pin, now: now)
        XCTAssertFalse(result.dataQualified)
        XCTAssertEqual(result.origin, .archivedSupervisedDriverDump)
        XCTAssertEqual(result.startedAt, started)
        XCTAssertEqual(result.finishedAt, finished)
        XCTAssertEqual(result.unqualifiedSnapshot.capturedAt, started)
    }

    func testRejectsMissingOrUnsafeEntries() throws {
        do {
            let fixture = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished)
            try FileManager.default.removeItem(at: fixture.sessionURL.appendingPathComponent("stderr.bin"))
            XCTAssertThrowsError(try read(fixture))
        }
        for kind in ["symlink", "hardlink", "fifo", "directory", "permissions"] {
            let fixture = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished)
            try fixture.replaceStdout(kind: kind)
            XCTAssertThrowsError(try read(fixture), "must reject \(kind)")
        }
    }

    func testRejectsUntrustedParentAndUnsafeSessionDirectory() throws {
        let untrustedParent = try fixture()
        try FileManager.default.setAttributes([.posixPermissions: 0o777], ofItemAtPath: untrustedParent.root.path)
        XCTAssertThrowsError(try read(untrustedParent))

        let wrongMode = try fixture()
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: wrongMode.sessionURL.path)
        XCTAssertThrowsError(try read(wrongMode))

        let symlinkSession = try fixture()
        try FileManager.default.removeItem(at: symlinkSession.sessionURL)
        try FileManager.default.createSymbolicLink(at: symlinkSession.sessionURL, withDestinationURL: symlinkSession.root)
        XCTAssertThrowsError(try read(symlinkSession))
    }

    func testRejectsOversizedReceiptAndCaptureAggregate() throws {
        let oversizedReceipt = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished,
                                                 receiptOverride: Data(repeating: 0x20, count: 8_193))
        XCTAssertThrowsError(try read(oversizedReceipt)) { XCTAssertEqual($0 as? NUTObservationBundleReaderError, .payloadTooLarge) }

        let oversizedCapture = try BundleFixture(stdout: Data(repeating: 0x61, count: 65_536),
                                                 stderr: Data(repeating: 0x62, count: 983_041),
                                                 pin: pin, started: started, finished: finished)
        XCTAssertThrowsError(try read(oversizedCapture)) { XCTAssertEqual($0 as? NUTObservationBundleReaderError, .payloadTooLarge) }

        let oversizedStdout = try BundleFixture(stdout: Data(repeating: 0x61, count: 65_537), stderr: Data(),
                                                pin: pin, started: started, finished: finished)
        XCTAssertThrowsError(try read(oversizedStdout)) { XCTAssertEqual($0 as? NUTObservationBundleReaderError, .payloadTooLarge) }
    }

    func testAcceptsExplicitlyEmptyExtendedACLs() throws {
        let fixture = try fixture()
        for url in fixture.bundleURLs {
            try fixture.setExtendedACL(nil, at: url)
        }
        XCTAssertNoThrow(try read(fixture))
    }

    func testRejectsNonemptyExtendedACLsOnEveryBundleObject() throws {
        for index in 0..<5 {
            for entry in ["allow write", "allow read", "deny delete"] {
                let fixture = try fixture()
                let url = fixture.bundleURLs[index]
                try fixture.setExtendedACL(entry, at: url)
                XCTAssertThrowsError(try read(fixture), "must reject ACL \(entry) on \(url.lastPathComponent)") {
                    XCTAssertEqual($0 as? NUTObservationBundleReaderError, .unsafeBundle)
                }
            }
        }
    }

    func testDelegatesPinHashAndProcessFailureChecksToDecoder() throws {
        let valid = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished)
        XCTAssertThrowsError(try reader().read(sessionDirectoryURL: valid.sessionURL, origin: .archivedSupervisedDriverDump,
                                               source: source(), expectedExecutableSHA256: String(repeating: "b", count: 64), now: now)) {
            XCTAssertEqual($0 as? NUTObservationImportError, .executablePinMismatch)
        }
        let mismatch = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished)
        try mismatch.replaceStdoutBytes(with: Data(repeating: 0x78, count: stdout.count))
        XCTAssertThrowsError(try read(mismatch)) { XCTAssertEqual($0 as? NUTObservationImportError, .invalidDigest) }
        let failure = try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished, status: "timed_out")
        XCTAssertThrowsError(try read(failure)) { XCTAssertEqual($0 as? NUTObservationImportError, .unsuccessfulProcess) }
    }

    func testStatusOnlyDumpImportsWithoutInventingNumericMeasurements() throws {
        let statusOnly = Data(("Network UPS Tools 2.8.5.1 (development iteration after 2.8.5) - APC Microlink protocol driver 0.05\n" +
                              "Warning: This is an experimental driver.\nSome features may not function correctly.\n\n" +
                              "driver.name: full-nut-hidapi-fake\nups.status: OL\n").utf8)
        let fixture = try BundleFixture(stdout: statusOnly, stderr: Data(), pin: pin, started: started, finished: finished)
        let result = try read(fixture)
        XCTAssertFalse(result.dataQualified)
        XCTAssertEqual(result.unqualifiedSnapshot.status.lineState, .onLine)
        XCTAssertTrue(result.unqualifiedSnapshot.metrics.allSatisfy { $0.value == nil })
    }

    func testRejectsEmptyDump() throws {
        let fixture = try BundleFixture(stdout: Data(), stderr: Data(), pin: pin, started: started, finished: finished)
        XCTAssertThrowsError(try read(fixture)) { XCTAssertEqual($0 as? NUTObservationImportError, .invalidDump) }
    }

    private func fixture() throws -> BundleFixture {
        try BundleFixture(stdout: stdout, stderr: stderr, pin: pin, started: started, finished: finished)
    }

    private func read(_ fixture: BundleFixture) throws -> ImportedNUTObservation {
        try reader().read(sessionDirectoryURL: fixture.sessionURL, origin: .archivedSupervisedDriverDump,
                          source: source(), expectedExecutableSHA256: pin, now: now)
    }

    private func reader() -> NUTObservationBundleReader { NUTObservationBundleReader() }

    private func source() -> MonitorSource {
        MonitorSource(provider: .nut, id: "synthetic", sessionID: "archive", identityStability: .configured)
    }

    private func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private final class BundleFixture {
        let root: URL
        let sessionURL: URL

        var bundleURLs: [URL] {
            [root, sessionURL] + ["receipt.json", "stdout.bin", "stderr.bin"].map {
                sessionURL.appendingPathComponent($0)
            }
        }

        init(stdout: Data, stderr: Data, pin: String, started: Date, finished: Date,
             receiptOverride: Data? = nil, status: String = "exited") throws {
            root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            sessionURL = root.appendingPathComponent("session", isDirectory: true)
            try FileManager.default.createDirectory(at: sessionURL, withIntermediateDirectories: true)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root.path)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: sessionURL.path)
            let receipt: [String: Any] = [
                "schema_version": 1, "status": status, "trigger": status == "exited" ? "completed" : "timeout",
                "returncode": (status == "exited" ? 0 : NSNull()) as Any, "stdout_bytes": stdout.count,
                "stderr_bytes": stderr.count, "maximum_output_bytes": 1_048_576,
                "executable_sha256": pin, "stdout_sha256": hash(stdout), "stderr_sha256": hash(stderr),
                "started_at_unix_seconds": started.timeIntervalSince1970,
                "finished_at_unix_seconds": finished.timeIntervalSince1970,
                "data_qualified": false, "error": NSNull(),
            ]
            let encoded = try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys])
            try write(receiptOverride ?? encoded, name: "receipt.json")
            try write(stdout, name: "stdout.bin")
            try write(stderr, name: "stderr.bin")
        }

        func replaceStdout(kind: String) throws {
            let file = sessionURL.appendingPathComponent("stdout.bin")
            try FileManager.default.removeItem(at: file)
            switch kind {
            case "symlink": try FileManager.default.createSymbolicLink(at: file, withDestinationURL: sessionURL.appendingPathComponent("stderr.bin"))
            case "hardlink": try FileManager.default.linkItem(at: sessionURL.appendingPathComponent("stderr.bin"), to: file)
            case "fifo":
                let result = file.path.withCString { mkfifo($0, mode_t(0o600)) }
                XCTAssertEqual(result, 0)
            case "directory": try FileManager.default.createDirectory(at: file, withIntermediateDirectories: false)
            case "permissions": try Data("x".utf8).write(to: file); try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file.path)
            default: XCTFail("unknown fixture kind")
            }
        }

        func replaceStdoutBytes(with data: Data) throws {
            let url = sessionURL.appendingPathComponent("stdout.bin")
            try data.write(to: url)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        }

        func setExtendedACL(_ entry: String?, at url: URL) throws {
            var acl = acl_init(entry == nil ? 0 : 1)
            guard acl != nil else { throw POSIXError(.ENOMEM) }
            defer { if let acl { _ = acl_free(UnsafeMutableRawPointer(acl)) } }
            if let entry {
                var aclEntry: acl_entry_t?
                guard acl_create_entry(&acl, &aclEntry) == 0, let aclEntry else { throw POSIXError(.EINVAL) }
                var qualifier = UUID().uuid
                let tag = entry == "deny delete" ? ACL_EXTENDED_DENY : ACL_EXTENDED_ALLOW
                guard acl_set_tag_type(aclEntry, tag) == 0 else { throw POSIXError(.EINVAL) }
                let qualifierResult = withUnsafePointer(to: &qualifier) { acl_set_qualifier(aclEntry, $0) }
                let permission = entry == "allow write" ? ACL_WRITE_DATA : (entry == "allow read" ? ACL_READ_DATA : ACL_DELETE)
                var permissions: acl_permset_t?
                guard qualifierResult == 0,
                      acl_get_permset(aclEntry, &permissions) == 0,
                      acl_add_perm(permissions, permission) == 0 else { throw POSIXError(.EINVAL) }
            }
            guard let acl else { throw POSIXError(.EINVAL) }
            let descriptor = url.path.withCString { open($0, O_RDONLY | O_NOFOLLOW | O_CLOEXEC) }
            guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            defer { _ = Darwin.close(descriptor) }
            guard acl_set_fd_np(descriptor, acl, ACL_TYPE_EXTENDED) == 0 else {
                throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
            }
        }

        private func write(_ data: Data, name: String) throws {
            let url = sessionURL.appendingPathComponent(name)
            try data.write(to: url)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        }

        private func hash(_ data: Data) -> String {
            SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        }

        deinit { try? FileManager.default.removeItem(at: root) }
    }
}
