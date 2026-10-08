import Foundation
import UPSModel

public struct HistoryRetention: Sendable {
    public let maximumAge: TimeInterval
    public let maximumRows: Int

    public static let standard = HistoryRetention(uncheckedMaximumAge: 90 * 24 * 60 * 60, maximumRows: 100_000)

    private init(uncheckedMaximumAge maximumAge: TimeInterval, maximumRows: Int) {
        self.maximumAge = maximumAge
        self.maximumRows = maximumRows
    }

    public init(maximumAge: TimeInterval = 90 * 24 * 60 * 60, maximumRows: Int = 100_000) throws {
        guard maximumAge.isFinite, maximumAge > 0, maximumRows > 0 else {
            throw HistoryError.invalidRequest
        }
        self.maximumAge = maximumAge
        self.maximumRows = maximumRows
    }
}

public struct HistoryQuery: Sendable {
    public let start: Date
    public let end: Date
    public let source: MonitorSource
    public let limit: Int

    public init(start: Date, end: Date, source: MonitorSource, limit: Int = 10_000) throws {
        guard start.timeIntervalSince1970.isFinite, end.timeIntervalSince1970.isFinite,
              start <= end, limit > 0, limit <= 10_000 else {
            throw HistoryError.invalidRequest
        }
        self.start = start
        self.end = end
        self.source = source
        self.limit = limit
    }
}

public struct HistorySessionSummary: Equatable, Sendable {
    public let source: MonitorSource
    public let firstCapturedAt: Date
    public let lastCapturedAt: Date
    public let sampleCount: Int

    public init(source: MonitorSource, firstCapturedAt: Date, lastCapturedAt: Date, sampleCount: Int) {
        self.source = source
        self.firstCapturedAt = firstCapturedAt
        self.lastCapturedAt = lastCapturedAt
        self.sampleCount = sampleCount
    }
}

public struct HistorySessionList: Equatable, Sendable {
    public let sessions: [HistorySessionSummary]
    public let hasMore: Bool

    public init(sessions: [HistorySessionSummary], hasMore: Bool) {
        self.sessions = sessions
        self.hasMore = hasMore
    }
}

public struct HistoryPage: Equatable, Sendable {
    public let records: [MonitorSnapshot]
    public let hasMore: Bool
    public let nextAfter: Date?

    public init(records: [MonitorSnapshot], hasMore: Bool, nextAfter: Date?) {
        self.records = records
        self.hasMore = hasMore
        self.nextAfter = nextAfter
    }
}

public enum HistoryError: Error, Equatable {
    case invalidRequest
    case unsafeLocation
    case databaseUnavailable
    case unsupportedDatabase
    case incompatibleSchema
    case invalidSnapshot
    case outsideRetentionWindow
    case corruptRecord
    case conflictingSample
}

public enum HistoryExportFormat: Sendable {
    case json
    case csv
}
