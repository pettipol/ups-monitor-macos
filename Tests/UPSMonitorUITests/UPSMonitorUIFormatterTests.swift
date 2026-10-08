import Foundation
import XCTest
import UPSModel
@testable import UPSMonitorUI

final class UPSMonitorUIFormatterTests: XCTestCase {
    func testMissingZeroAndNegativeMetricsRemainDistinct() {
        let missing = metric(.batteryCharge, value: nil, unit: .percent, quality: .unavailable)
        let zero = metric(.batteryCharge, value: 0, unit: .percent, quality: .available)
        let negative = metric(.inputCurrent, value: -1.25, unit: .amps, quality: .available)

        XCTAssertEqual(UPSMonitorFormatters.metricValue(missing), "Not reported")
        XCTAssertEqual(UPSMonitorFormatters.metricValue(zero), "0 %")
        let negativeText = UPSMonitorFormatters.metricValue(negative)
        XCTAssertTrue(negativeText.first == "-" || negativeText.first == "−")
        XCTAssertTrue(negativeText.hasSuffix(" A"))
    }

    func testUnitsQualityAndProvenanceAreExplicit() {
        XCTAssertEqual(UPSMonitorFormatters.unitLabel(.watts), "W")
        XCTAssertEqual(UPSMonitorFormatters.unitLabel(.voltAmps), "VA")
        XCTAssertEqual(UPSMonitorFormatters.qualityLabel(.calculating), "Calculating")
        XCTAssertEqual(UPSMonitorFormatters.provenanceLabel(.estimated), "Estimated")
        XCTAssertEqual(UPSMonitorFormatters.provenanceLabel(.driverDerived), "Driver-derived")
        XCTAssertEqual(UPSMonitorFormatters.metricName(.batteryRuntime), "Runtime estimate")
        XCTAssertEqual(UPSMonitorFormatters.metricName(.appleSourceTemperature), "Source temperature")
    }

    func testTimestampAndAgeFormattingRemainUsable() {
        let capturedAt = Date(timeIntervalSinceReferenceDate: 765_432.123456)
        let rendered = UPSMonitorFormatters.timestamp(capturedAt)
        XCTAssertFalse(rendered.isEmpty)
        XCTAssertEqual(UPSMonitorFormatters.relativeAge(from: capturedAt, to: capturedAt), "just now")
        XCTAssertEqual(UPSMonitorFormatters.relativeAge(from: capturedAt.addingTimeInterval(1), to: capturedAt), "time unknown")
    }

    func testStaleFormattingHonorsAgeAndFailedAcquisition() {
        let capturedAt = Date(timeIntervalSince1970: 1_000)
        let sample = MonitorSnapshot(
            source: MonitorSource(provider: .nut, id: "fixture", sessionID: "session", identityStability: .configured),
            capturedAt: capturedAt,
            status: MonitorStatus(lineState: .unknown, quality: .available),
            metrics: []
        )
        XCTAssertEqual(UPSMonitorFormatters.freshness(of: sample, now: capturedAt.addingTimeInterval(10), maximumAge: 15,
                                                       acquisitionSucceeded: true), .fresh)
        XCTAssertEqual(UPSMonitorFormatters.freshness(of: sample, now: capturedAt.addingTimeInterval(10), maximumAge: 5,
                                                       acquisitionSucceeded: true), .stale)
        XCTAssertEqual(UPSMonitorFormatters.freshness(of: sample, now: capturedAt, maximumAge: 15,
                                                       acquisitionSucceeded: false), .stale)
        XCTAssertTrue(UPSMonitorFormatters.freshnessLabel(of: sample, now: capturedAt.addingTimeInterval(10),
                                                          maximumAge: 5, acquisitionSucceeded: true).hasPrefix("Stale"))
    }

    func testSelectionKeyIsOpaqueToDisplayLabels() {
        let sample = MonitorSnapshot(
            source: MonitorSource(provider: .apple, id: "opaque-private-id", sessionID: "session-private", identityStability: .sessionLocal),
            capturedAt: Date(timeIntervalSince1970: 1_000),
            status: MonitorStatus(lineState: .unknown, quality: .available),
            metrics: []
        )
        let key = UPSMonitorFormatters.sourceKey(for: sample)
        let label = UPSMonitorFormatters.sourceLabel(at: 0, provider: sample.source.provider)
        XCTAssertTrue(key.contains(sample.source.id))
        XCTAssertEqual(label, "UPS 1 · Apple")
        XCTAssertFalse(label.contains(sample.source.id))
        XCTAssertFalse(label.contains(sample.source.sessionID))
    }

    private func metric(
        _ id: MonitorMetricID,
        value: Double?,
        unit: MonitorMetricUnit,
        quality: MonitorMetricQuality
    ) -> MonitorMetric {
        MonitorMetric(id: id, value: value, unit: unit, quality: quality, provenance: .reported)
    }
}
