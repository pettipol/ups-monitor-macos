import CoreFoundation
import Foundation

/// Strict decoder for the private, explicitly selected managed operational v2 receipt.
struct ManagedOperationalReceipt: Decodable {
    struct RunnerResult: Decodable {
        let trigger: String
        let returncode: Int32?
        let stdout_bytes: Int64
        let stderr_bytes: Int64
        let stdout_sha256: String
        let stderr_sha256: String
        let leader_reaped: Bool
        let group_absent: Bool
        let stdout_eof: Bool
        let stderr_eof: Bool
        let consumer_quiesced: Bool

        var ownershipResolved: Bool {
            leader_reaped && group_absent && stdout_eof && stderr_eof && consumer_quiesced
        }
    }

    struct CaptureResult: Decodable {
        let schema_version: Int
        let `protocol`: String
        let state: String
        let terminal_reason: String
        let first_error: String?
        let publication_error: String?
        let source_id: String
        let session_id: String
        let started_at_unix_ms: Int64
        let published_at_unix_ms: Int64?
        let sample_count: Int64
        let end_reason: String?
        let runner_result: RunnerResult?
        let consumer_quiesced: Bool
        let publisher_quiesced: Bool
        let publisher_closed: Bool
        let terminal_published: Bool
        let ownership_resolved: Bool
    }

    struct Adapter: Decodable {
        let capture_result: CaptureResult?
        let control_reason: String?
        let adapter_error: String?
        let watcher_quiesced: Bool
        let ownership_resolved: Bool
    }

    let `protocol`: String
    let schema_version: Int
    let launch_id: String
    let adapter: Adapter

    private static let terminalReasons: Set<String> = [
        "cancelled", "device_lost", "session_lost", "guard_error", "output_error",
        "protocol_error", "capture_limit", "deadline", "child_failed", "child_unreaped",
        "io_error", "cleanup_unresolved",
    ]
    private static let endReasons: Set<String> = [
        "cancelled", "device_lost", "session_lost", "guard_error", "output_error",
    ]
    private static let runnerTriggers: Set<String> = [
        "cancelled", "child_exited", "child_nonzero_exit", "child_unreaped", "cleanup_error",
        "clock_invalid", "clock_regression", "consumer_error", "consumer_backpressure", "chunk_limit",
        "output_counter_overflow", "output_rate_limit", "output_io_failed", "output_incomplete",
        "progress_deadline", "startup_deadline", "runner_error", "cleanup_unresolved",
        "worker_start_failed", "worker_error", "progress_overflow",
    ]
    private static let firstErrors: Set<String> = terminalReasons.union(runnerTriggers).union([
        "active_publication_failed", "finalizer_start_failed", "terminal_clock_invalid",
        "terminal_publication_failed", "publisher_close_failed",
    ])
    private static let publicationErrors: Set<String> = [
        "active_publication_failed", "finalizer_start_failed", "terminal_clock_invalid",
        "terminal_publication_failed", "publisher_close_failed",
    ]
    private static let controlReasons: Set<String> = [
        "stop", "app_disconnected", "invalid_control", "signal", "control_failed",
    ]
    private static let adapterErrors: Set<String> = [
        "invalid_capture_receipt", "capture_failed", "observer_failed", "invalid_observer_receipt",
        "adapter_setup_failed", "watcher_join_failed", "control_close_failed", "handler_restore_failed",
        "invalid_control", "control_failed",
    ]

