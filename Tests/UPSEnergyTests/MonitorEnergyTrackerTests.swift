import Foundation
import XCTest
import UPSModel
import UPSEnergy

final class MonitorEnergyTrackerTests: XCTestCase {
    func testSeparateChannelsZeroAndMissingPower() {
        var tracker = MonitorEnergyTracker()
        let source = source(id: "ups-a", session: "session-a")
        let t0 = date(0)
        tracker.observe(snapshot: snapshot(source: source, at: t0, input: 100, ups: 0),
                        acquisitionSucceeded: true, now: t0, monotonicSeconds: 0)
        XCTAssertEqual(tracker.summaries.map(\.channel), [.input, .ups])
        XCTAssertEqual(tracker.summaries.map(\.state), [.collecting, .collecting])
        XCTAssertNil(tracker.summaries[0].energyWh)
        XCTAssertNil(tracker.summaries[1].energyWh)

        let t10 = date(10)
        tracker.observe(snapshot: snapshot(source: source, at: t10, input: 100, ups: 0),
                        acquisitionSucceeded: true, now: t10, monotonicSeconds: 10)
        XCTAssertEqual(tracker.summaries[0].state, .estimated)
        XCTAssertEqual(tracker.summaries[0].energyWh ?? -1, 100 * 10 / 3_600, accuracy: 1e-12)
        XCTAssertEqual(tracker.summaries[1].energyWh, 0)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 10)

