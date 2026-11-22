import Darwin
import Foundation

public struct ManagedSyntheticProcessExit: Sendable {
    public let returnCode: Int32
    public let receipt: Data
    public let outputWithinBounds: Bool
    public init(returnCode: Int32, receipt: Data, outputWithinBounds: Bool) {
        self.returnCode = returnCode; self.receipt = receipt; self.outputWithinBounds = outputWithinBounds
    }
}
public enum ManagedSyntheticProcessEvent: Sendable {
    case receipt(Data), fault, finished(ManagedSyntheticProcessExit)
}
@MainActor public protocol ManagedSyntheticProcessHandle: AnyObject {
    func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws
    func requestStop()
}

/// Foundation owns/reaps this one supervisor. Ordinary Stop never terminates it.
@MainActor public final class ManagedSyntheticProcess: ManagedSyntheticProcessHandle {
    private let process = Process()
    private let input = Pipe(), output = Pipe(), error = Pipe()
    private var stopRequested = false
    private var sink: ManagedSyntheticDrain?
    public init() {}

    public func start(_ launch: ManagedSyntheticLaunch, receive: @escaping @MainActor (ManagedSyntheticProcessEvent) -> Void) throws {
        try Self.setCloseOnExec([
            input.fileHandleForReading, input.fileHandleForWriting,
            output.fileHandleForReading, output.fileHandleForWriting,
            error.fileHandleForReading, error.fileHandleForWriting,
        ])
        let writer = input.fileHandleForWriting.fileDescriptor
        guard fcntl(writer, F_SETNOSIGPIPE, 1) == 0,
              fcntl(writer, F_SETFL, fcntl(writer, F_GETFL) | O_NONBLOCK) == 0 else {
            throw ManagedSyntheticError.ownership
        }
        let sink = ManagedSyntheticDrain { event in Task { @MainActor in receive(event) } }
        self.sink = sink
        output.fileHandleForReading.readabilityHandler = { handle in sink.read(handle, standardError: false) }
        error.fileHandleForReading.readabilityHandler = { handle in sink.read(handle, standardError: true) }
        process.executableURL = launch.executableURL
        process.arguments = launch.arguments
        process.environment = ["PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"]
        process.standardInput = input; process.standardOutput = output; process.standardError = error
        process.terminationHandler = { process in sink.reaped(process.terminationStatus) }
        do {
            try process.run()
            // With Pipe objects, Foundation closes the child-side endpoints in
            // the parent during run(). Closing them again can fabricate failure.
        } catch {
            requestStop() // EOF even if launch completed before an ambiguous error.
            throw error
        }
    }
    static func setCloseOnExec(_ handles: [FileHandle]) throws {
        for handle in handles {
            let descriptor = handle.fileDescriptor
            let flags = fcntl(descriptor, F_GETFD)
            guard flags >= 0, fcntl(descriptor, F_SETFD, flags | FD_CLOEXEC) == 0 else {
                throw ManagedSyntheticError.ownership
            }
        }
    }
    public func requestStop() {
        guard !stopRequested else { return }
        stopRequested = true
        let bytes: [UInt8] = Array("STOP\n".utf8)
        let count = bytes.withUnsafeBytes { Darwin.write(input.fileHandleForWriting.fileDescriptor, $0.baseAddress, $0.count) }
        // F_SETNOSIGPIPE makes an already-closed reader a local error, never app death.
        // Short writes/errors still close the only writer: EOF requests cancellation.
        if count != bytes.count { sink?.fault() }
        do { try input.fileHandleForWriting.close() } catch { sink?.fault() }
    }
}

/// Only this lock-protected object runs on Foundation's pipe/termination queues.
private final class ManagedSyntheticDrain: @unchecked Sendable {
    private let lock = NSLock()
    private let receive: @Sendable (ManagedSyntheticProcessEvent) -> Void
    private var stdout = Data()
    private var stderrBytes = 0
    private var stdoutEOF = false, stderrEOF = false, sentReceipt = false, sentFault = false, sentExit = false
    private var returnCode: Int32?
    private var valid = true
    init(receive: @escaping @Sendable (ManagedSyntheticProcessEvent) -> Void) { self.receive = receive }

    func read(_ handle: FileHandle, standardError: Bool) {
        do {
            let data = try handle.read(upToCount: 4_096) ?? Data()
            var events: [ManagedSyntheticProcessEvent] = []
            lock.lock()
            if data.isEmpty {
                if standardError { stderrEOF = true } else { stdoutEOF = true }
                handle.readabilityHandler = nil
                try? handle.close()
            } else if standardError {
                stderrBytes = min(4_097, stderrBytes + data.count)
                if stderrBytes > 4_096 { valid = false }
            } else {
                if stdout.count <= 65_536 - data.count { stdout.append(data) } else { valid = false }
                if !sentReceipt, let newline = stdout.firstIndex(of: 10) {
                    sentReceipt = true; events.append(.receipt(Data(stdout[...newline])))
                }
            }
            if !valid && !sentFault { sentFault = true; events.append(.fault) }
            if let event = finishedLocked() { events.append(event) }
            lock.unlock()
            for event in events { receive(event) }
        } catch {
            handle.readabilityHandler = nil
            fault() // Retain the fd/object; read failure is not a fabricated EOF.
        }
    }
    func fault() {
        lock.lock(); valid = false
        let shouldSend = !sentFault; sentFault = true
        lock.unlock()
        if shouldSend { receive(.fault) }
    }
    func reaped(_ status: Int32) {
        lock.lock(); returnCode = status
        let event = finishedLocked()
        lock.unlock()
        if let event { receive(event) }
    }
    private func finishedLocked() -> ManagedSyntheticProcessEvent? {
        guard !sentExit, stdoutEOF, stderrEOF, let returnCode else { return nil }
        sentExit = true
        return .finished(ManagedSyntheticProcessExit(returnCode: returnCode, receipt: stdout, outputWithinBounds: valid))
    }
}
