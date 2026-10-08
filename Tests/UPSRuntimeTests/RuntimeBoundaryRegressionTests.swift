import Foundation
import Testing
import UPSModel
@testable import UPSRuntime

private let boundaryDate = Date(timeIntervalSince1970: 20_000)
private func boundarySnapshot(stability: IdentityStability = .configured) -> MonitorSnapshot {
    MonitorSnapshot(source: MonitorSource(provider: .nut, id: "source", sessionID: "session", identityStability: stability),
                    capturedAt: boundaryDate, status: MonitorStatus(quality: .unavailable), metrics: [])
}

private actor BoundaryGate {
    var started = false
    var released = false
    var saved = 0
    var continuation: CheckedContinuation<Void, Never>?
    func readIgnoringCancellation() async -> [MonitorSnapshot] {
        started = true
        if !released { await withCheckedContinuation { continuation = $0 } }
        return [boundarySnapshot()]
    }
    func release() {
        released = true
        continuation?.resume()
        continuation = nil
    }
    func save() { saved += 1 }
}

@Test func cancellationRejectsLateNonCooperativeResultAndPreventsHistoryWrite() async throws {
    let gate = BoundaryGate()
    let coordinator = try MonitorCoordinator(read: { await gate.readIgnoringCancellation() }, clock: { boundaryDate },
                                             sink: { _, _ in await gate.save() })
    let operation = Task { await coordinator.refresh() }
    for _ in 0..<100 where !(await gate.started) { try await Task.sleep(for: .milliseconds(2)) }
    #expect(await gate.started)
    operation.cancel()
    await gate.release()
    let result = await operation.value
    #expect(result.acquisition == .failed(.cancelled))
    #expect(result.sources.isEmpty)
    #expect(result.lastSuccessAt == nil)
    #expect(await gate.saved == 0)
    #expect(!result.isRefreshing)
}

@Test func sourceStabilityCannotHideDuplicateIdentityFromCoordinator() async throws {
    let gate = BoundaryGate()
    let coordinator = try MonitorCoordinator(read: { [boundarySnapshot(), boundarySnapshot(stability: .sessionLocal)] },
                                             clock: { boundaryDate }, sink: { _, _ in await gate.save() })
    #expect((await coordinator.refresh()).acquisition == .failed(.invalidCollection))
    #expect(await gate.saved == 0)
}

@Test func invalidClockDoesNotReadAndCannotBeLastAttempt() async throws {
    let gate = BoundaryGate()
    let coordinator = try MonitorCoordinator(read: { await gate.readIgnoringCancellation() },
                                             clock: { Date(timeIntervalSince1970: .infinity) })
    let state = await coordinator.refresh()
    #expect(state.acquisition == .failed(.invalidClock))
    #expect(state.lastAttemptAt == nil)
    #expect(!(await gate.started))
}
