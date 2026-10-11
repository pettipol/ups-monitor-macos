import Foundation
import UPSModel
import UPSWidgetData
import XCTest
@testable import UPSWidgetUI

final class PresentationNameWidgetViewTests: XCTestCase {
    func testSyntheticLabelTakesPriorityAndCanonicalNameKeepsProvider() {
        XCTAssertEqual(UPSWidgetPresentation.headerLabel(providerLabel: "Local NUT",
                                                          isSyntheticFixture: true,
                                                          presentationName: "Hall UPS"), "Synthetic UPS")
        XCTAssertEqual(UPSWidgetPresentation.headerLabel(providerLabel: "Local NUT",
                                                          isSyntheticFixture: false,
                                                          presentationName: "Hall UPS"), "Hall UPS · Local NUT")
        XCTAssertEqual(UPSWidgetPresentation.headerLabel(providerLabel: "Local NUT",
                                                          isSyntheticFixture: false), "UPS · Local NUT")
    }

    @MainActor
    func testWidgetViewsRemainConstructibleWithAndWithoutPresentationName() {
        let date = Date(timeIntervalSince1970: 1_000)
        let snapshot = MonitorSnapshot(
            source: MonitorSource(provider: .nut, id: "fixture-id", sessionID: "fixture-session",
                                  identityStability: .configured),
            capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
        let named = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 30,
                                   snapshot: snapshot, presentationName: "Hall UPS")
        let legacy = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 30,
                                    snapshot: snapshot)
        _ = UPSWidgetView(payload: named, date: date, isMedium: true)
        _ = UPSWidgetView(payload: legacy, date: date, isMedium: false)
    }
}
