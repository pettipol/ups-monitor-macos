import Foundation
import Testing
import ApplePowerSource
import UPSCore
import UPSModel
@testable import UPSRuntime

private let presentationNameDate = Date(timeIntervalSince1970: 10_000)
private let presentationNameSource = MonitorSource(provider: .apple, id: "opaque-source", sessionID: "session-a",
                                                   identityStability: .sessionLocal)

private func presentationNameSnapshot(at date: Date = presentationNameDate,
                                      source: MonitorSource = presentationNameSource) -> MonitorSnapshot {
    MonitorSnapshot(source: source, capturedAt: date,
                    status: MonitorStatus(quality: .unavailable), metrics: [])
}

@Test func PresentationNameAppleAdapterReadingsPairNamesWithoutChangingSnapshots() throws {
    let powerSource = PowerSource(id: "opaque-source", kind: .ups, isPresent: true, state: .unknown,
                                 isCharging: nil,
                                 charge: Metric(value: nil, unit: .ratio, quality: .unavailable, provenance: .derived),
                                 timeToEmpty: Metric(value: nil, unit: .seconds, quality: .unavailable, provenance: .estimated),
                                 timeToFullCharge: Metric(value: nil, unit: .seconds, quality: .unavailable, provenance: .estimated),
                                 batteryVoltage: Metric(value: nil, unit: .volts, quality: .unavailable, provenance: .reported),
                                 sourceCurrent: Metric(value: nil, unit: .amps, quality: .unavailable, provenance: .reported),
                                 sourceTemperature: Metric(value: nil, unit: .celsius, quality: .unavailable, provenance: .reported),
                                 internalFailure: nil, batteryHealth: nil)
    let observation = AppleSessionSnapshot(
        sessionID: "session-a",
        snapshot: PowerSourceSnapshot(capturedAt: presentationNameDate, availability: .available,
                                      discovery: DiscoveryCounts(ups: 1, internalBattery: 0, unknownType: 0),
                                      sources: [powerSource]),
        unidentifiedPresentSourceCount: 0,
        presentationNamesByOpaqueSourceID: ["opaque-source": "APC SMC1500I"]
    )

    let readings = try AppleSnapshotRuntimeAdapter.readings(from: observation)
    #expect(readings.count == 1)
    #expect(readings[0].presentationName == "APC SMC1500I")
    #expect(readings[0].snapshot.source.id == "opaque-source")
    #expect(try AppleSnapshotRuntimeAdapter.snapshots(from: observation) == [readings[0].snapshot])
}

@Test func PresentationNameLegacyReadRemainsNameFree() async throws {
    let coordinator = try MonitorCoordinator(read: { [presentationNameSnapshot()] }, clock: { presentationNameDate })
    let state = await coordinator.refresh()
    #expect(state.sources.first?.presentationName == nil)
}

@Test func PresentationNameInvalidFutureReadingPreservesSnapshotAndNameTogether() async throws {
    actor ReadSequence {
        var index = 0
        func read() -> [MonitorReading] {
            index += 1
            if index == 1 {
                return [MonitorReading(snapshot: presentationNameSnapshot(), presentationName: "APC SMC1500I")]
            }
            return [MonitorReading(snapshot: presentationNameSnapshot(at: presentationNameDate.addingTimeInterval(1)),
                                   presentationName: "Wrong UPS")]
        }
    }
    let reads = ReadSequence()
    let coordinator = try MonitorCoordinator(readWithPresentation: { await reads.read() },
                                             clock: { presentationNameDate })
    let fresh = await coordinator.refresh()
    let rejected = await coordinator.refresh()

    #expect(fresh.sources.first?.presentationName == "APC SMC1500I")
    #expect(rejected.acquisition == .failed(.invalidCollection))
    #expect(rejected.sources.first?.snapshot.capturedAt == presentationNameDate)
    #expect(rejected.sources.first?.presentationName == "APC SMC1500I")
    #expect(rejected.sources.first?.freshness == .stale)
}

