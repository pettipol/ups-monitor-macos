import CryptoKit
import Foundation
import Testing
import NUTClient
import NUTData
import UPSModel
@testable import UPSRuntime

private struct ExecutableFixture {
    let directory: URL
    let executable: URL
    let marker: URL

    init(contents: Data? = nil) throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        executable = directory.appendingPathComponent("fixture")
        marker = directory.appendingPathComponent("launched")
        let script = contents ?? Data("#!/bin/sh\ntouch '\(marker.path)'\n".utf8)
        try script.write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
    }

    var digest: String { SHA256.hash(data: (try? Data(contentsOf: executable)) ?? Data()).map { String(format: "%02x", $0) }.joined() }

    func cleanup() { try? FileManager.default.removeItem(at: directory) }
}

private func configuration(
    executable: URL,
    sourceID: String = "fixture-source",
    upsName: String = "fixture-ups"
) throws -> UPSCClientConfiguration {
    try UPSCClientConfiguration(
        executableURL: executable,
        executableQualification: .completionHardened,
        upsName: upsName,
        sourceID: sourceID
    )
}

@Suite struct NUTSnapshotReaderTests {
@Test func validHashPreflightDoesNotLaunchExecutable() async throws {
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let reader = try NUTSnapshotReader(configuration: config, expectedSHA256: fixture.digest, sessionID: "session-test")

    try await reader.validateExecutable()

    #expect(!FileManager.default.fileExists(atPath: fixture.marker.path))
}

@Test func digestMismatchRejectsBeforeAnyProcessCanLaunch() async throws {
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let reader = try NUTSnapshotReader(configuration: config, expectedSHA256: String(repeating: "0", count: 64), sessionID: "session-test")

    await #expect(throws: NUTSnapshotReaderError.digestMismatch) { try await reader.read() }
    #expect(!FileManager.default.fileExists(atPath: fixture.marker.path))
}

@Test func expectedDigestAndIdentityAreValidatedAtConstruction() throws {
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)

    #expect(throws: NUTSnapshotReaderError.invalidExpectedSHA256) {
        try NUTSnapshotReader(configuration: config, expectedSHA256: "not-a-digest")
    }
    #expect(throws: NUTSnapshotReaderError.invalidIdentity) {
        try NUTSnapshotReader(configuration: config, expectedSHA256: fixture.digest, sessionID: "bad session")
    }
    let opaqueIDConfig = try configuration(executable: fixture.executable, sourceID: "nut-opaque-session", upsName: "u")
    _ = try NUTSnapshotReader(
        configuration: opaqueIDConfig, expectedSHA256: fixture.digest, sessionID: "session-test"
    )
}

@Test func symlinkHardlinkUnsafeModeAndOversizeAreRejected() async throws {
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let reader = try NUTSnapshotReader(configuration: config, expectedSHA256: fixture.digest, sessionID: "session-test")

    let symlink = fixture.directory.appendingPathComponent("symlink")
    try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: fixture.executable)
    #expect(throws: UPSCClientConfigurationError.invalidExecutable) {
        try configuration(executable: symlink)
    }

    let hardlink = fixture.directory.appendingPathComponent("hardlink")
    try FileManager.default.linkItem(at: fixture.executable, to: hardlink)
    await #expect(throws: NUTSnapshotReaderError.unsafeExecutable) { try await reader.validateExecutable() }
    try FileManager.default.removeItem(at: hardlink)

    try FileManager.default.setAttributes([.posixPermissions: 0o770], ofItemAtPath: fixture.executable.path)
    await #expect(throws: NUTSnapshotReaderError.unsafeExecutable) { try await reader.validateExecutable() }
    try FileManager.default.setAttributes([.posixPermissions: 0o4700], ofItemAtPath: fixture.executable.path)
    await #expect(throws: NUTSnapshotReaderError.unsafeExecutable) { try await reader.validateExecutable() }

    let large = try ExecutableFixture(contents: Data(repeating: 0x41, count: 64 * 1024 * 1024 + 1))
    defer { large.cleanup() }
    let largeReader = try NUTSnapshotReader(
        configuration: configuration(executable: large.executable), expectedSHA256: large.digest, sessionID: "session-test"
    )
    await #expect(throws: NUTSnapshotReaderError.executableTooLarge) { try await largeReader.validateExecutable() }
}

