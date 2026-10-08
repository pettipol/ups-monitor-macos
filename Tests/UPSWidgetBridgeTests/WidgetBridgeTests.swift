import Foundation
import Testing
import UPSModel
import UPSWidgetData
@testable import UPSWidgetBridge

@Test func groupConfigurationRequiresExactEntitlementAndSafeIdentifier() throws {
    let identifier = "group.org.example.ups"
    #expect(try WidgetGroupConfiguration.validate(identifier: identifier, entitlements: [identifier]) == identifier)
    #expect(throws: WidgetGroupError.notConfigured) { try WidgetGroupConfiguration.validate(identifier: nil, entitlements: []) }
    #expect(throws: WidgetGroupError.entitlementMismatch) { try WidgetGroupConfiguration.validate(identifier: identifier, entitlements: []) }
    for invalid in ["../../elsewhere", "group..ups", "$(TEAM).ups", " group.org.ups", "group.org/ups"] {
        #expect(throws: WidgetGroupError.invalidIdentifier) { try WidgetGroupConfiguration.validate(identifier: invalid, entitlements: [invalid]) }
    }
}

@Test func publisherKeepsLatestSequenceAndLimitsReloadRequests() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-publisher-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let calls = ReloadCount()
    let publisher = WidgetSnapshotPublisher(store: store, reload: { await calls.increment() })
    let date = Date(timeIntervalSince1970: 5_000)
    let source = MonitorSource(provider: .apple, id: "synthetic", sessionID: "session", identityStability: .sessionLocal)
    func payload(_ interval: TimeInterval, state: WidgetAcquisition = .active) -> WidgetSnapshot {
        let time = date.addingTimeInterval(interval)
        let snapshot = MonitorSnapshot(source: source, capturedAt: time, status: MonitorStatus(quality: .unavailable), metrics: [])
        return WidgetSnapshot(publishedAt: time, acquisition: state, maximumAge: 10, snapshot: snapshot)
    }
    #expect(await publisher.publish(payload(0), now: date, uptime: 100, sequence: 1) == .shared)
    #expect(await publisher.publish(payload(5), now: date.addingTimeInterval(5), uptime: 105, sequence: 2) == .shared)
    #expect(await calls.value == 1)
    #expect(await publisher.publish(payload(30, state: .stopped), now: date.addingTimeInterval(30), uptime: 130, sequence: 3) == .shared)
    #expect(await calls.value == 2)
    #expect(await publisher.publish(payload(0), now: date, uptime: 100, sequence: 1) == .rejected)
    #expect(try await store.read(now: date.addingTimeInterval(31))?.acquisition == .stopped)
}

private actor ReloadCount {
    var value = 0
    func increment() { value += 1 }
}

@Test func publisherCoalescesConcurrentWritesWithoutReplayingEarlierSequences() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-order-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let publisher = WidgetSnapshotPublisher(store: store, reload: {})
    let base = Date(timeIntervalSince1970: 5_000)
    let now = base.addingTimeInterval(50)
    await withTaskGroup(of: Void.self) { group in
        for number in 1...40 {
            group.addTask {
                let capture = base.addingTimeInterval(Double(number))
                let sample = MonitorSnapshot(source: MonitorSource(provider: .apple, id: "synthetic", sessionID: "session", identityStability: .sessionLocal),
                                             capturedAt: capture, status: MonitorStatus(quality: .unavailable), metrics: [])
                let value = WidgetSnapshot(publishedAt: capture, acquisition: number == 40 ? .stopped : .active,
                                           maximumAge: 10, snapshot: sample)
                _ = await publisher.publish(value, now: now, uptime: Double(100 + number), sequence: UInt64(number))
            }
        }
    }
    let final = try await store.read(now: now)
    #expect(final?.acquisition == .stopped)
    #expect(final?.snapshot?.capturedAt == base.addingTimeInterval(40))
}
