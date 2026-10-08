import Foundation
import XCTest
import UPSModel
@testable import UPSRuntime

final class ReceiptTimingTests: XCTestCase {
    func testReceiptTimePrecedesSlowSinkAndCachedStatePreservesIt() async throws {
        let clock = ReceiptClock(10)
        let gate = ReceiptSinkGate()
        let sample = snapshot()
        let coordinator = try MonitorCoordinator(read: { [sample] }, clock: { sample.capturedAt },
                                                  monotonicClock: { clock.read() },
                                                  sink: { _, _ in await gate.wait() })
        let refresh = Task { await coordinator.refresh() }
        for _ in 0..<200 where !(await gate.entered) { try await Task.sleep(for: .milliseconds(5)) }
        let entered = await gate.entered
        XCTAssertTrue(entered)
        clock.set(30)
        let whileSaving = await coordinator.currentState()
        XCTAssertEqual(whileSaving.lastSuccessUptime, 10)
        await gate.release()
        let completed = await refresh.value
        XCTAssertEqual(completed.lastSuccessUptime, 10)
        clock.set(50)
        let cached = await coordinator.currentState()
        XCTAssertEqual(cached.lastSuccessUptime, 10, "UI reads must not manufacture acquisition time")
    }

    func testInvalidReceiptClockDoesNotReplaceSuccessfulBatchOrWriteSink() async throws {
        let clock = ReceiptClock(10)
        let sample = snapshot()
        let sink = ReceiptCounter()
        let coordinator = try MonitorCoordinator(read: { [sample] }, clock: { sample.capturedAt },
                                                  monotonicClock: { clock.read() },
                                                  sink: { _, _ in await sink.increment() })
        _ = await coordinator.refresh()
        for invalid in [Double.nan, .infinity, -1] {
            clock.set(invalid)
            let failed = await coordinator.refresh()
            XCTAssertEqual(failed.acquisition, .failed(.invalidClock))
            XCTAssertEqual(failed.lastSuccessUptime, 10)
            XCTAssertEqual(failed.sources.first?.snapshot, sample)
            XCTAssertNotEqual(failed.sources.first?.freshness, .fresh)
        }
        let count = await sink.value
        XCTAssertEqual(count, 1)
    }

    private func snapshot() -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: .nut, id: "synthetic", sessionID: "session",
                                               identityStability: .configured), capturedAt: Date(timeIntervalSince1970: 100),
                        status: MonitorStatus(lineState: .onLine, quality: .available), metrics: [])
    }
}

private final class ReceiptClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value: TimeInterval
    init(_ value: TimeInterval) { self.value = value }
    func read() -> TimeInterval { lock.lock(); defer { lock.unlock() }; return value }
    func set(_ value: TimeInterval) { lock.lock(); defer { lock.unlock() }; self.value = value }
}

private actor ReceiptCounter {
    var value = 0
    func increment() { value += 1 }
}

private actor ReceiptSinkGate {
    var entered = false
    private var released = false
    private var continuation: CheckedContinuation<Void, Never>?
    func wait() async {
        entered = true
        guard !released else { return }
        await withCheckedContinuation { continuation = $0 }
    }
    func release() {
        released = true
        continuation?.resume()
        continuation = nil
    }
}
