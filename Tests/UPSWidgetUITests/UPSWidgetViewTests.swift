import Foundation
import UPSModel
import UPSWidgetData
import XCTest
@testable import UPSWidgetUI

final class UPSWidgetViewTests: XCTestCase {
    func testUnavailableAndAcquisitionStatesAreExplicit() throws {
        let date = Date(timeIntervalSinceReferenceDate: 800_000_000)
        let source = makeSnapshot(at: date)
        let noSources = WidgetSnapshot(publishedAt: date, acquisition: .noSources,
                                       maximumAge: 60, snapshot: nil)
        let failed = WidgetSnapshot(publishedAt: date, acquisition: .readFailed,
                                    maximumAge: 60, snapshot: source)
        let stopped = WidgetSnapshot(publishedAt: date, acquisition: .stopped,
                                     maximumAge: 60, snapshot: source)

        XCTAssertEqual(UPSWidgetPresentation.stateLabel(payload: nil, date: date,
                                                         unavailableReason: "Widget not configured"),
                       "Widget not configured")
        XCTAssertEqual(UPSWidgetPresentation.stateLabel(payload: noSources, date: date), "No UPS detected")
        XCTAssertEqual(UPSWidgetPresentation.stateLabel(payload: failed, date: date), "Read failed · stale")
        XCTAssertEqual(UPSWidgetPresentation.stateLabel(payload: stopped, date: date), "Stopped · stale")
    }

    func testZeroMissingAndStaleCaptureStayDistinct() throws {
        let date = Date(timeIntervalSinceReferenceDate: 800_000_000)
        let zeroCharge = makeSnapshot(at: date, charge: 0)
        let missingCharge = makeSnapshot(at: date, charge: nil)
        let active = WidgetSnapshot(publishedAt: date, acquisition: .active,
                                    maximumAge: 30, snapshot: zeroCharge)

        XCTAssertEqual(UPSWidgetPresentation.chargeValue(zeroCharge), "0%")
        XCTAssertEqual(UPSWidgetPresentation.chargeValue(missingCharge), "Not reported")
        XCTAssertEqual(UPSWidgetPresentation.stateLabel(payload: active, date: date), "Last capture")
        XCTAssertEqual(UPSWidgetPresentation.statusLine(payload: active, date: date), "Last capture · On line")
        XCTAssertEqual(UPSWidgetPresentation.ageLabel(zeroCharge, date: date.addingTimeInterval(45)), "45 sec ago")
        XCTAssertTrue(UPSWidgetPresentation.isStale(payload: active, date: date.addingTimeInterval(45)))
        XCTAssertEqual(UPSWidgetPresentation.stateLabel(payload: active, date: date.addingTimeInterval(45)), "Stale capture")
    }

    func testMediumPowerPreservesUnitsAndProvenance() {
        let date = Date(timeIntervalSinceReferenceDate: 800_000_000)
        let snapshot = makeSnapshot(at: date, charge: 74, includePower: true)

        XCTAssertTrue(UPSWidgetPresentation.metricValue(.upsRealPower, in: snapshot).hasSuffix("W · Driver-derived"))
        XCTAssertTrue(UPSWidgetPresentation.metricValue(.upsApparentPower, in: snapshot).hasSuffix("VA · Driver-derived"))
        XCTAssertEqual(UPSWidgetPresentation.metricValue(.batteryRuntime, in: snapshot), "33 min · Estimated")
    }

    @MainActor
    func testViewSupportsSmallMediumAndUnavailableEntries() {
        let date = Date(timeIntervalSinceReferenceDate: 800_000_000)
        let payload = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 60,
                                     snapshot: makeSnapshot(at: date))

        _ = UPSWidgetView(payload: payload, date: date, isMedium: false)
        _ = UPSWidgetView(payload: payload, date: date, isMedium: true)
        _ = UPSWidgetView(payload: nil, date: date, isMedium: false,
                          unavailableReason: "Widget not configured")
    }

    private func makeSnapshot(at date: Date, charge: Double? = 74, includePower: Bool = false) -> MonitorSnapshot {
        var metrics = [MonitorMetric(
            id: .batteryCharge,
            value: charge,
            unit: .percent,
            quality: charge == nil ? .unavailable : .available,
            provenance: .reported
        )]
        if includePower {
            metrics.append(contentsOf: [
                MonitorMetric(id: .batteryRuntime, value: 1_980, unit: .seconds,
                              quality: .available, provenance: .estimated),
                MonitorMetric(id: .upsRealPower, value: 184.5, unit: .watts,
                              quality: .available, provenance: .driverDerived),
                MonitorMetric(id: .upsApparentPower, value: 212.7, unit: .voltAmps,
                              quality: .available, provenance: .driverDerived),
            ])
        }
        return MonitorSnapshot(
            source: MonitorSource(provider: .nut, id: "synthetic-ups", sessionID: "synthetic-session",
                                  identityStability: .configured),
            capturedAt: date,
            status: MonitorStatus(lineState: .onLine, quality: .available),
            metrics: metrics
        )
    }
}
