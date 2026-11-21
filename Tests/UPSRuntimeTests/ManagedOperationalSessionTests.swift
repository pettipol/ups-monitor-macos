import CryptoKit
import Foundation
import XCTest
@testable import UPSRuntime

final class ManagedOperationalSessionTests: XCTestCase {
    func testReceiptAcceptsOperationalCountsBeyondV1Limits() throws {
        let launchID = UUID().uuidString.lowercased()
        let receipt = try ManagedOperationalReceipt.decode(operationalReceipt(launchID: launchID), launchID: launchID)
        XCTAssertTrue(receipt.provesCleanup)
        XCTAssertEqual(receipt.captureState, "stopped")
        XCTAssertEqual(receipt.captureTerminalReason, "cancelled")
        XCTAssertEqual(receipt.adapter.capture_result?.sample_count, 25)
        XCTAssertEqual(receipt.adapter.capture_result?.runner_result?.stdout_bytes, 1_048_577)
    }

    @MainActor
    func testCleanStopWaitsForReceiptAndProcessCompletionBeforeResolvingMarker() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID)
        fake.receive?(.receipt(data))
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertEqual(controller.state, .starting)
        XCTAssertEqual(controller.receiptArchiveState, .pending)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receipt.path))
        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .stopped)
        XCTAssertEqual(controller.receiptArchiveState, .valid)
        XCTAssertEqual(try Data(contentsOf: fixture.receipt), data)
        XCTAssertEqual(permissions(at: fixture.receipt), 0o600)
        XCTAssertEqual(permissions(at: fixture.receiptStatus), 0o600)
        let status = try receiptStatus(at: fixture.receiptStatus)
        XCTAssertEqual(status["state"] as? String, "valid")
        XCTAssertEqual(status["launch_id"] as? String, fake.launchID)
        XCTAssertEqual(status["byte_count"] as? Int, data.count)
        XCTAssertEqual(status["sha256"] as? String, digest(data))
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: controller.workspace!.sessionDirectoryURL
            .appendingPathComponent("resolved-owner.json").path))
    }

    @MainActor
    func testFailedPublicationCanResolveOwnershipAndKeepsFailedState() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID, state: "failed",
                                      publicationError: "terminal_publication_failed",
                                      publishedAt: nil, terminalPublished: false)
        let receipt = try ManagedOperationalReceipt.decode(data, launchID: fake.launchID)
        XCTAssertTrue(receipt.provesCleanup)
        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testGuardErrorReceiptIsArchivedAndSessionRemainsFailed() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID, state: "failed",
                                      terminalReason: "guard_error", firstError: "guard_error",
                                      endReason: "guard_error")

        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))

        XCTAssertEqual(controller.receiptArchiveState, .valid)
        XCTAssertEqual(try Data(contentsOf: fixture.receipt), data)
        XCTAssertEqual(controller.state, .failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.sessionDirectory
            .appendingPathComponent("resolved-owner.json").path))
    }

    @MainActor
    func testMaximumSizeReceiptIsPreservedByteForByte() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        var data = operationalReceipt(launchID: fake.launchID)
        data.removeLast()
        data.append(Data(repeating: 0x20, count: 65_536 - data.count - 1))
        data.append(10)
        XCTAssertEqual(data.count, 65_536)

        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))

        XCTAssertEqual(controller.receiptArchiveState, .valid)
        XCTAssertEqual(try Data(contentsOf: fixture.receipt), data)
        XCTAssertEqual(try receiptStatus(at: fixture.receiptStatus)["byte_count"] as? Int, 65_536)
    }

    @MainActor
    func testValidReceiptWithUnresolvedCleanupIsArchivedWithoutResolvingOwner() async throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID, state: "failed",
                                      terminalReason: "guard_error", firstError: "guard_error",
                                      endReason: "guard_error", leaderReaped: false)

        fake.receive?(.receipt(data))
        XCTAssertEqual(controller.state, .unresolved)
        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))

        XCTAssertEqual(controller.receiptArchiveState, .valid)
        XCTAssertEqual(try Data(contentsOf: fixture.receipt), data)
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        let mayQuit = await controller.stopAndWait()
        XCTAssertFalse(mayQuit)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.sessionDirectory
            .appendingPathComponent("resolved-owner.json").path))
    }

    @MainActor
    func testKnownControlErrorCanSettleOwnershipButProjectsFailed() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID, adapterError: "invalid_control")
        let receipt = try ManagedOperationalReceipt.decode(data, launchID: fake.launchID)
        XCTAssertTrue(receipt.provesCleanup)
        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testCleanupAdapterErrorsKeepMarkerForEveryUnresolvedErrorCode() throws {
        let cleanupErrors = [
            "invalid_capture_receipt", "capture_failed", "observer_failed", "invalid_observer_receipt",
            "adapter_setup_failed", "watcher_join_failed", "control_close_failed", "handler_restore_failed",
        ]
        for code in cleanupErrors {
            let fixture = try Fixture(); defer { fixture.remove() }
            let fake = FakeProcess()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            _ = try startOperational(controller)
            let data = operationalReceipt(launchID: fake.launchID, adapterError: code)
            fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
            XCTAssertEqual(controller.state, .unresolved, code)
            XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path), code)
        }
    }

    @MainActor
    func testOperationalFailedCancelledReceiptRemainsFailed() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID, state: "failed", terminalReason: "cancelled")
        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    func testMalformedTypesUnknownReasonsAndContradictoryStoppedEvidenceFailClosed() throws {
        let launchID = UUID().uuidString.lowercased()
        var malformed = try receiptObject(launchID: launchID)
        malformed["schema_version"] = 1
        XCTAssertThrowsError(try ManagedOperationalReceipt.decode(encode(malformed), launchID: launchID))

        var boolCounter = try receiptObject(launchID: launchID)
        setCaptureValue(true, key: "sample_count", in: &boolCounter)
        XCTAssertThrowsError(try ManagedOperationalReceipt.decode(encode(boolCounter), launchID: launchID),
                             "Boolean must not pass as an integer counter")

        var unknownReason = try receiptObject(launchID: launchID)
        setCaptureValue("surprise", key: "terminal_reason", in: &unknownReason)
        XCTAssertThrowsError(try ManagedOperationalReceipt.decode(encode(unknownReason), launchID: launchID))

        var contradictory = try receiptObject(launchID: launchID)
        setRunnerValue("child_exited", key: "trigger", in: &contradictory)
        XCTAssertThrowsError(try ManagedOperationalReceipt.decode(encode(contradictory), launchID: launchID),
                             "A stopped capture requires cancelled runner evidence")

        var missingRunner = try receiptObject(launchID: launchID)
        setCaptureValue(NSNull(), key: "runner_result", in: &missingRunner)
        XCTAssertThrowsError(try ManagedOperationalReceipt.decode(encode(missingRunner), launchID: launchID),
                             "Missing runner evidence cannot prove cleanup")
    }

    func testFalseOwnershipFactNeverProvesCleanup() throws {
        let launchID = UUID().uuidString.lowercased()
        var receiptValue = try receiptObject(launchID: launchID)
        setRunnerValue(false, key: "group_absent", in: &receiptValue)
        let receipt = try ManagedOperationalReceipt.decode(encode(receiptValue), launchID: launchID)
        XCTAssertFalse(receipt.provesCleanup)
    }

    @MainActor
    func testWrongLaunchAndInvalidReceiptKeepMarker() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: UUID().uuidString.lowercased())
        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertEqual(controller.receiptArchiveState, .invalid)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receipt.path))
        XCTAssertEqual(try receiptStatus(at: fixture.receiptStatus)["state"] as? String, "invalid")
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
    }

    @MainActor
    func testAbsentAndOversizedFinalOutputPersistOnlyBoundedStatus() throws {
        for (index, data, withinBounds, expected) in [
            (0, Data(), true, "absent"),
            (1, Data(repeating: 0x58, count: 65_537), false, "invalid"),
        ] {
            let fixture = try Fixture(); defer { fixture.remove() }
            let fake = FakeProcess()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            _ = try startOperational(controller)

            fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: withinBounds)))

            XCTAssertEqual(controller.receiptArchiveState.rawValue, expected, "case \(index)")
            XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receipt.path))
            let statusBytes = try Data(contentsOf: fixture.receiptStatus)
            XCTAssertLessThanOrEqual(statusBytes.count, 1_024)
            XCTAssertEqual(try receiptStatus(at: fixture.receiptStatus)["state"] as? String, expected)
            XCTAssertEqual(controller.state, .unresolved)
            XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        }
    }

    @MainActor
    func testReceiptArchiveRejectsCollisionsAndSymlinksWithoutOverwrite() throws {
        for (index, name, symbolic) in [
            (0, "managed-receipt.json", false),
            (1, "managed-receipt.json", true),
            (2, "managed-receipt.tmp", false),
            (3, "managed-receipt.tmp", true),
        ] {
            let fixture = try Fixture(); defer { fixture.remove() }
            let fake = FakeProcess()
            let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
            _ = try startOperational(controller)
            let collision = fixture.sessionDirectory.appendingPathComponent(name)
            if symbolic {
                try FileManager.default.createSymbolicLink(at: collision,
                    withDestinationURL: fixture.container)
            } else {
                try Data("preexisting".utf8).write(to: collision)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: collision.path)
            }
            let data = operationalReceipt(launchID: fake.launchID)

            fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))

            XCTAssertEqual(controller.receiptArchiveState, .writeFailed, "case \(index)")
            XCTAssertEqual(controller.state, .unresolved)
            XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
            XCTAssertTrue(FileManager.default.fileExists(atPath: collision.path))
            if symbolic {
                XCTAssertEqual(try FileManager.default.destinationOfSymbolicLink(atPath: collision.path),
                               fixture.container.path)
            }
            XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receiptStatus.path))
        }
    }

    @MainActor
    func testStatusPersistenceFailureKeepsValidReceiptButDoesNotResolveOwner() async throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let statusTemporary = fixture.sessionDirectory.appendingPathComponent("managed-receipt-status.tmp")
        try FileManager.default.createSymbolicLink(at: statusTemporary,
            withDestinationURL: fixture.container)
        let data = operationalReceipt(launchID: fake.launchID)

        fake.receive?(.finished(.init(returnCode: 0, receipt: data, outputWithinBounds: true)))

        XCTAssertEqual(controller.receiptArchiveState, .writeFailed)
        XCTAssertEqual(try Data(contentsOf: fixture.receipt), data)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receiptStatus.path))
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
        let mayQuit = await controller.stopAndWait()
        XCTAssertFalse(mayQuit)
    }

    @MainActor
    func testPreliminaryReceiptEventIsNeverArchivedAndDuplicateFinishedIsIgnored() throws {
        let fixture = try Fixture(); defer { fixture.remove() }
        let fake = FakeProcess()
        let controller = ManagedSyntheticSessionController(root: { fixture.root }, makeProcess: { fake })
        _ = try startOperational(controller)
        let data = operationalReceipt(launchID: fake.launchID)

        fake.receive?(.receipt(data))

        XCTAssertEqual(controller.receiptArchiveState, .pending)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receipt.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.receiptStatus.path))
        fake.receive?(.finished(.init(returnCode: 7, receipt: data, outputWithinBounds: true)))
        let laterCleanReceipt = operationalReceipt(launchID: fake.launchID)
        fake.receive?(.finished(.init(returnCode: 0, receipt: laterCleanReceipt, outputWithinBounds: true)))
        XCTAssertEqual(controller.receiptArchiveState, .valid)
        XCTAssertEqual(try Data(contentsOf: fixture.receipt), data)
        XCTAssertEqual(controller.state, .unresolved)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.marker.path))
    }
}

