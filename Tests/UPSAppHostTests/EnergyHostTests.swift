import Foundation
import XCTest
import UPSEnergy
import UPSModel
import UPSMonitorUI
@testable import UPSAppHost

@MainActor
final class EnergyHostTests: XCTestCase {
    func testIndependentChannelsNeedNoHistoryAndExportOnlyEstimates() async throws {
        let fixture = EnergyHostFixture()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let model = makeModel(fixture, directory: directory)
        await model.startIfNeeded()
        await waitUntil { model.energyEstimates[1].state == .collecting }
        XCTAssertNil(model.energyEstimates[1].energyWh)
        XCTAssertFalse(model.canExportEnergy)
        fixture.advance(to: 105)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        XCTAssertEqual(model.energyEstimates[0].energyWh, 2.5)
        XCTAssertEqual(model.energyEstimates[1].energyWh, 5)
        XCTAssertFalse(model.recordsHistory)
        XCTAssertNil(model.historyBrowser)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        let data = try model.energyExportData()
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["schemaVersion"] as? Int, 1)
        XCTAssertEqual(json["quality"] as? String, "applicationEstimated")
        let estimates = try XCTUnwrap(json["estimates"] as? [[String: Any]])
        XCTAssertEqual(estimates.map { $0["channel"] as? String }, ["input", "ups"])
        XCTAssertEqual(estimates[1]["energyWh"] as? Double, 5)
        let text = String(decoding: data, as: UTF8.self).lowercased()
        for forbidden in ["uptime", "monotonic", "serial", "/users/", "executablepath"] {
            XCTAssertFalse(text.contains(forbidden), "Export must not contain \(forbidden)")
        }
        await model.stop()
    }

    func testCachedPollAndResetCannotReuseCoveredTime() async throws {
        let fixture = EnergyHostFixture()
        let model = makeModel(fixture)
        await model.startIfNeeded()
        await waitUntil { model.energyEstimates[1].state == .collecting }
        fixture.advance(to: 105)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        fixture.advance(to: 106, capturedAt: 105)
        model.refresh()
        await waitUntil { model.now == Date(timeIntervalSince1970: 106) && model.readState == .ready }
        XCTAssertEqual(model.energyEstimates[1].energyWh, 5)
        model.resetEnergy()
        model.refresh()
        try await Task.sleep(for: .milliseconds(80))
        XCTAssertEqual(model.energyEstimates[1].state, .unavailable)
        XCTAssertNil(model.energyEstimates[1].energyWh)
        fixture.advance(to: 110)
        model.refresh()
        await waitUntil { model.energyEstimates[1].state == .collecting }
        fixture.advance(to: 115)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        XCTAssertEqual(model.energyEstimates[1].energyWh, 5)
        await model.stop()
    }

    func testSourceSelectionResetsAndStopPreservesButDisablesExport() async throws {
        let fixture = EnergyHostFixture(twoSources: true)
        let model = makeModel(fixture)
        await model.startIfNeeded()
        await waitUntil { model.energyEstimates[1].state == .collecting }
        fixture.advance(to: 105)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        let second = try XCTUnwrap(model.sources.last)
        model.select(UPSMonitorFormatters.sourceKey(for: second))
        XCTAssertNil(model.energyEstimates[1].energyWh)
        model.refresh()
        await waitUntil { model.energyEstimates[1].source == second.source }
        fixture.advance(to: 110)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        XCTAssertEqual(model.energyEstimates[1].energyWh, 10)
        await model.stop()
        XCTAssertEqual(model.energyEstimates[1].state, .paused)
        XCTAssertEqual(model.energyEstimates[1].energyWh, 10)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertThrowsError(try model.energyExportData())
        let reads = fixture.readCount
        model.refresh()
        model.resetEnergy()
        await model.startIfNeeded()
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(fixture.readCount, reads)
        XCTAssertEqual(model.energyEstimates[1].energyWh, 10)
    }

    func testPreviewNeverReadsOrPersistsOrExportsFixtureEnergy() async throws {
        let fixture = EnergyHostFixture()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let model = makeModel(fixture, directory: directory, preview: true)
        await model.startIfNeeded()
        XCTAssertEqual(fixture.readCount, 0)
        XCTAssertNotNil(model.energyEstimates[1].energyWh)
        XCTAssertNil(model.energyEstimates[0].energyWh)
        XCTAssertFalse(model.canExportEnergy)
        XCTAssertThrowsError(try model.energyExportData())
        let estimates = model.energyEstimates
        model.resetEnergy()
        model.refresh()
        await model.setHistoryRecording(true)
        XCTAssertEqual(model.energyEstimates, estimates)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        await model.stop()
    }

    func testFailedReadBreaksCoverageUntilTwoFreshSamples() async {
        let fixture = EnergyHostFixture()
        let model = makeModel(fixture)
        await model.startIfNeeded()
        await waitUntil { model.energyEstimates[1].state == .collecting }
        fixture.advance(to: 105)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        fixture.setFailure(true)
        model.refresh()
        await waitUntil { model.energyEstimates[1].state == .paused }
        XCTAssertEqual(model.energyEstimates[1].energyWh, 5)
        fixture.setFailure(false)
        fixture.advance(to: 107)
        model.refresh()
        await waitUntil { model.selected?.capturedAt == Date(timeIntervalSince1970: 107) }
        XCTAssertEqual(model.energyEstimates[1].coveredDurationSeconds, 5)
        fixture.advance(to: 108)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 6 }
        await model.stop()
    }

    func testBackendReplacementClearsEnergyEvenWhenNewReaderFails() async {
        let fixture = EnergyHostFixture()
        let model = MonitorAppModel(
            read: { try fixture.read() }, clock: { fixture.date }, monotonicClock: { fixture.uptime },
            observesWorkspace: false, isPreview: false,
            nutReadFactory: { _ in { throw EnergyHostFailure.synthetic } })
        await model.startIfNeeded()
        await waitUntil { model.energyEstimates[1].state == .collecting }
        fixture.advance(to: 105)
        model.refresh()
        await waitUntil { model.energyEstimates[1].coveredDurationSeconds == 5 }
        model.connectionDraft = NUTConnectionDraft(executablePath: "/synthetic/upsc",
                                                   expectedSHA256: String(repeating: "a", count: 64),
                                                   upsName: "synthetic", completionQualified: true)
        await model.connectNUT()
        model.refresh()
        await waitUntil { model.readState == .failed }
        XCTAssertEqual(model.backend, .nut)
        XCTAssertTrue(model.energyEstimates.allSatisfy { $0.energyWh == nil && $0.source == nil })
        XCTAssertFalse(model.canExportEnergy)
        await model.stop()
    }

    private func makeModel(_ fixture: EnergyHostFixture, directory: URL? = nil,
                           preview: Bool = false) -> MonitorAppModel {
        MonitorAppModel(read: { try fixture.read() }, clock: { fixture.date },
                        monotonicClock: { fixture.uptime }, historyDirectoryURL: directory,
                        observesWorkspace: false, isPreview: preview)
    }

    private func waitUntil(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<300 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Expected synthetic energy state was not reached", file: file, line: line)
    }
}

