import Foundation

public enum UPSCTextDecodeError: Error, Equatable, Sendable {
    case invalidUTF8
    case inputTooLarge
    case tooManyLines
    case lineTooLong
    case malformedLine(line: Int)
    case invalidSourceID
    case invalidCaptureTime
    case noUsableTelemetry
    case duplicateField(NUTMetricID)
    case duplicateStatus
    case duplicateDriverName
    case invalidStatus
    case invalidJSON
    case emptyJSON
    case nonStringJSONValue
}

/// Decodes only the documented `upsc <ups>` text listing. This is not a NUT wire-protocol parser.
public struct UPSCTextDecoder: Sendable {
    public static let maximumInputBytes = 65_536
    public static let maximumLines = 512
    public static let maximumLineBytes = 1_024
    public static let maximumValueBytes = 512

    public init() {}

    public func decode(_ data: Data, sourceID: String, capturedAt: Date) throws -> NUTSnapshot {
        guard data.count <= Self.maximumInputBytes else { throw UPSCTextDecodeError.inputTooLarge }
        guard let text = String(data: data, encoding: .utf8) else { throw UPSCTextDecodeError.invalidUTF8 }
        return try decode(text, sourceID: sourceID, capturedAt: capturedAt)
    }

    public func decode(_ text: String, sourceID: String, capturedAt: Date) throws -> NUTSnapshot {
        guard isValidSourceID(sourceID) else { throw UPSCTextDecodeError.invalidSourceID }
        guard capturedAt.timeIntervalSince1970.isFinite else { throw UPSCTextDecodeError.invalidCaptureTime }
        guard text.utf8.count <= Self.maximumInputBytes else { throw UPSCTextDecodeError.inputTooLarge }

        let lines = text.utf8.split(separator: 10, omittingEmptySubsequences: false)
        guard lines.count <= Self.maximumLines else { throw UPSCTextDecodeError.tooManyLines }

        var knownValues: [String: String] = [:]
        var seenMetrics = Set<NUTMetricID>()
        var statusSeen = false
        var driverSeen = false

        for (offset, rawLine) in lines.enumerated() {
            var lineBytes = Array(rawLine)
            if lineBytes.last == 13 { lineBytes.removeLast() }
            guard lineBytes.count <= Self.maximumLineBytes else { throw UPSCTextDecodeError.lineTooLong }
            let line = String(decoding: lineBytes, as: UTF8.self)
            if line.isEmpty { continue }

            guard let colon = line.firstIndex(of: ":") else {
                throw UPSCTextDecodeError.malformedLine(line: offset + 1)
            }
            let key = String(line[..<colon])
            let rawValue = String(line[line.index(after: colon)...])
            guard isValidVariableName(key) else { throw UPSCTextDecodeError.malformedLine(line: offset + 1) }

            guard let metricID = NUTMetricID.allCases.first(where: { $0.nutVariable == key }) else {
                if key == "ups.status" {
                    guard !statusSeen else { throw UPSCTextDecodeError.duplicateStatus }
                    let value = trimHorizontalWhitespace(rawValue)
                    guard value.utf8.count <= Self.maximumValueBytes, hasNoControlCharacters(value) else {
                        throw UPSCTextDecodeError.lineTooLong
                    }
                    knownValues[key] = value
                    statusSeen = true
                } else if key == "driver.name" {
                    guard !driverSeen else { throw UPSCTextDecodeError.duplicateDriverName }
                    driverSeen = true
                    let value = trimHorizontalWhitespace(rawValue)
                    guard value.utf8.count <= Self.maximumValueBytes else { throw UPSCTextDecodeError.lineTooLong }
                    if value == "apcmicrolink" { knownValues[key] = value }
                }
                continue
            }

            guard seenMetrics.insert(metricID).inserted else { throw UPSCTextDecodeError.duplicateField(metricID) }
            let value = trimHorizontalWhitespace(rawValue)
            guard value.utf8.count <= Self.maximumValueBytes, hasNoControlCharacters(value) else {
                throw UPSCTextDecodeError.lineTooLong
            }
            knownValues[key] = value
        }

        return try makeSnapshot(values: knownValues, sourceID: sourceID, capturedAt: capturedAt)
    }

    fileprivate func makeSnapshot(values: [String: String], sourceID: String, capturedAt: Date) throws -> NUTSnapshot {
        guard isValidSourceID(sourceID) else { throw UPSCTextDecodeError.invalidSourceID }
        guard capturedAt.timeIntervalSince1970.isFinite else { throw UPSCTextDecodeError.invalidCaptureTime }

        let status = try decodeStatus(values["ups.status"])
        let driverProfile: DriverProfile = values["driver.name"] == "apcmicrolink" ? .apcMicrolink : .other
        var metrics = [NUTMetricID: NUTMetric]()
        for identifier in NUTMetricID.allCases {
            let provenance: NUTMetricProvenance
            if identifier == .batteryRuntime {
                provenance = .estimated
            } else if driverProfile == .apcMicrolink &&
                        (identifier == .upsRealPower || identifier == .upsApparentPower) {
                provenance = .derivedByDriver
            } else {
                provenance = .reported
            }
            guard let value = values[identifier.nutVariable] else {
                metrics[identifier] = NUTMetric(identifier: identifier, value: nil, quality: .unavailable, provenance: provenance)
                continue
            }
            guard let number = parseNUTNumber(value), number.isFinite,
                  !identifier.mustBeNonnegative || number >= 0,
                  identifier.percentRange?.contains(number) ?? true else {
                metrics[identifier] = NUTMetric(identifier: identifier, value: nil, quality: .invalid, provenance: provenance)
                continue
            }
            metrics[identifier] = NUTMetric(identifier: identifier, value: number, quality: .available, provenance: provenance)
        }

        guard metrics.values.contains(where: { $0.quality == .available }) ||
                status.quality != .unavailable else {
            throw UPSCTextDecodeError.noUsableTelemetry
        }

        return NUTSnapshot(sourceID: sourceID, capturedAt: capturedAt, status: status, metrics: metrics)
    }

