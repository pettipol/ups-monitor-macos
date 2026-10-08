import Foundation
@preconcurrency import UserNotifications
import UPSRuntime

@MainActor
final class SystemUPSAlertDelivery: UPSAlertDelivery {
    private lazy var center = UNUserNotificationCenter.current()
    private lazy var foregroundDelegate = UPSForegroundNotificationDelegate()

    func requestAuthorization() async throws -> Bool {
        let center = self.center
        let granted: Bool = try await withCheckedThrowingContinuation { continuation in
            center.requestAuthorization(options: [.alert]) { granted, error in
                if error != nil {
                    continuation.resume(throwing: UPSAlertDeliveryError.failed)
                } else {
                    continuation.resume(returning: granted)
                }
            }
        }
        if granted, await isAuthorized() {
            center.delegate = foregroundDelegate
        }
        return granted
    }

    func isAuthorized() async -> Bool {
        let settings: UNNotificationSettings = await withCheckedContinuation { continuation in
            center.getNotificationSettings { continuation.resume(returning: $0) }
        }
        return settings.authorizationStatus == .authorized && settings.alertSetting == .enabled
    }

    func submit(_ event: UPSAlertEvent) async throws {
        guard await isAuthorized() else { throw UPSAlertDeliveryError.notAuthorized }
        let request = Self.request(for: event)
        let _: Void = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            center.add(request) { error in
                if error != nil {
                    continuation.resume(throwing: UPSAlertDeliveryError.failed)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }

    func clear() async {
        center.removePendingNotificationRequests(withIdentifiers: Self.identifiers)
        center.removeDeliveredNotifications(withIdentifiers: Self.identifiers)
    }

    static func request(for event: UPSAlertEvent) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = "UPS Monitor"
        content.body = body(for: event)
        return UNNotificationRequest(
            identifier: identifier(for: event.kind),
            content: content,
            trigger: nil
        )
    }

    private static func identifier(for kind: UPSAlertKind) -> String {
        switch kind {
        case .onBattery: "ups-alert-1"
        case .powerRestored: "ups-alert-2"
        case .lowBattery: "ups-alert-3"
        case .monitoringUnavailable: "ups-alert-4"
        }
    }

    private static func body(for event: UPSAlertEvent) -> String {
        let time = event.capturedAt.formatted(date: .abbreviated, time: .shortened)
        return switch event.kind {
        case .onBattery: "Power is being supplied by battery. Observed \(time)."
        case .powerRestored: "Line power is available. Observed \(time)."
        case .lowBattery: "Latest UPS data indicates a low battery condition. Observed \(time)."
        case .monitoringUnavailable: "Monitoring data became unavailable. Last observation: \(time)."
        }
    }

    private static let identifiers = ["ups-alert-1", "ups-alert-2", "ups-alert-3", "ups-alert-4"]
}

@MainActor
private final class UPSForegroundNotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        let identifier = notification.request.identifier
        if ["ups-alert-1", "ups-alert-2", "ups-alert-3", "ups-alert-4"].contains(identifier) {
            completionHandler([.banner, .list])
        } else {
            completionHandler([])
        }
    }
}
