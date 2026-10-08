import Darwin
import Foundation
import Testing
import UPSModel
@testable import UPSWidgetData

private let widgetNow = Date(timeIntervalSince1970: 50_000)
private let widgetSource = MonitorSource(provider: .nut, id: "fixture-ups", sessionID: "session-a", identityStability: .configured)

private func monitorSample(at date: Date = widgetNow) -> MonitorSnapshot {
    MonitorSnapshot(
        source: widgetSource,
        capturedAt: date,
        status: MonitorStatus(quality: .unavailable),
        metrics: []
    )
}

private func widgetPayload(
    acquisition: WidgetAcquisition = .active,
    publishedAt: Date = widgetNow,
    snapshot: MonitorSnapshot? = monitorSample(),
    maximumAge: TimeInterval = 60
) -> WidgetSnapshot {
    WidgetSnapshot(publishedAt: publishedAt, acquisition: acquisition, maximumAge: maximumAge, snapshot: snapshot)
}

private func fixtureDirectory() -> URL {
    FileManager.default.temporaryDirectory.appendingPathComponent("widget-store-\(UUID().uuidString)", isDirectory: true)
}

@Test func payloadValidationAndFreshnessAreStrict() throws {
    let payload = widgetPayload()
    try payload.validate()
    #expect(!payload.isStale(at: widgetNow.addingTimeInterval(60)))
    #expect(payload.isStale(at: widgetNow.addingTimeInterval(60.01)))
    #expect(payload.isStale(at: Date(timeIntervalSince1970: .infinity)))
    #expect(widgetPayload(publishedAt: widgetNow.addingTimeInterval(1)).isStale(at: widgetNow))
    #expect(widgetPayload(acquisition: .stopped).isStale(at: widgetNow))
    #expect(widgetPayload(acquisition: .readFailed).isStale(at: widgetNow))

    #expect(throws: WidgetSnapshotValidationError.invalidAcquisition) {
        try WidgetSnapshot(publishedAt: widgetNow, acquisition: .active, maximumAge: 10, snapshot: nil).validate()
    }
    #expect(throws: WidgetSnapshotValidationError.invalidAcquisition) {
        try WidgetSnapshot(publishedAt: widgetNow, acquisition: .noSources, maximumAge: 10, snapshot: monitorSample()).validate()
    }
    #expect(throws: WidgetSnapshotValidationError.invalidDate) {
        try WidgetSnapshot(publishedAt: Date(timeIntervalSince1970: .infinity), acquisition: .active, maximumAge: 10, snapshot: monitorSample()).validate()
    }
    #expect(throws: WidgetSnapshotValidationError.invalidAge) {
        try WidgetSnapshot(publishedAt: widgetNow, acquisition: .active, maximumAge: .infinity, snapshot: monitorSample()).validate()
    }
    #expect(throws: WidgetSnapshotValidationError.invalidDate) {
        try WidgetSnapshot(publishedAt: widgetNow, acquisition: .active, maximumAge: 10, snapshot: monitorSample(at: widgetNow.addingTimeInterval(1))).validate()
    }
}

@Test func decodingValidatesAndRoundTrips() throws {
    let encoder = JSONEncoder()
    let decoder = JSONDecoder()
    let payload = widgetPayload()
    let encoded = try encoder.encode(payload)
    #expect(try decoder.decode(WidgetSnapshot.self, from: encoded) == payload)

    var object = try #require(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
    object["schemaVersion"] = 3
    let invalid = try JSONSerialization.data(withJSONObject: object)
    #expect(throws: (any Error).self) { try decoder.decode(WidgetSnapshot.self, from: invalid) }
}

@Test func storePreservesSubsecondDates() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let capturedAt = Date(timeIntervalSince1970: 50_000.1234567)
    let publishedAt = capturedAt.addingTimeInterval(0.2345678)
    let payload = widgetPayload(publishedAt: publishedAt, snapshot: monitorSample(at: capturedAt))
    try await store.write(payload, now: publishedAt.addingTimeInterval(1))
    #expect(try await store.read(now: publishedAt.addingTimeInterval(1)) == payload)
}

@Test func writerCreatesPrivateDirectoryAndReadOnlyStoreDoesNotRepair() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }

    let writer = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    var directoryInfo = stat()
    #expect(lstat(directory.path, &directoryInfo) == 0)
    #expect((directoryInfo.st_mode & 0o777) == 0o700)

    let readOnly = try WidgetSnapshotStore(directoryURL: directory, mode: .readOnly)
    #expect(try await readOnly.read(now: widgetNow) == nil)
    try await writer.write(widgetPayload(), now: widgetNow)
    #expect(try await readOnly.read(now: widgetNow) == widgetPayload())
}

@Test func atomicWriteAndReadRoundTripAndRejectFuturePublication() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let original = widgetPayload()
    try await store.write(original, now: widgetNow)
    #expect(try await store.read(now: widgetNow) == original)

    let replacement = widgetPayload(acquisition: .stopped, publishedAt: widgetNow.addingTimeInterval(1))
    await #expect(throws: WidgetStoreError.invalidSnapshot) {
        try await store.write(replacement, now: widgetNow)
    }
    #expect(try await store.read(now: widgetNow) == original)
}

