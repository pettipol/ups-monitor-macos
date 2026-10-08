import Foundation
import Testing
import UPSWidgetBridge

@Test func fixtureModeParsingIsExactAndMissingDefaultsToProduction() {
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: nil) == .disabled)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: "NO") == .disabled)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: "YES") == .enabled)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: "yes") == .invalid)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: "") == .invalid)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: "YES ") == .invalid)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: NSNumber(value: true)) == .invalid)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: NSNumber(value: 1)) == .invalid)
    #expect(WidgetGroupConfiguration.fixtureMode(infoValue: NSNull()) == .invalid)
}

@Test func fixtureAndInvalidModesNeverReuseProductionWidgetIdentity() throws {
    let productionKind = WidgetGroupConfiguration.widgetKind(for: .disabled)
    let fixtureKind = WidgetGroupConfiguration.widgetKind(for: .enabled)
    let invalidKind = WidgetGroupConfiguration.widgetKind(for: .invalid)
    let productionDirectory = WidgetGroupConfiguration.directoryName(for: .disabled)
    let fixtureDirectory = WidgetGroupConfiguration.directoryName(for: .enabled)
    let invalidDirectory = WidgetGroupConfiguration.directoryName(for: .invalid)
    let container = URL(fileURLWithPath: "/synthetic-app-group", isDirectory: true)

    #expect(productionKind == "UPSMonitorSnapshot")
    #expect(fixtureKind == "UPSMonitorSyntheticFixture")
    #expect(invalidKind == "UPSMonitorInvalidConfiguration")
    #expect(Set([productionKind, fixtureKind, invalidKind]).count == 3)
    #expect(productionDirectory == "UPSWidgetSnapshot")
    #expect(fixtureDirectory == "UPSWidgetSyntheticFixture")
    #expect(invalidDirectory == "UPSWidgetInvalidConfiguration")
    #expect(Set([productionDirectory, fixtureDirectory, invalidDirectory]).count == 3)
    let productionURL = try WidgetGroupConfiguration.dedicatedDirectoryURL(in: container, fixtureMode: .disabled)
    let fixtureURL = try WidgetGroupConfiguration.dedicatedDirectoryURL(in: container, fixtureMode: .enabled)
    #expect(productionURL.deletingLastPathComponent() == container)
    #expect(fixtureURL.deletingLastPathComponent() == container)
    #expect(productionURL != fixtureURL)
    #expect(throws: WidgetGroupError.invalidFixtureMode) {
        try WidgetGroupConfiguration.directoryURL(bundle: .main, fixtureMode: .invalid)
    }
}
