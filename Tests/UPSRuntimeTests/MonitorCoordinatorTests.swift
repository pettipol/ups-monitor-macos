import Foundation
import Testing
import UPSModel
@testable import UPSRuntime

private let fixedDate = Date(timeIntervalSince1970: 10_000)
private let runtimeSource = MonitorSource(provider: .nut, id: "synthetic-ups", sessionID: "session-a", identityStability: .configured)

private func snapshot(at date: Date = fixedDate, source: MonitorSource = runtimeSource) -> MonitorSnapshot {
    MonitorSnapshot(
        source: source,
        capturedAt: date,
        status: MonitorStatus(quality: .unavailable),
        metrics: []
    )
}

@Test func successfulRefreshSetsTimestampsAndNoSourcesIsNotAnError() async throws {
    let coordinator = try MonitorCoordinator(read: { [snapshot()] }, clock: { fixedDate })
    let populated = await coordinator.refresh()
    #expect(populated.acquisition == .succeeded)
    #expect(populated.sources.count == 1)
    #expect(populated.lastAttemptAt == fixedDate)
    #expect(populated.lastSuccessAt == fixedDate)

    let empty = try MonitorCoordinator(read: { [] }, clock: { fixedDate })
    let noSources = await empty.refresh()
    #expect(noSources.acquisition == .noSources)
    #expect(noSources.sources.isEmpty)
    #expect(noSources.lastSuccessAt == fixedDate)
}

@Test func failedReadPreservesCacheAndImmediatelyMarksItStale() async throws {
    actor ReadSwitch {
        var shouldFail = false
        func setFailure(_ value: Bool) { shouldFail = value }
        func read() throws -> [MonitorSnapshot] {
            if shouldFail { throw SyntheticReadError.failed }
            return [snapshot()]
        }
    }
    let control = ReadSwitch()
    let coordinator = try MonitorCoordinator(read: { try await control.read() }, clock: { fixedDate })
    _ = await coordinator.refresh()
    await control.setFailure(true)
    let failed = await coordinator.refresh()

    #expect(failed.acquisition == .failed(.readFailed))
    #expect(failed.sources.count == 1)
    #expect(failed.sources[0].snapshot.capturedAt == fixedDate)
    #expect(failed.sources[0].freshness == .stale)
    #expect(failed.lastSuccessAt == fixedDate)
}

@Test func malformedAndDuplicateCollectionsAreRejectedWithoutReplacingCache() async throws {
    actor ReadSwitch {
        var result: [MonitorSnapshot] = [snapshot()]
        func set(_ value: [MonitorSnapshot]) { result = value }
        func read() -> [MonitorSnapshot] { result }
    }
    let control = ReadSwitch()
    let coordinator = try MonitorCoordinator(read: { await control.read() }, clock: { fixedDate })
    _ = await coordinator.refresh()
    await control.set([snapshot(), snapshot()])
    let duplicate = await coordinator.refresh()
    #expect(duplicate.acquisition == .failed(.invalidCollection))
    #expect(duplicate.sources.count == 1)
    #expect(duplicate.sources[0].freshness == .stale)

    let invalid = MonitorSnapshot(schemaVersion: 2, source: runtimeSource, capturedAt: fixedDate,
                                  status: MonitorStatus(quality: .unavailable), metrics: [])
    await control.set([invalid])
    #expect((await coordinator.refresh()).acquisition == .failed(.invalidCollection))
}

@Test func futureCapturesAreRejected() async throws {
    let coordinator = try MonitorCoordinator(read: { [snapshot(at: fixedDate.addingTimeInterval(1))] }, clock: { fixedDate })
    let state = await coordinator.refresh()
    #expect(state.acquisition == .failed(.invalidCollection))
    #expect(state.sources.isEmpty)
}

@Test func storageFailureIsSeparateFromSuccessfulLiveState() async throws {
    let coordinator = try MonitorCoordinator(
        read: { [snapshot()] },
        clock: { fixedDate },
        sink: { _, _ in throw SyntheticReadError.failed }
    )
    let state = await coordinator.refresh()
    #expect(state.acquisition == .succeeded)
    #expect(state.sources.first?.freshness == .fresh)
    #expect(state.storageFailure)
}

