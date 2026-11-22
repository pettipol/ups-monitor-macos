import CryptoKit
import Foundation
import NUTData
import UPSModel

public enum NUTObservationOrigin: String, Sendable {
    case syntheticDriverDump = "synthetic_driver_dump"
    case archivedSupervisedDriverDump = "archived_supervised_driver_dump"
}

public enum NUTObservationProcessStatus: String, Sendable {
    case exited
    case timedOut = "timed_out"
    case outputLimit = "output_limit"
    case outputIncomplete = "output_incomplete"
    case cancelled
    case unreaped
    case error
}

public enum NUTObservationTrigger: String, Sendable {
    case completed
    case timeout
    case outputLimit = "output_limit"
    case outputIncomplete = "output_incomplete"
    case cancelled
    case none
}

public struct SupervisedNUTObservation: Sendable {
    public let origin: NUTObservationOrigin
    public let status: NUTObservationProcessStatus
    public let trigger: NUTObservationTrigger
    public let returnCode: Int?
    public let errorCode: String?
    public let stdout: Data
    public let stderr: Data
    public let stdoutBytes: Int
    public let stderrBytes: Int
    public let maximumOutputBytes: Int
    public let executableSHA256: String
    public let stdoutSHA256: String
    public let stderrSHA256: String
    public let startedAt: Date
    public let finishedAt: Date

    public init(
        origin: NUTObservationOrigin, status: NUTObservationProcessStatus, trigger: NUTObservationTrigger,
        returnCode: Int?, errorCode: String?, stdout: Data, stderr: Data, stdoutBytes: Int,
        stderrBytes: Int, maximumOutputBytes: Int, executableSHA256: String, stdoutSHA256: String,
        stderrSHA256: String, startedAt: Date, finishedAt: Date
    ) {
        self.origin = origin
        self.status = status
        self.trigger = trigger
        self.returnCode = returnCode
        self.errorCode = errorCode
        self.stdout = stdout
        self.stderr = stderr
        self.stdoutBytes = stdoutBytes
        self.stderrBytes = stderrBytes
        self.maximumOutputBytes = maximumOutputBytes
        self.executableSHA256 = executableSHA256
        self.stdoutSHA256 = stdoutSHA256
        self.stderrSHA256 = stderrSHA256
        self.startedAt = startedAt
        self.finishedAt = finishedAt
    }
}

public enum NUTObservationImportError: Error, Equatable, Sendable {
    case unsuccessfulProcess
    case invalidByteCounts
    case invalidOutputLimit
    case invalidDigest
    case executablePinMismatch
    case invalidDates
    case invalidSource
    case invalidDump
}

public struct ImportedNUTObservation: Sendable {
    public let origin: NUTObservationOrigin
    public let startedAt: Date
    public let finishedAt: Date
    public let unqualifiedSnapshot: MonitorSnapshot
    public let dataQualified = false

    public init(origin: NUTObservationOrigin, startedAt: Date, finishedAt: Date, unqualifiedSnapshot: MonitorSnapshot) {
        self.origin = origin
        self.startedAt = startedAt
        self.finishedAt = finishedAt
        self.unqualifiedSnapshot = unqualifiedSnapshot
    }
}

public enum NUTObservationAdapter {
    public static func decode(
        _ observation: SupervisedNUTObservation,
        source: MonitorSource,
        expectedExecutableSHA256: String,
        now: Date
    ) throws -> ImportedNUTObservation {
        guard observation.status == .exited, observation.trigger == .completed,
              observation.returnCode == 0, observation.errorCode == nil else {
            throw NUTObservationImportError.unsuccessfulProcess
        }
        guard observation.stdoutBytes >= 0, observation.stderrBytes >= 0,
              observation.stdoutBytes == observation.stdout.count,
              observation.stderrBytes == observation.stderr.count else {
            throw NUTObservationImportError.invalidByteCounts
        }
        guard observation.maximumOutputBytes >= 1, observation.maximumOutputBytes <= 1_048_576,
              observation.stdoutBytes <= observation.maximumOutputBytes,
              observation.stderrBytes <= observation.maximumOutputBytes - observation.stdoutBytes else {
            throw NUTObservationImportError.invalidOutputLimit
        }
        guard isSHA256(observation.executableSHA256), isSHA256(expectedExecutableSHA256),
              isSHA256(observation.stdoutSHA256), isSHA256(observation.stderrSHA256) else {
            throw NUTObservationImportError.invalidDigest
        }
        guard observation.executableSHA256.caseInsensitiveCompare(expectedExecutableSHA256) == .orderedSame else {
            throw NUTObservationImportError.executablePinMismatch
        }
        guard matches(observation.stdout, observation.stdoutSHA256), matches(observation.stderr, observation.stderrSHA256) else {
            throw NUTObservationImportError.invalidDigest
        }
        guard source.provider == .nut else { throw NUTObservationImportError.invalidSource }
        do { try source.validate() } catch { throw NUTObservationImportError.invalidSource }
        guard isFinite(observation.startedAt), isFinite(observation.finishedAt), isFinite(now),
              observation.startedAt <= observation.finishedAt, observation.finishedAt <= now else {
            throw NUTObservationImportError.invalidDates
        }

        do {
            let decoded = try NUTDriverDumpDecoder().decode(
                observation.stdout, sourceID: source.id, capturedAt: observation.startedAt
            )
            let snapshot = try MonitorSnapshotAdapter.fromNUT(decoded, source: source)
            return ImportedNUTObservation(
                origin: observation.origin, startedAt: observation.startedAt,
                finishedAt: observation.finishedAt, unqualifiedSnapshot: snapshot
            )
        } catch {
            throw NUTObservationImportError.invalidDump
        }
    }

    private static func isFinite(_ date: Date) -> Bool { date.timeIntervalSince1970.isFinite }

    private static func isSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0)
        }
    }

    private static func matches(_ data: Data, _ expected: String) -> Bool {
        let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        return actual.caseInsensitiveCompare(expected) == .orderedSame
    }
}
