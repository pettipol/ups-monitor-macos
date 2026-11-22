import Foundation
import XCTest
import UPSModel
import UPSRuntime
@testable import UPSAppHost

@MainActor
final class ArchivedObservationModelTests: XCTestCase {
    private let pin = String(repeating: "a", count: 64)
    private let started = Date(timeIntervalSince1970: 1_800_000_000)
    private let finished = Date(timeIntervalSince1970: 1_800_000_002)

    func testInvalidPinOriginAndFolderNeverCallLoader() throws {
        let directory = try makeDirectory()
        let loaderCalls = LockedValue(0)
        let model = ArchivedObservationModel(loader: { _, _, _, _, _ in
            loaderCalls.update { $0 += 1 }
            return Self.makeObservation(started: Date(timeIntervalSince1970: 1_800_000_000),
                                        finished: Date(timeIntervalSince1970: 1_800_000_002))
        })

        model.sessionDirectoryURL = directory
        model.origin = .syntheticDriverDump
        model.expectedExecutableSHA256 = "not-a-pin"
        model.importObservation()
        XCTAssertEqual(loaderCalls.read(), 0)
        XCTAssertNil(model.imported)
        XCTAssertEqual(model.errorMessage, "Enter a 64-character SHA-256 pin")

        model.expectedExecutableSHA256 = pin
        model.origin = nil
        model.importObservation()
        XCTAssertEqual(loaderCalls.read(), 0)
        XCTAssertEqual(model.errorMessage, "Choose a declared origin")

        model.origin = .syntheticDriverDump
        model.sessionDirectoryURL = directory.appendingPathComponent("missing")
        model.importObservation()
        XCTAssertEqual(loaderCalls.read(), 0)
        XCTAssertEqual(model.errorMessage, "Choose an archive directory")
    }

    func testSuccessfulImportPreservesTimesAndRemainsUnqualified() async throws {
        let directory = try makeDirectory()
        let expectedPin = pin
        let fixture = observation()
        let now = Date(timeIntervalSince1970: 1_800_000_010)
        let model = ArchivedObservationModel(clock: { now }, loader: { _, origin, source, receivedPin, receivedNow in
            XCTAssertEqual(origin, .archivedSupervisedDriverDump)
            XCTAssertEqual(source.provider, .nut)
            XCTAssertEqual(source.id, "archive")
            XCTAssertEqual(source.identityStability, .configured)
            XCTAssertEqual(receivedPin, expectedPin)
            XCTAssertEqual(receivedNow, now)
            return fixture
        })
        model.sessionDirectoryURL = directory
        model.origin = .archivedSupervisedDriverDump
        model.expectedExecutableSHA256 = pin

        let importTask = try XCTUnwrap(model.importObservation())
        await importTask.value

        XCTAssertEqual(model.imported?.startedAt, started)
        XCTAssertEqual(model.imported?.finishedAt, finished)
        XCTAssertEqual(model.imported?.unqualifiedSnapshot.capturedAt, started)
        XCTAssertEqual(model.imported?.dataQualified, false)
        XCTAssertNil(model.errorMessage)
    }

    func testFailedNewImportClearsPreviousResult() async throws {
        let directory = try makeDirectory()
        let shouldFail = LockedValue(false)
        let fixture = observation()
        let model = ArchivedObservationModel(loader: { _, _, _, _, _ in
            if shouldFail.read() { throw ArchivedObservationModelTestError.expected }
            return fixture
        })
        model.sessionDirectoryURL = directory
        model.origin = .syntheticDriverDump
        model.expectedExecutableSHA256 = pin
        let firstImport = try XCTUnwrap(model.importObservation())
        await firstImport.value

        model.expectedExecutableSHA256 = String(repeating: "b", count: 64)
        shouldFail.update { $0 = true }
        let failedImport = try XCTUnwrap(model.importObservation())
        XCTAssertNil(model.imported)
        await failedImport.value
        XCTAssertNil(model.imported)
        XCTAssertEqual(model.errorMessage, "The archived observation could not be imported")
    }

    func testInputResetAndCloseRejectLateResult() async throws {
        let directory = try makeDirectory()
        let fixture = observation()
        let loaderStarted = expectation(description: "loader started")
        let releaseLoader = DispatchSemaphore(value: 0)
        let loaderReturned = expectation(description: "loader returned")
        let model = ArchivedObservationModel(loader: { _, _, _, _, _ in
            loaderStarted.fulfill()
            _ = releaseLoader.wait(timeout: .now() + 3)
            loaderReturned.fulfill()
            return fixture
        })
        model.sessionDirectoryURL = directory
        model.origin = .syntheticDriverDump
        model.expectedExecutableSHA256 = pin
        let pendingImport = try XCTUnwrap(model.importObservation())

        await fulfillment(of: [loaderStarted], timeout: 1)
        model.origin = nil
        XCTAssertNil(model.imported)
        model.clear()
        XCTAssertNil(model.imported)
        releaseLoader.signal()
        await fulfillment(of: [loaderReturned], timeout: 1)
        await pendingImport.value
        XCTAssertNil(model.imported)
        XCTAssertFalse(model.isLoading)
    }

    private func observation() -> ImportedNUTObservation {
        Self.makeObservation(started: started, finished: finished)
    }

    nonisolated private static func makeObservation(started: Date, finished: Date) -> ImportedNUTObservation {
        let source = MonitorSource(
            provider: .nut, id: "archive", sessionID: "archive-session",
            identityStability: .configured
        )
        let snapshot = MonitorSnapshot(
            source: source, capturedAt: started,
            status: MonitorStatus(lineState: .onLine, quality: .available),
            metrics: [MonitorMetric(
                id: .batteryCharge, value: 76, unit: .percent,
                quality: .available, provenance: .reported
            )]
        )
        return ImportedNUTObservation(
            origin: .archivedSupervisedDriverDump,
            startedAt: started, finishedAt: finished,
            unqualifiedSnapshot: snapshot
        )
    }

    private func makeDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("archived-observation-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return directory
    }

}

private enum ArchivedObservationModelTestError: Error {
    case expected
}

private final class LockedValue<Value: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) { self.value = value }

    func read() -> Value {
        lock.lock()
        defer { lock.unlock() }
        return value
    }

    func update(_ body: (inout Value) -> Void) {
        lock.lock()
        defer { lock.unlock() }
        body(&value)
    }
}
