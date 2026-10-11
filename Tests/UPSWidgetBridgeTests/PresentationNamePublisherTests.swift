import Foundation
import XCTest
import UPSModel
import UPSWidgetData
import UPSWidgetBridge

final class PresentationNamePublisherTests: XCTestCase {
    func testPresentationNameOnlyChangesAreStoredAndReloadIsRateLimited() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-name-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
        let counter = PresentationReloadCounter()
        let publisher = WidgetSnapshotPublisher(store: store, reload: { await counter.increment() })
        let date = Date(timeIntervalSince1970: 50_000)
        let sample = MonitorSnapshot(source: MonitorSource(provider: .apple, id: "synthetic", sessionID: "session", identityStability: .sessionLocal),
                                     capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
        for (index, name) in ["Synthetic First", "Synthetic Second", "Synthetic Third"].enumerated() {
            let payload = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 60,
                                         snapshot: sample, presentationName: name)
            let result = await publisher.publish(payload, now: date, uptime: Double(index * 15), sequence: UInt64(index + 1))
            XCTAssertEqual(result, .shared, "Name-only changes must not be discarded as duplicate telemetry")
            let persisted = try await store.read(now: date)
            XCTAssertEqual(persisted?.presentationName, name)
            XCTAssertEqual(persisted?.snapshot, sample)
            let calls = await counter.value
            XCTAssertEqual(calls, index == 2 ? 2 : 1, "A name change follows the existing 30-second state-change reload limit")
        }
    }
}

private actor PresentationReloadCounter {
    private(set) var value = 0
    func increment() { value += 1 }
}
