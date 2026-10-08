import Foundation
import UPSModel
import UPSMonitorUI
import XCTest
@testable import UPSAppHost

final class MonitorAppModelTests: XCTestCase {
    @MainActor
    func testMenuTitleDoesNotConvertOutOfRangeChargeToInt() {
        let capturedAt = Date(timeIntervalSinceReferenceDate: 800_000_000)
        let snapshot = MonitorSnapshot(
            source: source(),
            capturedAt: capturedAt,
            status: MonitorStatus(lineState: .onLine, quality: .available),
            metrics: [MonitorMetric(id: .batteryCharge, value: Double.greatestFiniteMagnitude,
                                    unit: .percent, quality: .available, provenance: .reported)]
        )
        let model = MonitorAppModel(clock: { capturedAt }, observesWorkspace: false, isPreview: false)
        model.sources = [snapshot]
        model.selectedSourceKey = UPSMonitorFormatters.sourceKey(for: snapshot)
        model.now = capturedAt
        model.readState = .ready
        model.acquisitionSucceeded = true

        XCTAssertEqual(model.menuTitle, "UPS")
    }

    @MainActor
    func testStopPreventsSubsequentRefreshAndRestart() async throws {
        let reads = ReadCounter()
        let model = MonitorAppModel(
            read: {
                await reads.increment()
                return []
            },
            clock: { Date(timeIntervalSinceReferenceDate: 800_000_000) },
            observesWorkspace: false,
            isPreview: false
        )

        await model.startIfNeeded()
        await model.stop()
        let readsAtStop = await reads.value

        model.refresh()
        await model.startIfNeeded()
        try await Task.sleep(for: .milliseconds(50))

        let readsAfterStop = await reads.value
        XCTAssertEqual(readsAfterStop, readsAtStop)
        XCTAssertEqual(model.readState, .stopped)
    }

    private func source() -> MonitorSource {
        MonitorSource(provider: .nut, id: "synthetic-ups", sessionID: "synthetic-session",
                      identityStability: .configured)
    }
}

private actor ReadCounter {
    private(set) var value = 0

    func increment() {
        value += 1
    }
}
