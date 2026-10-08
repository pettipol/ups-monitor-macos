import Darwin
import Foundation
import XCTest
import NUTData
import UPSModel
import UPSRuntime
@testable import NUTClient

/// Opt-in integration coverage for one explicitly provided, completion-hardened upsc.
/// Every server is synthetic, binds only 127.0.0.1 on an ephemeral port, and is owned here.
final class UPSCInteropTests: XCTestCase {
    func testRuntimeReaderAdaptsRichSyntheticClientOutput() async throws {
        let inputs = try await interopInputs()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("nut-runtime-interop-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                               attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let fixture = try SyntheticNUTFixture.start(python: inputs.pythonURL, directory: directory, mode: "complete")
        defer { fixture.stop() }
        let configuration = try UPSCClientConfiguration(executableURL: inputs.executableURL,
                                                        executableQualification: .completionHardened,
                                                        upsName: "fixture", sourceID: "opaque-runtime", port: fixture.port)
        let reader = try NUTSnapshotReader(configuration: configuration, expectedSHA256: inputs.digest,
                                           sessionID: "synthetic-session")
        let snapshots = try await reader.read()
        let snapshot = try XCTUnwrap(snapshots.first)
        XCTAssertEqual(snapshots.count, 1)
        XCTAssertEqual(snapshot.source.provider, .nut)
        XCTAssertEqual(snapshot.source.id, "opaque-runtime")
        XCTAssertEqual(snapshot.status.lineState, .onLine)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .inputVoltage }?.value, 231.5)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .outputVoltage }?.value, 230.2)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .upsRealPower }?.unit, .watts)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .upsRealPower }?.value, 180)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .upsRealPower }?.provenance, .driverDerived)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .upsApparentPower }?.unit, .voltAmps)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .upsApparentPower }?.value, 220)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .batteryRuntime }?.provenance, .estimated)
        let encoded = try JSONEncoder().encode(snapshot)
        XCTAssertFalse(String(decoding: encoded, as: UTF8.self).contains("SYNTHETIC-PRIVATE-SERIAL"))
        try fixture.waitForExit()
        let result = try fixture.readResult()
        XCTAssertEqual(result.errors, [])
        XCTAssertEqual(result.commands.last, "LIST VAR fixture")
        XCTAssertTrue(result.commands.allSatisfy { $0 == "STARTTLS" || $0 == "LIST VAR fixture" })
    }

    func testPatchedUPSCCompletesOnlyWholeSyntheticLists() async throws {
        let inputs = try await interopInputs()
        let temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("nut-upsc-interop-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: temporaryDirectory) }

        for mode in ["complete", "truncated", "error", "wrong-end", "short-end", "extra-end"] {
            let fixture = try SyntheticNUTFixture.start(
                python: inputs.pythonURL,
                directory: temporaryDirectory,
                mode: mode
            )
            defer { fixture.stop() }

            let configuration = try UPSCClientConfiguration(
                executableURL: inputs.executableURL,
                executableQualification: .completionHardened,
                upsName: "fixture",
                sourceID: "interop-\(mode)",
                port: fixture.port,
                connectTimeoutSeconds: 2,
                overallDeadlineSeconds: 6
            )
            let reader = try NUTSnapshotReader(configuration: configuration,
                                               expectedSHA256: inputs.digest,
                                               sessionID: "synthetic-\(mode)")
            try await reader.validateExecutable()
            let client = UPSCClient(configuration: configuration)
            if mode == "complete" {
                let snapshot: NUTSnapshot
                do {
                    snapshot = try await client.readSnapshot()
                } catch {
                    try? fixture.waitForExit()
                    let commands = (try? fixture.readResult())?.commands ?? []
                    XCTFail("Complete synthetic read failed: \(error); observed commands: \(commands)")
                    throw error
                }
                XCTAssertEqual(snapshot.metrics[.batteryCharge]?.value, 73)
                XCTAssertEqual(snapshot.status.lineState, .onLine)
            } else {
                do {
                    _ = try await client.readSnapshot()
                    XCTFail("The hardened upsc must reject synthetic \(mode) list data")
                } catch {
                    XCTAssertEqual(error as? UPSCClientError, .processFailed)
                }
            }

            try fixture.waitForExit()
            let result = try fixture.readResult()
            XCTAssertEqual(result.errors, [])
            XCTAssertFalse(result.commands.isEmpty)
            XCTAssertEqual(result.commands.last, "LIST VAR fixture")
            XCTAssertEqual(result.commands.filter { $0 == "LIST VAR fixture" }.count, 1)
            XCTAssertTrue(result.commands.allSatisfy {
                $0 == "STARTTLS" || $0 == "LIST VAR fixture"
            }, "Unexpected command in synthetic read: \(result.commands)")
            fixture.stop()
        }
    }

    private struct InteropInputs {
        let executableURL: URL
        let digest: String
        let pythonURL: URL
    }

    private enum InteropConfigurationError: Error {
        case incomplete
        case invalid
    }

    private func interopInputs() async throws -> InteropInputs {
        let environment = ProcessInfo.processInfo.environment
        let executable = environment["UPS_TEST_UPSC"]
        let digest = environment["UPS_TEST_UPSC_SHA256"]
        let python = environment["UPS_TEST_PYTHON"]

        if executable == nil, digest == nil, python == nil {
            throw XCTSkip("Set UPS_TEST_UPSC, UPS_TEST_UPSC_SHA256 and UPS_TEST_PYTHON for synthetic runtime interop")
        }
        guard let executable, let digest, let python,
              !executable.isEmpty, !digest.isEmpty, !python.isEmpty,
              executable.hasPrefix("/"), python.hasPrefix("/"),
              isValidSHA256(digest) else {
            throw InteropConfigurationError.incomplete
        }

        let executableURL = URL(fileURLWithPath: executable)
        let pythonURL = URL(fileURLWithPath: python)
        let resolvedPythonURL = pythonURL.resolvingSymlinksInPath()
        guard FileManager.default.isExecutableFile(atPath: resolvedPythonURL.path),
              (try? resolvedPythonURL.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true else {
            throw InteropConfigurationError.invalid
        }

        let configuration = try UPSCClientConfiguration(
            executableURL: executableURL,
            executableQualification: .completionHardened,
            upsName: "fixture",
            sourceID: "interop-preflight",
            port: 1
        )
        let reader = try NUTSnapshotReader(configuration: configuration,
                                           expectedSHA256: digest,
                                           sessionID: "synthetic-preflight")
        try await reader.validateExecutable()
        return InteropInputs(executableURL: executableURL, digest: digest, pythonURL: pythonURL)
    }

    private func isValidSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 70) || ($0 >= 97 && $0 <= 102)
        }
    }
}

