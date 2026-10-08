import Foundation
import Security

public enum WidgetGroupError: Error, Equatable {
    case notConfigured, invalidIdentifier, entitlementMismatch, unavailable, invalidFixtureMode
}

public enum WidgetFixtureMode: Equatable, Sendable {
    case disabled
    case enabled
    case invalid
}

public enum WidgetGroupConfiguration {
    public static let productionWidgetKind = "UPSMonitorSnapshot"
    public static let syntheticWidgetKind = "UPSMonitorSyntheticFixture"
    public static let invalidWidgetKind = "UPSMonitorInvalidConfiguration"
    public static let productionDirectoryName = "UPSWidgetSnapshot"
    public static let syntheticDirectoryName = "UPSWidgetSyntheticFixture"
    public static let invalidDirectoryName = "UPSWidgetInvalidConfiguration"

    public static func fixtureMode(bundle: Bundle = .main) -> WidgetFixtureMode {
        guard let value = bundle.infoDictionary?["UPSWidgetFixtureMode"] else { return .disabled }
        return fixtureMode(infoValue: value)
    }

    public static func fixtureMode(infoValue: Any?) -> WidgetFixtureMode {
        guard let infoValue else { return .disabled }
        guard let value = infoValue as? String else { return .invalid }
        switch value {
        case "YES": return .enabled
        case "NO": return .disabled
        default: return .invalid
        }
    }

    public static func isSyntheticFixture(bundle: Bundle = .main) -> Bool {
        fixtureMode(bundle: bundle) == .enabled
    }

    public static func widgetKind(for mode: WidgetFixtureMode) -> String {
        switch mode {
        case .disabled: return productionWidgetKind
        case .enabled: return syntheticWidgetKind
        case .invalid: return invalidWidgetKind
        }
    }

    public static func directoryName(for mode: WidgetFixtureMode) -> String {
        switch mode {
        case .disabled: return productionDirectoryName
        case .enabled: return syntheticDirectoryName
        case .invalid: return invalidDirectoryName
        }
    }

    public static func directoryURL(bundle: Bundle = .main) throws -> URL {
        try directoryURL(bundle: bundle, fixtureMode: fixtureMode(bundle: bundle))
    }

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

    public static func directoryURL(bundle: Bundle = .main, fixtureMode: WidgetFixtureMode) throws -> URL {
        guard fixtureMode != .invalid else { throw WidgetGroupError.invalidFixtureMode }
        guard let identifier = bundle.object(forInfoDictionaryKey: "UPSAppGroupIdentifier") as? String,
              !identifier.isEmpty else { throw WidgetGroupError.notConfigured }
        guard let task = SecTaskCreateFromSelf(nil) else { throw WidgetGroupError.unavailable }
        let entitlements = SecTaskCopyValueForEntitlement(task, "com.apple.security.application-groups" as CFString, nil) as? [String] ?? []
        let validated = try validate(identifier: identifier, entitlements: entitlements)
        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: validated) else {
            throw WidgetGroupError.unavailable
        }
        // A URL alone does not establish group access on macOS. The store checks the directory.
        return try dedicatedDirectoryURL(in: container, fixtureMode: fixtureMode)
    }

    public static func dedicatedDirectoryURL(in container: URL, fixtureMode: WidgetFixtureMode) throws -> URL {
        guard fixtureMode != .invalid else { throw WidgetGroupError.invalidFixtureMode }
        return container.appendingPathComponent(directoryName(for: fixtureMode), isDirectory: true)
    }
}
