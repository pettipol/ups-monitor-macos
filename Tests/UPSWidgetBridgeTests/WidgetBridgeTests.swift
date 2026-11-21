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

@Test func lifecycleTransitionsReloadPerSessionButNotPerSampleOrDuplicate() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-session-refresh-v3-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let observations = ReloadAcquisitions()
    let date = Date(timeIntervalSince1970: 5_000)
    let source = MonitorSource(provider: .nut, id: "managed-synthetic", sessionID: "session",
                               identityStability: .configured)
    let status = MonitorStatus(quality: .unavailable)
    func sample(_ second: TimeInterval) -> MonitorSnapshot {
        MonitorSnapshot(source: source, capturedAt: date.addingTimeInterval(second), status: status, metrics: [])
    }
    func payload(_ second: TimeInterval, _ acquisition: WidgetAcquisition,
                 snapshot: MonitorSnapshot? = nil) -> WidgetSnapshot {
        WidgetSnapshot(publishedAt: date.addingTimeInterval(second), acquisition: acquisition,
                       maximumAge: 60, snapshot: snapshot)
    }
    let publisher = WidgetSnapshotPublisher(store: store, reload: {
        let saved = try? await store.read(now: date.addingTimeInterval(1_000))
        await observations.append(saved?.acquisition)
    })

    #expect(await publisher.publish(payload(0, .stopped), now: date, uptime: 100, sequence: 1) == .shared)
    #expect(await publisher.publish(payload(2, .active, snapshot: sample(2)),
                                    now: date.addingTimeInterval(2), uptime: 102, sequence: 2) == .shared)
    #expect(await publisher.publish(payload(5, .active, snapshot: sample(5)),
                                    now: date.addingTimeInterval(5), uptime: 105, sequence: 3) == .shared)
    #expect(await publisher.publish(payload(14, .stopped, snapshot: sample(5)),
                                    now: date.addingTimeInterval(14), uptime: 114, sequence: 4) == .shared)
    #expect(await observations.values == [.stopped, .active, .stopped])

    // A changed value while still stopped is written, but does not itself wake WidgetKit.
    #expect(await publisher.publish(payload(15, .stopped, snapshot: sample(15)),
                                    now: date.addingTimeInterval(15), uptime: 115, sequence: 5) == .shared)
    #expect(await observations.values == [.stopped, .active, .stopped])
    #expect(await publisher.publish(payload(15, .stopped, snapshot: sample(15)),
                                    now: date.addingTimeInterval(15), uptime: 116, sequence: 6) == .unchanged)

    // Distinct sessions at 16/18 and 20/22 each request one opening and one closing timeline.
    #expect(await publisher.publish(payload(16, .active, snapshot: sample(16)),
                                    now: date.addingTimeInterval(16), uptime: 117, sequence: 7) == .shared)
    #expect(await publisher.publish(payload(17, .active, snapshot: sample(17)),
                                    now: date.addingTimeInterval(17), uptime: 118, sequence: 8) == .shared)
    #expect(await publisher.publish(payload(18, .stopped, snapshot: sample(17)),
                                    now: date.addingTimeInterval(18), uptime: 119, sequence: 9) == .shared)
    #expect(await publisher.publish(payload(19, .stopped, snapshot: sample(17)),
                                    now: date.addingTimeInterval(19), uptime: 120, sequence: 10) == .unchanged)
    #expect(await publisher.publish(payload(20, .active, snapshot: sample(20)),
                                    now: date.addingTimeInterval(20), uptime: 121, sequence: 11) == .shared)
    #expect(await publisher.publish(payload(21, .active, snapshot: sample(21)),
                                    now: date.addingTimeInterval(21), uptime: 122, sequence: 12) == .shared)
    #expect(await publisher.publish(payload(22, .stopped, snapshot: sample(21)),
                                    now: date.addingTimeInterval(22), uptime: 123, sequence: 13) == .shared)
    #expect(await publisher.publish(payload(23, .stopped, snapshot: sample(21)),
                                    now: date.addingTimeInterval(23), uptime: 124, sequence: 14) == .unchanged)
    #expect(await observations.values == [.stopped, .active, .stopped, .active, .stopped, .active, .stopped],
            "Only the initial state and one request at each session boundary are sent")
    #expect(try await store.read(now: date.addingTimeInterval(23))?.acquisition == .stopped)
}