@MainActor
private func startOperational(_ controller: ManagedSyntheticSessionController) throws -> URL {
    try controller.start(profile: .operational) { _, launchID in
        ManagedSyntheticLaunch(executableURL: URL(fileURLWithPath: "/synthetic/python"), arguments: [launchID])
    }
}

private func operationalReceipt(launchID: String, state: String = "stopped",
                                adapterError: String? = nil, publicationError: String? = nil,
                                publishedAt: Int64? = 2_000, terminalPublished: Bool = true,
                                terminalReason: String? = nil, firstError: String? = nil,
                                endReason: String? = nil, leaderReaped: Bool = true) -> Data {
    try! encode(receiptObject(launchID: launchID, state: state, adapterError: adapterError,
                              publicationError: publicationError, publishedAt: publishedAt,
                              terminalPublished: terminalPublished, terminalReason: terminalReason,
                              firstError: firstError, endReason: endReason, leaderReaped: leaderReaped))
}

private func receiptObject(launchID: String, state: String = "stopped",
                          adapterError: String? = nil, publicationError: String? = nil,
                          publishedAt: Int64? = 2_000, terminalPublished: Bool = true,
                          terminalReason: String? = nil, firstError: String? = nil,
                          endReason: String? = nil, leaderReaped: Bool = true) throws -> [String: Any] {
    let runner: [String: Any] = [
        "trigger": "cancelled", "returncode": 0, "stdout_bytes": 1_048_577, "stderr_bytes": 8,
        "stdout_sha256": String(repeating: "a", count: 64), "stderr_sha256": String(repeating: "b", count: 64),
        "leader_reaped": leaderReaped, "group_absent": true, "stdout_eof": true, "stderr_eof": true,
        "consumer_quiesced": true,
    ]
    let capture: [String: Any] = [
        "schema_version": 2, "protocol": "ups-monitor.continuous.v2", "state": state,
        "terminal_reason": terminalReason ?? (state == "stopped" ? "cancelled" : "io_error"),
        "first_error": firstError as Any? ?? (state == "stopped" || terminalReason == "cancelled" ? NSNull() : "io_error"),
        "publication_error": publicationError as Any? ?? NSNull(),
        "source_id": "apcmicrolink-hidapi-operational", "session_id": String(repeating: "a", count: 32),
        "started_at_unix_ms": 1_000, "published_at_unix_ms": publishedAt as Any? ?? NSNull(),
        "sample_count": 25, "end_reason": endReason ?? "cancelled", "runner_result": runner,
        "consumer_quiesced": true, "publisher_quiesced": true, "publisher_closed": true,
        "terminal_published": terminalPublished, "ownership_resolved": true,
    ]
    let adapter: [String: Any] = [
        "capture_result": capture, "control_reason": "stop",
        "adapter_error": adapterError as Any? ?? NSNull(), "watcher_quiesced": true,
        "ownership_resolved": true,
    ]
    return ["protocol": "ups-monitor.managed-operational.v2", "schema_version": 2,
            "launch_id": launchID, "adapter": adapter]
}

