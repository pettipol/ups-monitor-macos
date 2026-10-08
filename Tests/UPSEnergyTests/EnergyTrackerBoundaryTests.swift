import Foundation
import XCTest
import UPSModel
import UPSEnergy

final class EnergyTrackerBoundaryTests: XCTestCase {
    func testCachedSampleDoesNotHideBackwardsReceiptClock() {
        var tracker = MonitorEnergyTracker()
        observe(&tracker, at: 100)
        observe(&tracker, at: 105)
        tracker.observe(snapshot: sample(at: 105), acquisitionSucceeded: true,
                        now: Date(timeIntervalSince1970: 105), monotonicSeconds: 104)
        XCTAssertEqual(tracker.summaries[1].state, .paused)
        observe(&tracker, at: 106)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 5,
                       "The backwards-clock boundary cannot be bridged")
        observe(&tracker, at: 107)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 6)
    }

    func testFutureTimestampCannotPoisonRecoveryWatermark() {
        var tracker = MonitorEnergyTracker()
        observe(&tracker, at: 100)
        observe(&tracker, at: 105)
        tracker.observe(snapshot: sample(at: 100_000), acquisitionSucceeded: true,
                        now: Date(timeIntervalSince1970: 106), monotonicSeconds: 106)
        observe(&tracker, at: 107)
        observe(&tracker, at: 108)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 6)
        XCTAssertEqual(tracker.summaries[1].lastCapturedAt, Date(timeIntervalSince1970: 108))
    }

    func testChangedValuesAtSameTimestampBreakRatherThanBridge() {
        var tracker = MonitorEnergyTracker()
        observe(&tracker, at: 100)
        observe(&tracker, at: 105)
        tracker.observe(snapshot: sample(at: 105, watts: 7_200), acquisitionSucceeded: true,
                        now: Date(timeIntervalSince1970: 106), monotonicSeconds: 106)
        observe(&tracker, at: 107)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 5)
    }

    func testUnadmittedForeignSnapshotCannotEraseSessionTotals() {
        let cases: [(watts: Double, captured: Double, now: Double, uptime: Double,
                     success: Bool, status: MonitorStatus)] = [
            (.nan, 106, 106, 106, true, MonitorStatus(lineState: .onLine, quality: .available)),
            (3_600, 106, 106, 106, false, MonitorStatus(lineState: .onLine, quality: .available)),
            (3_600, 100_000, 106, 106, true, MonitorStatus(lineState: .onLine, quality: .available)),
            (3_600, 50, 106, 106, true, MonitorStatus(lineState: .onLine, quality: .available)),
            (3_600, 106, .nan, 106, true, MonitorStatus(lineState: .onLine, quality: .available)),
            (3_600, 106, 106, .nan, true, MonitorStatus(lineState: .onLine, quality: .available)),
            (3_600, 106, 106, 106, true, MonitorStatus(lineState: .unknown, quality: .unavailable))
        ]
        for rejected in cases {
            var tracker = MonitorEnergyTracker()
            observe(&tracker, at: 100)
            observe(&tracker, at: 105)
            let foreign = MonitorSnapshot(
                source: MonitorSource(provider: .nut, id: "foreign", sessionID: "other",
                                      identityStability: .configured),
                capturedAt: Date(timeIntervalSince1970: rejected.captured),
                status: rejected.status,
                metrics: [MonitorMetric(id: .upsRealPower, value: rejected.watts, unit: .watts,
                                        quality: .available, provenance: .reported)])
            tracker.observe(snapshot: foreign, acquisitionSucceeded: rejected.success,
                            now: Date(timeIntervalSince1970: rejected.now), monotonicSeconds: rejected.uptime)
            XCTAssertEqual(tracker.summaries[1].source, sample(at: 100).source)
            XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 5)
            observe(&tracker, at: 107)
            observe(&tracker, at: 108)
            XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 6)
        }
    }

    private func observe(_ tracker: inout MonitorEnergyTracker, at time: TimeInterval) {
        let snapshot = sample(at: time)
        tracker.observe(snapshot: snapshot, acquisitionSucceeded: true, now: snapshot.capturedAt,
                        monotonicSeconds: time)
    }

    private func sample(at time: TimeInterval, watts: Double = 3_600) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: .nut, id: "synthetic", sessionID: "session",
                                               identityStability: .configured), capturedAt: Date(timeIntervalSince1970: time),
                        status: MonitorStatus(lineState: .onLine, quality: .available),
                        metrics: [MonitorMetric(id: .upsRealPower, value: watts, unit: .watts,
                                                quality: .available, provenance: .reported)])
    }
}
