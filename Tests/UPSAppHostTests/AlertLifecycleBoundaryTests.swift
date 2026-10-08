import Foundation
import XCTest
import UPSModel
import UPSRuntime
@testable import UPSAppHost

final class AlertLifecycleBoundaryTests: XCTestCase {
    @MainActor
    func testSourceSuspensionAndPolicyEditPreserveAlertCooldown() async {
        let delivery = LifecycleAlertDelivery()
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        await observe(controller, id: "first", time: 100)
        XCTAssertEqual(delivery.events.map(\.kind), [.onBattery])
        await controller.suspend()
        await observe(controller, id: "second", time: 101)
        XCTAssertEqual(delivery.events.count, 1, "Changing selected source must not bypass per-kind cooldown")
        controller.setPolicy(UPSAlertPolicy(lowChargeThreshold: 30))
        await observe(controller, id: "second", time: 102)
        XCTAssertEqual(delivery.events.count, 1, "Editing an unrelated threshold must not repeat a line alert")
        await controller.stop()
    }

    @MainActor
    private func observe(_ controller: UPSAlertController, id: String, time: TimeInterval) async {
        let date = Date(timeIntervalSince1970: time)
        let snapshot = MonitorSnapshot(source: MonitorSource(provider: .nut, id: id, sessionID: "synthetic",
                                                              identityStability: .configured), capturedAt: date,
                                       status: MonitorStatus(lineState: .onBattery, quality: .available), metrics: [])
        await controller.observe(snapshot: snapshot, acquisitionSucceeded: true,
                                 now: date, uptime: time, maximumAge: 10)
    }
}

@MainActor
private final class LifecycleAlertDelivery: UPSAlertDelivery {
    var events: [UPSAlertEvent] = []
    func requestAuthorization() async throws -> Bool { true }
    func isAuthorized() async -> Bool { true }
    func submit(_ event: UPSAlertEvent) async throws { events.append(event) }
    func clear() async {}
}
