import Foundation

/// Decodes the pinned stdout format emitted by the synthetic Microlink driver runs.
public struct NUTDriverDumpDecoder: Sendable {
    private static let preamble = "Network UPS Tools 2.8.5.1 (development iteration after 2.8.5) - APC Microlink protocol driver 0.05\nWarning: This is an experimental driver.\nSome features may not function correctly.\n\n"

    public init() {}

    public func decode(_ data: Data, sourceID: String, capturedAt: Date) throws -> NUTSnapshot {
        guard data.count <= UPSCTextDecoder.maximumInputBytes else { throw UPSCTextDecodeError.inputTooLarge }
        guard let text = String(data: data, encoding: .utf8) else { throw UPSCTextDecodeError.invalidUTF8 }
        guard text.hasPrefix(Self.preamble), text.hasSuffix("\n") else {
            throw UPSCTextDecodeError.invalidDriverDump
        }
        let body = String(text.dropFirst(Self.preamble.count))
        guard !body.isEmpty else { throw UPSCTextDecodeError.invalidDriverDump }

        let lines = text.utf8.split(separator: 10, omittingEmptySubsequences: false)
        guard lines.count <= UPSCTextDecoder.maximumLines else { throw UPSCTextDecodeError.tooManyLines }
        for line in lines {
            guard line.count <= UPSCTextDecoder.maximumLineBytes else { throw UPSCTextDecodeError.lineTooLong }
        }

        return try UPSCTextDecoder().decodeDriverDumpListing(body, sourceID: sourceID, capturedAt: capturedAt)
    }
}
