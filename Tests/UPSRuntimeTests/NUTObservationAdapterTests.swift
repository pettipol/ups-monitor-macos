import CryptoKit
import Foundation
import XCTest
import NUTData
import UPSModel
@testable import UPSRuntime

final class NUTObservationAdapterTests: XCTestCase {
    private let started = Date(timeIntervalSince1970: 1_800_000_000)
    private let finished = Date(timeIntervalSince1970: 1_800_000_002)
    private let now = Date(timeIntervalSince1970: 1_800_000_010)
    private let executablePin = String(repeating: "a", count: 64)

    func testSyntheticObservationImportsThroughDecoderAdapterAndCoordinator() async throws {
        let observation = makeObservation()
        let imported = try NUTObservationAdapter.decode(observation, source: source(),
                                                        expectedExecutableSHA256: executablePin, now: now)
        XCTAssertFalse(imported.dataQualified)
        XCTAssertEqual(imported.origin, .syntheticDriverDump)
        XCTAssertEqual(imported.startedAt, started)
        XCTAssertEqual(imported.finishedAt, finished)
        XCTAssertEqual(imported.unqualifiedSnapshot.capturedAt, started)
        XCTAssertEqual(imported.unqualifiedSnapshot.source, source())
        let metrics = Dictionary(uniqueKeysWithValues: imported.unqualifiedSnapshot.metrics.map { ($0.id, $0) })
        XCTAssertEqual(metrics[.batteryCharge]?.value, 76)
        XCTAssertEqual(metrics[.batteryRuntime]?.value, 590)
        XCTAssertEqual(metrics[.batteryRuntime]?.provenance, .estimated)
        XCTAssertEqual(metrics[.upsRealPower]?.value, nil)

        let referenceNow = now
        let coordinator = try MonitorCoordinator(read: { [imported.unqualifiedSnapshot] },
                                                 clock: { referenceNow }, monotonicClock: { 42 })
        let state = await coordinator.refresh()
        XCTAssertEqual(state.sources.first?.snapshot.capturedAt, started)
        XCTAssertEqual(state.sources.first?.source.provider, .nut)
        XCTAssertEqual(state.acquisition, .succeeded)
        XCTAssertFalse(state.isPolling)
    }

    func testRejectsEveryNonSuccessProcessOutcomeEvenWithValidOutput() async throws {
        let base = makeObservation()
        let statuses: [NUTObservationProcessStatus] = [.exited, .timedOut, .outputLimit, .outputIncomplete, .cancelled, .unreaped, .error]
        let triggers: [NUTObservationTrigger] = [.completed, .timeout, .outputLimit, .outputIncomplete, .cancelled, .none]
        for status in statuses {
            for trigger in triggers {
                let candidate = replacing(base, status: status, trigger: trigger)
                if status == .exited && trigger == .completed { continue }
                XCTAssertThrowsError(try NUTObservationAdapter.decode(candidate, source: source(),
                                                                      expectedExecutableSHA256: executablePin, now: now))
            }
        }
        for candidate in [replacing(base, returnCode: 1), replacing(base, errorCode: "EIO")] {
            XCTAssertThrowsError(try NUTObservationAdapter.decode(candidate, source: source(),
                                                                  expectedExecutableSHA256: executablePin, now: now))
        }
        XCTAssertThrowsError(try NUTObservationAdapter.decode(replacingWithMissingReturnCode(base), source: source(),
                                                              expectedExecutableSHA256: executablePin, now: now))

        let failedObservation = replacing(base, status: .error)
        let failureSource = source()
        let expectedPin = executablePin
        let referenceNow = now
        let failedCoordinator = try MonitorCoordinator(read: {
            let imported = try NUTObservationAdapter.decode(failedObservation, source: failureSource,
                                                             expectedExecutableSHA256: expectedPin, now: referenceNow)
            return [imported.unqualifiedSnapshot]
        }, clock: { referenceNow }, monotonicClock: { 44 })
        let failedState = await failedCoordinator.refresh()
        XCTAssertEqual(failedState.acquisition, .failed(.readFailed))
        XCTAssertTrue(failedState.sources.isEmpty, "A failed import must not create a measurement")
    }

