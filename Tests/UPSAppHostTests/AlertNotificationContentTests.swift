import Foundation
import Testing
@preconcurrency import UserNotifications
import UPSRuntime
@testable import UPSAppHost

@Suite struct AlertNotificationContentTests {
    @MainActor @Test func requestFactoryBuildsFourFixedPrivateAlertPayloads() {
        let capturedAt = Date(timeIntervalSince1970: 1_700_000_000)
        let time = capturedAt.formatted(date: .abbreviated, time: .shortened)
        let fixtures: [(UPSAlertKind, String, String)] = [
            (.onBattery, "ups-alert-1", "Power is being supplied by battery. Observed \(time)."),
            (.powerRestored, "ups-alert-2", "Line power is available. Observed \(time)."),
            (.lowBattery, "ups-alert-3", "Latest UPS data indicates a low battery condition. Observed \(time)."),
            (.monitoringUnavailable, "ups-alert-4", "Monitoring data became unavailable. Last observation: \(time)."),
        ]

        for (kind, identifier, body) in fixtures {
            let request = SystemUPSAlertDelivery.request(for: UPSAlertEvent(kind: kind, capturedAt: capturedAt))
            let content = request.content

            #expect(request.identifier == identifier)
            #expect(request.trigger == nil)
            #expect(content.title == "UPS Monitor")
            #expect(content.body == body)
            #expect(content.sound == nil)
            #expect(content.badge == nil)
            #expect(content.userInfo.isEmpty)
            #expect(content.attachments.isEmpty)
            #expect(content.categoryIdentifier.isEmpty)
        }
    }
}
