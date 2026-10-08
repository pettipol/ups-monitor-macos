import Foundation
import Security

public enum WidgetGroupError: Error, Equatable {
    case notConfigured, invalidIdentifier, entitlementMismatch, unavailable
}

public enum WidgetGroupConfiguration {
    public static let widgetKind = "UPSMonitorSnapshot"
    public static let directoryName = "UPSWidgetSnapshot"

    public static func validate(identifier: String?, entitlements: [String]) throws -> String {
        guard let identifier, !identifier.isEmpty else { throw WidgetGroupError.notConfigured }
        let segments = identifier.split(separator: ".", omittingEmptySubsequences: false)
        guard identifier.utf8.count <= 200, segments.count >= 3,
              segments.allSatisfy({ !$0.isEmpty }),
              identifier.utf8.allSatisfy({ (48...57).contains($0) || (65...90).contains($0)
                  || (97...122).contains($0) || $0 == 45 || $0 == 46 }),
              segments[0] == "group" || (segments[0].count == 10 && segments[0].utf8.allSatisfy({
                  (48...57).contains($0) || (65...90).contains($0)
              })) else { throw WidgetGroupError.invalidIdentifier }
        guard entitlements.contains(identifier) else { throw WidgetGroupError.entitlementMismatch }
        return identifier
    }

    public static func directoryURL(bundle: Bundle = .main) throws -> URL {
        guard let identifier = bundle.object(forInfoDictionaryKey: "UPSAppGroupIdentifier") as? String,
              !identifier.isEmpty else { throw WidgetGroupError.notConfigured }
        guard let task = SecTaskCreateFromSelf(nil) else { throw WidgetGroupError.unavailable }
        let entitlements = SecTaskCopyValueForEntitlement(task, "com.apple.security.application-groups" as CFString, nil) as? [String] ?? []
        let validated = try validate(identifier: identifier, entitlements: entitlements)
        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: validated) else {
            throw WidgetGroupError.unavailable
        }
        // A URL alone does not establish group access on macOS. The store checks the directory.
        return container.appendingPathComponent(directoryName, isDirectory: true)
    }
}