@Test func noSourcesClearsSnapshotAndReadRejectsFuturePayload() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    try await store.write(widgetPayload(), now: widgetNow)
    let empty = widgetPayload(acquisition: .noSources, snapshot: nil)
    try await store.write(empty, now: widgetNow)
    #expect(try await store.read(now: widgetNow) == empty)

    let future = widgetPayload(acquisition: .stopped, publishedAt: widgetNow.addingTimeInterval(1), snapshot: nil)
    await #expect(throws: WidgetStoreError.invalidSnapshot) {
        try await store.write(future, now: widgetNow)
    }
    #expect(try await store.read(now: widgetNow) == empty)
}

@Test func refusesReadOnlyMissingDirectoryAndReadOnlyWrites() async throws {
    let missing = fixtureDirectory()
    #expect(throws: WidgetStoreError.unsafeLocation) {
        try WidgetSnapshotStore(directoryURL: missing, mode: .readOnly)
    }

    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let writer = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let reader = try WidgetSnapshotStore(directoryURL: directory, mode: .readOnly)
    await #expect(throws: WidgetStoreError.readOnly) {
        try await reader.write(widgetPayload(), now: widgetNow)
    }
    #expect(try await writer.read(now: widgetNow) == nil)
}

@Test func directoryPrivacyIsRecheckedWithoutRepairingPermissions() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    #expect(chmod(directory.path, mode_t(0o755)) == 0)

    await #expect(throws: WidgetStoreError.unsafeLocation) {
        try await store.read(now: widgetNow)
    }
    await #expect(throws: WidgetStoreError.unsafeLocation) {
        try await store.write(widgetPayload(), now: widgetNow)
    }
    var info = stat()
    #expect(lstat(directory.path, &info) == 0)
    #expect((info.st_mode & 0o777) == 0o755)
}

@Test func refusesSymlinkOrWritableParentDirectory() throws {
    let base = fixtureDirectory()
    let realParent = base.appendingPathComponent("parent", isDirectory: true)
    let linkedParent = base.appendingPathComponent("linked-parent", isDirectory: true)
    try FileManager.default.createDirectory(at: realParent, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    defer { try? FileManager.default.removeItem(at: base) }
    #expect(symlink(realParent.path, linkedParent.path) == 0)
    #expect(throws: WidgetStoreError.unsafeLocation) {
        try WidgetSnapshotStore(directoryURL: linkedParent.appendingPathComponent("child", isDirectory: true), mode: .readWrite)
    }

    let writableParent = base.appendingPathComponent("writable-parent", isDirectory: true)
    try FileManager.default.createDirectory(at: writableParent, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    #expect(chmod(writableParent.path, mode_t(0o720)) == 0)
    #expect(throws: WidgetStoreError.unsafeLocation) {
        try WidgetSnapshotStore(directoryURL: writableParent.appendingPathComponent("child", isDirectory: true), mode: .readWrite)
    }
}

@Test func refusesSymlinkDirectoryAndSymlinkFile() async throws {
    let parent = fixtureDirectory()
    let realDirectory = parent.appendingPathComponent("real", isDirectory: true)
    let directoryLink = parent.appendingPathComponent("linked", isDirectory: true)
    try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    try FileManager.default.createDirectory(at: realDirectory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    defer { try? FileManager.default.removeItem(at: parent) }
    #expect(symlink(realDirectory.path, directoryLink.path) == 0)
    #expect(throws: WidgetStoreError.unsafeLocation) {
        try WidgetSnapshotStore(directoryURL: directoryLink, mode: .readOnly)
    }

    let store = try WidgetSnapshotStore(directoryURL: realDirectory, mode: .readWrite)
    let target = parent.appendingPathComponent("target.json")
    try Data("{}".utf8).write(to: target)
    #expect(chmod(target.path, mode_t(0o600)) == 0)
    #expect(symlink(target.path, realDirectory.appendingPathComponent("snapshot.json").path) == 0)
    await #expect(throws: WidgetStoreError.unsafeLocation) {
        try await store.write(widgetPayload(), now: widgetNow)
    }
}

@Test func refusesHardLinkedAndNonprivateTargets() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let target = directory.appendingPathComponent("snapshot.json")
    try Data("{}".utf8).write(to: target)
    #expect(chmod(target.path, mode_t(0o600)) == 0)

    let hardLink = directory.appendingPathComponent("extra-link")
    #expect(link(target.path, hardLink.path) == 0)
    await #expect(throws: WidgetStoreError.unsafeLocation) {
        try await store.write(widgetPayload(), now: widgetNow)
    }
    #expect(unlink(hardLink.path) == 0)

    #expect(chmod(target.path, mode_t(0o644)) == 0)
    await #expect(throws: WidgetStoreError.unsafeLocation) {
        try await store.write(widgetPayload(), now: widgetNow)
    }
}

@Test func boundedReadRejectsOversizedPayload() async throws {
    let directory = fixtureDirectory()
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let target = directory.appendingPathComponent("snapshot.json")
    try Data(repeating: 0x20, count: 65_537).write(to: target)
    #expect(chmod(target.path, mode_t(0o600)) == 0)
    await #expect(throws: WidgetStoreError.payloadTooLarge) {
        try await store.read(now: widgetNow)
    }
}
