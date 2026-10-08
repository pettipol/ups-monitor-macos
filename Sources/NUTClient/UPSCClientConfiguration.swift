import Foundation

public enum UPSCClientConfigurationError: Error, Equatable, Sendable {
    case invalidExecutable
    case nonLoopbackAddress
    case invalidUPSName
    case invalidSourceID
    case invalidPort
    case invalidTimeout
    case invalidOutputLimit
}

public enum UPSCClientError: Error, Equatable, Sendable {
    case readInProgress
    case cancelled
    case deadlineExceeded
    case outputLimitExceeded
    case processLaunchFailed
    case processFailed
    case invalidResponse
}

public enum UPSCExecutableQualification: String, Codable, Sendable {
    /// Caller asserts that this exact executable rejects incomplete/stale NUT lists and supports
    /// JSON output plus `-A none`. No runtime fallback or automatic qualification is performed.
    case completionHardened
}

/// Fixed, loopback-only settings for one read-only `upsc` query.
public struct UPSCClientConfiguration: Sendable {
    public let executableURL: URL
    public let executableQualification: UPSCExecutableQualification
    public let upsName: String
    public let sourceID: String
    public let host: String
    public let port: Int
    public let connectTimeoutSeconds: Int
    public let overallDeadlineSeconds: Double
    public let maximumStandardOutputBytes: Int
    public let maximumStandardErrorBytes: Int

    public init(
        executableURL: URL,
        executableQualification: UPSCExecutableQualification,
        upsName: String,
        sourceID: String,
        host: String = "127.0.0.1",
        port: Int = 3493,
        connectTimeoutSeconds: Int = 3,
        overallDeadlineSeconds: Double = 8,
        maximumStandardOutputBytes: Int = 65_536,
        maximumStandardErrorBytes: Int = 4_096
    ) throws {
        guard executableURL.isFileURL,
              executableURL.path.hasPrefix("/"),
              FileManager.default.isExecutableFile(atPath: executableURL.path),
              let attributes = try? FileManager.default.attributesOfItem(atPath: executableURL.path),
              attributes[.type] as? FileAttributeType == .typeRegular else {
            throw UPSCClientConfigurationError.invalidExecutable
        }
        guard host == "127.0.0.1" else { throw UPSCClientConfigurationError.nonLoopbackAddress }
        guard Self.isSafeName(upsName) else { throw UPSCClientConfigurationError.invalidUPSName }
        guard Self.isSafeName(sourceID) else { throw UPSCClientConfigurationError.invalidSourceID }
        guard (1...65_535).contains(port) else { throw UPSCClientConfigurationError.invalidPort }
        guard (1...30).contains(connectTimeoutSeconds),
              overallDeadlineSeconds.isFinite,
              (0.1...60).contains(overallDeadlineSeconds) else {
            throw UPSCClientConfigurationError.invalidTimeout
        }
        guard (1...65_536).contains(maximumStandardOutputBytes),
              (1...16_384).contains(maximumStandardErrorBytes) else {
            throw UPSCClientConfigurationError.invalidOutputLimit
        }

        self.executableURL = executableURL.standardizedFileURL
        self.executableQualification = executableQualification
        self.upsName = upsName
        self.sourceID = sourceID
        self.host = host
        self.port = port
        self.connectTimeoutSeconds = connectTimeoutSeconds
        self.overallDeadlineSeconds = overallDeadlineSeconds
        self.maximumStandardOutputBytes = maximumStandardOutputBytes
        self.maximumStandardErrorBytes = maximumStandardErrorBytes
    }

    var arguments: [String] {
        ["-j", "-A", "none", "-W", String(connectTimeoutSeconds), "\(upsName)@\(host):\(port)"]
    }

    var environment: [String: String] {
        [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C",
            "LC_ALL": "C",
            "NUT_DEBUG_LEVEL": "0",
        ]
    }

    private static func isSafeName(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 64 else { return false }
        let bytes = Array(value.utf8)
        guard isASCIIAlphaNumeric(bytes[0]) else { return false }
        return bytes.dropFirst().allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 90) ||
            ($0 >= 97 && $0 <= 122) || $0 == 45 || $0 == 46 || $0 == 95
        }
    }

    private static func isASCIIAlphaNumeric(_ byte: UInt8) -> Bool {
        (byte >= 48 && byte <= 57) || (byte >= 65 && byte <= 90) ||
        (byte >= 97 && byte <= 122)
    }
}
