import Darwin
import Foundation
import NUTData
import UPSModel

/// Shares the existing reader's fixed error taxonomy; parsing remains explicit v2.
public typealias NUTOperationalSampleReaderError = NUTContinuousSampleReaderError

/// Reads only the published schema-2 operational envelope; it never autodetects v1,
/// starts a process, or opens USB. Terminal envelopes are never projected as active data.
public actor NUTOperationalSampleReader {
    public typealias Clock = @Sendable () -> Date
    public typealias MonotonicClock = @Sendable () -> TimeInterval

    private static let protocolName = "ups-monitor.continuous.v2"
    fileprivate static let maxPayloadBytes = 16_384
    private static let freshnessMilliseconds: Int64 = 10_000
    private static let maxReadAge: TimeInterval = 10

    private let sampleFileURL: URL
    private let expectedSourceID: String
    private let expectedSessionID: String
    private let clock: Clock
    private let monotonicClock: MonotonicClock
    private let connectionWallTime: Date
    private let connectionMonotonicTime: TimeInterval
    private var lastSample: SampleWire?
    private var staticNominalValues: [String: (value: String, observedMS: Int)] = [:]
    private var sessionStartedAtUnixMS: Int64?
    private var lastPublishedAtUnixMS: Int64?
    private var becameTerminal = false

    public init(
        sampleFileURL: URL,
        expectedSourceID: String,
        expectedSessionID: String,
        clock: @escaping Clock = { Date() },
        monotonicClock: @escaping MonotonicClock = { ProcessInfo.processInfo.systemUptime }
    ) throws {
        guard Self.validIdentifier(expectedSourceID), Self.validIdentifier(expectedSessionID), sampleFileURL.isFileURL else {
            throw NUTContinuousSampleReaderError.wrongIdentity
        }
        let now = clock()
        let uptime = monotonicClock()
        guard now.timeIntervalSince1970.isFinite, uptime.isFinite else {
            throw NUTContinuousSampleReaderError.clockDiscontinuity
        }
        self.sampleFileURL = sampleFileURL.standardizedFileURL
        self.expectedSourceID = expectedSourceID
        self.expectedSessionID = expectedSessionID
        self.clock = clock
        self.monotonicClock = monotonicClock
        connectionWallTime = now
        connectionMonotonicTime = uptime
    }

    /// Pins the logical IDs in a privately published file. This is replay control, not authentication.
    public static func connect(
        directoryURL: URL,
        clock: @escaping Clock = { Date() },
        monotonicClock: @escaping MonotonicClock = { ProcessInfo.processInfo.systemUptime }
    ) async throws -> NUTOperationalSampleReader {
        let fileURL = directoryURL.appendingPathComponent("sample.json", isDirectory: false)
        let now = clock()
        let envelope = try decodeEnvelope(try SecureSampleFile.read(fileURL), now: now)
        guard envelope.state == .active, envelope.terminalReason == nil,
              let sample = envelope.sample else { throw NUTContinuousSampleReaderError.terminalSession }
        let reader = try NUTOperationalSampleReader(sampleFileURL: fileURL,
                                                   expectedSourceID: envelope.sourceID,
                                                   expectedSessionID: envelope.sessionID,
                                                   clock: clock, monotonicClock: monotonicClock)
        _ = try await reader.project(envelope, sample: sample, now: now,
                                     monotonicNow: monotonicClock())
        return reader
    }

    public func read() async throws -> [MonitorSnapshot] {
        guard !becameTerminal else { throw NUTContinuousSampleReaderError.terminalSession }
        let now = clock()
        let monotonicNow = monotonicClock()
        guard now.timeIntervalSince1970.isFinite, monotonicNow.isFinite else {
            throw NUTContinuousSampleReaderError.clockDiscontinuity
        }
        let wallElapsed = now.timeIntervalSince(connectionWallTime)
        let monotonicElapsed = monotonicNow - connectionMonotonicTime
        guard wallElapsed >= 0, monotonicElapsed >= 0, abs(wallElapsed - monotonicElapsed) <= 1 else {
            throw NUTContinuousSampleReaderError.clockDiscontinuity
        }
        let envelope = try Self.decodeEnvelope(try SecureSampleFile.read(sampleFileURL), now: now)
        guard envelope.sourceID == expectedSourceID, envelope.sessionID == expectedSessionID else {
            throw NUTContinuousSampleReaderError.wrongIdentity
        }
        guard envelope.state == .active, envelope.terminalReason == nil,
              let sample = envelope.sample else {
            becameTerminal = true
            throw NUTContinuousSampleReaderError.terminalSession
        }
        return [try project(envelope, sample: sample, now: now, monotonicNow: monotonicNow)]
    }

    private func project(_ envelope: EnvelopeWire, sample: SampleWire,
                         now: Date, monotonicNow: TimeInterval) throws -> MonitorSnapshot {
        guard envelope.sourceID == expectedSourceID, envelope.sessionID == expectedSessionID else {
            throw NUTContinuousSampleReaderError.wrongIdentity
        }
        guard envelope.state == .active, envelope.terminalReason == nil else {
            throw NUTContinuousSampleReaderError.terminalSession
        }
        if let sessionStartedAtUnixMS, envelope.startedAtUnixMS != sessionStartedAtUnixMS {
            throw NUTContinuousSampleReaderError.replayOrRegression
        }
        if let lastPublishedAtUnixMS, envelope.publishedAtUnixMS < lastPublishedAtUnixMS {
            throw NUTContinuousSampleReaderError.replayOrRegression
        }
        let publishedAt = Date(timeIntervalSince1970: Double(envelope.publishedAtUnixMS) / 1_000)
        guard publishedAt <= now.addingTimeInterval(0.1), now.timeIntervalSince(publishedAt) <= Self.maxReadAge else {
            throw NUTContinuousSampleReaderError.staleEnvelope
        }
        let start = Date(timeIntervalSince1970: Double(envelope.startedAtUnixMS) / 1_000)
        let elapsedAtRead = now.timeIntervalSince(start)
        guard start <= now.addingTimeInterval(0.1), elapsedAtRead >= 0,
              Double(sample.elapsedMS) / 1_000 <= elapsedAtRead + 0.1,
              abs(elapsedAtRead - (monotonicNow - connectionMonotonicTime
                                    + connectionWallTime.timeIntervalSince(start))) <= 1 else {
            throw NUTContinuousSampleReaderError.clockDiscontinuity
        }

        if let lastSample {
            guard sample.sequence >= lastSample.sequence,
                  sample.slot >= lastSample.slot,
                  sample.elapsedMS >= lastSample.elapsedMS else {
                throw NUTContinuousSampleReaderError.replayOrRegression
            }
            if sample.sequence == lastSample.sequence {
                guard sample == lastSample else { throw NUTContinuousSampleReaderError.replayOrRegression }
            } else {
                guard sample.slot > lastSample.slot, sample.elapsedMS > lastSample.elapsedMS else {
                    throw NUTContinuousSampleReaderError.replayOrRegression
                }
            }
        }
        let source = MonitorSource(provider: .nut, id: expectedSourceID,
                                   sessionID: expectedSessionID, identityStability: .configured)
        do { try source.validate() } catch { throw NUTContinuousSampleReaderError.wrongIdentity }
        let values = try validatedValues(sample, startedAt: start, now: now)
        let status = try projectStatus(values.statusField, now: now,
                                       observedAt: values.statusDate)
        let result = MonitorSnapshot(source: source, capturedAt: values.capturedAt, status: status, metrics: values.metrics)
        try result.validate()
        lastSample = sample
        staticNominalValues = values.staticNominals
        if sessionStartedAtUnixMS == nil { sessionStartedAtUnixMS = envelope.startedAtUnixMS }
        lastPublishedAtUnixMS = envelope.publishedAtUnixMS
        return result
    }

    private static func decodeEnvelope(_ data: Data, now: Date) throws -> EnvelopeWire {
        guard data.count <= maxPayloadBytes else { throw NUTContinuousSampleReaderError.payloadTooLarge }
        switch JSONDuplicateKeyScanner(data).result {
        case .valid: break
        case .duplicateKey: throw NUTContinuousSampleReaderError.duplicateJSONKey
        case .malformed: throw NUTContinuousSampleReaderError.malformedEnvelope
        }
        switch JSONDuplicateKeyScanner(data, validateIntegerLexemes: true).result {
        case .valid: break
        case .duplicateKey: throw NUTContinuousSampleReaderError.duplicateJSONKey
        case .malformed: throw NUTContinuousSampleReaderError.malformedEnvelope
        }
        do {
            let value = try JSONDecoder().decode(EnvelopeWire.self, from: data)
            guard value.schemaVersion == 2, value.protocolName == protocolName,
                  validIdentifier(value.sourceID), validIdentifier(value.sessionID),
                  (0...9_007_199_254_740_991).contains(value.startedAtUnixMS),
                  (value.startedAtUnixMS...9_007_199_254_740_991).contains(value.publishedAtUnixMS),
                  Double(value.publishedAtUnixMS) / 1_000 <= now.timeIntervalSince1970 + 0.1 else {
                throw NUTContinuousSampleReaderError.malformedEnvelope
            }
            switch value.state {
            case .active:
                guard value.terminalReason == nil, value.sample != nil else {
                    throw NUTContinuousSampleReaderError.malformedEnvelope
                }
            case .stopped:
                guard value.terminalReason == "cancelled" else {
                    throw NUTContinuousSampleReaderError.malformedEnvelope
                }
            case .failed:
                guard let reason = value.terminalReason,
                      ["cancelled", "device_lost", "session_lost", "guard_error", "output_error", "protocol_error",
                       "capture_limit", "deadline", "child_failed", "child_unreaped", "io_error",
                       "cleanup_unresolved"].contains(reason) else {
                    throw NUTContinuousSampleReaderError.malformedEnvelope
                }
            }
            return value
        } catch let error as NUTContinuousSampleReaderError { throw error }
        catch { throw NUTContinuousSampleReaderError.malformedEnvelope }
    }

    private func validatedValues(_ sample: SampleWire, startedAt: Date, now: Date) throws -> ProjectedValues {
        guard sample.protocolName == Self.protocolName, sample.schemaVersion == 2, sample.type == .sample,
              (1...9_007_199_254_740_991).contains(sample.sequence),
              (0...9_007_199_254_740_991).contains(sample.slot),
              (0...9_007_199_254_740_991).contains(sample.elapsedMS),
              (0...9_007_199_254_740_991).contains(sample.missedSlots),
              sample.slot == sample.elapsedMS / 5_000,
              sample.missedSlots == sample.slot + 1 - sample.sequence,
              Set(sample.fields.keys) == Set(FieldName.allCases.map(\.rawValue)) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        var fieldValues = Dictionary(uniqueKeysWithValues: sample.fields.map { ($0.key, $0.value) })
        var nextStaticNominals = staticNominalValues
        try validateWireFields(sample)
        for name in [FieldName.upsRealPowerNominal, .upsPowerNominal] {
            guard let field = fieldValues[name.rawValue] else { throw NUTContinuousSampleReaderError.invalidSample }
            if field.state == .observed {
                guard let value = field.value, let observedMS = field.observedMS,
                      numeric(value) != nil else { throw NUTContinuousSampleReaderError.invalidSample }
                if let existing = nextStaticNominals[name.rawValue],
                   numeric(existing.value) != numeric(value) {
                    throw NUTContinuousSampleReaderError.invalidSample
                }
                nextStaticNominals[name.rawValue] = (value, observedMS)
            } else if field.state == .unavailable, let existing = nextStaticNominals[name.rawValue] {
                fieldValues[name.rawValue] = FieldWire(value: existing.value, observedMS: existing.observedMS,
                                                       kind: .static, state: .observed)
            }
        }
        var decodedMetrics = [NUTMetricID: NUTMetric]()
        var invalidMetricIDs = Set<NUTMetricID>()
        var fieldDates: [String: Date] = [:]
        var freshNumericLines = [String]()

        for name in FieldName.allCases {
            guard let field = fieldValues[name.rawValue], field.kind == name.kind else {
                throw NUTContinuousSampleReaderError.invalidSample
            }
            switch field.state {
            case .observed:
                guard let raw = field.value, let observed = field.observedMS,
                      observed >= 0, observed <= sample.elapsedMS else {
                    throw NUTContinuousSampleReaderError.invalidSample
                }
                let observedAt = startedAt.addingTimeInterval(Double(observed) / 1_000)
                let ageMS = Int64((now.timeIntervalSince(observedAt) * 1_000).rounded(.down))
                fieldDates[name.rawValue] = observedAt
                if name.metricID != nil, name != .upsRealPower, name != .upsPower,
                   name != .upsStatus, (name.kind == .static && ageMS >= 0) || (ageMS >= 0 && ageMS <= Self.freshnessMilliseconds) {
                    guard let decoderNumber = decoderCompatibleNumber(raw) else {
                        throw NUTContinuousSampleReaderError.invalidSample
                    }
                    freshNumericLines.append("\(name.nutVariable): \(decoderNumber)")
                }
            case .unavailable, .invalid:
                guard field.value == nil, field.observedMS == nil else {
                    throw NUTContinuousSampleReaderError.invalidSample
                }
            }
        }

        // Both temperature names alias the same descriptor observation.
        let batteryTemperature = fieldValues[FieldName.batteryTemperature.rawValue]!
        let upsTemperature = fieldValues[FieldName.upsTemperature.rawValue]!
        guard batteryTemperature.state == upsTemperature.state,
              batteryTemperature.value == upsTemperature.value,
              batteryTemperature.observedMS == upsTemperature.observedMS else {
            throw NUTContinuousSampleReaderError.invalidSample
        }

        // Let the existing decoder enforce domain, range and metric validity for numeric values.
        if !freshNumericLines.isEmpty {
            for line in freshNumericLines {
                let parts = line.split(separator: ":", maxSplits: 1).map(String.init)
                guard parts.count == 2,
                      let name = FieldName.allCases.first(where: { $0.rawValue == parts[0] }),
                      let id = name.metricID else { continue }
                do {
                    let listing = try UPSCTextDecoder().decode(
                        line, sourceID: expectedSourceID,
                        capturedAt: fieldDates[name.rawValue] ?? startedAt
                    )
                    if let metric = listing.metrics[id] { decodedMetrics[id] = metric }
                    else { invalidMetricIDs.insert(id) }
                } catch { invalidMetricIDs.insert(id) }
            }
        }
        var output: [MonitorMetric] = []
        var captureDates = [Date]()
        for name in FieldName.allCases where name.metricID != nil {
            guard let id = name.metricID else { continue }
            let field = fieldValues[name.rawValue]!
            let date = fieldDates[name.rawValue]
            let quality: MonitorMetricQuality
            let value: Double?
            let provenance: MonitorMetricProvenance
            let reportedProvenance: MonitorMetricProvenance = name == .batteryRuntime ? .estimated : .reported
            if field.state == .invalid {
                quality = .invalid; value = nil; provenance = reportedProvenance
            } else if field.state == .unavailable || date == nil {
                quality = .unavailable; value = nil; provenance = reportedProvenance
            } else if name.kind == .static {
                let parsed = decodedMetrics[id]
                if let number = parsed?.value, parsed?.quality == .available {
                    quality = .available; value = number; provenance = .reported
                } else {
                    quality = .invalid; value = nil; provenance = .reported
                }
            } else if name == .upsRealPower || name == .upsPower {
                let loadName: FieldName = name == .upsRealPower ? .upsLoad : .experimentalApparentLoad
                let nominalName: FieldName = name == .upsRealPower ? .upsRealPowerNominal : .upsPowerNominal
                let load = fieldValues[loadName.rawValue]!
                let nominal = fieldValues[nominalName.rawValue]!
                let freshLoad = load.state == .observed && fieldDates[loadName.rawValue].map {
                    let age = now.timeIntervalSince($0)
                    return age >= 0 && age <= Double(Self.freshnessMilliseconds) / 1_000
                } == true
                if freshLoad, let percent = numeric(load.value), (0...100).contains(percent),
                   let rating = numeric(nominal.value), rating > 0,
                   nominal.state == .observed {
                    quality = .available; value = percent * rating / 100; provenance = .driverDerived
                    if let loadDate = fieldDates[loadName.rawValue] { captureDates.append(loadDate) }
                } else {
                    quality = .unavailable; value = nil; provenance = .driverDerived
                }
            } else {
                let parsed = decodedMetrics[id]
                if invalidMetricIDs.contains(id) || (field.state == .observed && numeric(field.value) == nil) {
                    quality = .invalid; value = nil; provenance = reportedProvenance
                } else if let date, now.timeIntervalSince(date) >= 0,
                   now.timeIntervalSince(date) <= Double(Self.freshnessMilliseconds) / 1_000,
                   let number = parsed?.value, parsed?.quality == .available {
                    quality = .available; value = number; provenance = reportedProvenance
                    captureDates.append(date)
                } else if field.state == .invalid {
                    quality = .invalid; value = nil; provenance = reportedProvenance
                } else {
                    quality = .unavailable; value = nil; provenance = reportedProvenance
                }
            }
            guard let monitorID = MonitorMetricID(rawValue: id.rawValue) else {
                throw NUTContinuousSampleReaderError.invalidSample
            }
            output.append(MonitorMetric(id: monitorID, value: value, unit: monitorID.allowedUnit,
                                        quality: quality, provenance: provenance))
        }

        // Validate the derived wire values against their load dependencies; never trust them as inputs.
        let statusField = fieldValues[FieldName.upsStatus.rawValue]!
        let statusDate = fieldDates[FieldName.upsStatus.rawValue]
        if statusField.state == .observed, let statusDate,
           now.timeIntervalSince(statusDate) >= 0,
           now.timeIntervalSince(statusDate) <= Double(Self.freshnessMilliseconds) / 1_000,
           hasRecognizedStatus(statusField.value) {
            captureDates.append(statusDate)
        }
        try validateDerived(name: .upsRealPower, loadName: .upsLoad, nominalName: .upsRealPowerNominal,
                            fields: fieldValues, fieldDates: fieldDates)
        try validateDerived(name: .upsPower, loadName: .experimentalApparentLoad, nominalName: .upsPowerNominal,
                            fields: fieldValues, fieldDates: fieldDates)
        guard let capturedAt = captureDates.min() else { throw NUTContinuousSampleReaderError.noFreshTelemetry }
        return ProjectedValues(metrics: output, capturedAt: capturedAt, statusField: statusField,
                               statusDate: statusDate, staticNominals: nextStaticNominals)
    }

    private func validateDerived(name: FieldName, loadName: FieldName, nominalName: FieldName,
                                 fields: [String: FieldWire],
                                 fieldDates: [String: Date]) throws {
        guard let derived = fields[name.rawValue], derived.kind == .driverDerived else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        if derived.state != .observed { return }
        guard let load = fields[loadName.rawValue], load.state == .observed,
              let nominal = fields[nominalName.rawValue], nominal.state == .observed,
              fieldDates[loadName.rawValue] != nil,
              let loadValue = numeric(load.value), (0...100).contains(loadValue),
              let nominalValue = numeric(nominal.value), nominalValue > 0 else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        let expectedValue = loadValue * nominalValue / 100
        guard expectedValue.isFinite,
              derived.observedMS == load.observedMS, let derivedValue = numeric(derived.value),
              abs(derivedValue - expectedValue) <= max(1e-6, max(abs(expectedValue), abs(derivedValue)) * 1e-9) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
    }

    private func projectStatus(_ field: FieldWire, now: Date, observedAt: Date?) throws -> MonitorStatus {
        guard field.kind == .reported else { throw NUTContinuousSampleReaderError.invalidSample }
        guard field.state == .observed, let raw = field.value, let observedAt,
              now.timeIntervalSince(observedAt) >= 0,
              now.timeIntervalSince(observedAt) <= Double(Self.freshnessMilliseconds) / 1_000 else {
            return MonitorStatus(lineState: .unknown, quality: field.state == .invalid ? .invalid : .unavailable)
        }
        let tokens = raw.split(separator: " ").map(String.init)
        let allowlist: Set<String> = ["OL", "OB", "LB", "HB", "RB", "OFF", "BYPASS", "CAL", "OVER", "TRIM", "BOOST", "FSD", "ALARM"]
        guard raw.utf8.count <= 128, !tokens.isEmpty, tokens.joined(separator: " ") == raw,
              tokens == tokens.sorted(), Set(tokens).count == tokens.count,
              tokens.allSatisfy({ allowlist.contains($0) }), !(tokens.contains("OL") && tokens.contains("OB")) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        guard !tokens.isEmpty else { return MonitorStatus(lineState: .unknown, quality: .unavailable) }
        let lineState: MonitorLineState = tokens.contains("OL") ? .onLine : tokens.contains("OB") ? .onBattery : .unknown
        var flags = Set<MonitorStatusFlag>()
        let mapping: [String: MonitorStatusFlag] = [
            "LB": .lowBattery, "HB": .highBattery, "RB": .replaceBattery, "OFF": .outputOff,
            "BYPASS": .bypass, "CAL": .calibration, "OVER": .overload, "TRIM": .trim,
            "BOOST": .boost, "FSD": .forcedShutdown, "ALARM": .alarm,
        ]
        for token in tokens { if let flag = mapping[token] { flags.insert(flag) } }
        return MonitorStatus(lineState: lineState, flags: flags, quality: .available)
    }

    private func hasRecognizedStatus(_ raw: String?) -> Bool {
        guard let raw, !raw.isEmpty else { return false }
        return true
    }

    private func validateWireFields(_ sample: SampleWire) throws {
        guard Set(sample.fields.keys) == Set(FieldName.allCases.map(\.rawValue)) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        for name in FieldName.allCases {
            guard let field = sample.fields[name.rawValue], field.kind == name.kind else {
                throw NUTContinuousSampleReaderError.invalidSample
            }
            switch field.state {
            case .observed:
                guard let value = field.value, let observed = field.observedMS,
                      observed >= 0, observed <= sample.elapsedMS else {
                    throw NUTContinuousSampleReaderError.invalidSample
                }
                if name == .upsStatus {
                    try validateStatusValue(value)
                } else {
                    guard let number = numeric(value) else {
                        throw NUTContinuousSampleReaderError.invalidSample
                    }
                    if name == .upsLoad || name == .experimentalApparentLoad {
                        guard (0...100).contains(number) else {
                            throw NUTContinuousSampleReaderError.invalidSample
                        }
                    }
                    if name == .upsRealPowerNominal || name == .upsPowerNominal {
                        guard number > 0 else { throw NUTContinuousSampleReaderError.invalidSample }
                    }
                }
            case .unavailable, .invalid:
                guard field.value == nil, field.observedMS == nil else {
                    throw NUTContinuousSampleReaderError.invalidSample
                }
            }
        }

        let batteryTemperature = sample.fields[FieldName.batteryTemperature.rawValue]!
        let upsTemperature = sample.fields[FieldName.upsTemperature.rawValue]!
        guard batteryTemperature == upsTemperature else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        try validateDerivedWire(name: .upsRealPower, loadName: .upsLoad,
                                nominalName: .upsRealPowerNominal, fields: sample.fields)
        try validateDerivedWire(name: .upsPower, loadName: .experimentalApparentLoad,
                                nominalName: .upsPowerNominal, fields: sample.fields)
    }

    private func validateDerivedWire(name: FieldName, loadName: FieldName,
                                     nominalName: FieldName, fields: [String: FieldWire]) throws {
        guard let derived = fields[name.rawValue], derived.kind == .driverDerived else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        guard derived.state == .observed else { return }
        guard let load = fields[loadName.rawValue], load.state == .observed,
              let nominal = fields[nominalName.rawValue], nominal.state == .observed,
              let loadValue = numeric(load.value), (0...100).contains(loadValue),
              let nominalValue = numeric(nominal.value), nominalValue > 0,
              let derivedValue = numeric(derived.value),
              derived.observedMS == load.observedMS else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        let expected = loadValue * nominalValue / 100
        guard expected.isFinite, abs(derivedValue - expected)
                <= max(1e-6, max(abs(expected), abs(derivedValue)) * 1e-9) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
    }

    private func validateStatusValue(_ raw: String) throws {
        let allowed: Set<String> = ["OL", "OB", "LB", "HB", "RB", "OFF", "BYPASS", "CAL", "OVER", "TRIM", "BOOST", "FSD", "ALARM"]
        let tokens = raw.split(separator: " ").map(String.init)
        guard raw.utf8.count <= 128, tokens.joined(separator: " ") == raw,
              tokens == tokens.sorted(), Set(tokens).count == tokens.count,
              tokens.allSatisfy({ allowed.contains($0) }), !(tokens.contains("OL") && tokens.contains("OB")) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
    }

    private static func validIdentifier(_ value: String) -> Bool {
        guard (1...64).contains(value.utf8.count), let first = value.utf8.first else { return false }
        return isAlphaNumeric(first) && value.utf8.allSatisfy { isAlphaNumeric($0) || $0 == 45 || $0 == 46 || $0 == 95 }
    }

    private static func isAlphaNumeric(_ byte: UInt8) -> Bool {
        (48...57).contains(byte) || (65...90).contains(byte) || (97...122).contains(byte)
    }

    private func numeric(_ text: String?) -> Double? {
        guard let text, text.utf8.count <= 32, text.range(of: #"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"#, options: .regularExpression) != nil,
              let value = Double(text), value.isFinite else { return nil }
        return value
    }

    /// Expands v2's accepted exponent syntax without changing its parsed Double value.
    /// UPSCTextDecoder remains unchanged, preserving the narrower v1 text contract.
    private func decoderCompatibleNumber(_ text: String) -> String? {
        guard let parsed = numeric(text) else { return nil }
        guard let exponentIndex = text.firstIndex(where: { $0 == "e" || $0 == "E" }) else {
            return text
        }
        if parsed == 0 { return text.hasPrefix("-") ? "-0" : "0" }

        let significand = String(text[..<exponentIndex])
        let exponentText = String(text[text.index(after: exponentIndex)...])
        let exponentDigits = exponentText.hasPrefix("+") ? String(exponentText.dropFirst()) : exponentText
        guard let exponent = Int(exponentDigits) else { return nil }
        let negative = significand.hasPrefix("-")
        let unsigned = negative ? String(significand.dropFirst()) : significand
        let parts = unsigned.split(separator: ".", omittingEmptySubsequences: false)
        guard (1...2).contains(parts.count) else { return nil }
        let integerDigits = String(parts[0])
        let fractionalDigits = parts.count == 2 ? String(parts[1]) : ""
        let digits = integerDigits + fractionalDigits
        let decimalPoint = integerDigits.count + exponent

        var integerPart: String
        var fractionPart: String
        if decimalPoint <= 0 {
            integerPart = "0"
            fractionPart = String(repeating: "0", count: -decimalPoint) + digits
        } else if decimalPoint >= digits.count {
            integerPart = digits + String(repeating: "0", count: decimalPoint - digits.count)
            fractionPart = ""
        } else {
            let split = digits.index(digits.startIndex, offsetBy: decimalPoint)
            integerPart = String(digits[..<split])
            fractionPart = String(digits[split...])
        }
        while integerPart.count > 1 && integerPart.first == "0" { integerPart.removeFirst() }
        guard !integerPart.isEmpty,
              integerPart.utf8.count + fractionPart.utf8.count <= 512 else { return nil }
        let sign = negative ? "-" : ""
        let normalized = sign + integerPart + (fractionPart.isEmpty ? "" : "." + fractionPart)
        guard let normalizedValue = Double(normalized), normalizedValue.isFinite,
              normalizedValue == parsed else { return nil }
        return normalized
    }

    private struct ProjectedValues {
        var metrics: [MonitorMetric]
        var capturedAt: Date
        var statusField: FieldWire
        var statusDate: Date?
        var staticNominals: [String: (value: String, observedMS: Int)]
    }
}

private enum EnvelopeState: String, Decodable { case active, stopped, failed }
private enum SampleType: String, Decodable { case sample, end }
private enum FieldKind: String, Decodable { case reported, driverDerived, `static` }
private enum FieldState: String, Decodable { case observed, unavailable, invalid }

private enum FieldName: String, CaseIterable {
    case upsStatus = "ups.status"
    case batteryCharge = "battery.charge"
    case batteryRuntime = "battery.runtime"
    case batteryVoltage = "battery.voltage"
    case batteryTemperature = "battery.temperature"
    case upsTemperature = "ups.temperature"
    case inputVoltage = "input.voltage"
    case inputFrequency = "input.frequency"
    case outputVoltage = "output.voltage"
    case outputCurrent = "output.current"
    case outputFrequency = "output.frequency"
    case upsLoad = "ups.load"
    case experimentalApparentLoad = "experimental.ups.load.apparent"
    case upsRealPowerNominal = "ups.realpower.nominal"
    case upsPowerNominal = "ups.power.nominal"
    case upsRealPower = "ups.realpower"
    case upsPower = "ups.power"

    var kind: FieldKind {
        switch self {
        case .upsRealPowerNominal, .upsPowerNominal: .static
        case .upsRealPower, .upsPower: .driverDerived
        default: .reported
        }
    }
    var metricID: NUTMetricID? {
        switch self {
        case .upsStatus, .experimentalApparentLoad: nil
        case .batteryCharge: .batteryCharge
        case .batteryRuntime: .batteryRuntime
        case .batteryVoltage: .batteryVoltage
        case .batteryTemperature: .batteryTemperature
        case .upsTemperature: .upsTemperature
        case .inputVoltage: .inputVoltage
        case .inputFrequency: .inputFrequency
        case .outputVoltage: .outputVoltage
        case .outputCurrent: .outputCurrent
        case .outputFrequency: .outputFrequency
        case .upsLoad: .upsLoad
        case .upsRealPowerNominal: .upsRealPowerNominal
        case .upsPowerNominal: .upsApparentPowerNominal
        case .upsRealPower: .upsRealPower
        case .upsPower: .upsApparentPower
        }
    }
    var nutVariable: String { rawValue }
}

private struct EnvelopeWire: Decodable {
    let schemaVersion: Int
    let protocolName: String
    let sourceID: String
    let sessionID: String
    let state: EnvelopeState
    let startedAtUnixMS: Int64
    let publishedAtUnixMS: Int64
    let terminalReason: String?
    let sample: SampleWire?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", protocolName = "protocol", sourceID = "source_id"
        case sessionID = "session_id", state, startedAtUnixMS = "started_at_unix_ms"
        case publishedAtUnixMS = "published_at_unix_ms", terminalReason = "terminal_reason", sample
    }
    init(from decoder: Decoder) throws {
        let dynamic = try decoder.container(keyedBy: DynamicJSONKey.self)
        guard Set(dynamic.allKeys.map(\.stringValue)) == Set(["schema_version", "protocol", "source_id", "session_id", "state", "started_at_unix_ms", "published_at_unix_ms", "terminal_reason", "sample"]) else {
            throw NUTContinuousSampleReaderError.malformedEnvelope
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try c.decode(Int.self, forKey: .schemaVersion)
        protocolName = try c.decode(String.self, forKey: .protocolName)
        sourceID = try c.decode(String.self, forKey: .sourceID)
        sessionID = try c.decode(String.self, forKey: .sessionID)
        state = try c.decode(EnvelopeState.self, forKey: .state)
        startedAtUnixMS = try c.decode(Int64.self, forKey: .startedAtUnixMS)
        publishedAtUnixMS = try c.decode(Int64.self, forKey: .publishedAtUnixMS)
        terminalReason = try c.decodeIfPresent(String.self, forKey: .terminalReason)
        sample = try c.decodeIfPresent(SampleWire.self, forKey: .sample)
    }
}

private struct SampleWire: Decodable, Equatable {
    let protocolName: String
    let schemaVersion: Int
    let type: SampleType
    let sequence: Int
    let slot: Int
    let elapsedMS: Int
    let missedSlots: Int
    let fields: [String: FieldWire]

    enum CodingKeys: String, CodingKey {
        case protocolName = "protocol", schemaVersion = "schema_version", type, sequence, slot
        case elapsedMS = "elapsed_ms", missedSlots = "missed_slots", fields
    }
    init(from decoder: Decoder) throws {
        let dynamic = try decoder.container(keyedBy: DynamicJSONKey.self)
        guard Set(dynamic.allKeys.map(\.stringValue)) == Set(["protocol", "schema_version", "type", "sequence", "slot", "elapsed_ms", "missed_slots", "fields"]) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        protocolName = try c.decode(String.self, forKey: .protocolName)
        schemaVersion = try c.decode(Int.self, forKey: .schemaVersion)
        type = try c.decode(SampleType.self, forKey: .type)
        sequence = try c.decode(Int.self, forKey: .sequence)
        slot = try c.decode(Int.self, forKey: .slot)
        elapsedMS = try c.decode(Int.self, forKey: .elapsedMS)
        missedSlots = try c.decode(Int.self, forKey: .missedSlots)
        fields = try c.decode([String: FieldWire].self, forKey: .fields)
    }
}

private struct FieldWire: Decodable, Equatable {
    let value: String?
    let observedMS: Int?
    let kind: FieldKind
    let state: FieldState
    init(value: String?, observedMS: Int?, kind: FieldKind, state: FieldState) {
        self.value = value
        self.observedMS = observedMS
        self.kind = kind
        self.state = state
    }
    enum CodingKeys: String, CodingKey { case value, observedMS = "observed_ms", kind, state }
    init(from decoder: Decoder) throws {
        let dynamic = try decoder.container(keyedBy: DynamicJSONKey.self)
        guard Set(dynamic.allKeys.map(\.stringValue)) == Set(["value", "observed_ms", "kind", "state"]) else {
            throw NUTContinuousSampleReaderError.invalidSample
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        value = try c.decodeIfPresent(String.self, forKey: .value)
        observedMS = try c.decodeIfPresent(Int.self, forKey: .observedMS)
        kind = try c.decode(FieldKind.self, forKey: .kind)
        state = try c.decode(FieldState.self, forKey: .state)
    }
}

private struct DynamicJSONKey: CodingKey, Hashable {
    let stringValue: String
    let intValue: Int?
    init?(stringValue: String) { self.stringValue = stringValue; intValue = nil }
    init?(intValue: Int) { stringValue = String(intValue); self.intValue = intValue }
}

private struct JSONDuplicateKeyScanner {
    enum Result { case valid, malformed, duplicateKey }

    private static let integerKeys: Set<String> = [
        "schema_version", "started_at_unix_ms", "published_at_unix_ms",
        "sequence", "slot", "elapsed_ms", "missed_slots", "observed_ms",
    ]
    let bytes: [UInt8]
    let validateIntegerLexemes: Bool
    private(set) var index = 0
    private(set) var duplicateKeyFound = false

    init(_ data: Data, validateIntegerLexemes: Bool = false) {
        bytes = Array(data)
        self.validateIntegerLexemes = validateIntegerLexemes
    }
    var result: Result {
        var scan = self
        guard scan.parseValue(depth: 0) else {
            return scan.duplicateKeyFound ? .duplicateKey : .malformed
        }
        scan.skipWhitespace()
        guard scan.index == scan.bytes.count else { return .malformed }
        return scan.duplicateKeyFound ? .duplicateKey : .valid
    }
    mutating private func skipWhitespace() { while index < bytes.count && [9, 10, 13, 32].contains(bytes[index]) { index += 1 } }
    mutating private func parseValue(depth: Int, key: String? = nil) -> Bool {
        guard depth < 64 else { return false }
        skipWhitespace(); guard index < bytes.count else { return false }
        let isInteger = validateIntegerLexemes && key.map(Self.integerKeys.contains) == true
        switch bytes[index] {
        case 123:
            guard !isInteger else { return false }
            return parseObject(depth: depth + 1)
        case 91:
            guard !isInteger else { return false }
            return parseArray(depth: depth + 1)
        case 34: return !isInteger && parseString() != nil
        default:
            let start = index
            while index < bytes.count && ![9, 10, 13, 32, 44, 93, 125].contains(bytes[index]) { index += 1 }
            guard index > start else { return false }
            let token = String(decoding: bytes[start..<index], as: UTF8.self)
            if isInteger {
                if key == "observed_ms", token == "null" { return true }
                return token.range(of: #"^-?(?:0|[1-9][0-9]*)$"#, options: .regularExpression) != nil
            }
            return true
        }
    }
    mutating private func parseObject(depth: Int) -> Bool {
        index += 1; skipWhitespace()
        if take(125) { return true }
        var keys = Set<String>()
        while index < bytes.count {
            skipWhitespace(); guard let key = parseString() else { return false }
            guard keys.insert(key).inserted else { duplicateKeyFound = true; return false }
            skipWhitespace(); guard take(58), parseValue(depth: depth, key: key) else { return false }
            skipWhitespace(); if take(125) { return true }; guard take(44) else { return false }
        }
        return false
    }
    mutating private func parseArray(depth: Int) -> Bool {
        index += 1; skipWhitespace()
        if take(93) { return true }
        while parseValue(depth: depth) { skipWhitespace(); if take(93) { return true }; guard take(44) else { return false } }
        return false
    }
    mutating private func parseString() -> String? {
        guard take(34) else { return nil }
        let start = index - 1
        while index < bytes.count {
            let byte = bytes[index]; index += 1
            if byte == 92 { guard index < bytes.count else { return nil }; index += 1 }
            else if byte == 34 {
                let data = Data(bytes[start..<index])
                return (try? JSONDecoder().decode(String.self, from: data))
            } else if byte < 32 { return nil }
        }
        return nil
    }
    mutating private func take(_ byte: UInt8) -> Bool {
        guard index < bytes.count, bytes[index] == byte else { return false }; index += 1; return true
    }
}

private struct SecureSampleFile {
    static func read(_ url: URL) throws -> Data {
        guard url.isFileURL, url.lastPathComponent == "sample.json" else { throw NUTContinuousSampleReaderError.unsafeFile }
        let directory = url.deletingLastPathComponent().standardizedFileURL
        let leaf = directory.lastPathComponent
        let parent = open(directory.deletingLastPathComponent().path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parent >= 0 else { throw NUTContinuousSampleReaderError.unsafeFile }
        defer { _ = Darwin.close(parent) }
        guard trustedParent(parent) else { throw NUTContinuousSampleReaderError.unsafeFile }
        let session = leaf.withCString { openat(parent, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
        guard session >= 0 else { throw NUTContinuousSampleReaderError.unsafeFile }
        defer { _ = Darwin.close(session) }
        guard privateDirectory(session) else { throw NUTContinuousSampleReaderError.unsafeFile }
        let fd = "sample.json".withCString { openat(session, $0, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC) }
        guard fd >= 0 else { throw NUTContinuousSampleReaderError.unsafeFile }
        defer { _ = Darwin.close(fd) }
        var before = stat(); var namedBefore = stat()
        guard fstat(fd, &before) == 0,
              fstatat(session, "sample.json", &namedBefore, AT_SYMLINK_NOFOLLOW) == 0,
              privateFile(before), emptyACL(fd), same(before, namedBefore) else { throw NUTContinuousSampleReaderError.unsafeFile }
        guard before.st_size >= 0 else { throw NUTContinuousSampleReaderError.unsafeFile }
        guard before.st_size <= off_t(NUTOperationalSampleReader.maxPayloadBytes) else { throw NUTContinuousSampleReaderError.payloadTooLarge }
        var bytes = Data(); bytes.reserveCapacity(Int(before.st_size))
        var buffer = [UInt8](repeating: 0, count: 4096)
        while true {
            let count = buffer.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress, $0.count) }
            if count == 0 { break }
            if count < 0 { if errno == EINTR { continue }; throw NUTContinuousSampleReaderError.ioFailure }
            guard bytes.count + count <= NUTOperationalSampleReader.maxPayloadBytes else { throw NUTContinuousSampleReaderError.payloadTooLarge }
            bytes.append(contentsOf: buffer.prefix(count))
        }
        var after = stat(); var namedAfter = stat()
        guard fstat(fd, &after) == 0,
              fstatat(session, "sample.json", &namedAfter, AT_SYMLINK_NOFOLLOW) == 0,
              privateFile(after), emptyACL(fd), same(before, after), same(after, namedAfter),
              bytes.count == Int(before.st_size), trustedParent(parent), privateDirectory(session) else {
            throw NUTContinuousSampleReaderError.unsafeFile
        }
        return bytes
    }
    private static func trustedParent(_ fd: Int32) -> Bool {
        var s = stat(); return fstat(fd, &s) == 0 && s.st_mode & S_IFMT == S_IFDIR && s.st_uid == getuid()
            && s.st_mode & 0o022 == 0 && emptyACL(fd)
    }
    private static func privateDirectory(_ fd: Int32) -> Bool {
        var s = stat(); return fstat(fd, &s) == 0 && s.st_mode & S_IFMT == S_IFDIR && s.st_mode & 0o7777 == 0o700
            && s.st_uid == getuid() && emptyACL(fd)
    }
    private static func privateFile(_ s: stat) -> Bool {
        s.st_mode & S_IFMT == S_IFREG && s.st_mode & 0o7777 == 0o600 && s.st_uid == getuid() && s.st_nlink == 1
    }
    private static func emptyACL(_ fd: Int32) -> Bool {
        errno = 0
        guard let acl = acl_get_fd_np(fd, ACL_TYPE_EXTENDED) else { return errno == ENOENT }
        defer { _ = acl_free(UnsafeMutableRawPointer(acl)) }
        guard acl_valid(acl) == 0 else { return false }
        var entry: acl_entry_t?; errno = 0
        return acl_get_entry(acl, Int32(ACL_FIRST_ENTRY.rawValue), &entry) == -1 && errno == EINVAL
    }
    private static func same(_ a: stat, _ b: stat) -> Bool {
        a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_mode == b.st_mode && a.st_uid == b.st_uid
            && a.st_gid == b.st_gid && a.st_nlink == b.st_nlink && a.st_size == b.st_size
            && a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec
            && a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec
    }
}
