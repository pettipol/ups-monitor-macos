import Darwin
import Foundation
import Testing
import UPSModel
@testable import UPSWidgetData

private func boundaryPayload(at date: Date) -> WidgetSnapshot {
    let source = MonitorSource(provider: .apple, id: "synthetic", sessionID: "session", identityStability: .sessionLocal)
    let sample = MonitorSnapshot(source: source, capturedAt: date,
                                 status: MonitorStatus(quality: .unavailable), metrics: [])
    return WidgetSnapshot(publishedAt: date.addingTimeInterval(0.125), acquisition: .active,
                          maximumAge: 10, snapshot: sample)
}

@Test func rejectedWidgetWriteCannotDestroyPreviousFractionalCapture() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-boundary-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let date = Date(timeIntervalSinceReferenceDate: 700_000_000.000123)
    let original = boundaryPayload(at: date)
    let now = date.addingTimeInterval(1)
    try await store.write(original, now: now)
    let file = directory.appendingPathComponent("snapshot.json")
    let bytes = try Data(contentsOf: file)
    let invalid = WidgetSnapshot(publishedAt: now, acquisition: .active, maximumAge: 10, snapshot: nil)
    await #expect(throws: WidgetStoreError.invalidSnapshot) { try await store.write(invalid, now: now) }
    #expect(try Data(contentsOf: file) == bytes)
    let reopened = try WidgetSnapshotStore(directoryURL: directory, mode: .readOnly)
    #expect(try await reopened.read(now: now) == original)
}

@Test func widgetStoreRefusesNonregularFilesWithoutBlocking() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-fifo-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let file = directory.appendingPathComponent("snapshot.json")
    #expect(mkfifo(file.path, mode_t(0o600)) == 0)
    let now = Date(timeIntervalSince1970: 100)
    await #expect(throws: WidgetStoreError.unsafeLocation) { try await store.read(now: now) }
    await #expect(throws: WidgetStoreError.unsafeLocation) { try await store.write(boundaryPayload(at: now), now: now.addingTimeInterval(1)) }
}

@Test func widgetFreshnessNeverTreatsPublicationAsANewMeasurement() {
    let date = Date(timeIntervalSince1970: 100)
    let payload = boundaryPayload(at: date)
    #expect(!payload.isStale(at: date.addingTimeInterval(10)))
    #expect(payload.isStale(at: date.addingTimeInterval(10.001)))
    #expect(payload.isStale(at: date))
    #expect(payload.isStale(at: Date(timeIntervalSince1970: .infinity)))
    let stopped = WidgetSnapshot(publishedAt: date.addingTimeInterval(1), acquisition: .stopped,
                                  maximumAge: 10, snapshot: payload.snapshot)
    #expect(stopped.isStale(at: date.addingTimeInterval(2)))
    #expect(stopped.snapshot?.capturedAt == date)
}