        let t11 = date(11)
        tracker.observe(snapshot: snapshot(source: source, at: t11, input: nil, ups: 0),
                        acquisitionSucceeded: true, now: t11, monotonicSeconds: 11)
        XCTAssertEqual(tracker.summaries[0].state, .paused)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 1)
        XCTAssertEqual(tracker.summaries[0].energyWh ?? -1, 100 * 10 / 3_600, accuracy: 1e-12)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 11)
    }

    func testCachedSnapshotIsHarmlessButCannotResumePause() {
        var tracker = MonitorEnergyTracker()
        let source = source(id: "ups-a", session: "session-a")
        let first = snapshot(source: source, at: date(0), input: 80, ups: nil)
        tracker.observe(snapshot: first, acquisitionSucceeded: true, now: date(0), monotonicSeconds: 0)
        tracker.observe(snapshot: first, acquisitionSucceeded: true, now: date(5), monotonicSeconds: 0)
        XCTAssertEqual(tracker.summaries[0].state, .collecting)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 0)

        tracker.observe(snapshot: nil, acquisitionSucceeded: false, now: date(6), monotonicSeconds: 6)
        XCTAssertEqual(tracker.summaries[0].state, .paused)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 1)
        tracker.observe(snapshot: first, acquisitionSucceeded: true, now: date(7), monotonicSeconds: 7)
        XCTAssertEqual(tracker.summaries[0].state, .paused, "Cached capture cannot re-prime an interrupted segment")

        let resumed = snapshot(source: source, at: date(8), input: 80, ups: nil)
        tracker.observe(snapshot: resumed, acquisitionSucceeded: true, now: date(8), monotonicSeconds: 8)
        XCTAssertEqual(tracker.summaries[0].state, .collecting)
        XCTAssertNil(tracker.summaries[0].energyWh)
        let next = snapshot(source: source, at: date(10), input: 80, ups: nil)
        tracker.observe(snapshot: next, acquisitionSucceeded: true, now: date(10), monotonicSeconds: 10)
        XCTAssertEqual(tracker.summaries[0].energyWh ?? -1, 80 * 2 / 3_600, accuracy: 1e-12)
    }

    func testProvenanceChangeBreaksBeforeRepriming() {
        var tracker = MonitorEnergyTracker()
        let source = source(id: "ups-a", session: "session-a")
        tracker.observe(snapshot: snapshot(source: source, at: date(0), input: 40, ups: nil),
                        acquisitionSucceeded: true, now: date(0), monotonicSeconds: 0)
        tracker.observe(snapshot: snapshot(source: source, at: date(5), input: 60, ups: nil,
                                          inputProvenance: .estimated),
                        acquisitionSucceeded: true, now: date(5), monotonicSeconds: 5)
        XCTAssertEqual(tracker.summaries[0].state, .collecting)
        XCTAssertNil(tracker.summaries[0].energyWh)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 1)
        XCTAssertEqual(tracker.summaries[0].powerProvenances, [.estimated, .reported])

        tracker.observe(snapshot: snapshot(source: source, at: date(10), input: 60, ups: nil,
                                          inputProvenance: .estimated),
                        acquisitionSucceeded: true, now: date(10), monotonicSeconds: 10)
        XCTAssertEqual(tracker.summaries[0].state, .estimated)
        XCTAssertEqual(tracker.summaries[0].energyWh ?? -1, 60 * 5 / 3_600, accuracy: 1e-12)
    }

    func testSourceSessionSwitchResetsTotalsAndOlderCaptureBreaksWithoutLoweringWatermark() {
        var tracker = MonitorEnergyTracker()
        let first = source(id: "ups-a", session: "session-a")
        tracker.observe(snapshot: snapshot(source: first, at: date(0), input: 100, ups: nil),
                        acquisitionSucceeded: true, now: date(0), monotonicSeconds: 0)
        tracker.observe(snapshot: snapshot(source: first, at: date(5), input: 100, ups: nil),
                        acquisitionSucceeded: true, now: date(5), monotonicSeconds: 5)
        XCTAssertEqual(tracker.summaries[0].energyWh ?? -1, 100 * 5 / 3_600, accuracy: 1e-12)

        let second = source(id: "ups-a", session: "session-b")
        tracker.observe(snapshot: snapshot(source: second, at: date(6), input: 50, ups: nil),
                        acquisitionSucceeded: true, now: date(6), monotonicSeconds: 6)
        XCTAssertEqual(tracker.summaries[0].source, second)
        XCTAssertNil(tracker.summaries[0].energyWh)
        XCTAssertEqual(tracker.summaries[0].state, .collecting)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 0)

        tracker.observe(snapshot: snapshot(source: second, at: date(5), input: 900, ups: nil),
                        acquisitionSucceeded: true, now: date(7), monotonicSeconds: 7)
        XCTAssertEqual(tracker.summaries[0].state, .paused)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 1)
        tracker.observe(snapshot: snapshot(source: second, at: date(8), input: 50, ups: nil),
                        acquisitionSucceeded: true, now: date(8), monotonicSeconds: 8)
        XCTAssertEqual(tracker.summaries[0].state, .collecting)
        XCTAssertNil(tracker.summaries[0].energyWh)
    }

    func testUnvalidatedForeignSnapshotCannotResetOrAdvanceCurrentSource() {
        var tracker = MonitorEnergyTracker()
        let current = source(id: "ups-a", session: "session-a")
        tracker.observe(snapshot: snapshot(source: current, at: date(100), input: nil, ups: 3_600),
                        acquisitionSucceeded: true, now: date(100), monotonicSeconds: 100)
        tracker.observe(snapshot: snapshot(source: current, at: date(105), input: nil, ups: 3_600),
                        acquisitionSucceeded: true, now: date(105), monotonicSeconds: 105)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 5)

        let foreign = source(id: "ups-b", session: "session-b")
        let invalidForeign = MonitorSnapshot(
            source: foreign,
            capturedAt: date(10_000),
            status: MonitorStatus(lineState: .unknown, quality: .available),
            metrics: [MonitorMetric(id: .upsRealPower, value: -1, unit: .watts,
                                    quality: .available, provenance: .reported)]
        )
        tracker.observe(snapshot: invalidForeign, acquisitionSucceeded: true,
                        now: date(10_000), monotonicSeconds: 106)
        XCTAssertEqual(tracker.summaries[1].source, current)
        XCTAssertEqual(tracker.summaries[1].state, .paused)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 5)

        tracker.observe(snapshot: snapshot(source: current, at: date(107), input: nil, ups: 3_600),
                        acquisitionSucceeded: true, now: date(107), monotonicSeconds: 107)
        XCTAssertEqual(tracker.summaries[1].coveredDurationSeconds, 5)
    }

    func testClockMismatchAndStaleOrInvalidReadBreakContinuity() {
        var tracker = MonitorEnergyTracker()
        let source = source(id: "ups-a", session: "session-a")
        tracker.observe(snapshot: snapshot(source: source, at: date(0), input: 100, ups: 100),
                        acquisitionSucceeded: true, now: date(0), monotonicSeconds: 0)
        tracker.observe(snapshot: snapshot(source: source, at: date(5), input: 100, ups: 100),
                        acquisitionSucceeded: true, now: date(5), monotonicSeconds: 2)
        XCTAssertEqual(tracker.summaries.map(\.state), [.collecting, .collecting])
        XCTAssertEqual(tracker.summaries.map(\.gapOrBreakCount), [1, 1])

        let stale = snapshot(source: source, at: date(5), input: 100, ups: 100)
        tracker.observe(snapshot: stale, acquisitionSucceeded: true, now: date(20), monotonicSeconds: 3)
        XCTAssertEqual(tracker.summaries.map(\.state), [.paused, .paused])
        XCTAssertEqual(tracker.summaries.map(\.gapOrBreakCount), [2, 2])

        let invalid = snapshot(source: source, at: date(21), input: -1, ups: 100)
        tracker.observe(snapshot: invalid, acquisitionSucceeded: true, now: date(21), monotonicSeconds: 4)
        XCTAssertEqual(tracker.summaries.map(\.state), [.paused, .paused])
        XCTAssertEqual(tracker.summaries.map(\.gapOrBreakCount), [2, 2], "Repeated interruption is coalesced")
    }

    func testResetPauseAndFiniteOverflowBehavior() {
        var tracker = MonitorEnergyTracker()
        let source = source(id: "ups-a", session: "session-a")
        tracker.observe(snapshot: snapshot(source: source, at: date(0), input: 10, ups: nil),
                        acquisitionSucceeded: true, now: date(0), monotonicSeconds: 0)
        tracker.pause()
        tracker.pause()
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 1)
        XCTAssertEqual(tracker.summaries[0].state, .paused)
        tracker.reset()
        XCTAssertEqual(tracker.summaries.map(\.state), [.unavailable, .unavailable])
        XCTAssertNil(tracker.summaries[0].source)
        XCTAssertEqual(tracker.summaries[0].gapOrBreakCount, 0)

        var overflowTracker = MonitorEnergyTracker()
        for index in 0...800 {
            let time = Double(index * 10)
            let sample = snapshot(source: source, at: date(time), input: Double.greatestFiniteMagnitude, ups: nil)
            overflowTracker.observe(snapshot: sample, acquisitionSucceeded: true,
                                    now: sample.capturedAt, monotonicSeconds: time)
        }
        let overflowSummary = overflowTracker.summaries[0]
        XCTAssertEqual(overflowSummary.state, .estimated)
        XCTAssertTrue(overflowSummary.energyWh?.isFinite == true)
        XCTAssertTrue(overflowSummary.coveredDurationSeconds.isFinite)
    }

    private func snapshot(source: MonitorSource, at date: Date, input: Double?, ups: Double?,
                          inputProvenance: MonitorMetricProvenance = .reported,
                          upsProvenance: MonitorMetricProvenance = .reported,
                          statusQuality: MonitorStatusQuality = .available,
                          flags: Set<MonitorStatusFlag> = []) -> MonitorSnapshot {
        var metrics: [MonitorMetric] = []
        if let input {
            metrics.append(MonitorMetric(id: .inputRealPower, value: input, unit: .watts,
                                         quality: .available, provenance: inputProvenance))
        }
        if let ups {
            metrics.append(MonitorMetric(id: .upsRealPower, value: ups, unit: .watts,
                                         quality: .available, provenance: upsProvenance))
        }
        return MonitorSnapshot(source: source, capturedAt: date,
                               status: MonitorStatus(lineState: .unknown, flags: flags,
                                                     quality: statusQuality), metrics: metrics)
    }

    private func source(id: String, session: String) -> MonitorSource {
        MonitorSource(provider: .nut, id: id, sessionID: session, identityStability: .configured)
    }

    private func date(_ seconds: TimeInterval) -> Date {
        Date(timeIntervalSince1970: 1_800_000_000 + seconds)
    }
}