@Test func samePublisherRearmsLifecycleAfterOneDayIdle() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-session-idle-v3-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let observations = ReloadAcquisitions()
    let date = Date(timeIntervalSince1970: 6_000)
    let source = MonitorSource(provider: .nut, id: "managed-synthetic", sessionID: "session",
                               identityStability: .configured)
    let status = MonitorStatus(quality: .unavailable)
    func sample(_ second: TimeInterval) -> MonitorSnapshot {
        MonitorSnapshot(source: source, capturedAt: date.addingTimeInterval(second), status: status, metrics: [])
    }
    func payload(_ second: TimeInterval, _ acquisition: WidgetAcquisition,
                 snapshot: MonitorSnapshot? = nil) -> WidgetSnapshot {
        WidgetSnapshot(publishedAt: date.addingTimeInterval(second), acquisition: acquisition,
                       maximumAge: 60, snapshot: snapshot)
    }
    let publisher = WidgetSnapshotPublisher(store: store, reload: {
        let saved = try? await store.read(now: date.addingTimeInterval(100_000))
        await observations.append(saved?.acquisition)
    })

    #expect(await publisher.publish(payload(0, .stopped), now: date, uptime: 100, sequence: 1) == .shared)
    #expect(await publisher.publish(payload(2, .active, snapshot: sample(2)),
                                    now: date.addingTimeInterval(2), uptime: 102, sequence: 2) == .shared)
    #expect(await publisher.publish(payload(14, .stopped, snapshot: sample(2)),
                                    now: date.addingTimeInterval(14), uptime: 114, sequence: 3) == .shared)
    #expect(await publisher.publish(payload(86_400, .stopped), now: date.addingTimeInterval(86_400),
                                    uptime: 86_500, sequence: 4) == .shared)
    #expect(await publisher.publish(payload(86_402, .active, snapshot: sample(86_402)),
                                    now: date.addingTimeInterval(86_402), uptime: 86_502, sequence: 5) == .shared)
    #expect(await publisher.publish(payload(86_405, .active, snapshot: sample(86_405)),
                                    now: date.addingTimeInterval(86_405), uptime: 86_505, sequence: 6) == .shared)
    #expect(await publisher.publish(payload(86_414, .stopped, snapshot: sample(86_405)),
                                    now: date.addingTimeInterval(86_414), uptime: 86_514, sequence: 7) == .shared)
    #expect(await publisher.publish(payload(86_415, .stopped, snapshot: sample(86_405)),
                                    now: date.addingTimeInterval(86_415), uptime: 86_515, sequence: 8) == .unchanged)
    #expect(await observations.values == [.stopped, .active, .stopped, .stopped, .active, .stopped],
            "The later active/Stop pair must refresh even after the publisher has handled an earlier session")
}

@Test func duplicateRetriesOnlyAnUnannouncedStopAfterMonotonicTimeRecovers() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-stop-retry-v3-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let observations = ReloadAcquisitions()
    let date = Date(timeIntervalSince1970: 9_000)
    let source = MonitorSource(provider: .nut, id: "managed-synthetic", sessionID: "session",
                               identityStability: .configured)
    let status = MonitorStatus(quality: .unavailable)
    func sample(_ second: TimeInterval) -> MonitorSnapshot {
        MonitorSnapshot(source: source, capturedAt: date.addingTimeInterval(second), status: status, metrics: [])
    }
    let initial = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 60, snapshot: sample(0))
    let stop = WidgetSnapshot(publishedAt: date.addingTimeInterval(2), acquisition: .stopped,
                              maximumAge: 60, snapshot: sample(0))
    let publisher = WidgetSnapshotPublisher(store: store, reload: {
        let saved = try? await store.read(now: date.addingTimeInterval(1_000))
        await observations.append(saved?.acquisition)
    })

    #expect(await publisher.publish(initial, now: date, uptime: 100, sequence: 1) == .shared)
    #expect(await publisher.publish(stop, now: date.addingTimeInterval(2), uptime: 99, sequence: 2) == .shared)
    #expect(await observations.values == [.active], "The regressive uptime stores Stop but does not request")
    #expect(try await store.read(now: date.addingTimeInterval(3))?.acquisition == .stopped)
    // Same stopped payload/sample; only wall-clock now, monotonic uptime and sequence advance.
    #expect(await publisher.publish(stop, now: date.addingTimeInterval(3), uptime: 101, sequence: 3) == .shared)
    #expect(await observations.values == [.active, .stopped], "The still-pending Stop transition retries once after the write")
    #expect(await publisher.publish(stop, now: date.addingTimeInterval(4), uptime: 102, sequence: 4) == .unchanged)
    #expect(await observations.values == [.active, .stopped], "An already-announced duplicate does not wake again")
}