    static func decode(_ data: Data, launchID: String) throws -> Self {
        guard data.count <= 65_536, data.last == 10,
              data.dropLast().contains(10) == false,
              let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(envelope.keys) == ["protocol", "schema_version", "launch_id", "adapter"],
              validInteger(envelope["schema_version"], minimum: 2, maximum: 2),
              let adapter = envelope["adapter"] as? [String: Any],
              Set(adapter.keys) == ["capture_result", "control_reason", "adapter_error", "watcher_quiesced", "ownership_resolved"],
              validBoolean(adapter["watcher_quiesced"]), validBoolean(adapter["ownership_resolved"]) else {
            throw ManagedSyntheticError.receipt
        }
        if let control = adapter["control_reason"], !(control is NSNull) {
            guard let value = control as? String, controlReasons.contains(value) else {
                throw ManagedSyntheticError.receipt
            }
        }
        if let error = adapter["adapter_error"], !(error is NSNull) {
            guard let value = error as? String, adapterErrors.contains(value) else {
                throw ManagedSyntheticError.receipt
            }
        }
        if let rawCapture = adapter["capture_result"], !(rawCapture is NSNull) {
            guard let capture = rawCapture as? [String: Any] else { throw ManagedSyntheticError.receipt }
            try validateCaptureShape(capture)
        }

        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.protocol == "ups-monitor.managed-operational.v2",
              value.schema_version == 2,
              isUUID(launchID), value.launch_id == launchID,
              validAdapter(value.adapter) else { throw ManagedSyntheticError.receipt }
        return value
    }

    var captureState: String? { adapter.capture_result?.state }
    var captureTerminalReason: String? { adapter.capture_result?.terminal_reason }

    /// Cleanup proof is independent of data/publication success; callers still project failure.
    var provesCleanup: Bool {
        guard adapter.watcher_quiesced, adapter.ownership_resolved,
              adapter.adapter_error.map({ ["invalid_control", "control_failed"].contains($0) }) ?? true,
              let capture = adapter.capture_result,
              capture.state == "stopped" || capture.state == "failed",
              capture.source_id == "apcmicrolink-hidapi-operational",
              Self.validUUID32(capture.session_id),
              capture.started_at_unix_ms >= 0,
              capture.published_at_unix_ms.map({ $0 >= capture.started_at_unix_ms }) ?? (capture.state == "failed"),
              capture.sample_count >= 0,
              capture.runner_result != nil,
              let runner = capture.runner_result,
              runner.ownershipResolved,
              capture.consumer_quiesced, capture.publisher_quiesced,
              capture.publisher_closed, capture.ownership_resolved else { return false }

        if capture.state == "stopped" {
            return capture.terminal_reason == "cancelled"
                && capture.first_error == nil
                && capture.publication_error == nil
                && capture.published_at_unix_ms != nil
                && capture.terminal_published
                && capture.end_reason == "cancelled"
                && runner.trigger == "cancelled"
                && runner.returncode == 0
        }
        // A failed capture can have settled ownership even if publication failed.
        return Self.terminalReasons.contains(capture.terminal_reason)
    }

    private static func validAdapter(_ adapter: Adapter) -> Bool {
        if let reason = adapter.control_reason, !controlReasons.contains(reason) { return false }
        if let error = adapter.adapter_error, !adapterErrors.contains(error) { return false }
        guard let capture = adapter.capture_result else { return true }
        guard capture.schema_version == 2, capture.protocol == "ups-monitor.continuous.v2",
              ["stopped", "failed", "unresolved"].contains(capture.state),
              terminalReasons.contains(capture.terminal_reason),
              capture.first_error.map(firstErrors.contains) ?? true,
              capture.publication_error.map(publicationErrors.contains) ?? true,
              capture.source_id == "apcmicrolink-hidapi-operational",
              validUUID32(capture.session_id),
              (0...9_007_199_254_740_991).contains(capture.started_at_unix_ms),
              capture.published_at_unix_ms.map({ (capture.started_at_unix_ms...9_007_199_254_740_991).contains($0) }) ?? true,
              (0...9_007_199_254_740_991).contains(capture.sample_count),
              capture.end_reason.map(endReasons.contains) ?? true else { return false }
        if let runner = capture.runner_result {
            guard runner.stdout_bytes >= 0, runner.stderr_bytes >= 0,
                  runner.stdout_sha256.count == 64, runner.stderr_sha256.count == 64,
                  runner.stdout_sha256.utf8.allSatisfy(isLowerHex),
                  runner.stderr_sha256.utf8.allSatisfy(isLowerHex),
                  runner.trigger.isEmpty == false, runnerTriggers.contains(runner.trigger) else { return false }
        }
        if capture.state == "stopped" {
            guard capture.terminal_reason == "cancelled", capture.first_error == nil,
                  capture.publication_error == nil, capture.published_at_unix_ms != nil,
                  capture.terminal_published, capture.end_reason == "cancelled",
                  let runner = capture.runner_result, runner.trigger == "cancelled", runner.returncode == 0 else { return false }
        }
        return true
    }