@Test func readAdaptsSyntheticSnapshotAndKeepsConfiguredIdentity() async throws {
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let capturedAt = Date(timeIntervalSince1970: 1_700_000_123.456)
    let nut = NUTSnapshot(
        sourceID: config.sourceID,
        capturedAt: capturedAt,
        status: NUTStatus(lineState: .onLine, flags: [], quality: .available),
        metrics: [.upsLoad: NUTMetric(identifier: .upsLoad, value: 42, quality: .available)]
    )
    let reader = try NUTSnapshotReader(
        configuration: config, expectedSHA256: fixture.digest, sessionID: "session-test", snapshotRead: { nut }
    )

    let snapshots = try await reader.read()
    #expect(snapshots.count == 1)
    #expect(snapshots[0].source.provider == .nut)
    #expect(snapshots[0].source.id == config.sourceID)
    #expect(snapshots[0].source.sessionID == "session-test")
    #expect(snapshots[0].source.identityStability == .configured)
    #expect(snapshots[0].capturedAt == capturedAt)
    #expect(snapshots[0].metrics.first?.value == 42)
    #expect(!FileManager.default.fileExists(atPath: fixture.marker.path))
}

@Test func preCancelledValidationDoesNotHashOrRead() async throws {
    actor Calls { var value = 0; func increment() { value += 1 } }
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let calls = Calls()
    let reader = try NUTSnapshotReader(
        configuration: config,
        expectedSHA256: fixture.digest,
        sessionID: "session-test",
        snapshotRead: { await calls.increment(); throw UPSCClientError.processFailed }
    )
    let task = Task {
        withUnsafeCurrentTask { $0?.cancel() }
        return try await reader.read()
    }

    await #expect(throws: NUTSnapshotReaderError.cancelled) { try await task.value }
    #expect(await calls.value == 0)
}

@Test func concurrentReadIsRejectedWhileFirstReadIsSuspended() async throws {
    actor SnapshotGate {
        var continuation: CheckedContinuation<NUTSnapshot, Error>?
        var started = false

        func read() async throws -> NUTSnapshot {
            started = true
            return try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
            }
        }

        func waitUntilStarted() async {
            while !started { await Task.yield() }
        }

        func release(_ snapshot: NUTSnapshot) {
            continuation?.resume(returning: snapshot)
            continuation = nil
        }
    }

    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let nut = NUTSnapshot(
        sourceID: config.sourceID,
        capturedAt: Date(timeIntervalSince1970: 1_700_000_124),
        status: NUTStatus(lineState: .onLine, flags: [], quality: .available),
        metrics: [:]
    )
    let gate = SnapshotGate()
    let reader = try NUTSnapshotReader(
        configuration: config,
        expectedSHA256: fixture.digest,
        sessionID: "session-test",
        snapshotRead: { try await gate.read() }
    )
    let firstRead = Task { try await reader.read() }
    await gate.waitUntilStarted()

    await #expect(throws: NUTSnapshotReaderError.readInProgress) { try await reader.read() }
    await gate.release(nut)
    #expect(try await firstRead.value.count == 1)
}

@Test func changedExecutableAfterPreflightRejectsBeforeSnapshotRead() async throws {
    actor Calls { var value = 0; func increment() { value += 1 } }
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let calls = Calls()
    let reader = try NUTSnapshotReader(
        configuration: config,
        expectedSHA256: fixture.digest,
        sessionID: "session-test",
        snapshotRead: { await calls.increment(); throw UPSCClientError.processFailed }
    )
    try await reader.validateExecutable()
    try Data("#!/bin/sh\nexit 2\n".utf8).write(to: fixture.executable)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: fixture.executable.path)

    await #expect(throws: NUTSnapshotReaderError.digestMismatch) { try await reader.read() }
    #expect(await calls.value == 0)
}

@Test func callbackFailureAndSourceMismatchAreMappedToRedactedErrors() async throws {
    enum FixtureError: Error { case failure }
    let fixture = try ExecutableFixture()
    defer { fixture.cleanup() }
    let config = try configuration(executable: fixture.executable)
    let failingReader = try NUTSnapshotReader(
        configuration: config,
        expectedSHA256: fixture.digest,
        sessionID: "session-test",
        snapshotRead: { throw FixtureError.failure }
    )
    await #expect(throws: NUTSnapshotReaderError.readFailed) { try await failingReader.read() }

    let mismatchedSnapshot = NUTSnapshot(
        sourceID: "other-source",
        capturedAt: Date(timeIntervalSince1970: 1_700_000_125),
        status: NUTStatus(lineState: .onLine, flags: [], quality: .available),
        metrics: [:]
    )
    let mismatchedReader = try NUTSnapshotReader(
        configuration: config,
        expectedSHA256: fixture.digest,
        sessionID: "session-test",
        snapshotRead: { mismatchedSnapshot }
    )
    await #expect(throws: NUTSnapshotReaderError.invalidSnapshot) { try await mismatchedReader.read() }
}
}