@Test func ordinaryReloadLimitsRemainForSecondaryStateChangesAndValues() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ups-widget-ordinary-refresh-v3-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
    let calls = ReloadCount()
    let publisher = WidgetSnapshotPublisher(store: store, reload: { await calls.increment() })
    let date = Date(timeIntervalSince1970: 8_000)
    let source = MonitorSource(provider: .nut, id: "synthetic", sessionID: "session",
                               identityStability: .configured)
    let status = MonitorStatus(quality: .unavailable)
    func sample(_ second: TimeInterval) -> MonitorSnapshot {
        MonitorSnapshot(source: source, capturedAt: date.addingTimeInterval(second), status: status, metrics: [])
    }
    func payload(_ second: TimeInterval, _ acquisition: WidgetAcquisition,
                 snapshot: MonitorSnapshot? = nil, maximumAge: TimeInterval = 60) -> WidgetSnapshot {
        WidgetSnapshot(publishedAt: date.addingTimeInterval(second), acquisition: acquisition,
                       maximumAge: maximumAge, snapshot: snapshot)
    }

    #expect(await publisher.publish(payload(0, .noSources), now: date, uptime: 100, sequence: 1) == .shared)
    #expect(await publisher.publish(payload(29, .readFailed, snapshot: sample(29)),
                                    now: date.addingTimeInterval(29), uptime: 129, sequence: 2) == .shared)
    #expect(await calls.value == 1, "Changed acquisition remains limited before 30 seconds")
    #expect(await publisher.publish(payload(30, .readFailed, snapshot: sample(30)),
                                    now: date.addingTimeInterval(30), uptime: 130, sequence: 3) == .shared)
    #expect(await calls.value == 2, "Changed acquisition may request at 30 seconds")
    #expect(await publisher.publish(payload(329, .readFailed, snapshot: sample(329), maximumAge: 61),
                                    now: date.addingTimeInterval(329), uptime: 429, sequence: 4) == .shared)
    #expect(await calls.value == 2, "Unchanged requested state remains limited before five minutes")
    #expect(await publisher.publish(payload(330, .readFailed, snapshot: sample(330), maximumAge: 62),
                                    now: date.addingTimeInterval(330), uptime: 430, sequence: 5) == .shared)
    #expect(await calls.value == 3, "Ordinary unchanged-state reload remains allowed at five minutes")
    #expect(await publisher.publish(payload(359, .active, snapshot: sample(359)),
                                    now: date.addingTimeInterval(359), uptime: 459, sequence: 6) == .shared)
    #expect(await calls.value == 3, "Recovery with an accumulated sample remains limited before 30 seconds")
    #expect(await publisher.publish(payload(360, .active, snapshot: sample(360)),
                                    now: date.addingTimeInterval(360), uptime: 460, sequence: 7) == .shared)
    #expect(await calls.value == 4, "Recovery with an accumulated sample may reload at 30 seconds")
}

private actor ReloadAcquisitions {
    private(set) var values: [WidgetAcquisition] = []
    func append(_ value: WidgetAcquisition?) { if let value { values.append(value) } }
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
