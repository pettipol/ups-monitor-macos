import Foundation
import XCTest
@testable import NUTClient

final class UPSCClientTests: XCTestCase {
    private var temporaryDirectory: URL!
    private var helperURL: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("nut-client-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: false)
        helperURL = try compileSyntheticHelper(in: temporaryDirectory)
    }

    override func tearDownWithError() throws {
        if let temporaryDirectory {
            try? FileManager.default.removeItem(at: temporaryDirectory)
        }
        try super.tearDownWithError()
    }

    func testConfigurationBuildsOnlyTheFixedLoopbackReadRequest() throws {
        let configuration = try makeConfiguration(port: 35_001)

        XCTAssertEqual(configuration.arguments, ["-j", "-A", "none", "-W", "3", "my-ups@127.0.0.1:35001"])
        XCTAssertEqual(configuration.environment, [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C",
            "LC_ALL": "C",
            "NUT_DEBUG_LEVEL": "0",
        ])

        XCTAssertThrowsError(try makeConfiguration(port: 35_001, host: "localhost")) {
            XCTAssertEqual($0 as? UPSCClientConfigurationError, .nonLoopbackAddress)
        }
        XCTAssertThrowsError(try makeConfiguration(port: 35_001, upsName: "-x;ups")) {
            XCTAssertEqual($0 as? UPSCClientConfigurationError, .invalidUPSName)
        }
        XCTAssertThrowsError(try makeConfiguration(port: 0)) {
            XCTAssertEqual($0 as? UPSCClientConfigurationError, .invalidPort)
        }
    }

    func testSyntheticChildReceivesMinimalEnvironmentAndReturnsTypedSnapshot() async throws {
        let client = UPSCClient(configuration: try makeConfiguration(port: 35_006))
        let requestedTime = Date(timeIntervalSince1970: 1_800_000_000)

        let snapshot = try await client.readSnapshot(capturedAt: requestedTime)

        XCTAssertEqual(snapshot.sourceID, "synthetic-ups")
        XCTAssertEqual(snapshot.capturedAt, requestedTime)
        XCTAssertEqual(snapshot.metrics[.batteryCharge]?.value, 99.5)
        XCTAssertEqual(snapshot.status.lineState, .onLine)
    }

    func testNonzeroExitAndPartialJSONBecomeRedactedTypedErrors() async throws {
        let failedClient = UPSCClient(configuration: try makeConfiguration(port: 35_002))
        do {
            _ = try await failedClient.readSnapshot()
            XCTFail("Expected nonzero child exit")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .processFailed)
            XCTAssertFalse(String(describing: error).contains("PRIVATE_SYNTHETIC_MARKER"))
        }

