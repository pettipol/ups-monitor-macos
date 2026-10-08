import Foundation
import XCTest
import UPSModel
import UPSMonitorUI
import UPSRuntime
@testable import UPSAppHost

final class AlertHostIntegrationTests: XCTestCase {
    @MainActor
    func testPreviewCannotAuthorizeOrSubmitAlerts() async {
        let delivery = HostAlertDelivery()
        let alerts = UPSAlertController(delivery: delivery)
        let model = MonitorAppModel(observesWorkspace: false, isPreview: true, alerts: alerts)
        await model.startIfNeeded()
        await model.setAlertsEnabled(true)
        await model.stop()
        XCTAssertEqual(delivery.authorizationRequests, 0)
        XCTAssertEqual(delivery.statusQueries, 0)
        XCTAssertEqual(delivery.submissions.count, 0)
        XCTAssertEqual(delivery.clearCalls, 0)
        XCTAssertFalse(alerts.isEnabled)
    }

    @MainActor
    func testLiveHostIsSilentByDefaultAndStopRejectsLaterEnable() async {
        let delivery = HostAlertDelivery()
        let alerts = UPSAlertController(delivery: delivery)
        let fixture = makeSnapshot(id: "one", line: .onBattery)
        let model = MonitorAppModel(read: { [fixture] }, clock: { fixture.capturedAt },
                                    observesWorkspace: false, isPreview: false, alerts: alerts)
        await model.startIfNeeded()
        for _ in 0..<100 where model.sources.isEmpty { try? await Task.sleep(for: .milliseconds(10)) }
        XCTAssertFalse(model.sources.isEmpty)
        await model.stop()
        await model.setAlertsEnabled(true)
        XCTAssertEqual(delivery.authorizationRequests, 0)
        XCTAssertEqual(delivery.statusQueries, 0)
        XCTAssertEqual(delivery.clearCalls, 0)
        XCTAssertTrue(delivery.submissions.isEmpty)
    }

    @MainActor
    func testHostSubmitsOnlyForSelectedSourceAfterExplicitEnable() async {
        let delivery = HostAlertDelivery()
        let alerts = UPSAlertController(delivery: delivery)
        let online = makeSnapshot(id: "first", line: .onLine)
        let battery = makeSnapshot(id: "second", line: .onBattery)
        let model = MonitorAppModel(read: { [online, battery] }, clock: { online.capturedAt },
                                    observesWorkspace: false, isPreview: false, alerts: alerts)
        await model.setAlertsEnabled(true)
        await model.startIfNeeded()
        for _ in 0..<100 where model.sources.count != 2 { try? await Task.sleep(for: .milliseconds(10)) }
        XCTAssertEqual(model.sources.count, 2)
        XCTAssertTrue(delivery.submissions.isEmpty, "Unselected on-battery source must not notify")
        let key = UPSMonitorFormatters.sourceKey(for: battery)
        model.select(key)
        for _ in 0..<200 where delivery.submissions.isEmpty { try? await Task.sleep(for: .milliseconds(10)) }
        XCTAssertEqual(delivery.authorizationRequests, 1)
        XCTAssertEqual(delivery.submissions.map(\.kind), [.onBattery])
        await model.stop()
        XCTAssertFalse(alerts.isEnabled)
    }

    @MainActor
    func testPendingNotificationDoesNotFreezeLiveClock() async {
        let delivery = HostAlertDelivery()
        delivery.holdSubmission = true
        let alerts = UPSAlertController(delivery: delivery)
        let fixture = MonitorSnapshot(source: makeSnapshot(id: "one", line: .onBattery).source,
                                      capturedAt: Date(),
                                      status: MonitorStatus(lineState: .onBattery, quality: .available), metrics: [])
        let model = MonitorAppModel(read: { [fixture] }, observesWorkspace: false,
                                    isPreview: false, alerts: alerts)
        await model.setAlertsEnabled(true)
        await model.startIfNeeded()
        for _ in 0..<200 where delivery.pendingSubmission == nil {
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertNotNil(delivery.pendingSubmission)
        let previous = model.now
        for _ in 0..<200 where model.now <= previous {
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertGreaterThan(model.now, previous, "Delivery must not hold the live freshness clock")
        XCTAssertEqual(delivery.submissions.count, 1, "Duplicate polls must not queue more deliveries")
        delivery.holdSubmission = false
        delivery.pendingSubmission?.resume()
        delivery.pendingSubmission = nil
        await model.stop()
    }

    private func makeSnapshot(id: String, line: MonitorLineState) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: .nut, id: id, sessionID: "synthetic-session",
                                               identityStability: .configured),
                        capturedAt: Date(timeIntervalSince1970: 20_000),
                        status: MonitorStatus(lineState: line, quality: .available), metrics: [])
    }
}

@MainActor
private final class HostAlertDelivery: UPSAlertDelivery {
    var authorizationRequests = 0
    var statusQueries = 0
    var clearCalls = 0
    var submissions: [UPSAlertEvent] = []
    var holdSubmission = false
    var pendingSubmission: CheckedContinuation<Void, Never>?
    func requestAuthorization() async throws -> Bool { authorizationRequests += 1; return true }
    func isAuthorized() async -> Bool { statusQueries += 1; return true }
    func submit(_ event: UPSAlertEvent) async throws {
        submissions.append(event)
        if holdSubmission {
            await withCheckedContinuation { pendingSubmission = $0 }
        }
    }
    func clear() async { clearCalls += 1 }
}