private final class SyntheticNUTFixture {
    struct Result: Decodable {
        let commands: [String]
        let errors: [String]
    }

    private let process: Process
    private let termination: DispatchSemaphore
    private let resultURL: URL
    private let output: Pipe
    private(set) var port: Int

    private init(
        process: Process,
        output: Pipe,
        termination: DispatchSemaphore,
        resultURL: URL,
        port: Int
    ) {
        self.process = process
        self.output = output
        self.termination = termination
        self.resultURL = resultURL
        self.port = port
    }

    static func start(python: URL, directory: URL, mode: String) throws -> SyntheticNUTFixture {
        let scriptURL = directory.appendingPathComponent("synthetic_nut_fixture.py")
        let resultURL = directory.appendingPathComponent("fixture-\(mode).json")
        try Self.script.write(to: scriptURL, atomically: true, encoding: .utf8)

        let process = Process()
        let output = Pipe()
        let termination = DispatchSemaphore(value: 0)
        let fixture = SyntheticNUTFixture(
            process: process,
            output: output,
            termination: termination,
            resultURL: resultURL,
            port: 0
        )
        process.executableURL = python
        process.arguments = [scriptURL.path, mode, resultURL.path]
        process.environment = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": directory.path,
            "LC_ALL": "C",
            "PYTHONUNBUFFERED": "1",
        ]
        process.currentDirectoryURL = URL(fileURLWithPath: "/", isDirectory: true)
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { _ in termination.signal() }
        try process.run()
        try? output.fileHandleForWriting.close()