private func setCaptureValue(_ value: Any, key: String, in envelope: inout [String: Any]) {
    guard var adapter = envelope["adapter"] as? [String: Any],
          var capture = adapter["capture_result"] as? [String: Any] else { return }
    capture[key] = value
    adapter["capture_result"] = capture
    envelope["adapter"] = adapter
}

private func setRunnerValue(_ value: Any, key: String, in envelope: inout [String: Any]) {
    guard var adapter = envelope["adapter"] as? [String: Any],
          var capture = adapter["capture_result"] as? [String: Any],
          var runner = capture["runner_result"] as? [String: Any] else { return }
    runner[key] = value
    capture["runner_result"] = runner
    adapter["capture_result"] = capture
    envelope["adapter"] = adapter
}

private func encode(_ object: [String: Any]) throws -> Data {
    try JSONSerialization.data(withJSONObject: object) + Data([10])
}

private func digest(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

private func receiptStatus(at url: URL) throws -> [String: Any] {
    try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
}

private func permissions(at url: URL) -> Int? {
    (try? FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as? NSNumber)?.intValue
}

@MainActor private final class FakeProcess: ManagedSyntheticProcessHandle {
    var receive: (@MainActor (ManagedSyntheticProcessEvent) -> Void)?
    var launchID = ""
    func start(_ launch: ManagedSyntheticLaunch,
               receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        launchID = launch.arguments.last ?? ""
        self.receive = receive
    }
    func requestStop() {}
}

private struct Fixture {
    let container: URL
    let root: URL
    var marker: URL { root.appendingPathComponent("active-owner.json") }
    var sessionDirectory: URL {
        let children = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        return children.first { $0.lastPathComponent.hasPrefix("session-") }!
    }
    var receipt: URL { sessionDirectory.appendingPathComponent("managed-receipt.json") }
    var receiptStatus: URL { sessionDirectory.appendingPathComponent("managed-receipt-status.json") }

    init() throws {
        container = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        root = container.appendingPathComponent("sessions", isDirectory: true)
        try FileManager.default.createDirectory(at: container, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
    }
    func remove() { try? FileManager.default.removeItem(at: container) }
}
