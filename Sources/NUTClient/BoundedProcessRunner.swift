import Darwin
import Foundation

struct BoundedProcessRunner: Sendable {
    let invocation: UPSCProcessInvocation

    func run() async throws -> Data {
        let execution = ProcessExecution(invocation: invocation)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                execution.start(continuation)
            }
        } onCancel: {
            execution.cancel()
        }
    }
}

private final class ProcessExecution: @unchecked Sendable {
    private enum Channel {
        case standardOutput
        case standardError
    }

    private let invocation: UPSCProcessInvocation
    private let queue = DispatchQueue(label: "NUTClient.ProcessExecution")
    private let cancellationLock = NSLock()
    private var cancellationRequested = false
    private var process: Process?
    private var outputPipe: Pipe?
    private var errorPipe: Pipe?
    private var outputReadSource: DispatchSourceRead?
    private var errorReadSource: DispatchSourceRead?
    private var timer: DispatchSourceTimer?
    private var forceKillTimer: DispatchSourceTimer?
    private var continuation: CheckedContinuation<Data, Error>?
    private var output = Data()
    private var errorByteCount = 0
    private var outputEOF = false
    private var errorEOF = false
    private var processExited = false
    private var terminationStatus: Int32?
    private var failure: UPSCClientError?
    private var completed = false

    init(invocation: UPSCProcessInvocation) {
        self.invocation = invocation
    }

    func start(_ continuation: CheckedContinuation<Data, Error>) {
        queue.async {
            self.continuation = continuation
            if self.isCancellationRequested {
                self.finish(.failure(UPSCClientError.cancelled))
                return
            }
            self.launch()
        }
    }

    func cancel() {
        cancellationLock.lock()
        cancellationRequested = true
        cancellationLock.unlock()
        queue.async {
            // The cancellation handler can run before start installs the continuation.
            // In that case start observes the flag and completes it itself.
            if self.continuation != nil { self.fail(.cancelled) }
        }
    }

    private var isCancellationRequested: Bool {
        cancellationLock.lock()
        defer { cancellationLock.unlock() }
        return cancellationRequested
    }

    private func launch() {
        let child = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        child.executableURL = invocation.executableURL
        child.arguments = invocation.arguments
        child.environment = invocation.environment
        child.currentDirectoryURL = URL(fileURLWithPath: "/", isDirectory: true)
        child.standardInput = FileHandle.nullDevice
        child.standardOutput = stdout
        child.standardError = stderr
        child.terminationHandler = { [weak self] process in
            guard let owner = self else { return }
            let status = process.terminationStatus
            owner.queue.async { owner.processDidExit(status: status) }
        }

        process = child
        outputPipe = stdout
        errorPipe = stderr
        let outputSource = makeReadSource(for: stdout.fileHandleForReading, channel: .standardOutput)
        let errorSource = makeReadSource(for: stderr.fileHandleForReading, channel: .standardError)
        guard let outputSource, let errorSource else {
            outputSource?.resume()
            outputSource?.cancel()
            errorSource?.resume()
            errorSource?.cancel()
            finish(.failure(UPSCClientError.processLaunchFailed))
            return
        }
        outputReadSource = outputSource
        errorReadSource = errorSource
        outputReadSource?.resume()
        errorReadSource?.resume()

        do {
            try child.run()
            try? stdout.fileHandleForWriting.close()
            try? stderr.fileHandleForWriting.close()
        } catch {
            finish(.failure(UPSCClientError.processLaunchFailed))
            return
        }

        let deadline = DispatchSource.makeTimerSource(queue: queue)
        deadline.schedule(deadline: .now() + invocation.overallDeadlineSeconds)
        deadline.setEventHandler { [weak self] in self?.fail(.deadlineExceeded) }
        timer = deadline
        deadline.resume()
    }

    private func makeReadSource(for handle: FileHandle, channel: Channel) -> DispatchSourceRead? {
        let descriptor = handle.fileDescriptor
        let flags = fcntl(descriptor, F_GETFL)
        guard flags >= 0, fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) == 0 else {
            return nil
        }
        let source = DispatchSource.makeReadSource(fileDescriptor: descriptor, queue: queue)
        source.setEventHandler { [weak self] in self?.drain(descriptor, from: channel) }
        source.setCancelHandler { try? handle.close() }
        return source
    }

    private func drain(_ descriptor: Int32, from channel: Channel) {
        var buffer = [UInt8](repeating: 0, count: 4_096)
        // Yield to deadline and termination events even if a child keeps the pipe
        // continuously readable.
        for _ in 0..<8 where !completed {
            let count = buffer.withUnsafeMutableBytes { rawBuffer in
                Darwin.read(descriptor, rawBuffer.baseAddress, rawBuffer.count)
            }
            if count > 0 {
                received(Data(buffer.prefix(count)), from: channel)
                continue
            }
            if count == 0 {
                switch channel {
                case .standardOutput:
                    outputEOF = true
                    outputReadSource?.cancel()
                    outputReadSource = nil
                case .standardError:
                    errorEOF = true
                    errorReadSource?.cancel()
                    errorReadSource = nil
                }
                finishIfReady()
                return
            }
            if errno == EAGAIN || errno == EWOULDBLOCK { return }
            fail(.processFailed)
            return
        }
    }

    private func received(_ data: Data, from channel: Channel) {
        guard !completed, failure == nil else { return }
        switch channel {
        case .standardOutput:
            guard data.count <= invocation.maximumStandardOutputBytes,
                  output.count <= invocation.maximumStandardOutputBytes - data.count else {
                fail(.outputLimitExceeded)
                return
            }
            output.append(data)
        case .standardError:
            guard data.count <= invocation.maximumStandardErrorBytes,
                  errorByteCount <= invocation.maximumStandardErrorBytes - data.count else {
                fail(.outputLimitExceeded)
                return
            }
            errorByteCount += data.count
        }
    }

    private func processDidExit(status: Int32) {
        guard !processExited else { return }
        processExited = true
        terminationStatus = status
        if failure != nil {
            finish(.failure(failure!))
        } else if status != 0 {
            finish(.failure(UPSCClientError.processFailed))
        } else {
            finishIfReady()
        }
    }

    private func finishIfReady() {
        guard processExited, outputEOF, errorEOF else { return }
        guard terminationStatus == 0 else {
            finish(.failure(UPSCClientError.processFailed))
            return
        }
        finish(.success(output))
    }

    private func fail(_ error: UPSCClientError) {
        guard !completed, failure == nil else { return }
        failure = error
        guard let process, process.isRunning else {
            if processExited || process == nil { finish(.failure(error)) }
            return
        }

        process.terminate()
        let forceKill = DispatchSource.makeTimerSource(queue: queue)
        forceKill.schedule(deadline: .now() + .milliseconds(200))
        forceKill.setEventHandler { [weak process] in
            guard let process, process.isRunning else { return }
            let childPID = process.processIdentifier
            if childPID > 0 { _ = Darwin.kill(childPID, SIGKILL) }
        }
        forceKillTimer?.cancel()
        forceKillTimer = forceKill
        forceKill.resume()
    }

    private func finish(_ result: Result<Data, Error>) {
        guard !completed else { return }
        completed = true
        timer?.cancel()
        forceKillTimer?.cancel()
        outputReadSource?.cancel()
        errorReadSource?.cancel()
        try? outputPipe?.fileHandleForWriting.close()
        try? errorPipe?.fileHandleForWriting.close()
        continuation?.resume(with: result)
        continuation = nil
    }
}