private final class EnergyHostFixture: @unchecked Sendable {
    private let lock = NSLock()
    private var time: TimeInterval = 100
    private var captured: TimeInterval = 100
    private var count = 0
    private var fails = false
    private let twoSources: Bool

    init(twoSources: Bool = false) { self.twoSources = twoSources }
    var date: Date { lock.withLock { Date(timeIntervalSince1970: time) } }
    var uptime: TimeInterval { lock.withLock { time } }
    var readCount: Int { lock.withLock { count } }
    func advance(to time: TimeInterval, capturedAt: TimeInterval? = nil) {
        lock.withLock { self.time = time; captured = capturedAt ?? time }
    }
    func setFailure(_ fails: Bool) { lock.withLock { self.fails = fails } }
    func read() throws -> [MonitorSnapshot] {
        try lock.withLock {
            count += 1
            if fails { throw EnergyHostFailure.synthetic }
            return (twoSources ? [1, 2] : [1]).map { index in
                MonitorSnapshot(
                    source: MonitorSource(provider: .nut, id: "synthetic-\(index)", sessionID: "energy-test",
                                          identityStability: .configured),
                    capturedAt: Date(timeIntervalSince1970: captured),
                    status: MonitorStatus(lineState: .onLine, quality: .available),
                    metrics: [
                        MonitorMetric(id: .upsRealPower, value: 3_600 * Double(index), unit: .watts,
                                      quality: .available, provenance: .reported),
                        MonitorMetric(id: .inputRealPower, value: 1_800 * Double(index), unit: .watts,
                                      quality: .available, provenance: .driverDerived)
                    ])
            }
        }
    }
}

private enum EnergyHostFailure: Error { case synthetic }
