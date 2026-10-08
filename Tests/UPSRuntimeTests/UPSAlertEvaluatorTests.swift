import Foundation
import XCTest
import UPSModel
@testable import UPSRuntime

final class UPSAlertEvaluatorTests: XCTestCase {
    func testLineTransitionsRequireContinuityAndReplayDoesNotRetrigger() {
        var evaluator = UPSAlertEvaluator()
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        XCTAssertTrue(evaluate(&evaluator, source: source, line: .onLine, capture: start, uptime: 0).isEmpty)
        XCTAssertTrue(evaluate(&evaluator, source: source, line: .onLine, capture: start, uptime: 1).isEmpty)
        XCTAssertEqual(evaluate(&evaluator, source: source, line: .onBattery,
                                capture: start.addingTimeInterval(1), uptime: 2).map(\.kind), [.onBattery])
        XCTAssertTrue(evaluate(&evaluator, source: source, line: .onBattery,
                               capture: start.addingTimeInterval(1), uptime: 3).isEmpty)
        XCTAssertEqual(evaluate(&evaluator, source: source, line: .onLine,
                                capture: start.addingTimeInterval(2), uptime: 4).map(\.kind), [.powerRestored])

        XCTAssertTrue(evaluate(&evaluator, source: source, line: .unknown,
                               capture: start.addingTimeInterval(3), uptime: 5,
                               acquisitionSucceeded: false).isEmpty)
        XCTAssertTrue(evaluate(&evaluator, source: source, line: .onLine,
                               capture: start.addingTimeInterval(4), uptime: 6).isEmpty)
        XCTAssertEqual(evaluate(&evaluator, source: source, line: .onBattery,
                                capture: start.addingTimeInterval(5), uptime: 62).map(\.kind), [.onBattery])
    }

    func testLowBatteryLatchUsesFlagChargeAndRecoveryHysteresis() {
        var evaluator = UPSAlertEvaluator()
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        func sample(_ offset: TimeInterval, charge: Double?, flags: Set<MonitorStatusFlag> = [],
                    acquisitionSucceeded: Bool = true) -> [UPSAlertKind] {
            evaluate(&evaluator, source: source, line: .onLine, capture: start.addingTimeInterval(offset),
                     uptime: offset, charge: charge, flags: flags,
                     acquisitionSucceeded: acquisitionSucceeded).map(\.kind)
        }
        XCTAssertEqual(sample(0, charge: 0), [.lowBattery])
        XCTAssertTrue(sample(1, charge: 15).isEmpty)
        XCTAssertTrue(sample(2, charge: nil).isEmpty)
        XCTAssertTrue(sample(3, charge: 24).isEmpty)
        XCTAssertTrue(sample(4, charge: nil, acquisitionSucceeded: false).isEmpty)
        XCTAssertTrue(sample(5, charge: 21).isEmpty)
        XCTAssertTrue(sample(6, charge: 25).isEmpty)
        XCTAssertEqual(sample(61, charge: 19), [.lowBattery])

        var flagEvaluator = UPSAlertEvaluator()
        XCTAssertEqual(evaluate(&flagEvaluator, source: source, line: .onLine, capture: start, uptime: 0,
                                charge: nil, flags: [.lowBattery]).map(\.kind), [.lowBattery])
        XCTAssertTrue(evaluate(&flagEvaluator, source: source, line: .onLine,
                               capture: start.addingTimeInterval(1), uptime: 1, charge: nil).isEmpty)
        XCTAssertTrue(evaluate(&flagEvaluator, source: source, line: .onLine,
                               capture: start.addingTimeInterval(2), uptime: 2, charge: 24).isEmpty)
        XCTAssertEqual(evaluate(&flagEvaluator, source: source, line: .onLine,
                                capture: start.addingTimeInterval(60), uptime: 60, charge: 25).map(\.kind), [])
        XCTAssertEqual(evaluate(&flagEvaluator, source: source, line: .onLine,
                                capture: start.addingTimeInterval(61), uptime: 61, charge: 0).map(\.kind), [.lowBattery])
    }

