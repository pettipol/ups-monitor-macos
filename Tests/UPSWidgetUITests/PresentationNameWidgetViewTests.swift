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

    func testAppleWidgetTitleCompactsOnlyCompleteRecognizedSuffix() {
        let fullName = "Synthetic Tower 1500 FW:UPS 9.9 / ID=9999"
        XCTAssertEqual(UPSWidgetPresentation.headerLabel(
            providerLabel: "Apple", isSyntheticFixture: false, presentationName: fullName,
            sourceProvider: .apple), "Synthetic Tower 1500 · Apple")
        XCTAssertEqual(UPSWidgetPresentation.accessibilityHeaderLabel(
            providerLabel: "Apple", isSyntheticFixture: false, presentationName: fullName),
                       "Synthetic Tower 1500 FW:UPS 9.9 / ID=9999 · Apple")

        XCTAssertEqual(UPSWidgetPresentation.headerLabel(
            providerLabel: "Local NUT", isSyntheticFixture: false, presentationName: fullName,
            sourceProvider: .nut), "Synthetic Tower 1500 FW:UPS 9.9 / ID=9999 · Local NUT")
        XCTAssertEqual(UPSWidgetPresentation.headerLabel(
            providerLabel: "Apple", isSyntheticFixture: false, presentationName: fullName),
                       "Synthetic Tower 1500 FW:UPS 9.9 / ID=9999 · Apple")
    }

    func testMalformedOrEmptyPrefixSuffixesRemainUnchanged() {
        let unchanged = [
            "Synthetic Tower FW:UPS 9.9 / ID=9999 trailing",
            "Synthetic Tower FW:UPS 9 / ID=9999",
            "Synthetic Tower FW:UPS 9.9 / ID=x",
            " FW:UPS 9.9 / ID=9999",
            "Synthetic Tower ups 9.9 / ID=9999",
            "Synthetic Tower UPS 9.9 / ID=9999",
            "Synthetic Custom Name",
        ]
        for name in unchanged {
            let canonicalName = name.trimmingCharacters(in: .whitespacesAndNewlines)
            XCTAssertEqual(UPSWidgetPresentation.headerLabel(
                providerLabel: "Apple", isSyntheticFixture: false, presentationName: name,
                sourceProvider: .apple), "\(canonicalName) · Apple", "Unexpected compaction for: \(name)")
        }
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

        let appleSnapshot = MonitorSnapshot(
            source: MonitorSource(provider: .apple, id: "fixture-apple", sessionID: "fixture-session",
                                  identityStability: .sessionLocal),
            capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
        let fullName = "Synthetic Tower 1500 FW:UPS 9.9 / ID=9999"
        let applePayload = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 30,
                                          snapshot: appleSnapshot, presentationName: fullName)
        XCTAssertEqual(applePayload.presentationName, fullName)
        _ = UPSWidgetView(payload: applePayload, date: date, isMedium: false)
        _ = UPSWidgetView(payload: applePayload, date: date, isMedium: true)
    }
}
