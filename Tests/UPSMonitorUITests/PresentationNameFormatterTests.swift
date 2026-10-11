import Foundation
import UPSModel
import XCTest
@testable import UPSMonitorUI

final class PresentationNameFormatterTests: XCTestCase {
    func testFallbackAndNamedLabelsUseDisplayNameWithoutSourceKey() {
        let provider = MonitorProvider.nut
        XCTAssertEqual(UPSMonitorFormatters.sourceLabel(at: 1, provider: provider), "UPS 2 · NUT")
        XCTAssertEqual(UPSMonitorFormatters.sourceLabel(at: 0, provider: provider,
                                                        presentationName: "Hall UPS"), "Hall UPS · NUT")
        XCTAssertEqual(UPSMonitorFormatters.sourceLabel(at: 1, provider: provider,
                                                        presentationName: "Hall UPS",
                                                        includeOrdinal: true), "Hall UPS · UPS 2 · NUT")
        XCTAssertNotEqual(UPSMonitorFormatters.sourceLabel(at: 0, provider: provider,
                                                           presentationName: "Hall UPS",
                                                           includeOrdinal: true),
                          UPSMonitorFormatters.sourceLabel(at: 1, provider: provider,
                                                          presentationName: "Hall UPS",
                                                          includeOrdinal: true))
        XCTAssertFalse(UPSMonitorFormatters.sourceLabel(at: 0, provider: provider,
                                                        presentationName: "Hall UPS").contains("opaque-key"))
    }

    @MainActor
    func testViewsCanBeInitializedWithPresentationNameMaps() {
        let date = Date(timeIntervalSince1970: 1_000)
        let map: [String: String] = ["opaque-key": "Hall UPS"]
        _ = UPSMenuContentView(sources: [], presentationNamesBySourceKey: map,
                               selectedSourceKey: nil, readState: .noSources, now: date,
                               acquisitionSucceeded: false, onSelect: { _ in },
                               onRefresh: {}, onOpenDetails: {})
        _ = UPSDetailsView(sources: [], presentationNamesBySourceKey: map,
                           selectedSourceKey: nil, readState: .noSources, now: date,
                           acquisitionSucceeded: false, onSelect: { _ in }, onRefresh: {})
    }
}
