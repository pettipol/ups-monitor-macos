import Foundation
import XCTest
import UPSModel
@testable import UPSRuntime

final class AlertBoundaryRegressionTests: XCTestCase {
    func testDirectCaptureGapCannotProveMainsRestoration() {
        var evaluator = UPSAlertEvaluator()
        let battery = snapshot(at: 100, line: .onBattery, charge: 19)
        let initial = evaluate(&evaluator, battery, uptime: 100)
        XCTAssertEqual(Set(initial.map(\.kind)), [.onBattery, .lowBattery])

        let restoredAfterGap = snapshot(at: 200, line: .onLine, charge: 19)
        let afterGap = evaluate(&evaluator, restoredAfterGap, uptime: 200)
        XCTAssertTrue(afterGap.isEmpty, "A sampling gap cannot prove a continuous restoration; low charge stays latched")
    }

    func testReplayCannotOverwriteObservedLineState() {
        var evaluator = UPSAlertEvaluator()
        _ = evaluate(&evaluator, snapshot(at: 100, line: .onBattery), uptime: 100)
        XCTAssertTrue(evaluate(&evaluator, snapshot(at: 100, line: .onLine), uptime: 101).isEmpty)
        let next = evaluate(&evaluator, snapshot(at: 105, line: .onLine), uptime: 105)
        XCTAssertEqual(next.map(\.kind), [.powerRestored])
    }

    func testStaleAndFutureDataStartOneLossTimerWithoutRestoration() {
        var evaluator = UPSAlertEvaluator()
        let previous = snapshot(at: 100, line: .onBattery)
        _ = evaluate(&evaluator, previous, uptime: 100)
        XCTAssertTrue(evaluator.evaluate(snapshot: previous, acquisitionSucceeded: true,
                                          now: Date(timeIntervalSince1970: 111), uptime: 111,
                                          maximumAge: 10, policy: UPSAlertPolicy()).isEmpty)
        let future = snapshot(at: 160, line: .onLine)
        XCTAssertTrue(evaluator.evaluate(snapshot: future, acquisitionSucceeded: true,
                                          now: Date(timeIntervalSince1970: 130), uptime: 130,
                                          maximumAge: 10, policy: UPSAlertPolicy()).isEmpty)
        let lost = evaluator.evaluate(snapshot: nil, acquisitionSucceeded: false,
                                       now: Date(timeIntervalSince1970: 141), uptime: 141,
                                       maximumAge: 10, policy: UPSAlertPolicy())
        XCTAssertEqual(lost, [UPSAlertEvent(kind: .monitoringUnavailable, capturedAt: previous.capturedAt)])
        XCTAssertTrue(evaluate(&evaluator, snapshot(at: 142, line: .onLine), uptime: 142).isEmpty)
    }

    func testMalformedMetricAndInvalidClocksCannotEmit() {
        let valid = snapshot(at: 100, line: .onBattery)
        let invalid = MonitorSnapshot(source: valid.source, capturedAt: valid.capturedAt, status: valid.status,
                                      metrics: [MonitorMetric(id: .inputVoltage, value: 230, unit: .watts,
                                                              quality: .available, provenance: .reported)])
        var evaluator = UPSAlertEvaluator()
        XCTAssertTrue(evaluate(&evaluator, invalid, uptime: 100).isEmpty)
        for time in [TimeInterval.nan, .infinity, -1] {
            XCTAssertTrue(evaluator.evaluate(snapshot: valid, acquisitionSucceeded: true, now: valid.capturedAt,
                                              uptime: time, maximumAge: 10, policy: UPSAlertPolicy()).isEmpty)
        }
        XCTAssertTrue(evaluator.evaluate(snapshot: valid, acquisitionSucceeded: true,
                                          now: Date(timeIntervalSince1970: .infinity), uptime: 100,
                                          maximumAge: 10, policy: UPSAlertPolicy()).isEmpty)
        XCTAssertTrue(evaluator.evaluate(snapshot: valid, acquisitionSucceeded: true, now: valid.capturedAt,
                                          uptime: 100, maximumAge: 10,
                                          policy: UPSAlertPolicy(lowChargeThreshold: 51)).isEmpty)
    }

    private func evaluate(_ evaluator: inout UPSAlertEvaluator, _ snapshot: MonitorSnapshot,
                          uptime: TimeInterval) -> [UPSAlertEvent] {
        evaluator.evaluate(snapshot: snapshot, acquisitionSucceeded: true, now: snapshot.capturedAt,
                           uptime: uptime, maximumAge: 10, policy: UPSAlertPolicy())
    }

    private func snapshot(at seconds: TimeInterval, line: MonitorLineState,
                          charge: Double = 60) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: .nut, id: "synthetic", sessionID: "test",
                                               identityStability: .configured),
                        capturedAt: Date(timeIntervalSince1970: seconds),
                        status: MonitorStatus(lineState: line, quality: .available),
                        metrics: [MonitorMetric(id: .batteryCharge, value: charge, unit: .percent,
                                                quality: .available, provenance: .reported)])
    }
}