    func testMonitoringLossNeedsThirtyContinuousSecondsAndUsesLastCapture() {
        var evaluator = UPSAlertEvaluator()
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        let initial = snapshot(source: source, at: start, line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: initial, acquisitionSucceeded: true, now: start,
                                          uptime: 0, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)
        XCTAssertTrue(evaluator.evaluate(snapshot: nil, acquisitionSucceeded: false, now: start.addingTimeInterval(1),
                                          uptime: 1, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)
        XCTAssertTrue(evaluator.evaluate(snapshot: nil, acquisitionSucceeded: false, now: start.addingTimeInterval(30),
                                          uptime: 30, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)
        let event = evaluator.evaluate(snapshot: nil, acquisitionSucceeded: false, now: start.addingTimeInterval(31),
                                       uptime: 31, maximumAge: 60, policy: UPSAlertPolicy())
        XCTAssertEqual(event, [UPSAlertEvent(kind: .monitoringUnavailable, capturedAt: start)])
        XCTAssertTrue(evaluator.evaluate(snapshot: nil, acquisitionSucceeded: false, now: start.addingTimeInterval(90),
                                          uptime: 90, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)

        let recovered = snapshot(source: source, at: start.addingTimeInterval(91), line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: recovered, acquisitionSucceeded: true,
                                          now: recovered.capturedAt, uptime: 91, maximumAge: 60,
                                          policy: UPSAlertPolicy()).isEmpty)
    }

    func testRecoveryBeforeLossDeadlineCancelsAndRearmsTimer() {
        var evaluator = UPSAlertEvaluator()
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        let initial = snapshot(source: source, at: start, line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: initial, acquisitionSucceeded: true, now: start,
                                          uptime: 0, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)

        func failure(_ time: TimeInterval) -> [UPSAlertEvent] {
            evaluator.evaluate(snapshot: nil, acquisitionSucceeded: false, now: start.addingTimeInterval(time),
                               uptime: time, maximumAge: 60, policy: UPSAlertPolicy())
        }
        XCTAssertTrue(failure(1).isEmpty)
        XCTAssertTrue(failure(20).isEmpty)
        let recovered = snapshot(source: source, at: start.addingTimeInterval(21), line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: recovered, acquisitionSucceeded: true,
                                          now: recovered.capturedAt, uptime: 21, maximumAge: 60,
                                          policy: UPSAlertPolicy()).isEmpty)
        XCTAssertTrue(failure(22).isEmpty)
        XCTAssertTrue(failure(51).isEmpty)
        XCTAssertEqual(failure(52), [UPSAlertEvent(kind: .monitoringUnavailable,
                                                   capturedAt: recovered.capturedAt)])
    }

    func testLossRecoveryRearmerAndCooldownAreSharedAcrossSources() {
        var evaluator = UPSAlertEvaluator()
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        let firstSource = source(id: "ups-a", session: "session-a")
        let secondSource = source(id: "ups-b", session: "session-b")
        XCTAssertEqual(evaluate(&evaluator, source: firstSource, line: .onBattery, capture: start, uptime: 0).map(\.kind), [.onBattery])
        XCTAssertTrue(evaluate(&evaluator, source: secondSource, line: .onBattery,
                               capture: start.addingTimeInterval(10), uptime: 10).isEmpty)
        XCTAssertTrue(evaluate(&evaluator, source: secondSource, line: .onBattery,
                               capture: start.addingTimeInterval(70), uptime: 70).isEmpty,
                      "A suppressed source transition must not be delivered later")

        let thirdSource = source(id: "ups-c", session: "session-c")
        XCTAssertEqual(evaluate(&evaluator, source: thirdSource, line: .onBattery,
                                capture: start.addingTimeInterval(71), uptime: 71).map(\.kind), [.onBattery])
    }

    func testUnavailableStaleFutureInvalidAndBackwardsInputsDoNotInventTransitions() {
        var evaluator = UPSAlertEvaluator()
        let source = source(id: "ups-a", session: "session-a")
        let start = Date(timeIntervalSince1970: 1_800_000_000)
        let unavailable = snapshot(source: source, at: start, line: .onBattery, quality: .unavailable)
        XCTAssertTrue(evaluator.evaluate(snapshot: unavailable, acquisitionSucceeded: true, now: start,
                                          uptime: 0, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)
        let future = snapshot(source: source, at: start.addingTimeInterval(100), line: .onBattery)
        XCTAssertTrue(evaluator.evaluate(snapshot: future, acquisitionSucceeded: true, now: start,
                                          uptime: 1, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)
        let offline = snapshot(source: source, at: start.addingTimeInterval(2), line: .onBattery, flags: [.sourceOffline])
        XCTAssertTrue(evaluator.evaluate(snapshot: offline, acquisitionSucceeded: true,
                                          now: offline.capturedAt, uptime: 2, maximumAge: 60,
                                          policy: UPSAlertPolicy()).isEmpty)
        let valid = snapshot(source: source, at: start.addingTimeInterval(3), line: .onBattery)
        XCTAssertEqual(evaluator.evaluate(snapshot: valid, acquisitionSucceeded: true, now: valid.capturedAt,
                                           uptime: 3, maximumAge: 60, policy: UPSAlertPolicy()).map(\.kind), [.onBattery])
        let backwards = snapshot(source: source, at: start.addingTimeInterval(4), line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: backwards, acquisitionSucceeded: true, now: backwards.capturedAt,
                                          uptime: 2, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)
        let afterReset = snapshot(source: source, at: start.addingTimeInterval(5), line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: afterReset, acquisitionSucceeded: true, now: afterReset.capturedAt,
                                          uptime: 3, maximumAge: 60, policy: UPSAlertPolicy()).isEmpty)

        var invalid = UPSAlertEvaluator()
        XCTAssertTrue(invalid.evaluate(snapshot: nil, acquisitionSucceeded: false, now: start,
                                       uptime: 0, maximumAge: .infinity,
                                       policy: UPSAlertPolicy(lowChargeThreshold: 4)).isEmpty)
    }

    private func evaluate(_ evaluator: inout UPSAlertEvaluator, source: MonitorSource, line: MonitorLineState,
                          capture: Date, uptime: TimeInterval, charge: Double? = nil,
                          flags: Set<MonitorStatusFlag> = [], acquisitionSucceeded: Bool = true) -> [UPSAlertEvent] {
        let value = snapshot(source: source, at: capture, line: line, charge: charge, flags: flags)
        return evaluator.evaluate(snapshot: value, acquisitionSucceeded: acquisitionSucceeded,
                                  now: capture, uptime: uptime, maximumAge: 60, policy: UPSAlertPolicy())
    }

    private func snapshot(source: MonitorSource, at date: Date, line: MonitorLineState,
                          quality: MonitorStatusQuality = .available,
                          charge: Double? = nil, flags: Set<MonitorStatusFlag> = []) -> MonitorSnapshot {
        let metrics = charge.map {
            [MonitorMetric(id: .batteryCharge, value: $0, unit: .percent, quality: .available, provenance: .reported)]
        } ?? []
        return MonitorSnapshot(source: source, capturedAt: date,
                               status: MonitorStatus(lineState: quality == .available ? line : .unknown,
                                                     flags: flags, quality: quality), metrics: metrics)
    }

    private func source(id: String, session: String) -> MonitorSource {
        MonitorSource(provider: .nut, id: id, sessionID: session, identityStability: .configured)
    }
}