    func testRejectsIntegrityDateSourceAndDumpFailures() async throws {
        let base = makeObservation()
        let invalidCount = replacing(base, stdoutBytes: base.stdoutBytes + 1)
        let negativeCount = replacing(base, stdoutBytes: -1)
        let invalidLimits = [0, 1_048_577, Int.max].map { replacing(base, maximumOutputBytes: $0) }
        let invalidHash = replacing(base, stdoutSHA256: String(repeating: "0", count: 64))
        let invalidPin = replacing(base, executableSHA256: String(repeating: "b", count: 64))
        let future = replacing(base, finishedAt: now.addingTimeInterval(1))
        let inverted = replacing(base, startedAt: finished, finishedAt: started)
        let nonfiniteStart = replacing(base, startedAt: Date(timeIntervalSince1970: .infinity))
        let nonfiniteFinish = replacing(base, finishedAt: Date(timeIntervalSince1970: .infinity))
        let nonfiniteNow = Date(timeIntervalSince1970: .nan)
        let metadataOnly = makeObservation(stdout: dump("driver.name: full-nut-hidapi-fake\n"))
        let malformed = makeObservation(stdout: dump("driver.name: unsupported\nbattery.charge: 76\n"))
        let wrongSource = MonitorSource(provider: .apple, id: "synthetic", sessionID: "session", identityStability: .sessionLocal)
        var cases: [(SupervisedNUTObservation, MonitorSource, String, Date)] = [
            (invalidCount, source(), executablePin, now), (negativeCount, source(), executablePin, now),
            (invalidHash, source(), executablePin, now), (invalidPin, source(), executablePin, now),
            (future, source(), executablePin, now), (inverted, source(), executablePin, now),
            (nonfiniteStart, source(), executablePin, now), (nonfiniteFinish, source(), executablePin, now),
            (metadataOnly, source(), executablePin, now),
            (malformed, source(), executablePin, now), (base, wrongSource, executablePin, now),
            (base, source(), "wrong", now),
        ]
        cases.append(contentsOf: invalidLimits.map { ($0, source(), executablePin, now) })
        cases.append((base, source(), executablePin, nonfiniteNow))
        for (item, identity, pin, referenceDate) in cases {
            XCTAssertThrowsError(try NUTObservationAdapter.decode(item, source: identity,
                                                                  expectedExecutableSHA256: pin, now: referenceDate))
        }

        let statusOnly = makeObservation(stdout: dump("driver.name: full-nut-hidapi-fake\nups.status: OL\n"))
        let statusOnlyImport = try NUTObservationAdapter.decode(statusOnly, source: source(),
                                                               expectedExecutableSHA256: executablePin, now: now)
        XCTAssertFalse(statusOnlyImport.dataQualified)
        XCTAssertEqual(statusOnlyImport.unqualifiedSnapshot.status.lineState, .onLine)
        XCTAssertTrue(statusOnlyImport.unqualifiedSnapshot.metrics.allSatisfy { $0.value == nil })

        let nonemptyStderr = Data("synthetic warning\n".utf8)
        let withStderr = makeObservation(stderr: nonemptyStderr)
        let upperCaseDigests = replacingDigests(withStderr,
                                                 executableSHA256: executablePin.uppercased(),
                                                 stdoutSHA256: withStderr.stdoutSHA256.uppercased(),
                                                 stderrSHA256: withStderr.stderrSHA256.uppercased())
        XCTAssertNoThrow(try NUTObservationAdapter.decode(upperCaseDigests, source: source(),
                                                          expectedExecutableSHA256: executablePin.uppercased(), now: now))
        let stderrMismatch = replacingDigests(withStderr, stderrSHA256: String(repeating: "0", count: 64))
        XCTAssertThrowsError(try NUTObservationAdapter.decode(stderrMismatch, source: source(),
                                                              expectedExecutableSHA256: executablePin, now: now))
        let stderrCountMismatch = makeObservation(stderr: nonemptyStderr, stderrBytes: nonemptyStderr.count + 1)
        XCTAssertThrowsError(try NUTObservationAdapter.decode(stderrCountMismatch, source: source(),
                                                              expectedExecutableSHA256: executablePin, now: now))
        let oldStart = started.addingTimeInterval(-60)
        let archived = replacing(base, origin: .archivedSupervisedDriverDump,
                                 startedAt: oldStart, finishedAt: oldStart.addingTimeInterval(2))
        let oldImport = try NUTObservationAdapter.decode(archived, source: source(),
                                                        expectedExecutableSHA256: executablePin, now: now)
        let referenceNow = now
        let oldCoordinator = try MonitorCoordinator(read: { [oldImport.unqualifiedSnapshot] },
                                                    clock: { referenceNow }, monotonicClock: { 43 })
        let oldState = await oldCoordinator.refresh()
        XCTAssertEqual(oldState.sources.first?.freshness, .stale)
    }

    private func source() -> MonitorSource {
        MonitorSource(provider: .nut, id: "synthetic", sessionID: "session", identityStability: .configured)
    }

    private func dump(_ body: String = "driver.name: full-nut-hidapi-fake\nups.status: \nbattery.charge: 76\nbattery.runtime: 590\n") -> Data {
        Data(("Network UPS Tools 2.8.5.1 (development iteration after 2.8.5) - APC Microlink protocol driver 0.05\n" +
              "Warning: This is an experimental driver.\nSome features may not function correctly.\n\n" + body).utf8)
    }