@Test func stopCancelsAndFencesLateReaderCompletion() async throws {
    actor ReadGate {
        var continuation: CheckedContinuation<[MonitorSnapshot], Error>?
        var started = false
        func read() async throws -> [MonitorSnapshot] {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
                started = true
            }
        }
        func waitUntilStarted() async {
            while !started { await Task.yield() }
        }
        func release() { continuation?.resume(returning: [snapshot()]); continuation = nil }
    }
    let gate = ReadGate()
    let coordinator = try MonitorCoordinator(read: { try await gate.read() }, clock: { fixedDate })
    let attempt = Task { await coordinator.refresh() }
    await gate.waitUntilStarted()
    #expect((await coordinator.currentState()).isRefreshing)
    await coordinator.stop()
    await gate.release()
    _ = await attempt.value

    let stopped = await coordinator.currentState()
    #expect(stopped.acquisition == .stopped)
    #expect(stopped.sources.isEmpty)
    #expect(!stopped.isRefreshing)
}

@Test func overlappingRefreshDoesNotStartASecondRead() async throws {
    actor ReadGate {
        var continuation: CheckedContinuation<[MonitorSnapshot], Error>?
        var readCount = 0
        func read() async throws -> [MonitorSnapshot] {
            readCount += 1
            return try await withCheckedThrowingContinuation { continuation = $0 }
        }
        func release() { continuation?.resume(returning: [snapshot()]); continuation = nil }
    }
    let gate = ReadGate()
    let coordinator = try MonitorCoordinator(read: { try await gate.read() }, clock: { fixedDate })
    let first = Task { await coordinator.refresh() }
    while !(await coordinator.currentState()).isRefreshing { await Task.yield() }
    _ = await coordinator.refresh()
    #expect(await gate.readCount == 1)
    await gate.release()
    _ = await first.value
}

@Test func invalidPollingIntervalsAreRejected() {
    #expect(throws: MonitorCoordinatorConfigurationError.invalidPollInterval) {
        try MonitorCoordinator(pollInterval: 0.5, read: { [] })
    }
    #expect(throws: MonitorCoordinatorConfigurationError.invalidPollInterval) {
        try MonitorCoordinator(pollInterval: 301, read: { [] })
    }
}

@Test func refreshCancelledBeforeAdmissionDoesNotReadOrPersist() async throws {
    actor Counters {
        var reads = 0
        var writes = 0
        func read() -> [MonitorSnapshot] { reads += 1; return [snapshot()] }
        func write() { writes += 1 }
    }
    let counters = Counters()
    let coordinator = try MonitorCoordinator(
        read: { await counters.read() },
        clock: { fixedDate },
        sink: { _, _ in await counters.write() }
    )
    let cancelledAttempt = Task {
        withUnsafeCurrentTask { $0?.cancel() }
        return await coordinator.refresh()
    }
    let state = await cancelledAttempt.value

    #expect(await counters.reads == 0)
    #expect(await counters.writes == 0)
    #expect(state.sources.isEmpty)
    #expect(state.acquisition == .failed(.cancelled))
}

@Test func callerCancellationIsPropagatedToTheActiveRead() async throws {
    actor CancellationGate {
        var continuation: CheckedContinuation<[MonitorSnapshot], Error>?
        var started = false
        var cancelled = false

        func read() async throws -> [MonitorSnapshot] {
            started = true
            return try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { continuation in
                    self.continuation = continuation
                }
            } onCancel: {
                Task { await self.cancelRead() }
            }
        }

        func waitUntilStarted() async {
            while !started { await Task.yield() }
        }

        func waitForCancellation() async -> Bool {
            for _ in 0..<100 {
                if cancelled { return true }
                try? await Task.sleep(for: .milliseconds(5))
            }
            return cancelled
        }

        func release() {
            continuation?.resume(returning: [snapshot()])
            continuation = nil
        }

        private func cancelRead() {
            cancelled = true
            continuation?.resume(throwing: CancellationError())
            continuation = nil
        }
    }

    let gate = CancellationGate()
    let writeCounter = WriteCounter()
    let withSink = try MonitorCoordinator(
        read: { try await gate.read() },
        clock: { fixedDate },
        sink: { _, _ in await writeCounter.increment() }
    )
    let attempt = Task { await withSink.refresh() }
    await gate.waitUntilStarted()
    attempt.cancel()
    let propagated = await gate.waitForCancellation()
    if !propagated { await gate.release() }
    let state = await attempt.value

    #expect(propagated)
    #expect(await writeCounter.value == 0)
    #expect(state.sources.isEmpty)
    #expect(state.acquisition == .failed(.cancelled))
}

private enum SyntheticReadError: Error { case failed }

private actor WriteCounter {
    private(set) var value = 0
    func increment() { value += 1 }
}
