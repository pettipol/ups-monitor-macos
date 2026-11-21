import Foundation
import NUTData
import UPSModel

public enum NUTObservationReceiptDecodeError: Error, Equatable, Sendable {
    case invalidReceipt
}

public struct NUTObservationReceiptDecoder: Sendable {
    public init() {}

    public func decode(
        _ receipt: Data,
        stdout: Data,
        stderr: Data,
        origin: NUTObservationOrigin,
        source: MonitorSource,
        expectedExecutableSHA256: String,
        now: Date
    ) throws -> ImportedNUTObservation {
        guard receipt.count <= 8_192,
              String(data: receipt, encoding: .utf8) != nil,
              !receipt.contains(0) else {
            throw NUTObservationReceiptDecodeError.invalidReceipt
        }

        let wire: ReceiptWire
        do {
            // JSONDecoder auto-detects UTF-16/32; the receipt contract permits UTF-8 only.
            wire = try JSONDecoder().decode(ReceiptWire.self, from: receipt)
        } catch {
            throw NUTObservationReceiptDecodeError.invalidReceipt
        }

        guard wire.schemaVersion == 1,
              wire.dataQualified == false,
              wire.errorIsNull,
              let status = NUTObservationProcessStatus(rawValue: wire.status),
              let trigger = NUTObservationTrigger(rawValue: wire.trigger),
              let startedAt = finiteDate(seconds: wire.startedAtUnixSeconds),
              let finishedAt = finiteDate(seconds: wire.finishedAtUnixSeconds) else {
            throw NUTObservationReceiptDecodeError.invalidReceipt
        }

        let observation = SupervisedNUTObservation(
            origin: origin,
            status: status,
            trigger: trigger,
            returnCode: wire.returnCode.map(Int.init),
            errorCode: nil,
            stdout: stdout,
            stderr: stderr,
            stdoutBytes: wire.stdoutBytes,
            stderrBytes: wire.stderrBytes,
            maximumOutputBytes: wire.maximumOutputBytes,
            executableSHA256: wire.executableSHA256,
            stdoutSHA256: wire.stdoutSHA256,
            stderrSHA256: wire.stderrSHA256,
            startedAt: startedAt,
            finishedAt: finishedAt
        )
        return try NUTObservationAdapter.decode(
            observation,
            source: source,
            expectedExecutableSHA256: expectedExecutableSHA256,
            now: now
        )
    }

    private func finiteDate(seconds: Double) -> Date? {
        guard seconds.isFinite else { return nil }
        let date = Date(timeIntervalSince1970: seconds)
        return date.timeIntervalSince1970.isFinite ? date : nil
    }
}

private struct ReceiptWire: Decodable {
    let schemaVersion: Int
    let status: String
    let trigger: String
    let returnCode: Int64?
    let stdoutBytes: Int
    let stderrBytes: Int
    let maximumOutputBytes: Int
    let executableSHA256: String
    let stdoutSHA256: String
    let stderrSHA256: String
    let startedAtUnixSeconds: Double
    let finishedAtUnixSeconds: Double
    let dataQualified: Bool
    let errorIsNull: Bool

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        let expectedKeys: Set<String> = [
            "schema_version", "status", "trigger", "returncode", "stdout_bytes", "stderr_bytes",
            "maximum_output_bytes", "executable_sha256", "stdout_sha256", "stderr_sha256",
            "started_at_unix_seconds", "finished_at_unix_seconds", "data_qualified", "error",
        ]
        guard Set(container.allKeys.map(\.stringValue)) == expectedKeys else {
            throw NUTObservationReceiptDecodeError.invalidReceipt
        }
        schemaVersion = try container.decode(Int.self, forKey: DynamicCodingKey("schema_version"))
        status = try container.decode(String.self, forKey: DynamicCodingKey("status"))
        trigger = try container.decode(String.self, forKey: DynamicCodingKey("trigger"))
        returnCode = try container.decodeIfPresent(Int64.self, forKey: DynamicCodingKey("returncode"))
        stdoutBytes = try container.decode(Int.self, forKey: DynamicCodingKey("stdout_bytes"))
        stderrBytes = try container.decode(Int.self, forKey: DynamicCodingKey("stderr_bytes"))
        maximumOutputBytes = try container.decode(Int.self, forKey: DynamicCodingKey("maximum_output_bytes"))
        executableSHA256 = try container.decode(String.self, forKey: DynamicCodingKey("executable_sha256"))
        stdoutSHA256 = try container.decode(String.self, forKey: DynamicCodingKey("stdout_sha256"))
        stderrSHA256 = try container.decode(String.self, forKey: DynamicCodingKey("stderr_sha256"))
        startedAtUnixSeconds = try container.decode(Double.self, forKey: DynamicCodingKey("started_at_unix_seconds"))
        finishedAtUnixSeconds = try container.decode(Double.self, forKey: DynamicCodingKey("finished_at_unix_seconds"))
        dataQualified = try container.decode(Bool.self, forKey: DynamicCodingKey("data_qualified"))
        errorIsNull = try container.decodeNil(forKey: DynamicCodingKey("error"))
        guard errorIsNull,
              NUTObservationProcessStatus(rawValue: status) != nil,
              NUTObservationTrigger(rawValue: trigger) != nil else {
            throw NUTObservationReceiptDecodeError.invalidReceipt
        }
    }
}

private struct DynamicCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?

    init(_ stringValue: String) {
        self.stringValue = stringValue
        self.intValue = nil
    }

    init?(stringValue: String) {
        self.init(stringValue)
    }

    init?(intValue: Int) {
        self.stringValue = String(intValue)
        self.intValue = intValue
    }
}
