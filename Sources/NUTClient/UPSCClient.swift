import Foundation
import NUTData

/// Reads a single explicitly configured UPS through the installed NUT `upsc` executable.
/// A rejected read is an error; this type does not return or preserve a previous snapshot.
public actor UPSCClient {
    private let configuration: UPSCClientConfiguration

    public init(configuration: UPSCClientConfiguration) {
        self.configuration = configuration
    }

    /// Captures one output snapshot. By default, the timestamp is taken after the child exits.
    public func readSnapshot(capturedAt requestedCaptureTime: Date? = nil) async throws -> NUTSnapshot {
        guard SourceReadRegistry.shared.acquire(sourceID: configuration.sourceID) else {
            throw UPSCClientError.readInProgress
        }
        defer { SourceReadRegistry.shared.release(sourceID: configuration.sourceID) }

        guard !Task.isCancelled else { throw UPSCClientError.cancelled }
        let invocation = UPSCProcessInvocation(
            executableURL: configuration.executableURL,
            arguments: configuration.arguments,
            environment: configuration.environment,
            overallDeadlineSeconds: configuration.overallDeadlineSeconds,
            maximumStandardOutputBytes: configuration.maximumStandardOutputBytes,
            maximumStandardErrorBytes: configuration.maximumStandardErrorBytes
        )
        let output = try await BoundedProcessRunner(invocation: invocation).run()
        guard !Task.isCancelled else { throw UPSCClientError.cancelled }

        do {
            return try UPSCJSONDecoder().decode(
                output,
                sourceID: configuration.sourceID,
                capturedAt: requestedCaptureTime ?? Date()
            )
        } catch {
            throw UPSCClientError.invalidResponse
        }
    }
}

struct UPSCProcessInvocation: Sendable {
    let executableURL: URL
    let arguments: [String]
    let environment: [String: String]
    let overallDeadlineSeconds: Double
    let maximumStandardOutputBytes: Int
    let maximumStandardErrorBytes: Int
}

private final class SourceReadRegistry: @unchecked Sendable {
    static let shared = SourceReadRegistry()

    private let lock = NSLock()
    private var activeSourceIDs = Set<String>()

    func acquire(sourceID: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return activeSourceIDs.insert(sourceID).inserted
    }

    func release(sourceID: String) {
        lock.lock()
        activeSourceIDs.remove(sourceID)
        lock.unlock()
    }
}
