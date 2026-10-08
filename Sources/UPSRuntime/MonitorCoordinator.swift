import Foundation
import UPSModel

public enum MonitorRuntimeFailure: Equatable, Sendable {
    case readFailed
    case cancelled
    case invalidCollection
    case invalidClock
}

public enum MonitorAcquisitionState: Equatable, Sendable {
    case idle
    case refreshing
    case succeeded
    case noSources
    case failed(MonitorRuntimeFailure)
    case stopped
}

public struct MonitorSourceState: Equatable, Sendable {
    public let source: MonitorSource
    public let snapshot: MonitorSnapshot
    public let freshness: SnapshotFreshness

    public init(source: MonitorSource, snapshot: MonitorSnapshot, freshness: SnapshotFreshness) {
        self.source = source
        self.snapshot = snapshot
        self.freshness = freshness
    }
}

public struct MonitorCoordinatorState: Equatable, Sendable {
    public let sources: [MonitorSourceState]
    public let acquisition: MonitorAcquisitionState
    public let lastAttemptAt: Date?
    public let lastSuccessAt: Date?
    public let lastSuccessUptime: TimeInterval?
    public let maximumAge: TimeInterval
    public let isPolling: Bool
    public let isRefreshing: Bool
    public let storageFailure: Bool

    public init(
        sources: [MonitorSourceState],
        acquisition: MonitorAcquisitionState,
        lastAttemptAt: Date?,
        lastSuccessAt: Date?,
        maximumAge: TimeInterval,
        isPolling: Bool,
        isRefreshing: Bool,
        storageFailure: Bool,
        lastSuccessUptime: TimeInterval? = nil
    ) {
        self.sources = sources
        self.acquisition = acquisition
        self.lastAttemptAt = lastAttemptAt
        self.lastSuccessAt = lastSuccessAt
        self.lastSuccessUptime = lastSuccessUptime
        self.maximumAge = maximumAge
        self.isPolling = isPolling
        self.isRefreshing = isRefreshing
        self.storageFailure = storageFailure
    }
}

public enum MonitorCoordinatorConfigurationError: Error, Equatable {
    case invalidPollInterval
}