    private func makeObservation(
        stdout: Data? = nil, origin: NUTObservationOrigin = .syntheticDriverDump,
        status: NUTObservationProcessStatus = .exited, trigger: NUTObservationTrigger = .completed,
        returnCode: Int? = 0, errorCode: String? = nil, stdoutBytes: Int? = nil, stderr: Data = Data(),
        stderrBytes: Int? = nil,
        maximumOutputBytes: Int = 65_536, executableSHA256: String? = nil,
        stdoutSHA256: String? = nil, stderrSHA256: String? = nil,
        startedAt: Date? = nil, finishedAt: Date? = nil
    ) -> SupervisedNUTObservation {
        let out = stdout ?? dump()
        let err = stderr
        return SupervisedNUTObservation(
            origin: origin, status: status, trigger: trigger, returnCode: returnCode, errorCode: errorCode,
            stdout: out, stderr: err, stdoutBytes: stdoutBytes ?? out.count, stderrBytes: stderrBytes ?? err.count,
            maximumOutputBytes: maximumOutputBytes, executableSHA256: executableSHA256 ?? executablePin,
            stdoutSHA256: stdoutSHA256 ?? hash(out), stderrSHA256: stderrSHA256 ?? hash(err),
            startedAt: startedAt ?? started, finishedAt: finishedAt ?? finished
        )
    }

    private func replacing(_ value: SupervisedNUTObservation, origin: NUTObservationOrigin? = nil,
                           status: NUTObservationProcessStatus? = nil, trigger: NUTObservationTrigger? = nil,
                           returnCode: Int? = nil, errorCode: String? = nil, stdoutBytes: Int? = nil,
                           maximumOutputBytes: Int? = nil, executableSHA256: String? = nil,
                           stdoutSHA256: String? = nil, startedAt: Date? = nil, finishedAt: Date? = nil) -> SupervisedNUTObservation {
        SupervisedNUTObservation(
            origin: origin ?? value.origin, status: status ?? value.status, trigger: trigger ?? value.trigger,
            returnCode: returnCode ?? value.returnCode, errorCode: errorCode ?? value.errorCode,
            stdout: value.stdout, stderr: value.stderr, stdoutBytes: stdoutBytes ?? value.stdoutBytes,
            stderrBytes: value.stderrBytes, maximumOutputBytes: maximumOutputBytes ?? value.maximumOutputBytes,
            executableSHA256: executableSHA256 ?? value.executableSHA256,
            stdoutSHA256: stdoutSHA256 ?? value.stdoutSHA256, stderrSHA256: value.stderrSHA256,
            startedAt: startedAt ?? value.startedAt, finishedAt: finishedAt ?? value.finishedAt
        )
    }

    private func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func replacingWithMissingReturnCode(_ value: SupervisedNUTObservation) -> SupervisedNUTObservation {
        SupervisedNUTObservation(
            origin: value.origin, status: value.status, trigger: value.trigger, returnCode: nil,
            errorCode: value.errorCode, stdout: value.stdout, stderr: value.stderr,
            stdoutBytes: value.stdoutBytes, stderrBytes: value.stderrBytes,
            maximumOutputBytes: value.maximumOutputBytes, executableSHA256: value.executableSHA256,
            stdoutSHA256: value.stdoutSHA256, stderrSHA256: value.stderrSHA256,
            startedAt: value.startedAt, finishedAt: value.finishedAt
        )
    }

    private func replacing(_ value: SupervisedNUTObservation, maximumOutputBytes: Int) -> SupervisedNUTObservation {
        SupervisedNUTObservation(
            origin: value.origin, status: value.status, trigger: value.trigger, returnCode: value.returnCode,
            errorCode: value.errorCode, stdout: value.stdout, stderr: value.stderr,
            stdoutBytes: value.stdoutBytes, stderrBytes: value.stderrBytes,
            maximumOutputBytes: maximumOutputBytes, executableSHA256: value.executableSHA256,
            stdoutSHA256: value.stdoutSHA256, stderrSHA256: value.stderrSHA256,
            startedAt: value.startedAt, finishedAt: value.finishedAt
        )
    }

    private func replacingDigests(_ value: SupervisedNUTObservation, executableSHA256: String? = nil,
                                  stdoutSHA256: String? = nil, stderrSHA256: String? = nil) -> SupervisedNUTObservation {
        SupervisedNUTObservation(
            origin: value.origin, status: value.status, trigger: value.trigger, returnCode: value.returnCode,
            errorCode: value.errorCode, stdout: value.stdout, stderr: value.stderr,
            stdoutBytes: value.stdoutBytes, stderrBytes: value.stderrBytes,
            maximumOutputBytes: value.maximumOutputBytes, executableSHA256: executableSHA256 ?? value.executableSHA256,
            stdoutSHA256: stdoutSHA256 ?? value.stdoutSHA256, stderrSHA256: stderrSHA256 ?? value.stderrSHA256,
            startedAt: value.startedAt, finishedAt: value.finishedAt
        )
    }
}
