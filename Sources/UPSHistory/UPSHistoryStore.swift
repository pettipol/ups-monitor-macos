import Foundation
import Darwin
import SQLite3
import UPSModel

private let sqliteTransient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

public actor UPSHistoryStore {
    private static let applicationID: Int32 = 0x55505348
    private static let schemaVersion: Int32 = 1
    private static let databaseName = "history.sqlite3"
    private static let maximumPayloadBytes = 64 * 1024
    private let retention: HistoryRetention
    private nonisolated(unsafe) var database: OpaquePointer?
    private let encoder: JSONEncoder

    public init(directoryURL: URL, retention: HistoryRetention = .standard) throws {
        self.retention = retention
        self.encoder = Self.makeEncoder()
        guard directoryURL.isFileURL else { throw HistoryError.unsafeLocation }
        let requestedDirectory = directoryURL.standardizedFileURL
        try Self.prepareDirectory(requestedDirectory)
        guard let resolvedDirectory = realpath(requestedDirectory.path, nil) else { throw HistoryError.unsafeLocation }
        defer { free(resolvedDirectory) }
        let directory = URL(fileURLWithPath: String(cString: resolvedDirectory), isDirectory: true)
        let databaseURL = directory.appendingPathComponent(Self.databaseName, isDirectory: false)
        guard databaseURL.isFileURL else { throw HistoryError.unsafeLocation }
        let path = databaseURL.path
        let wasCreated = try Self.prepareDatabaseFile(databaseURL)
        var handle: OpaquePointer?
        let flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX | SQLITE_OPEN_NOFOLLOW
        guard sqlite3_open_v2(path, &handle, flags, nil) == SQLITE_OK, let handle else {
            if let handle { sqlite3_close(handle) }
            throw HistoryError.databaseUnavailable
        }
        self.database = handle
        sqlite3_busy_timeout(handle, 1_000)

        do {
            if wasCreated {
                try Self.initializeSchema(handle)
            } else {
                try Self.validateExistingSchema(handle)
            }
            try Self.configureDatabase(handle)
        } catch {
            sqlite3_close(handle)
            self.database = nil
            throw error
        }
    }

    deinit {
        if let database { sqlite3_close(database) }
    }

    public func close() throws {
        guard let database else { return }
        guard sqlite3_close(database) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
        self.database = nil
    }

    public func append(_ snapshot: MonitorSnapshot, now: Date = Date()) throws {
        guard let database else { throw HistoryError.databaseUnavailable }
        do { try snapshot.validate() } catch { throw HistoryError.invalidSnapshot }
        let payload: Data
        do { payload = try encoder.encode(snapshot) } catch { throw HistoryError.invalidSnapshot }
        guard payload.count <= Self.maximumPayloadBytes else { throw HistoryError.invalidSnapshot }
        guard let capturedMicros = Self.microseconds(snapshot.capturedAt) else { throw HistoryError.invalidSnapshot }
        let cutoff = try Self.retentionCutoff(now: now, maximumAge: retention.maximumAge)
        guard let nowMicros = Self.microseconds(now) else { throw HistoryError.invalidRequest }
        guard capturedMicros <= nowMicros else { throw HistoryError.invalidSnapshot }
        guard capturedMicros >= cutoff else { throw HistoryError.outsideRetentionWindow }

        try Self.execute(database, "BEGIN IMMEDIATE")
        do {
            var inserted = false
            do {
                let statement = try Self.prepare(database, sql: "INSERT OR IGNORE INTO samples(provider, source_id, session_id, captured_us, payload) VALUES(?, ?, ?, ?, ?)")
                defer { sqlite3_finalize(statement) }
                try Self.bind(text: snapshot.source.provider.rawValue, at: 1, to: statement)
                try Self.bind(text: snapshot.source.id, at: 2, to: statement)
                try Self.bind(text: snapshot.source.sessionID, at: 3, to: statement)
                guard sqlite3_bind_int64(statement, 4, capturedMicros) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
                let bindResult = payload.withUnsafeBytes { bytes in
                    sqlite3_bind_blob(statement, 5, bytes.baseAddress, Int32(payload.count), sqliteTransient)
                }
                guard bindResult == SQLITE_OK else { throw HistoryError.databaseUnavailable }
                let stepResult = sqlite3_step(statement)
                inserted = sqlite3_changes(database) == 1
                guard stepResult == SQLITE_DONE else { throw HistoryError.databaseUnavailable }
            }
            if !inserted {
                let existing = try Self.existingSnapshot(database, provider: snapshot.source.provider.rawValue,
                                                         id: snapshot.source.id, sessionID: snapshot.source.sessionID,
                                                         capturedMicros: capturedMicros)
                guard existing == snapshot else { throw HistoryError.conflictingSample }
            }
            _ = try applyRetention(database, cutoff: cutoff)
            try Self.execute(database, "COMMIT")
        } catch {
            try? Self.execute(database, "ROLLBACK")
            throw error
        }
    }

    @discardableResult
    public func prune(now: Date = Date()) throws -> Int {
        guard let database else { throw HistoryError.databaseUnavailable }
        let cutoff = try Self.retentionCutoff(now: now, maximumAge: retention.maximumAge)
        try Self.execute(database, "BEGIN IMMEDIATE")
        do {
            let removed = try applyRetention(database, cutoff: cutoff)
            try Self.execute(database, "COMMIT")
            return removed
        } catch {
            try? Self.execute(database, "ROLLBACK")
            throw error
        }
    }

    public func query(_ query: HistoryQuery) throws -> [MonitorSnapshot] {
        guard let database else { throw HistoryError.databaseUnavailable }
        do { try query.source.validate() } catch { throw HistoryError.invalidRequest }
        let statement = try Self.prepare(database, sql: "SELECT provider, source_id, session_id, captured_us, payload FROM samples WHERE provider=? AND source_id=? AND session_id=? AND captured_us>=? AND captured_us<=? ORDER BY captured_us ASC, rowid ASC LIMIT ?")
        defer { sqlite3_finalize(statement) }
        try Self.bind(text: query.source.provider.rawValue, at: 1, to: statement)
        try Self.bind(text: query.source.id, at: 2, to: statement)
        try Self.bind(text: query.source.sessionID, at: 3, to: statement)
        guard let start = Self.microseconds(query.start), let end = Self.microseconds(query.end) else {
            throw HistoryError.invalidRequest
        }
        sqlite3_bind_int64(statement, 4, start)
        sqlite3_bind_int64(statement, 5, end)
        sqlite3_bind_int64(statement, 6, Int64(query.limit))
        var records: [MonitorSnapshot] = []
        while true {
            let result = sqlite3_step(statement)
            if result == SQLITE_DONE { break }
            guard result == SQLITE_ROW else { throw HistoryError.databaseUnavailable }
            records.append(try Self.decodeRecord(statement, decoder: Self.decoder()))
        }
        return records
    }

    public func sessions(limit: Int = 100) throws -> HistorySessionList {
        guard let database else { throw HistoryError.databaseUnavailable }
        guard (1...500).contains(limit) else { throw HistoryError.invalidRequest }
        let sql = "SELECT provider, source_id, session_id, MIN(captured_us), MAX(captured_us), COUNT(*) FROM samples GROUP BY provider, source_id, session_id ORDER BY MAX(captured_us) DESC, provider ASC, source_id ASC, session_id ASC LIMIT ?"
        let statement = try Self.prepare(database, sql: sql)
        defer { sqlite3_finalize(statement) }
        guard sqlite3_bind_int64(statement, 1, Int64(limit + 1)) == SQLITE_OK else {
            throw HistoryError.databaseUnavailable
        }

        var summaries: [HistorySessionSummary] = []
        var hasMore = false
        while true {
            let result = sqlite3_step(statement)
            if result == SQLITE_DONE { break }
            guard result == SQLITE_ROW else { throw HistoryError.databaseUnavailable }
            guard let provider = Self.columnText(statement, 0), let id = Self.columnText(statement, 1),
                  let sessionID = Self.columnText(statement, 2) else { throw HistoryError.corruptRecord }
            let firstMicros = sqlite3_column_int64(statement, 3)
            let lastMicros = sqlite3_column_int64(statement, 4)
            let count = sqlite3_column_int64(statement, 5)
            guard count > 0, count <= Int64(Int.max), Self.date(fromMicroseconds: firstMicros) != nil else {
                throw HistoryError.corruptRecord
            }
            let representative = try Self.sessionRepresentative(
                database, provider: provider, id: id, sessionID: sessionID, capturedMicros: lastMicros
            )
            let firstRepresentative: MonitorSnapshot
            if firstMicros == lastMicros {
                firstRepresentative = representative
            } else {
                firstRepresentative = try Self.sessionRepresentative(
                    database, provider: provider, id: id, sessionID: sessionID, capturedMicros: firstMicros
                )
            }
            let summary = HistorySessionSummary(source: representative.source, firstCapturedAt: firstRepresentative.capturedAt,
                                                lastCapturedAt: representative.capturedAt,
                                                sampleCount: Int(count))
            if summaries.count == limit {
                hasMore = true
                break
            }
            summaries.append(summary)
        }
        return HistorySessionList(sessions: summaries, hasMore: hasMore)
    }

    public func queryPage(_ query: HistoryQuery, after: Date? = nil) throws -> HistoryPage {
        guard let database else { throw HistoryError.databaseUnavailable }
        do { try query.source.validate() } catch { throw HistoryError.invalidRequest }
        guard let start = Self.microseconds(query.start), let end = Self.microseconds(query.end), start <= end else {
            throw HistoryError.invalidRequest
        }
        let afterMicros: Int64?
        if let after {
            guard after.timeIntervalSince1970.isFinite, after >= query.start, after <= query.end,
                  let value = Self.microseconds(after) else { throw HistoryError.invalidRequest }
            afterMicros = value
        } else {
            afterMicros = nil
        }

        let sql: String
        if afterMicros == nil {
            sql = "SELECT provider, source_id, session_id, captured_us, payload FROM samples WHERE provider=? AND source_id=? AND session_id=? AND captured_us>=? AND captured_us<=? ORDER BY captured_us ASC LIMIT ?"
        } else {
            sql = "SELECT provider, source_id, session_id, captured_us, payload FROM samples WHERE provider=? AND source_id=? AND session_id=? AND captured_us>=? AND captured_us<=? AND captured_us>? ORDER BY captured_us ASC LIMIT ?"
        }
        let statement = try Self.prepare(database, sql: sql)
        defer { sqlite3_finalize(statement) }
        try Self.bind(text: query.source.provider.rawValue, at: 1, to: statement)
        try Self.bind(text: query.source.id, at: 2, to: statement)
        try Self.bind(text: query.source.sessionID, at: 3, to: statement)
        guard sqlite3_bind_int64(statement, 4, start) == SQLITE_OK,
              sqlite3_bind_int64(statement, 5, end) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
        let limitIndex: Int32
        if let afterMicros {
            guard sqlite3_bind_int64(statement, 6, afterMicros) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
            limitIndex = 7
        } else {
            limitIndex = 6
        }
        guard sqlite3_bind_int64(statement, limitIndex, Int64(query.limit + 1)) == SQLITE_OK else {
            throw HistoryError.databaseUnavailable
        }

        var records: [MonitorSnapshot] = []
        var hasMore = false
        while true {
            let result = sqlite3_step(statement)
            if result == SQLITE_DONE { break }
            guard result == SQLITE_ROW else { throw HistoryError.databaseUnavailable }
            let snapshot = try Self.decodeRecord(statement, decoder: Self.decoder())
            if records.count == query.limit {
                hasMore = true
                break
            }
            records.append(snapshot)
        }
        return HistoryPage(records: records, hasMore: hasMore, nextAfter: hasMore ? records.last?.capturedAt : nil)
    }

    public func export(_ query: HistoryQuery, format: HistoryExportFormat) throws -> Data {
        let records = try self.query(query)
        return try Self.encodeExport(records, format: format)
    }

    public static func encodeExport(_ records: [MonitorSnapshot], format: HistoryExportFormat) throws -> Data {
        guard records.count <= 10_000 else { throw HistoryError.invalidRequest }
        do {
            for record in records { try record.validate() }
        } catch {
            throw HistoryError.invalidSnapshot
        }
        switch format {
        case .json:
            do { return try makeEncoder().encode(records) } catch { throw HistoryError.invalidSnapshot }
        case .csv:
            return Data(Self.csv(records).utf8)
        }
    }

    @discardableResult
    public func delete(source: MonitorSource) throws -> Int {
        guard let database else { throw HistoryError.databaseUnavailable }
        do { try source.validate() } catch { throw HistoryError.invalidRequest }
        let statement = try Self.prepare(database, sql: "DELETE FROM samples WHERE provider=? AND source_id=? AND session_id=?")
        defer { sqlite3_finalize(statement) }
        try Self.bind(text: source.provider.rawValue, at: 1, to: statement)
        try Self.bind(text: source.id, at: 2, to: statement)
        try Self.bind(text: source.sessionID, at: 3, to: statement)
        guard sqlite3_step(statement) == SQLITE_DONE else { throw HistoryError.databaseUnavailable }
        return Int(sqlite3_changes(database))
    }

    @discardableResult
    public func clear() throws -> Int {
        guard let database else { throw HistoryError.databaseUnavailable }
        let statement = try Self.prepare(database, sql: "DELETE FROM samples")
        defer { sqlite3_finalize(statement) }
        guard sqlite3_step(statement) == SQLITE_DONE else { throw HistoryError.databaseUnavailable }
        return Int(sqlite3_changes(database))
    }

    private func applyRetention(_ database: OpaquePointer, cutoff: Int64) throws -> Int {
        let ageDelete = try Self.prepare(database, sql: "DELETE FROM samples WHERE captured_us < ?")
        defer { sqlite3_finalize(ageDelete) }
        guard sqlite3_bind_int64(ageDelete, 1, cutoff) == SQLITE_OK,
              sqlite3_step(ageDelete) == SQLITE_DONE else {
            throw HistoryError.databaseUnavailable
        }
        let ageRemoved = Int(sqlite3_changes(database))
        let countDelete = try Self.prepare(database, sql: "DELETE FROM samples WHERE rowid IN (SELECT rowid FROM samples ORDER BY captured_us DESC, rowid DESC LIMIT -1 OFFSET ?)")
        defer { sqlite3_finalize(countDelete) }
        guard sqlite3_bind_int64(countDelete, 1, Int64(retention.maximumRows)) == SQLITE_OK,
              sqlite3_step(countDelete) == SQLITE_DONE else {
            throw HistoryError.databaseUnavailable
        }
        let countRemoved = Int(sqlite3_changes(database))
        return ageRemoved + countRemoved
    }

    private static func decodeRecord(_ statement: OpaquePointer, decoder: JSONDecoder) throws -> MonitorSnapshot {
        guard let providerText = Self.columnText(statement, 0), let id = Self.columnText(statement, 1),
              let sessionID = Self.columnText(statement, 2) else { throw HistoryError.corruptRecord }
        let indexedTime = sqlite3_column_int64(statement, 3)
        let count = Int(sqlite3_column_bytes(statement, 4))
        guard count > 0, count <= Self.maximumPayloadBytes,
              let blob = sqlite3_column_blob(statement, 4) else { throw HistoryError.corruptRecord }
        let data = Data(bytes: blob, count: count)
        let snapshot: MonitorSnapshot
        do {
            snapshot = try decoder.decode(MonitorSnapshot.self, from: data)
            try snapshot.validate()
        } catch { throw HistoryError.corruptRecord }
        guard snapshot.source.provider.rawValue == providerText, snapshot.source.id == id,
              snapshot.source.sessionID == sessionID, Self.microseconds(snapshot.capturedAt) == indexedTime else {
            throw HistoryError.corruptRecord
        }
        return snapshot
    }

    private static func sessionRepresentative(_ database: OpaquePointer, provider: String, id: String,
                                              sessionID: String, capturedMicros: Int64) throws -> MonitorSnapshot {
        let statement = try prepare(database, sql: "SELECT provider, source_id, session_id, captured_us, payload FROM samples WHERE provider=? AND source_id=? AND session_id=? AND captured_us=?")
        defer { sqlite3_finalize(statement) }
        try bind(text: provider, at: 1, to: statement)
        try bind(text: id, at: 2, to: statement)
        try bind(text: sessionID, at: 3, to: statement)
        guard sqlite3_bind_int64(statement, 4, capturedMicros) == SQLITE_OK,
              sqlite3_step(statement) == SQLITE_ROW else { throw HistoryError.corruptRecord }
        return try decodeRecord(statement, decoder: decoder())
    }

    private static func prepareDirectory(_ url: URL) throws {
        var info = stat()
        if lstat(url.path, &info) != 0 {
            guard errno == ENOENT else { throw HistoryError.unsafeLocation }
            do {
                try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true,
                                                        attributes: [.posixPermissions: 0o700])
            } catch { throw HistoryError.unsafeLocation }
            guard lstat(url.path, &info) == 0 else { throw HistoryError.unsafeLocation }
        }
        guard (info.st_mode & S_IFMT) == S_IFDIR, (info.st_mode & 0o777) == 0o700,
              info.st_uid == getuid() else {
            throw HistoryError.unsafeLocation
        }
    }

    private static func prepareDatabaseFile(_ url: URL) throws -> Bool {
        guard url.isFileURL else { throw HistoryError.unsafeLocation }
        let path = url.path
        let descriptor = open(path, O_CREAT | O_EXCL | O_RDWR | O_NOFOLLOW, mode_t(0o600))
        if descriptor >= 0 {
            let permissionResult = fchmod(descriptor, mode_t(0o600))
            var createdInfo = stat()
            let statResult = fstat(descriptor, &createdInfo)
            let closeResult = Darwin.close(descriptor)
            guard permissionResult == 0, statResult == 0, closeResult == 0,
                  (createdInfo.st_mode & S_IFMT) == S_IFREG, (createdInfo.st_mode & 0o777) == 0o600,
                  createdInfo.st_uid == getuid(), createdInfo.st_nlink == 1 else {
                throw HistoryError.unsafeLocation
            }
            return true
        }
        guard errno == EEXIST else { throw HistoryError.unsafeLocation }
        var info = stat()
        guard lstat(path, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              (info.st_mode & 0o777) == 0o600, info.st_uid == getuid(), info.st_nlink == 1 else {
            throw HistoryError.unsafeLocation
        }
        try validateReadOnlyDatabase(path)
        return false
    }

    private static func validateReadOnlyDatabase(_ path: String) throws {
        var handle: OpaquePointer?
        guard sqlite3_open_v2(path, &handle, SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX | SQLITE_OPEN_NOFOLLOW, nil) == SQLITE_OK,
              let handle else {
            if let handle { sqlite3_close(handle) }
            throw HistoryError.unsupportedDatabase
        }
        defer { sqlite3_close(handle) }
        try setTrustedSchemaOff(handle)
        let appID = try pragmaInt(handle, "PRAGMA application_id")
        let version = try pragmaInt(handle, "PRAGMA user_version")
        guard appID == applicationID else { throw HistoryError.unsupportedDatabase }
        guard version == schemaVersion else { throw HistoryError.incompatibleSchema }
        try verifySchema(handle)
    }

    private static func initializeSchema(_ database: OpaquePointer) throws {
        try execute(database, "BEGIN IMMEDIATE")
        do {
            try execute(database, "CREATE TABLE samples (provider TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL, captured_us INTEGER NOT NULL, payload BLOB NOT NULL, UNIQUE(provider, source_id, session_id, captured_us))")
            try execute(database, "CREATE INDEX samples_time_idx ON samples(captured_us)")
            try execute(database, "PRAGMA application_id=1431327560")
            try execute(database, "PRAGMA user_version=1")
            try execute(database, "COMMIT")
        } catch {
            try? execute(database, "ROLLBACK")
            throw HistoryError.databaseUnavailable
        }
    }

    private static func validateExistingSchema(_ database: OpaquePointer) throws {
        let appID = try pragmaInt(database, "PRAGMA application_id")
        let version = try pragmaInt(database, "PRAGMA user_version")
        guard appID == applicationID else { throw HistoryError.unsupportedDatabase }
        guard version == schemaVersion else { throw HistoryError.incompatibleSchema }
        try verifySchema(database)
    }

    private static func verifySchema(_ database: OpaquePointer) throws {
        let expected: Set<String> = [
            "index|samples_time_idx|samples|CREATE INDEX samples_time_idx ON samples(captured_us)",
            "index|sqlite_autoindex_samples_1|samples|",
            "table|samples|samples|CREATE TABLE samples (provider TEXT NOT NULL, source_id TEXT NOT NULL, session_id TEXT NOT NULL, captured_us INTEGER NOT NULL, payload BLOB NOT NULL, UNIQUE(provider, source_id, session_id, captured_us))",
        ]
        let statement = try prepare(database, sql: "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master")
        defer { sqlite3_finalize(statement) }
        var found = Set<String>()
        while true {
            let result = sqlite3_step(statement)
            if result == SQLITE_DONE { break }
            guard result == SQLITE_ROW,
                  let type = columnText(statement, 0), let name = columnText(statement, 1),
                  let tableName = columnText(statement, 2), let sql = columnText(statement, 3) else {
                throw HistoryError.incompatibleSchema
            }
            found.insert("\(type)|\(name)|\(tableName)|\(sql)")
        }
        guard found == expected else { throw HistoryError.incompatibleSchema }
    }

    private static func configureDatabase(_ database: OpaquePointer) throws {
        guard try pragmaText(database, "PRAGMA journal_mode=DELETE").lowercased() == "delete" else {
            throw HistoryError.databaseUnavailable
        }
        try execute(database, "PRAGMA synchronous=FULL")
        guard try pragmaInt(database, "PRAGMA synchronous") == 2 else { throw HistoryError.databaseUnavailable }
        try execute(database, "PRAGMA secure_delete=ON")
        guard try pragmaInt(database, "PRAGMA secure_delete") == 1 else { throw HistoryError.databaseUnavailable }
        try setTrustedSchemaOff(database)
    }

    private static func setTrustedSchemaOff(_ database: OpaquePointer) throws {
        try execute(database, "PRAGMA trusted_schema=OFF")
        guard try pragmaInt(database, "PRAGMA trusted_schema") == 0 else { throw HistoryError.databaseUnavailable }
    }

    private static func csv(_ snapshots: [MonitorSnapshot]) -> String {
        var rows = ["captured_at,captured_at_reference_seconds,provider,source_id,session_id,identity_stability,record_type,field,value,unit,quality,provenance"]
        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        for snapshot in snapshots {
            let date = dateFormatter.string(from: snapshot.capturedAt)
            let referenceSeconds = String(snapshot.capturedAt.timeIntervalSinceReferenceDate)
            let sharedFields = [snapshot.source.provider.rawValue, snapshot.source.id, snapshot.source.sessionID,
                                snapshot.source.identityStability.rawValue]
            rows.append(csvRow(date: date, referenceSeconds: referenceSeconds,
                               fields: sharedFields + ["status", "line_state", snapshot.status.lineState.rawValue,
                                                       "", snapshot.status.quality.rawValue, ""]))
            rows.append(csvRow(date: date, referenceSeconds: referenceSeconds,
                               fields: sharedFields + ["status", "quality", snapshot.status.quality.rawValue,
                                                       "", snapshot.status.quality.rawValue, ""]))
            let statusValues: [(String, String?)] = [
                ("internal_failure", snapshot.status.internalFailure.map(String.init)),
                ("battery_health", snapshot.status.batteryHealth?.rawValue),
                ("is_charging", snapshot.status.isCharging.map(String.init)),
            ]
            for (field, value) in statusValues {
                rows.append(csvRow(date: date, referenceSeconds: referenceSeconds,
                                   fields: sharedFields + ["status", field, value ?? "", "", "", ""]))
            }
            for flag in snapshot.status.flags.sorted(by: { $0.rawValue < $1.rawValue }) {
                rows.append(csvRow(date: date, referenceSeconds: referenceSeconds,
                                   fields: sharedFields + ["status_flag", flag.rawValue, "", "", "", ""]))
            }
            for metric in snapshot.metrics {
                let textFields = sharedFields + ["metric", metric.id.rawValue]
                let numeric = csvNumericCell(metric.value.map { String($0) } ?? "")
                let trailingFields = [metric.unit.rawValue, metric.quality.rawValue, metric.provenance.rawValue]
                let row = [csvCell(date), csvNumericCell(referenceSeconds)] + textFields.map(csvCell) + [numeric] + trailingFields.map(csvCell)
                rows.append(row.joined(separator: ","))
            }
        }
        return rows.joined(separator: "\n") + "\n"
    }

    private static func csvCell(_ value: String) -> String {
        let safe = value.first.map { "=+-@\t\r".contains($0) } ?? false
        let prefixed = safe ? "'" + value : value
        return "\"" + prefixed.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }

    private static func csvRow(date: String, referenceSeconds: String, fields: [String]) -> String {
        ([csvCell(date), csvNumericCell(referenceSeconds)] + fields.map(csvCell)).joined(separator: ",")
    }

    private static func csvNumericCell(_ value: String) -> String {
        "\"" + value.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }

    private static func microseconds(_ date: Date) -> Int64? {
        let scaled = (date.timeIntervalSince1970 * 1_000_000).rounded()
        guard scaled.isFinite, scaled > Double(Int64.min), scaled < Double(Int64.max) else { return nil }
        return Int64(scaled)
    }

    private static func date(fromMicroseconds value: Int64) -> Date? {
        let date = Date(timeIntervalSince1970: Double(value) / 1_000_000)
        return date.timeIntervalSince1970.isFinite ? date : nil
    }

    private static func retentionCutoff(now: Date, maximumAge: TimeInterval) throws -> Int64 {
        guard microseconds(now) != nil, maximumAge.isFinite, maximumAge > 0,
              let cutoff = microseconds(now.addingTimeInterval(-maximumAge)) else {
            throw HistoryError.invalidRequest
        }
        return cutoff
    }

    private static func makeEncoder() -> JSONEncoder {
        let value = JSONEncoder()
        value.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return value
    }

    private static func decoder() -> JSONDecoder { JSONDecoder() }

    private static func existingSnapshot(_ database: OpaquePointer, provider: String, id: String, sessionID: String,
                                         capturedMicros: Int64) throws -> MonitorSnapshot {
        let statement = try prepare(database, sql: "SELECT provider, source_id, session_id, captured_us, payload FROM samples WHERE provider=? AND source_id=? AND session_id=? AND captured_us=?")
        defer { sqlite3_finalize(statement) }
        try bind(text: provider, at: 1, to: statement)
        try bind(text: id, at: 2, to: statement)
        try bind(text: sessionID, at: 3, to: statement)
        guard sqlite3_bind_int64(statement, 4, capturedMicros) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
        guard sqlite3_step(statement) == SQLITE_ROW else { throw HistoryError.databaseUnavailable }
        return try decodeRecord(statement, decoder: decoder())
    }

    private static func prepare(_ database: OpaquePointer, sql: String) throws -> OpaquePointer {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
            throw HistoryError.databaseUnavailable
        }
        return statement
    }

    private static func execute(_ database: OpaquePointer, _ sql: String) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else { throw HistoryError.databaseUnavailable }
    }

    private static func pragmaInt(_ database: OpaquePointer, _ sql: String) throws -> Int32 {
        let statement = try prepare(database, sql: sql)
        defer { sqlite3_finalize(statement) }
        guard sqlite3_step(statement) == SQLITE_ROW else { throw HistoryError.databaseUnavailable }
        return sqlite3_column_int(statement, 0)
    }

    private static func pragmaText(_ database: OpaquePointer, _ sql: String) throws -> String {
        let statement = try prepare(database, sql: sql)
        defer { sqlite3_finalize(statement) }
        guard sqlite3_step(statement) == SQLITE_ROW, let value = columnText(statement, 0) else {
            throw HistoryError.databaseUnavailable
        }
        return value
    }

    private static func bind(text: String, at index: Int32, to statement: OpaquePointer) throws {
        let result = text.withCString { sqlite3_bind_text(statement, index, $0, -1, sqliteTransient) }
        guard result == SQLITE_OK else { throw HistoryError.databaseUnavailable }
    }

    private static func columnText(_ statement: OpaquePointer, _ index: Int32) -> String? {
        guard let pointer = sqlite3_column_text(statement, index) else { return nil }
        return String(cString: pointer)
    }
}
