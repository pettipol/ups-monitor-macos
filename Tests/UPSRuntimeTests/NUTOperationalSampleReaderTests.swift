import Darwin
import Foundation
import XCTest
import UPSModel
import UPSRuntime

final class NUTOperationalSampleReaderTests: XCTestCase {
    func testActiveV2EnvelopeProjectsFreshValuesAtWideElapsedTime() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        let elapsed: Int64 = 4_294_972_296
        let slot = elapsed / 5_000
        let now = fixture.date(atElapsedMS: elapsed)
        let clock = OperationalReaderClock(date: now, uptime: 500)
        try fixture.publish(
            sample: Self.sample(observedMS: elapsed),
            publishedAt: now, sequence: slot + 1, slot: slot, elapsedMS: elapsed
        )

        let reader = try await NUTOperationalSampleReader.connect(
            directoryURL: fixture.directoryURL,
            clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)

        XCTAssertEqual(snapshot.source.id, "operational-source")
        XCTAssertEqual(snapshot.source.sessionID, "0123456789abcdef0123456789abcdef")
        XCTAssertEqual(snapshot.capturedAt.timeIntervalSince(now), 0, accuracy: 0.001)
        XCTAssertEqual(snapshot.status.lineState, .onLine)
        XCTAssertEqual(metric(.batteryCharge, in: snapshot)?.value, 82)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot)?.provenance, .estimated)
        XCTAssertEqual(metric(.batteryVoltage, in: snapshot)?.quality, .unavailable)
        XCTAssertNil(metric(.batteryVoltage, in: snapshot)?.value)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.value, 100)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.provenance, .driverDerived)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot)?.value, 150)
        XCTAssertEqual(metric(.upsRealPowerNominal, in: snapshot)?.provenance, .reported)
        try snapshot.validate()
    }

    func testPublisherExponentNumbersProjectThroughTheExistingDomainDecoder() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        var fields = Self.sample()
        fields["battery.charge"] = .observed("8.2e1", observedMS: 0, kind: "reported")
        fields["ups.realpower.nominal"] = .observed("1e+3", observedMS: 0, kind: "static")
        fields["ups.power.nominal"] = .observed("1.5e+3", observedMS: 0, kind: "static")
        try fixture.publish(sample: fields, publishedAt: fixture.startedAt)
        let fixedDate = fixture.startedAt
        let reader = try await NUTOperationalSampleReader.connect(
            directoryURL: fixture.directoryURL,
            clock: { fixedDate }, monotonicClock: { 120 }
        )

        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)
        XCTAssertEqual(metric(.batteryCharge, in: snapshot)?.value, 82)
        XCTAssertEqual(metric(.upsRealPowerNominal, in: snapshot)?.value, 1_000)
        XCTAssertEqual(metric(.upsApparentPowerNominal, in: snapshot)?.value, 1_500)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.value, 100)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot)?.value, 150)
    }

    func testMaximumSafeElapsedAndObservationTimestampsAreAccepted() async throws {
        let maximumSafe: Int64 = 9_007_199_254_740_991
        let fixture = try OperationalFixture(startedAtUnixMS: 0)
        defer { fixture.remove() }
        let slot = maximumSafe / 5_000
        let now = Date(timeIntervalSince1970: Double(maximumSafe) / 1_000)
        let clock = OperationalReaderClock(date: now, uptime: 700)
        try fixture.publish(
            sample: Self.sample(observedMS: maximumSafe), publishedAt: now,
            sequence: slot + 1, slot: slot, elapsedMS: maximumSafe,
            publishedAtUnixMS: maximumSafe
        )

        let reader = try await NUTOperationalSampleReader.connect(
            directoryURL: fixture.directoryURL,
            clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)
        XCTAssertEqual(snapshot.status.lineState, .onLine)
    }

    func testStoppedAndFailedV2EnvelopesAreTerminalAtConnect() async throws {
        for (state, reason) in [("stopped", "cancelled"), ("failed", "cleanup_unresolved")] {
            let fixture = try OperationalFixture()
            defer { fixture.remove() }
            try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt,
                                state: state, reason: reason)
            let fixedDate = fixture.startedAt
            do {
                _ = try await NUTOperationalSampleReader.connect(
                    directoryURL: fixture.directoryURL,
                    clock: { fixedDate }, monotonicClock: { 50 }
                )
                XCTFail("A \(state) envelope must not produce an active reader")
            } catch {
                XCTAssertEqual(error as? NUTOperationalSampleReaderError, .terminalSession)
            }
        }
    }

    func testExistingReaderCannotProjectTerminalEnvelopeAsActive() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        let clock = OperationalReaderClock(date: fixture.startedAt, uptime: 70)
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let reader = try await NUTOperationalSampleReader.connect(
            directoryURL: fixture.directoryURL,
            clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt,
                            state: "failed", reason: "device_lost")
        do {
            _ = try await reader.read()
            XCTFail("A terminal envelope must never be projected as active telemetry")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .terminalSession)
        }
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        do {
            _ = try await reader.read()
            XCTFail("A terminal reader must not resume after a later active rewrite")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .terminalSession)
        }
    }

    func testStaleDynamicFieldsAreNotRelabelledFreshByNewPublication() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        let now = fixture.startedAt.addingTimeInterval(11)
        try fixture.publish(sample: Self.sample(observedMS: 0),
                            publishedAt: now, sequence: 3, slot: 2, elapsedMS: 11_000)
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { now }, monotonicClock: { 61 }
            )
            XCTFail("A fresh envelope cannot make old dynamic observations fresh")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .noFreshTelemetry)
        }
    }

    func testStaleEnvelopePublicationIsRejected() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        let now = fixture.startedAt.addingTimeInterval(11)
        try fixture.publish(sample: Self.sample(observedMS: 11_000),
                            publishedAt: fixture.startedAt,
                            sequence: 3, slot: 2, elapsedMS: 11_000)
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { now }, monotonicClock: { 61 }
            )
            XCTFail("An envelope older than the read-age bound must be rejected")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .staleEnvelope)
        }
    }

    func testFreshStatusDoesNotRefreshStaleDerivedPowerDependencies() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        let now = fixture.startedAt.addingTimeInterval(11)
        var fields = Self.sample(observedMS: 0)
        fields["ups.status"] = .observed("OL", observedMS: 11_000, kind: "reported")
        fields["battery.charge"] = .observed("82", observedMS: 11_000, kind: "reported")
        try fixture.publish(sample: fields, publishedAt: now,
                            sequence: 3, slot: 2, elapsedMS: 11_000)
        let reader = try await NUTOperationalSampleReader.connect(
            directoryURL: fixture.directoryURL,
            clock: { now }, monotonicClock: { 61 }
        )

        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)
        XCTAssertEqual(metric(.batteryCharge, in: snapshot)?.quality, .available)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.quality, .unavailable)
        XCTAssertNil(metric(.upsRealPower, in: snapshot)?.value)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot)?.quality, .unavailable)
    }

    func testOverflowingDerivedExpectationIsRejectedWithStaleDependenciesAndFreshStatus() async throws {
        for (load, nominal, derived) in [
            ("ups.load", "ups.realpower.nominal", "ups.realpower"),
            ("experimental.ups.load.apparent", "ups.power.nominal", "ups.power"),
        ] {
            let fixture = try OperationalFixture()
            defer { fixture.remove() }
            let now = fixture.date(atElapsedMS: 11_000)
            var fields = Self.sample(observedMS: 0)
            fields["ups.status"] = .observed("OL", observedMS: 11_000, kind: "reported")
            fields[load] = .observed("100", observedMS: 0, kind: "reported")
            fields[nominal] = .observed("1e308", observedMS: 0, kind: "static")
            fields[derived] = .observed("1e308", observedMS: 0, kind: "driverDerived")
            try fixture.publish(sample: fields, publishedAt: now,
                                sequence: 3, slot: 2, elapsedMS: 11_000)

            do {
                _ = try await NUTOperationalSampleReader.connect(
                    directoryURL: fixture.directoryURL,
                    clock: { now }, monotonicClock: { 61 }
                )
                XCTFail("Finite wire values must not hide an overflowing \(derived) dependency behind stale telemetry")
            } catch {
                XCTAssertEqual(error as? NUTOperationalSampleReaderError, .invalidSample)
            }
        }
    }

    func testCachedNominalDoesNotHideMalformedUnavailableWireField() async throws {
        let malformedFields: [FieldFixture] = [
            .unavailable(kind: "reported"),
            FieldFixture(value: "999", observedMS: 5_000,
                         kind: "static", state: "unavailable"),
        ]
        for malformed in malformedFields {
            let fixture = try OperationalFixture()
            defer { fixture.remove() }
            let clock = OperationalReaderClock(date: fixture.startedAt, uptime: 130)
            try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
            let reader = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { clock.date }, monotonicClock: { clock.uptime }
            )
            clock.advance(seconds: 5)
            var next = Self.sample(observedMS: 5_000)
            next["ups.realpower.nominal"] = malformed
            next["ups.realpower"] = .unavailable(kind: "driverDerived")
            try fixture.publish(sample: next, publishedAt: clock.date,
                                sequence: 2, slot: 1, elapsedMS: 5_000)
            do {
                _ = try await reader.read()
                XCTFail("A cached static value must not mask an invalid incoming nominal field")
            } catch {
                XCTAssertEqual(error as? NUTOperationalSampleReaderError, .invalidSample)
            }
        }
    }

    func testV1SchemaAndDuplicateEnvelopeKeysAreRejected() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt,
                            schemaVersion: 1, protocolName: "ups-monitor.continuous.v1")
        let fixedDate = fixture.startedAt
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { fixedDate }, monotonicClock: { 50 }
            )
            XCTFail("The explicit v2 reader must not autodetect or accept v1")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .malformedEnvelope)
        }

        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let bytes = try XCTUnwrap(String(data: fixture.readBytes(), encoding: .utf8))
        let duplicate = bytes.replacingOccurrences(
            of: "\"source_id\":\"operational-source\"",
            with: "\"source_id\":\"operational-source\",\"source_id\":\"other\""
        )
        try fixture.writeRaw(Data(duplicate.utf8))
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { fixedDate }, monotonicClock: { 50 }
            )
            XCTFail("Duplicate envelope keys must be rejected")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .duplicateJSONKey)
        }
    }

    func testMalformedAndOversizedPayloadsAreRejected() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        try fixture.writeRaw(Data("{not-json}\n".utf8))
        let fixedDate = fixture.startedAt
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { fixedDate }, monotonicClock: { 50 }
            )
            XCTFail("Malformed JSON must be rejected")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .malformedEnvelope)
        }

        try fixture.writeRaw(Data(repeating: 0x20, count: 16_385))
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { fixedDate }, monotonicClock: { 50 }
            )
            XCTFail("Payloads above the local bound must be rejected")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .payloadTooLarge)
        }
    }

    func testSymlinkSampleFileIsRejected() async throws {
        let fixture = try OperationalFixture()
        defer { fixture.remove() }
        let target = fixture.parentURL.appendingPathComponent("target.json")
        try Data("{}".utf8).write(to: target)
        chmod(target.path, 0o600)
        let sample = fixture.directoryURL.appendingPathComponent("sample.json")
        try FileManager.default.createSymbolicLink(at: sample, withDestinationURL: target)
        let fixedDate = fixture.startedAt
        do {
            _ = try await NUTOperationalSampleReader.connect(
                directoryURL: fixture.directoryURL,
                clock: { fixedDate }, monotonicClock: { 50 }
            )
            XCTFail("A symlink must not be followed")
        } catch {
            XCTAssertEqual(error as? NUTOperationalSampleReaderError, .unsafeFile)
        }
    }

    private func metric(_ id: MonitorMetricID, in snapshot: MonitorSnapshot) -> MonitorMetric? {
        snapshot.metrics.first { $0.id == id }
    }

    private static func sample(observedMS: Int64 = 0) -> [String: FieldFixture] {
        var fields = Dictionary(uniqueKeysWithValues: [
            "ups.status", "battery.charge", "battery.runtime", "battery.voltage", "battery.temperature",
            "ups.temperature", "input.voltage", "input.frequency", "output.voltage", "output.current",
            "output.frequency", "ups.load", "experimental.ups.load.apparent", "ups.realpower.nominal",
            "ups.power.nominal", "ups.realpower", "ups.power",
        ].map { ($0, FieldFixture.unavailable(kind: Self.kind(for: $0))) })
        fields["ups.status"] = .observed("OL", observedMS: observedMS, kind: "reported")
        fields["battery.charge"] = .observed("82", observedMS: observedMS, kind: "reported")
        fields["battery.runtime"] = .observed("1200", observedMS: observedMS, kind: "reported")
        fields["battery.temperature"] = .observed("25", observedMS: observedMS, kind: "reported")
        fields["ups.temperature"] = .observed("25", observedMS: observedMS, kind: "reported")
        fields["ups.load"] = .observed("10", observedMS: observedMS, kind: "reported")
        fields["experimental.ups.load.apparent"] = .observed("10", observedMS: observedMS, kind: "reported")
        fields["ups.realpower.nominal"] = .observed("1000", observedMS: observedMS, kind: "static")
        fields["ups.power.nominal"] = .observed("1500", observedMS: observedMS, kind: "static")
        fields["ups.realpower"] = .observed("100", observedMS: observedMS, kind: "driverDerived")
        fields["ups.power"] = .observed("150", observedMS: observedMS, kind: "driverDerived")
        return fields
    }

    private static func kind(for name: String) -> String {
        if name.hasSuffix(".nominal") { return "static" }
        if name == "ups.realpower" || name == "ups.power" { return "driverDerived" }
        return "reported"
    }
}