        var line = Data()
        while line.count < 32 {
            guard let byte = try output.fileHandleForReading.read(upToCount: 1), !byte.isEmpty else { break }
            line.append(byte)
            if byte.last == 10 { break }
        }
        guard let text = String(data: line, encoding: .ascii),
              let port = Int(text.trimmingCharacters(in: .whitespacesAndNewlines)),
              (1...65_535).contains(port) else {
            fixture.stop()
            throw UPSCClientError.processLaunchFailed
        }
        fixture.port = port
        return fixture
    }

    func waitForExit() throws {
        guard termination.wait(timeout: .now() + 8) == .success else {
            stop()
            throw UPSCClientError.deadlineExceeded
        }
        guard process.terminationStatus == 0 else { throw UPSCClientError.processFailed }
    }

    func readResult() throws -> Result {
        try JSONDecoder().decode(Result.self, from: Data(contentsOf: resultURL))
    }

    func stop() {
        if process.isRunning {
            process.terminate()
            if termination.wait(timeout: .now() + 0.5) != .success {
                let childPID = process.processIdentifier
                if childPID > 0 { _ = Darwin.kill(childPID, SIGKILL) }
                _ = termination.wait(timeout: .now() + 1)
            }
        }
        try? output.fileHandleForReading.close()
    }

    private static let script = #"""
    import json
    import signal
    import socket
    import sys

    mode, result_path = sys.argv[1:]
    commands = []
    errors = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)
    signal.alarm(10)
    print(server.getsockname()[1], flush=True)

    try:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(3)
            reader = connection.makefile("rb")
            for _ in range(4):
                line = reader.readline(257)
                if not line:
                    break
                command = line.decode("ascii").strip()
                commands.append(command)
                if command == "STARTTLS":
                    connection.sendall(b"ERR FEATURE-NOT-SUPPORTED\n")
                    continue
                if command != "LIST VAR fixture":
                    errors.append("unexpected-command")
                    break
                connection.sendall(
                    b"BEGIN LIST VAR fixture\n"
                    b'VAR fixture ups.status "OL"\n'
                    b'VAR fixture battery.charge "73"\n'
                    b'VAR fixture driver.name "apcmicrolink"\n'
                    b'VAR fixture battery.runtime "900"\n'
                    b'VAR fixture input.voltage "231.5"\n'
                    b'VAR fixture output.voltage "230.2"\n'
                    b'VAR fixture ups.realpower "180"\n'
                    b'VAR fixture ups.power "220"\n'
                    b'VAR fixture ups.serial "SYNTHETIC-PRIVATE-SERIAL"\n'
                )
                if mode == "complete":
                    connection.sendall(b"END LIST VAR fixture\n")
                elif mode == "error":
                    connection.sendall(b"ERR DATA-STALE\n")
                elif mode == "wrong-end":
                    connection.sendall(b"END LIST VAR another-fixture\n")
                elif mode == "short-end":
                    connection.sendall(b"END LIST\n")
                elif mode == "extra-end":
                    connection.sendall(b"END LIST VAR fixture unexpected\n")
                break
    except (OSError, UnicodeError):
        errors.append("fixture-server-error")
    finally:
        server.close()
        with open(result_path, "w", encoding="utf-8") as result:
            json.dump({"commands": commands, "errors": errors}, result)
    """#
}