@Test func PresentationNameSinkReceivesSnapshotWithoutName() async throws {
    actor SnapshotSink {
        var snapshots: [MonitorSnapshot] = []
        func append(_ snapshot: MonitorSnapshot) { snapshots.append(snapshot) }
        func values() -> [MonitorSnapshot] { snapshots }
    }
    let sink = SnapshotSink()
    let coordinator = try MonitorCoordinator(
        readWithPresentation: {
            [MonitorReading(snapshot: presentationNameSnapshot(), presentationName: "APC SMC1500I")]
        },
        clock: { presentationNameDate },
        sink: { snapshot, _ in await sink.append(snapshot) }
    )
    let state = await coordinator.refresh()
    #expect(state.sources.first?.presentationName == "APC SMC1500I")
    let stored = await sink.values()
    #expect(stored == [presentationNameSnapshot()])
    let encoded = String(decoding: try JSONEncoder().encode(stored), as: UTF8.self)
    #expect(encoded.contains("APC SMC1500I") == false)
}

@Test func PresentationNameStaysPairedWhenCoordinatorSortsSources() async throws {
    let secondSource = MonitorSource(provider: .apple, id: "opaque-z", sessionID: "session-a",
                                     identityStability: .sessionLocal)
    let coordinator = try MonitorCoordinator(
        readWithPresentation: {
            [MonitorReading(snapshot: presentationNameSnapshot(source: secondSource), presentationName: "Second"),
             MonitorReading(snapshot: presentationNameSnapshot(), presentationName: "First")]
        },
        clock: { presentationNameDate }
    )
    let state = await coordinator.refresh()
    #expect(state.sources.map(\.source.id) == ["opaque-source", "opaque-z"])
    #expect(state.sources.map(\.presentationName) == ["First", "Second"])
}

@Test func PresentationNameFailedAndCancelledReadsKeepPreviousPair() async throws {
    actor ReadSwitch {
        var mode = 0
        var continuation: CheckedContinuation<[MonitorReading], Error>?
        var continuationInstalled = false
        var releaseRequested = false
        func read() async throws -> [MonitorReading] {
            mode += 1
            if mode == 1 { return [MonitorReading(snapshot: presentationNameSnapshot(), presentationName: "Original UPS")] }
            if mode == 2 { throw CancellationError() }
            if mode == 3 {
                return try await withCheckedThrowingContinuation { continuation in
                    self.continuation = continuation
                    continuationInstalled = true
                    if releaseRequested { resumeLateRead() }
                }
            }
            return [MonitorReading(snapshot: presentationNameSnapshot(at: presentationNameDate.addingTimeInterval(1)),
                                   presentationName: "Future UPS")]
        }
        func waitForContinuationInstalled() async -> Bool {
            for _ in 0..<200 {
                if continuationInstalled { return true }
                try? await Task.sleep(for: .milliseconds(5))
            }
            return continuationInstalled
        }
        func release() {
            releaseRequested = true
            resumeLateRead()
        }
        private func resumeLateRead() {
            guard let continuation else { return }
            continuation.resume(returning: [MonitorReading(snapshot: presentationNameSnapshot(),
                                                            presentationName: "Late UPS")])
            self.continuation = nil
        }
    }
    let reads = ReadSwitch()
    let coordinator = try MonitorCoordinator(readWithPresentation: { try await reads.read() },
                                             clock: { presentationNameDate })
    _ = await coordinator.refresh()
    let failed = await coordinator.refresh()
    #expect(failed.sources.first?.presentationName == "Original UPS")

    let attempt = Task { await coordinator.refresh() }
    let continuationInstalled = await reads.waitForContinuationInstalled()
    #expect(continuationInstalled)
    await coordinator.stop()
    await reads.release()
    _ = await attempt.value
    let stopped = await coordinator.currentState()
    #expect(stopped.acquisition == .stopped)
    #expect(stopped.sources.first?.snapshot.capturedAt == presentationNameDate)
    #expect(stopped.sources.first?.presentationName == "Original UPS")
}