    private static func validateCaptureShape(_ value: [String: Any]) throws {
        let keys: Set<String> = [
            "schema_version", "protocol", "state", "terminal_reason", "first_error", "publication_error",
            "source_id", "session_id", "started_at_unix_ms", "published_at_unix_ms", "sample_count",
            "end_reason", "runner_result", "consumer_quiesced", "publisher_quiesced", "publisher_closed",
            "terminal_published", "ownership_resolved",
        ]
        guard Set(value.keys) == keys,
              validInteger(value["schema_version"], minimum: 2, maximum: 2),
              validInteger(value["started_at_unix_ms"], minimum: 0, maximum: 9_007_199_254_740_991),
              validInteger(value["sample_count"], minimum: 0, maximum: 9_007_199_254_740_991),
              nullableInteger(value["published_at_unix_ms"], minimum: 0, maximum: 9_007_199_254_740_991),
              nullableString(value["first_error"]), nullableString(value["publication_error"]),
              nullableString(value["end_reason"]),
              validBoolean(value["consumer_quiesced"]), validBoolean(value["publisher_quiesced"]),
              validBoolean(value["publisher_closed"]), validBoolean(value["terminal_published"]),
              validBoolean(value["ownership_resolved"]) else { throw ManagedSyntheticError.receipt }
        if let rawRunner = value["runner_result"], !(rawRunner is NSNull) {
            guard let runner = rawRunner as? [String: Any], Set(runner.keys) == [
                "trigger", "returncode", "stdout_bytes", "stderr_bytes", "stdout_sha256", "stderr_sha256",
                "leader_reaped", "group_absent", "stdout_eof", "stderr_eof", "consumer_quiesced",
            ], nullableInteger(runner["returncode"], minimum: Int64(Int32.min), maximum: Int64(Int32.max)),
                  validInteger(runner["stdout_bytes"], minimum: 0, maximum: Int64.max),
                  validInteger(runner["stderr_bytes"], minimum: 0, maximum: Int64.max),
                  validBoolean(runner["leader_reaped"]), validBoolean(runner["group_absent"]),
                  validBoolean(runner["stdout_eof"]), validBoolean(runner["stderr_eof"]),
                  validBoolean(runner["consumer_quiesced"]) else { throw ManagedSyntheticError.receipt }
        }
    }

    private static func validInteger(_ value: Any?, minimum: Int64, maximum: Int64) -> Bool {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: number.objCType)) else {
            return false
        }
        let integer = number.int64Value
        return integer >= minimum && integer <= maximum
    }

    private static func nullableInteger(_ value: Any?, minimum: Int64, maximum: Int64) -> Bool {
        guard let value else { return false }
        return value is NSNull || validInteger(value, minimum: minimum, maximum: maximum)
    }

    private static func validBoolean(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID()
    }

    private static func nullableString(_ value: Any?) -> Bool {
        guard let value else { return false }
        if value is NSNull { return true }
        guard let string = value as? String else { return false }
        return string.utf8.count <= 128
    }

    private static func isUUID(_ value: String) -> Bool {
        UUID(uuidString: value)?.uuidString.lowercased() == value
    }

    private static func validUUID32(_ value: String) -> Bool {
        value.utf8.count == 32 && value.utf8.allSatisfy(isLowerHex)
    }

    private static func isLowerHex(_ value: UInt8) -> Bool {
        (48...57).contains(value) || (97...102).contains(value)
    }
}