private struct FieldFixture {
    let value: String?
    let observedMS: Int64?
    let kind: String
    let state: String

    static func observed(_ value: String, observedMS: Int64, kind: String) -> Self {
        Self(value: value, observedMS: observedMS, kind: kind, state: "observed")
    }
    static func unavailable(kind: String) -> Self {
        Self(value: nil, observedMS: nil, kind: kind, state: "unavailable")
    }
}

private final class OperationalReaderClock: @unchecked Sendable {
    private let lock = NSLock()
    private var storedDate: Date
    private var storedUptime: TimeInterval
    var date: Date { lock.lock(); defer { lock.unlock() }; return storedDate }
    var uptime: TimeInterval { lock.lock(); defer { lock.unlock() }; return storedUptime }
    init(date: Date, uptime: TimeInterval) { storedDate = date; storedUptime = uptime }
    func advance(seconds: TimeInterval) {
        lock.lock(); storedDate.addTimeInterval(seconds); storedUptime += seconds; lock.unlock()
    }
}

private final class OperationalFixture {
    let parentURL: URL
    let directoryURL: URL
    let startedAt: Date
    private let sourceID = "operational-source"
    private let sessionID = "0123456789abcdef0123456789abcdef"
    private let startedAtMS: Int64

    init(startedAtUnixMS: Int64 = 1_800_000_000_000) throws {
        startedAtMS = startedAtUnixMS
        startedAt = Date(timeIntervalSince1970: Double(startedAtUnixMS) / 1_000)
        parentURL = FileManager.default.temporaryDirectory.appendingPathComponent("operational-reader-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: parentURL, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        directoryURL = parentURL.appendingPathComponent("session", isDirectory: true)
        try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
    }

    func date(atElapsedMS elapsedMS: Int64) -> Date {
        Date(timeIntervalSince1970: Double(startedAtMS + elapsedMS) / 1_000)
    }

    func publish(sample: [String: FieldFixture], publishedAt: Date,
                 state: String = "active", reason: String? = nil,
                 sequence: Int64 = 1, slot: Int64 = 0, elapsedMS: Int64 = 0,
                 schemaVersion: Int = 2, protocolName: String = "ups-monitor.continuous.v2",
                 publishedAtUnixMS: Int64? = nil) throws {
        let sampleObject: [String: Any] = [
            "protocol": protocolName, "schema_version": schemaVersion, "type": "sample",
            "sequence": sequence, "slot": slot, "elapsed_ms": elapsedMS,
            "missed_slots": slot + 1 - sequence,
            "fields": Dictionary(uniqueKeysWithValues: sample.map { ($0.key, fieldObject($0.value)) }),
        ]
        var envelope: [String: Any] = [
            "schema_version": 2, "protocol": "ups-monitor.continuous.v2",
            "source_id": sourceID, "session_id": sessionID, "state": state,
            "started_at_unix_ms": startedAtMS,
            "published_at_unix_ms": publishedAtUnixMS ?? milliseconds(publishedAt),
            "terminal_reason": reason.map { $0 as Any } ?? NSNull(),
            "sample": sampleObject,
        ]
        if schemaVersion == 1 {
            envelope["schema_version"] = 1
            envelope["protocol"] = "ups-monitor.continuous.v1"
        }
        try writeRaw(JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys]))
    }

    func readBytes() throws -> Data {
        try Data(contentsOf: directoryURL.appendingPathComponent("sample.json"))
    }

    func writeRaw(_ data: Data) throws {
        let file = directoryURL.appendingPathComponent("sample.json")
        try data.write(to: file, options: .atomic)
        chmod(file.path, 0o600)
    }

    func remove() { try? FileManager.default.removeItem(at: parentURL) }

    private func fieldObject(_ field: FieldFixture) -> [String: Any] {
        ["value": field.value as Any? ?? NSNull(),
         "observed_ms": field.observedMS as Any? ?? NSNull(),
         "kind": field.kind, "state": field.state]
    }

    private func milliseconds(_ date: Date) -> Int64 {
        Int64((date.timeIntervalSince1970 * 1_000).rounded())
    }
}