    private func decodeStatus(_ value: String?) throws -> NUTStatus {
        guard let value else {
            return NUTStatus(lineState: .unknown, flags: [], quality: .unavailable)
        }
        guard !value.isEmpty, hasNoControlCharacters(value) else { throw UPSCTextDecodeError.invalidStatus }
        let tokens = value.split(whereSeparator: { $0 == " " || $0 == "\t" })
        guard !tokens.isEmpty, tokens.count <= 16, tokens.allSatisfy({ $0.utf8.count <= 16 }) else {
            throw UPSCTextDecodeError.invalidStatus
        }

        var hasUnknownToken = false
        var onLine = false
        var onBattery = false
        var outputOff = false
        var flags = Set<NUTStatusFlag>()
        for token in tokens {
            switch token {
            case "OL": onLine = true
            case "OB": onBattery = true
            case "OFF": outputOff = true
            case "LB": flags.insert(.lowBattery)
            case "HB": flags.insert(.highBattery)
            case "RB": flags.insert(.replaceBattery)
            case "BYPASS": flags.insert(.bypass)
            case "CAL": flags.insert(.calibration)
            case "CHRG": flags.insert(.charging)
            case "DISCHRG": flags.insert(.discharging)
            case "OVER": flags.insert(.overload)
            case "TRIM": flags.insert(.trim)
            case "BOOST": flags.insert(.boost)
            case "FSD": flags.insert(.forcedShutdown)
            case "ALARM": flags.insert(.alarm)
            default: hasUnknownToken = true
            }
        }
        if outputOff { flags.insert(.outputOff) }
        let stateCount = [onLine, onBattery].filter { $0 }.count
        let state: NUTLineState
        let quality: NUTStatusQuality
        if stateCount > 1 {
            state = .unknown
            quality = .invalid
        } else if hasUnknownToken {
            state = .unknown
            quality = .unqualified
        } else if onLine {
            state = .onLine
            quality = .available
        } else if onBattery {
            state = .onBattery
            quality = .available
        } else if outputOff {
            state = .off
            quality = .available
        } else {
            state = .unknown
            quality = .available
        }
        return NUTStatus(lineState: state, flags: flags, quality: quality)
    }

    private func isValidSourceID(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 64 else { return false }
        return value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 90) ||
            ($0 >= 97 && $0 <= 122) || $0 == 45 || $0 == 46 || $0 == 95
        }
    }

    private func isValidVariableName(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 128 else { return false }
        return value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 90) ||
            ($0 >= 97 && $0 <= 122) || $0 == 46 || $0 == 95
        }
    }

    private func hasNoControlCharacters(_ value: String) -> Bool {
        value.unicodeScalars.allSatisfy { !CharacterSet.controlCharacters.contains($0) }
    }

    private func trimHorizontalWhitespace(_ value: String) -> String {
        value.trimmingCharacters(in: CharacterSet(charactersIn: " \t"))
    }

    private func parseNUTNumber(_ value: String) -> Double? {
        let bytes = Array(value.utf8)
        guard !bytes.isEmpty else { return nil }
        var index = 0
        if bytes[index] == 45 || bytes[index] == 43 { index += 1 }
        let integerStart = index
        while index < bytes.count, bytes[index] >= 48, bytes[index] <= 57 { index += 1 }
        let hasIntegerDigits = index > integerStart
        var hasFractionDigits = false
        if index < bytes.count, bytes[index] == 46 {
            index += 1
            let fractionStart = index
            while index < bytes.count, bytes[index] >= 48, bytes[index] <= 57 { index += 1 }
            hasFractionDigits = index > fractionStart
        }
        guard index == bytes.count, hasIntegerDigits || hasFractionDigits,
              let value = Double(value), value.isFinite else { return nil }
        return value
    }
}

/// Decodes native `upsc -j <ups>` output. This is available in the inspected NUT upsc implementation;
/// callers targeting older builds must handle command-level JSON option failure themselves.
public struct UPSCJSONDecoder: Sendable {
    public init() {}

    public func decode(_ data: Data, sourceID: String, capturedAt: Date) throws -> NUTSnapshot {
        guard data.count <= UPSCTextDecoder.maximumInputBytes else { throw UPSCTextDecodeError.inputTooLarge }
        let object: Any
        do {
            object = try JSONSerialization.jsonObject(with: data, options: [])
        } catch {
            throw UPSCTextDecodeError.invalidJSON
        }
        guard let entries = object as? [String: Any] else { throw UPSCTextDecodeError.invalidJSON }
        guard !entries.isEmpty else { throw UPSCTextDecodeError.emptyJSON }
        guard entries["error"] == nil else { throw UPSCTextDecodeError.invalidJSON }
        guard entries.count <= UPSCTextDecoder.maximumLines else { throw UPSCTextDecodeError.tooManyLines }

        var values = [String: String]()
        for (key, rawValue) in entries {
            guard let value = rawValue as? String else { throw UPSCTextDecodeError.nonStringJSONValue }
            guard key.utf8.count <= 128, value.utf8.count <= UPSCTextDecoder.maximumValueBytes else {
                throw UPSCTextDecodeError.lineTooLong
            }
            values[key] = value
        }
        return try UPSCTextDecoder().makeSnapshot(values: values, sourceID: sourceID, capturedAt: capturedAt)
    }
}

private enum DriverProfile {
    case other
    case apcMicrolink
}
