import Foundation
import UPSWidgetData

public enum WidgetPublicationResult: Equatable, Sendable {
    case shared, unchanged, rejected, unavailable
}

public actor WidgetSnapshotPublisher {
    private struct Publication: Sendable {
        let value: WidgetSnapshot
        let now: Date
        let uptime: TimeInterval
    }

    private let store: WidgetSnapshotStore
    private let reload: @Sendable () async -> Void
    private var pending: Publication?
    private var inFlight: Task<Void, Never>?
    private var lastSequence: UInt64?
    private var lastShared: WidgetSnapshot?
    private var lastReloadUptime: TimeInterval?
    private var lastReloadSnapshot: WidgetSnapshot?
    private var result: WidgetPublicationResult = .unchanged

    public init(store: WidgetSnapshotStore, reload: @escaping @Sendable () async -> Void) {
        self.store = store
        self.reload = reload
    }

    public func publish(_ value: WidgetSnapshot, now: Date, uptime: TimeInterval,
                        sequence: UInt64) async -> WidgetPublicationResult {
        guard now.timeIntervalSince1970.isFinite, value.publishedAt <= now,
              uptime.isFinite, uptime >= 0, (try? value.validate()) != nil,
              lastSequence.map({ sequence > $0 }) ?? true else { return .rejected }
        lastSequence = sequence
        if inFlight == nil, let lastShared, Self.sameContent(value, lastShared) { return .unchanged }
        pending = Publication(value: value, now: now, uptime: uptime)
        if inFlight == nil { inFlight = Task { await self.drain() } }
        await inFlight?.value
        return result
    }

    private func drain() async {
        // One writer drains the latest pending value; memory is bounded even during slow I/O.
        while let publication = pending {
            pending = nil
            do {
                try await store.write(publication.value, now: publication.now)
                lastShared = publication.value
                result = .shared
                if shouldReload(publication) {
                    lastReloadUptime = publication.uptime
                    lastReloadSnapshot = publication.value
                    await reload()
                }
            } catch { result = .unavailable }
        }
        inFlight = nil
    }

    private func shouldReload(_ publication: Publication) -> Bool {
        guard let previous = lastReloadUptime else { return true }
        let elapsed = publication.uptime - previous
        guard elapsed >= 0 else { return false }
        let changedState = publication.value.acquisition != lastReloadSnapshot?.acquisition
            || publication.value.snapshot?.source != lastReloadSnapshot?.snapshot?.source
            || publication.value.snapshot?.status != lastReloadSnapshot?.snapshot?.status
        return elapsed >= 300 || (changedState && elapsed >= 30)
    }

    private static func sameContent(_ lhs: WidgetSnapshot, _ rhs: WidgetSnapshot) -> Bool {
        lhs.acquisition == rhs.acquisition && lhs.maximumAge == rhs.maximumAge && lhs.snapshot == rhs.snapshot
    }
}