public actor MonitorCoordinator {
    public typealias Read = @Sendable () async throws -> [MonitorSnapshot]
    public typealias Clock = @Sendable () -> Date
    public typealias MonotonicClock = @Sendable () -> TimeInterval
    public typealias Sink = @Sendable (MonitorSnapshot, Date) async throws -> Void

    private let pollInterval: TimeInterval
    private let maximumAge: TimeInterval
    private let read: Read
    private let clock: Clock
    private let monotonicClock: MonotonicClock
    private let sink: Sink?
    private var generation: UInt64 = 0
    private var nextOperationID: UInt64 = 0
    private var inFlightOperationID: UInt64?
    private var activeReadTask: Task<[MonitorSnapshot], Error>?
    private var pollingTask: Task<Void, Never>?
    private var cachedSnapshots: [MonitorSnapshot] = []
    private var acquisition: MonitorAcquisitionState = .idle
    private var lastAttemptAt: Date?
    private var lastSuccessAt: Date?
    private var lastSuccessUptime: TimeInterval?
    private var cacheStale = false
    private var storageFailure = false

    public init(
        pollInterval: TimeInterval = 5,
        read: @escaping Read,
        clock: @escaping Clock = { Date() },
        monotonicClock: @escaping MonotonicClock = { ProcessInfo.processInfo.systemUptime },
        sink: Sink? = nil
    ) throws {
        guard pollInterval.isFinite, (1...300).contains(pollInterval) else {
            throw MonitorCoordinatorConfigurationError.invalidPollInterval
        }
        self.pollInterval = pollInterval
        maximumAge = pollInterval * 2
        self.read = read
        self.clock = clock
        self.monotonicClock = monotonicClock
        self.sink = sink
    }

    @discardableResult
    public func refresh() async -> MonitorCoordinatorState {
        guard inFlightOperationID == nil else { return currentState() }
        guard !Task.isCancelled else {
            acquisition = .failed(.cancelled)
            cacheStale = true
            return currentState()
        }

        nextOperationID &+= 1
        let operationID = nextOperationID
        let operationGeneration = generation
        inFlightOperationID = operationID
        acquisition = .refreshing

        let attemptTime = clock()
        if Self.isValidDate(attemptTime) {
            lastAttemptAt = attemptTime
        } else {
            finish(operationID: operationID)
            acquisition = .failed(.invalidClock)
            cacheStale = true
            return currentState()
        }

        let task = Task { try await read() }
        activeReadTask = task
        let snapshots: [MonitorSnapshot]
        do {
            snapshots = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: {
                task.cancel()
            }
        } catch is CancellationError {
            activeReadTask = nil
            finish(operationID: operationID)
            guard generation == operationGeneration else { return currentState() }
            acquisition = .failed(.cancelled)
            cacheStale = true
            return currentState()
        } catch {
            activeReadTask = nil
            finish(operationID: operationID)
            guard generation == operationGeneration else { return currentState() }
            acquisition = .failed(Task.isCancelled ? .cancelled : .readFailed)
            cacheStale = true
            return currentState()
        }
        activeReadTask = nil

        guard !Task.isCancelled else {
            finish(operationID: operationID)
            guard generation == operationGeneration else { return currentState() }
            acquisition = .failed(.cancelled)
            cacheStale = true
            return currentState()
        }
        guard generation == operationGeneration else {
            finish(operationID: operationID)
            return currentState()
        }
        let receivedUptime = monotonicClock()
        let now = clock()
        guard Self.isValidDate(now), receivedUptime.isFinite, receivedUptime >= 0 else {
            finish(operationID: operationID)
            acquisition = .failed(.invalidClock)
            cacheStale = true
            return currentState()
        }
        guard Self.isValidCollection(snapshots, now: now) else {
            finish(operationID: operationID)
            acquisition = .failed(.invalidCollection)
            cacheStale = true
            return currentState()
        }

        cachedSnapshots = snapshots.sorted(by: Self.sourceOrder)
        lastSuccessAt = now
        lastSuccessUptime = receivedUptime
        cacheStale = false
        storageFailure = false
        acquisition = snapshots.isEmpty ? .noSources : .succeeded

        if let sink {
            for snapshot in cachedSnapshots {
                guard generation == operationGeneration, !Task.isCancelled else { break }
                do {
                    try await sink(snapshot, now)
                } catch {
                    guard generation == operationGeneration else { break }
                    storageFailure = true
                }
            }
        }
        finish(operationID: operationID)
        return currentState()
    }

    public func start() {
        guard pollingTask == nil else { return }
        generation &+= 1
        let pollingGeneration = generation
        acquisition = .idle
        pollingTask = Task { [weak self] in
            await self?.poll(generation: pollingGeneration)
        }
    }

    public func stop() {
        generation &+= 1
        pollingTask?.cancel()
        pollingTask = nil
        activeReadTask?.cancel()
        cacheStale = true
        acquisition = .stopped
    }

    /// Waits for the owned read to unwind; a previously admitted sink may still finish.
    public func stopAndWait() async {
        let readTask = activeReadTask
        stop()
        _ = try? await readTask?.value
    }

    public func currentState() -> MonitorCoordinatorState {
        let now = clock()
        let acquisitionSucceeded = !cacheStale && Self.isValidDate(now)
        let sourceStates = cachedSnapshots.map { snapshot in
            MonitorSourceState(
                source: snapshot.source,
                snapshot: snapshot,
                freshness: evaluateFreshness(
                    snapshot: snapshot,
                    now: now,
                    maximumAge: maximumAge,
                    acquisitionSucceeded: acquisitionSucceeded
                )
            )
        }
        return MonitorCoordinatorState(
            sources: sourceStates,
            acquisition: acquisition,
            lastAttemptAt: lastAttemptAt,
            lastSuccessAt: lastSuccessAt,
            maximumAge: maximumAge,
            isPolling: pollingTask != nil,
            isRefreshing: inFlightOperationID != nil,
            storageFailure: storageFailure,
            lastSuccessUptime: lastSuccessUptime
        )
    }

    private func poll(generation pollingGeneration: UInt64) async {
        while !Task.isCancelled, generation == pollingGeneration {
            await refresh()
            do {
                try await Task.sleep(for: .seconds(pollInterval))
            } catch {
                break
            }
        }
    }

    private func finish(operationID: UInt64) {
        guard inFlightOperationID == operationID else { return }
        inFlightOperationID = nil
        activeReadTask = nil
    }

    private static func isValidCollection(_ snapshots: [MonitorSnapshot], now: Date) -> Bool {
        var seen = Set<SourceIdentityKey>()
        for snapshot in snapshots {
            do { try snapshot.validate() } catch { return false }
            let key = SourceIdentityKey(
                provider: snapshot.source.provider.rawValue,
                id: snapshot.source.id,
                sessionID: snapshot.source.sessionID
            )
            guard snapshot.capturedAt <= now, seen.insert(key).inserted else { return false }
        }
        return true
    }

    private static func isValidDate(_ date: Date) -> Bool {
        date.timeIntervalSince1970.isFinite
    }

    private static func sourceOrder(_ lhs: MonitorSnapshot, _ rhs: MonitorSnapshot) -> Bool {
        let left = "\(lhs.source.provider.rawValue)|\(lhs.source.id)|\(lhs.source.sessionID)"
        let right = "\(rhs.source.provider.rawValue)|\(rhs.source.id)|\(rhs.source.sessionID)"
        return left < right
    }
}

private struct SourceIdentityKey: Hashable {
    let provider: String
    let id: String
    let sessionID: String
}