        let partialClient = UPSCClient(configuration: try makeConfiguration(port: 35_003))
        do {
            _ = try await partialClient.readSnapshot()
            XCTFail("Expected malformed JSON rejection")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .invalidResponse)
        }
    }

    func testOutputLimitAndOverallDeadlineTerminateOnlySyntheticChild() async throws {
        let boundedClient = UPSCClient(configuration: try makeConfiguration(
            port: 35_004,
            deadline: 3,
            stdoutLimit: 8_192
        ))
        do {
            _ = try await boundedClient.readSnapshot()
            XCTFail("Expected output cap")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .outputLimitExceeded)
        }

        let stderrBoundedClient = UPSCClient(configuration: try makeConfiguration(
            port: 35_007,
            deadline: 3,
            stderrLimit: 1_024
        ))
        do {
            _ = try await stderrBoundedClient.readSnapshot()
            XCTFail("Expected stderr cap")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .outputLimitExceeded)
        }

        let deadlineClient = UPSCClient(configuration: try makeConfiguration(port: 35_005, deadline: 0.3))
        do {
            _ = try await deadlineClient.readSnapshot()
            XCTFail("Expected deadline")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .deadlineExceeded)
        }
    }

    func testContinuousWriterIgnoringTerminationYieldsToKillTimerAndReleasesSourceGate() async throws {
        let completed = expectation(description: "Continuous synthetic writer is reaped")
        let client = UPSCClient(configuration: try makeConfiguration(
            port: 35_008,
            deadline: 0.5,
            stdoutLimit: 65_536
        ))

        Task {
            do {
                _ = try await client.readSnapshot()
                XCTFail("Expected the continuous writer to exceed the output cap")
            } catch {
                XCTAssertEqual(error as? UPSCClientError, .outputLimitExceeded)
            }
            completed.fulfill()
        }
        await fulfillment(of: [completed], timeout: 3)

        let nextRead = UPSCClient(configuration: try makeConfiguration(port: 35_001))
        let snapshot = try await nextRead.readSnapshot()
        XCTAssertEqual(snapshot.status.lineState, .onLine)
    }

    func testCancellationAndSingleInflightRead() async throws {
        let client = UPSCClient(configuration: try makeConfiguration(port: 35_005, deadline: 10))
        let first = Task { try await client.readSnapshot() }
        try await Task.sleep(for: .milliseconds(100))

        let overlappingClient = UPSCClient(configuration: try makeConfiguration(port: 35_005))
        do {
            _ = try await overlappingClient.readSnapshot()
            XCTFail("Expected the overlapping read to be rejected")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .readInProgress)
        }

        first.cancel()
        do {
            _ = try await first.value
            XCTFail("Expected cancellation")
        } catch {
            XCTAssertEqual(error as? UPSCClientError, .cancelled)
        }
    }

    private func makeConfiguration(
        port: Int,
        host: String = "127.0.0.1",
        upsName: String = "my-ups",
        deadline: Double = 3,
        stdoutLimit: Int = 65_536,
        stderrLimit: Int = 1_024
    ) throws -> UPSCClientConfiguration {
        try UPSCClientConfiguration(
            executableURL: helperURL,
            executableQualification: .completionHardened,
            upsName: upsName,
            sourceID: "synthetic-ups",
            host: host,
            port: port,
            connectTimeoutSeconds: 3,
            overallDeadlineSeconds: deadline,
            maximumStandardOutputBytes: stdoutLimit,
            maximumStandardErrorBytes: stderrLimit
        )
    }

    private func compileSyntheticHelper(in directory: URL) throws -> URL {
        let sourceURL = directory.appendingPathComponent("synthetic_upsc_helper.c")
        let executableURL = directory.appendingPathComponent("synthetic-upsc-helper")
        try Self.helperSource.write(to: sourceURL, atomically: true, encoding: .utf8)

        let compiler = Process()
        compiler.executableURL = URL(fileURLWithPath: "/usr/bin/clang")
        compiler.arguments = ["-std=c11", "-Wall", "-Werror", sourceURL.path, "-o", executableURL.path]
        compiler.environment = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C"]
        compiler.currentDirectoryURL = URL(fileURLWithPath: "/", isDirectory: true)
        try compiler.run()
        compiler.waitUntilExit()
        guard compiler.terminationStatus == 0,
              FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            throw UPSCClientError.processLaunchFailed
        }
        return executableURL
    }

    private static let helperSource = #"""
    #include <signal.h>
    #include <stdio.h>
    #include <stdlib.h>
    #include <string.h>
    #include <unistd.h>

    static int expected_arguments(int argc, char **argv) {
        return argc == 7 && strcmp(argv[1], "-j") == 0 &&
            strcmp(argv[2], "-A") == 0 && strcmp(argv[3], "none") == 0 &&
            strcmp(argv[4], "-W") == 0 && strcmp(argv[5], "3") == 0 &&
            strncmp(argv[6], "my-ups@127.0.0.1:", 17) == 0;
    }

    int main(int argc, char **argv) {
        if (!expected_arguments(argc, argv)) return 90;
        const char *port = strrchr(argv[6], ':');
        if (port == NULL) return 91;
        port++;

        if (strcmp(port, "35001") == 0) {
            puts("{\"battery.charge\":\"99.5\",\"ups.status\":\"OL\"}");
            return 0;
        }
        if (strcmp(port, "35002") == 0) {
            fputs("PRIVATE_SYNTHETIC_MARKER", stderr);
            return 42;
        }
        if (strcmp(port, "35003") == 0) {
            fputs("{\"battery.charge\":", stdout);
            return 0;
        }
        if (strcmp(port, "35004") == 0) {
            for (int i = 0; i < 100000; i++) fputs("X", stdout);
            fflush(stdout);
            return 0;
        }
        if (strcmp(port, "35005") == 0) {
            signal(SIGTERM, SIG_IGN);
            for (;;) sleep(1);
        }
        if (strcmp(port, "35006") == 0) {
            const char *debug_level = getenv("NUT_DEBUG_LEVEL");
            if (debug_level == NULL || strcmp(debug_level, "0") != 0 ||
                getenv("HOME") != NULL || getenv("NUT_AUTHCONF_FILE") != NULL ||
                getenv("NUT_AUTHCONF_PATH") != NULL) {
                fputs("PRIVATE_SYNTHETIC_MARKER", stderr);
                return 43;
            }
            puts("{\"battery.charge\":\"99.5\",\"ups.status\":\"OL\"}");
            return 0;
        }
        if (strcmp(port, "35007") == 0) {
            for (int i = 0; i < 100000; i++) fputs("E", stderr);
            fflush(stderr);
            return 0;
        }
        if (strcmp(port, "35008") == 0) {
            signal(SIGTERM, SIG_IGN);
            alarm(5);
            for (;;) {
                const char output[] = "continuous synthetic output\n";
                if (write(STDOUT_FILENO, output, sizeof(output) - 1) < 0) return 93;
            }
        }
        return 92;
    }
    """#
}
