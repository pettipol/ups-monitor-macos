import AppKit
import Foundation
import Observation
import UniformTypeIdentifiers
import UPSHistory
import UPSModel

enum HistoryBrowserRange: String, CaseIterable {
    case hour = "Hour", day = "Day", week = "Week", session = "Session"
    var duration: TimeInterval? {
        switch self {
        case .hour: 3_600
        case .day: 86_400
        case .week: 604_800
        case .session: nil
        }
    }
}

@Observable
@MainActor
final class HistoryBrowserModel: Identifiable {
    let id = UUID()
    private(set) var sessions: [HistorySessionSummary] = []
    private(set) var sessionsTruncated = false
    private(set) var selectedKey: String?
    private(set) var range: HistoryBrowserRange = .hour
    var metric: MonitorMetricID = .batteryCharge
    private(set) var page: HistoryPage?
    private(set) var pageNumber = 1
    private(set) var isLoading = false
    private(set) var errorMessage: String?
    @ObservationIgnored private let store: UPSHistoryStore
    @ObservationIgnored private let pageSize: Int
    @ObservationIgnored private let onMutation: @MainActor @Sendable () async -> Void
    @ObservationIgnored private var cursors: [Date?] = [nil]
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var closed = false

    init(store: UPSHistoryStore, pageSize: Int = 2_000,
         onMutation: @escaping @MainActor @Sendable () async -> Void = {}) {
        self.store = store
        self.pageSize = min(max(pageSize, 1), 10_000)
        self.onMutation = onMutation
    }

    var selectedSession: HistorySessionSummary? { sessions.first { Self.key($0.source) == selectedKey } }
    var canExport: Bool { !closed && !isLoading && !(page?.records.isEmpty ?? true) }
    var canGoBack: Bool { !closed && !isLoading && page != nil && cursors.count > 1 }
    var canGoForward: Bool { !closed && !isLoading && page?.hasMore == true }

    static func key(_ source: MonitorSource) -> String {
        "\(source.provider.rawValue)|\(source.id)|\(source.sessionID)"
    }

    func refresh() async {
        guard !closed else { return }
        let token = beginRequest()
        defer { finishRequest(token) }
        do {
            let catalog = try await store.sessions()
            guard isCurrent(token) else { return }
            sessions = catalog.sessions
            sessionsTruncated = catalog.hasMore
            if selectedSession == nil { selectedKey = sessions.first.map { Self.key($0.source) } }
            await load(cursors: [nil])
        } catch {
            guard isCurrent(token) else { return }
            errorMessage = "History unavailable"
        }
    }

    func selectSession(_ key: String) async {
        guard !closed, sessions.contains(where: { Self.key($0.source) == key }) else { return }
        selectedKey = key
        await load(cursors: [nil])
    }

    func selectRange(_ value: HistoryBrowserRange) async {
        guard !closed else { return }
        range = value
        await load(cursors: [nil])
    }

    func nextPage() async {
        guard canGoForward, let next = page?.nextAfter else { return }
        await load(cursors: cursors + [next])
    }

    func previousPage() async {
        guard canGoBack else { return }
        await load(cursors: Array(cursors.dropLast()))
    }

    func exportData(_ format: HistoryExportFormat) throws -> Data {
        guard canExport, let page else { throw HistoryError.invalidRequest }
        return try UPSHistoryStore.encodeExport(page.records, format: format)
    }

    func export(_ format: HistoryExportFormat) {
        guard canExport else { return }
        do {
            let data = try exportData(format)
            let panel = NSSavePanel()
            panel.allowedContentTypes = format == .json ? [.json] : [.commaSeparatedText]
            panel.nameFieldStringValue = format == .json ? "ups-history-page.json" : "ups-history-page.csv"
            panel.title = "Export Displayed History Page"
            guard panel.runModal() == .OK, !closed, let url = panel.url else { return }
            try data.write(to: url, options: .atomic)
        } catch { if !closed { errorMessage = "Page export unavailable" } }
    }

    func deleteSelectedSession() async {
        guard !closed, !isLoading, let source = selectedSession?.source else { return }
        await mutate { try await self.store.delete(source: source) }
    }

    func clearAllHistory() async {
        guard !closed, !isLoading else { return }
        await mutate { try await self.store.clear() }
    }

    func close() {
        closed = true
        generation += 1
        isLoading = false
    }

    private func load(cursors proposedCursors: [Date?]) async {
        guard !closed else { return }
        let token = beginRequest()
        defer { finishRequest(token) }
        pageNumber = proposedCursors.count
        guard let session = selectedSession else { cursors = [nil]; return }
        do {
            let start = range.duration.map { session.lastCapturedAt.addingTimeInterval(-$0) }
                ?? session.firstCapturedAt.addingTimeInterval(-1)
            let query = try HistoryQuery(start: start, end: session.lastCapturedAt, source: session.source, limit: pageSize)
            let result = try await store.queryPage(query, after: proposedCursors.last ?? nil)
            guard isCurrent(token) else { return }
            page = result
            cursors = proposedCursors
        } catch {
            guard isCurrent(token) else { return }
            errorMessage = "History page unavailable"
        }
    }

    private func mutate(_ operation: () async throws -> Int) async {
        let token = beginRequest()
        defer { finishRequest(token) }
        do {
            _ = try await operation()
            await onMutation()
            guard isCurrent(token) else { return }
            await refresh()
        } catch {
            guard isCurrent(token) else { return }
            errorMessage = "History deletion unavailable"
        }
    }

    private func beginRequest() -> Int {
        generation += 1
        isLoading = true
        page = nil
        errorMessage = nil
        return generation
    }
    private func isCurrent(_ token: Int) -> Bool { !closed && generation == token }
    private func finishRequest(_ token: Int) { if isCurrent(token) { isLoading = false } }
}
