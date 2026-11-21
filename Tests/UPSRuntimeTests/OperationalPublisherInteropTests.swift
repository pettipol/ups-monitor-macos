import Foundation
import XCTest
import UPSModel
import UPSRuntime

/// These resources are byte copies of the real Python publisher's output,
/// generated from explicitly synthetic input and a fixed synthetic clock.
final class OperationalPublisherInteropTests: XCTestCase {
    private let fixedDate = Date(timeIntervalSince1970: 1_800_000_005)

    func testActualPublisherActiveEnvelopeProjectsValuesAndProvenance() async throws {
        let directory = try copyPublisherFixture("active")
        defer { try? FileManager.default.removeItem(at: directory) }
        let now = fixedDate
        let reader = try await NUTOperationalSampleReader.connect(
            directoryURL: directory, clock: { now }, monotonicClock: { 100 }
        )
        let snapshots = try await reader.read()
        XCTAssertEqual(snapshots.count, 1)
        let snapshot = try XCTUnwrap(snapshots.first)
        XCTAssertEqual(snapshot.source.id, "interop-source")
        XCTAssertEqual(snapshot.status.lineState, .onLine)
        let expected: [(MonitorMetricID, Double)] = [
            (.batteryCharge, 82), (.batteryRuntime, 3_600), (.batteryVoltage, 24),
            (.inputVoltage, 230), (.outputVoltage, 230),
            (.upsRealPowerNominal, 1_000), (.upsApparentPowerNominal, 1_500),
            (.upsRealPower, 100), (.upsApparentPower, 150),
        ]
        for (id, value) in expected {
            let metric = try XCTUnwrap(snapshot.metrics.first { $0.id == id })
            XCTAssertEqual(try XCTUnwrap(metric.value), value, accuracy: 0.000_001)
        }
        XCTAssertEqual(snapshot.metrics.first { $0.id == .upsRealPower }?.provenance, .driverDerived)
        XCTAssertEqual(snapshot.metrics.first { $0.id == .batteryRuntime }?.provenance, .estimated)
        try snapshot.validate()
    }

    func testActualPublisherStoppedEnvelopeIsTerminalDespiteRetainedSample() async throws {
        try await assertTerminal("stopped")
    }

    func testActualPublisherFailedEnvelopeIsTerminalDespiteRetainedSample() async throws {
        try await assertTerminal("failed")
    }

    private func assertTerminal(_ name: String) async throws {
        let directory = try copyPublisherFixture(name)
        defer { try? FileManager.default.removeItem(at: directory) }
        let now = fixedDate
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: directory, clock: { now }, monotonicClock: { 100 }
            )
            XCTFail("A terminal publisher envelope must never expose its retained sample as active")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .terminalSession)
        }
    }

    private func copyPublisherFixture(_ name: String) throws -> URL {
        let resource = try XCTUnwrap(Bundle.module.url(
            forResource: name, withExtension: "json", subdirectory: "Fixtures"
        ))
        let payload = try Data(contentsOf: resource)
        XCTAssertLessThanOrEqual(payload.count, 12_288)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(
            "operational-publisher-interop-" + UUID().uuidString, isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700]
        )
        do {
            let sample = directory.appendingPathComponent("sample.json")
            try payload.write(to: sample)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: sample.path)
        } catch {
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
        return directory
    }
}
