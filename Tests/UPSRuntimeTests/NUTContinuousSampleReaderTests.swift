import Darwin
import Foundation
import XCTest
import UPSModel
import UPSRuntime

final class NUTContinuousSampleReaderTests: XCTestCase {
    private let sourceID = "trial-source"
    private let sessionID = "session-1"

    func testConnectProjectsFreshAllowedMetricsAndDerivedUnits() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)

        XCTAssertEqual(snapshot.source.id, sourceID)
        XCTAssertEqual(snapshot.source.sessionID, sessionID)
        XCTAssertEqual(snapshot.capturedAt, fixture.startedAt)
        XCTAssertEqual(snapshot.status.lineState, .onLine)
        XCTAssertEqual(snapshot.status.quality, .available)
        XCTAssertEqual(metric(.batteryRuntime, in: snapshot)?.provenance, .estimated)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.value, 100)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.unit, .watts)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.provenance, .driverDerived)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot)?.value, 150)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot)?.unit, .voltAmps)
        XCTAssertEqual(metric(.batteryTemperature, in: snapshot)?.value, 25)
        XCTAssertEqual(metric(.upsTemperature, in: snapshot)?.value, 25)
        XCTAssertEqual(metric(.upsRealPowerNominal, in: snapshot)?.provenance, .reported)
        XCTAssertEqual(metric(.upsLoad, in: snapshot)?.value, 10)
        try snapshot.validate()
    }

    func testStaleDynamicTelemetryExpiresEvenWhenEnvelopeIsRepublished() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        let initial = Self.sample()
        try fixture.publish(sample: initial, publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        clock.advance(seconds: 11)
        try fixture.publish(sample: initial, publishedAt: clock.date)
        do {
            _ = try await reader.read()
            XCTFail("A republished envelope must not make its old measurement fresh")
        } catch {
            XCTAssertEqual(error as? NUTContinuousSampleReaderError, .noFreshTelemetry)
        }
    }

    func testStaticNominalsPersistWithoutMovingDynamicCaptureTime() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        let sample = Self.sample()
        try fixture.publish(sample: sample, publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        clock.advance(seconds: 5)
        var next = Self.sample()
        next["ups.status"] = .observed("OL", observedMS: 5_000, kind: "reported")
        next["battery.charge"] = .observed("82", observedMS: 5_000, kind: "reported")
        next["battery.runtime"] = .observed("1200", observedMS: 5_000, kind: "reported")
        next["battery.temperature"] = .observed("25", observedMS: 5_000, kind: "reported")
        next["ups.temperature"] = .observed("25", observedMS: 5_000, kind: "reported")
        next["ups.load"] = .observed("10", observedMS: 5_000, kind: "reported")
        next["experimental.ups.load.apparent"] = .observed("10", observedMS: 5_000, kind: "reported")
        next["ups.realpower"] = .observed("100", observedMS: 5_000, kind: "driverDerived")
        next["ups.power"] = .observed("150", observedMS: 5_000, kind: "driverDerived")
        next["ups.realpower.nominal"] = .unavailable(kind: "static")
        next["ups.power.nominal"] = .unavailable(kind: "static")
        try fixture.publish(sample: next, publishedAt: clock.date, sequence: 2, slot: 1, elapsedMS: 5_000)
        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)
        XCTAssertEqual(snapshot.capturedAt, clock.date)
        XCTAssertEqual(metric(.upsRealPowerNominal, in: snapshot)?.value, 1_000)
        XCTAssertEqual(metric(.upsApparentPowerNominal, in: snapshot)?.value, 1_500)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.value, 100)
    }

    func testStaleLoadDependencyHidesDerivedPowerButKeepsFreshFields() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        clock.advance(seconds: 11)
        var next = Self.sample()
        next["ups.status"] = .observed("OL", observedMS: 11_000, kind: "reported")
        next["battery.charge"] = .observed("82", observedMS: 11_000, kind: "reported")
        next["ups.load"] = .observed("10", observedMS: 0, kind: "reported")
        next["experimental.ups.load.apparent"] = .observed("10", observedMS: 0, kind: "reported")
        next["ups.realpower"] = .observed("100", observedMS: 0, kind: "driverDerived")
        next["ups.power"] = .observed("150", observedMS: 0, kind: "driverDerived")
        try fixture.publish(sample: next, publishedAt: clock.date, sequence: 2, slot: 2, elapsedMS: 11_000)
        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)
        XCTAssertEqual(metric(.batteryCharge, in: snapshot)?.quality, .available)
        XCTAssertEqual(metric(.upsRealPower, in: snapshot)?.quality, .unavailable)
        XCTAssertNil(metric(.upsRealPower, in: snapshot)?.value)
        XCTAssertEqual(metric(.upsApparentPower, in: snapshot)?.quality, .unavailable)
    }

    func testInvalidNumericFieldIsInvalidAndMissingFieldRemainsUnavailable() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        var sample = Self.sample()
        sample["battery.charge"] = .observed("101", observedMS: 0, kind: "reported")
        try fixture.publish(sample: sample, publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        let readings = try await reader.read()
        let snapshot = try XCTUnwrap(readings.first)
        XCTAssertEqual(metric(.batteryCharge, in: snapshot)?.quality, .invalid)
        XCTAssertNil(metric(.batteryCharge, in: snapshot)?.value)
        XCTAssertEqual(metric(.batteryVoltage, in: snapshot)?.quality, .unavailable)
        XCTAssertNil(metric(.batteryVoltage, in: snapshot)?.value)
    }

    func testEmptyObservedStatusDoesNotCountAsFreshTelemetry() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        var fields = Self.sample()
        for name in ["battery.charge", "battery.runtime", "battery.voltage", "battery.temperature", "ups.temperature",
                     "input.voltage", "input.frequency", "output.voltage", "output.current", "output.frequency",
                     "ups.load", "experimental.ups.load.apparent", "ups.realpower", "ups.power"] {
            let kind = name == "ups.realpower" || name == "ups.power" ? "driverDerived" : "reported"
            fields[name] = .unavailable(kind: kind)
        }
        fields["ups.status"] = .observed("", observedMS: 0, kind: "reported")
        let now = fixture.startedAt
        try fixture.publish(sample: fields, publishedAt: now)
        do {
            _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                            clock: { now }, monotonicClock: { 100 })
            XCTFail("Empty status is unavailable and cannot make nominal-only input a sample")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .noFreshTelemetry) }
    }

    func testNonCanonicalObservedStatusIsRejected() async throws {
        for value in [" OL ", "OL  RB", "   "] {
            let fixture = try Fixture()
            defer { fixture.remove() }
            var sample = Self.sample()
            sample["ups.status"] = .observed(value, observedMS: 0, kind: "reported")
            try fixture.publish(sample: sample, publishedAt: fixture.startedAt)
            let fixedDate = fixture.startedAt
            do {
                _ = try await NUTContinuousSampleReader.connect(
                    directoryURL: fixture.directoryURL,
                    clock: { fixedDate }, monotonicClock: { 100 }
                )
                XCTFail("Non-canonical status must be rejected: \(value.debugDescription)")
            } catch {
                XCTAssertEqual(error as? NUTContinuousSampleReaderError, .invalidSample,
                               "Unexpected rejection for status \(value.debugDescription)")
            }
        }
    }

    func testUnknownEnvelopeSampleAndFieldKeysAreRejected() async throws {
        // Envelope keys must be enumerated dynamically: an enum-keyed container hides unknown keys.
        do {
            let fixture = try Fixture()
            defer { fixture.remove() }
            try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
            var envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture.readBytes()) as? [String: Any])
            envelope["unexpected"] = true
            try fixture.writeRaw(JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys]))
            let fixedDate = fixture.startedAt
            do {
                _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                                clock: { fixedDate }, monotonicClock: { 100 })
                XCTFail("Unknown envelope key must fail closed")
            } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .malformedEnvelope) }
        }

        // Apply the same check at the nested sample and field record boundaries.
        for target in ["sample", "field"] {
            let fixture = try Fixture()
            defer { fixture.remove() }
            try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
            var envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture.readBytes()) as? [String: Any])
            var sample = try XCTUnwrap(envelope["sample"] as? [String: Any])
            if target == "sample" {
                sample["unexpected"] = true
            } else {
                var fields = try XCTUnwrap(sample["fields"] as? [String: Any])
                var status = try XCTUnwrap(fields["ups.status"] as? [String: Any])
                status["unexpected"] = true
                fields["ups.status"] = status
                sample["fields"] = fields
            }
            envelope["sample"] = sample
            try fixture.writeRaw(JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys]))
            let fixedDate = fixture.startedAt
            do {
                _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                                clock: { fixedDate }, monotonicClock: { 100 })
                XCTFail("Unknown \(target) key must fail closed")
            } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .invalidSample) }
        }
    }

    func testElapsedTimeMustMatchFiveSecondSampleSlot() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt.addingTimeInterval(5), uptime: 105)
        // At 5 seconds the matching slot is 1; this fixture's sequence/missed_slots are otherwise valid.
        try fixture.publish(sample: Self.sample(), publishedAt: clock.date,
                            sequence: 1, slot: 0, elapsedMS: 5_000)
        do {
            _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                            clock: { clock.date }, monotonicClock: { clock.uptime })
            XCTFail("Slot must equal elapsed_ms / 5000")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .invalidSample) }
    }

    func testNewSequenceMustAdvanceSlotAndElapsedButMaySkipSequence() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt.addingTimeInterval(6), uptime: 106)
        let baseline = Self.sample()
        try fixture.publish(sample: baseline, publishedAt: clock.date, sequence: 1, slot: 1, elapsedMS: 6_000)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )

        // Sol counterexample: a new sequence cannot reuse slot=1 and elapsed_ms=6000.
        try fixture.publish(sample: baseline, publishedAt: clock.date, sequence: 2, slot: 1, elapsedMS: 6_000)
        do {
            _ = try await reader.read()
            XCTFail("A new sequence must advance both slot and elapsed_ms")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .replayOrRegression) }

        // The consumer may skip sequence 2 while still requiring time and slot progress.
        clock.advance(seconds: 4)
        try fixture.publish(sample: baseline, publishedAt: clock.date, sequence: 3, slot: 2, elapsedMS: 10_000)
        let readings = try await reader.read()
        XCTAssertEqual(readings.first?.source.sessionID, sessionID)
    }

    func testObservedDerivedRequiresDependenciesAndPythonTolerance() async throws {
        let missingFixture = try Fixture()
        defer { missingFixture.remove() }
        var missing = Self.sample()
        missing["ups.load"] = .unavailable(kind: "reported")
        missing["ups.realpower"] = .observed("100", observedMS: 0, kind: "driverDerived")
        try missingFixture.publish(sample: missing, publishedAt: missingFixture.startedAt)
        let missingDate = missingFixture.startedAt
        do {
            _ = try await NUTContinuousSampleReader.connect(
                directoryURL: missingFixture.directoryURL,
                clock: { missingDate }, monotonicClock: { 100 }
            )
            XCTFail("Observed derived power without a reported load dependency is malformed")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .invalidSample) }

        let incoherentFixture = try Fixture()
        defer { incoherentFixture.remove() }
        var incoherent = Self.sample()
        incoherent["ups.load"] = .observed("31.5", observedMS: 0, kind: "reported")
        incoherent["ups.realpower.nominal"] = .observed("650", observedMS: 0, kind: "static")
        incoherent["ups.realpower"] = .observed("204.7501", observedMS: 0, kind: "driverDerived")
        try incoherentFixture.publish(sample: incoherent, publishedAt: incoherentFixture.startedAt)
        let incoherentDate = incoherentFixture.startedAt
        do {
            _ = try await NUTContinuousSampleReader.connect(
                directoryURL: incoherentFixture.directoryURL,
                clock: { incoherentDate }, monotonicClock: { 100 }
            )
            XCTFail("Derived power outside Python's tolerance must be rejected")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .invalidSample) }

        let toleratedFixture = try Fixture()
        defer { toleratedFixture.remove() }
        var withinTolerance = Self.sample()
        withinTolerance["ups.load"] = .observed("31.5", observedMS: 0, kind: "reported")
        withinTolerance["ups.realpower.nominal"] = .observed("650", observedMS: 0, kind: "static")
        withinTolerance["ups.realpower"] = .observed("204.7500005", observedMS: 0, kind: "driverDerived")
        try toleratedFixture.publish(sample: withinTolerance, publishedAt: toleratedFixture.startedAt)
        let toleratedDate = toleratedFixture.startedAt
        _ = try await NUTContinuousSampleReader.connect(
            directoryURL: toleratedFixture.directoryURL,
            clock: { toleratedDate }, monotonicClock: { 100 }
        )
    }

    func testFloatingPointEncodedIntegerFieldIsRejected() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let json = try XCTUnwrap(String(data: fixture.readBytes(), encoding: .utf8))
        let malformed = json.replacingOccurrences(of: "\"schema_version\":1,\"sequence\"",
                                                  with: "\"schema_version\":1.0,\"sequence\"")
        XCTAssertNotEqual(json, malformed, "The fixture must target the nested sample schema_version token")
        try fixture.writeRaw(Data(malformed.utf8))
        let fixedDate = fixture.startedAt
        do {
            _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                            clock: { fixedDate }, monotonicClock: { 100 })
            XCTFail("Wire integer fields must reject JSON float tokens such as 1.0")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .malformedEnvelope) }
    }

    func testChangedSameSequencePayloadFailsClosed() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        var changed = Self.sample()
        changed["ups.load"] = .observed("20", observedMS: 0, kind: "reported")
        changed["ups.realpower"] = .observed("200", observedMS: 0, kind: "driverDerived")
        try fixture.publish(sample: changed, publishedAt: fixture.startedAt)
        do {
            _ = try await reader.read()
            XCTFail("A changed payload at an accepted sequence must fail")
        } catch {
            XCTAssertEqual(error as? NUTContinuousSampleReaderError, .replayOrRegression)
        }
    }

    func testSameSequenceCannotBeMadeFreshByChangingSessionStart() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        let sample = Self.sample()
        try fixture.publish(sample: sample, publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        clock.advance(seconds: 1)
        try fixture.publish(sample: sample, publishedAt: clock.date,
                            startedAt: fixture.startedAt.addingTimeInterval(1))
        do {
            _ = try await reader.read()
            XCTFail("Changing the start anchor must not reset observation age")
        } catch {
            XCTAssertEqual(error as? NUTContinuousSampleReaderError, .replayOrRegression)
        }
    }

    func testTerminalSessionCannotResurrectForExistingReader() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let reader = try await NUTContinuousSampleReader.connect(
            directoryURL: fixture.directoryURL, clock: { clock.date }, monotonicClock: { clock.uptime }
        )
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt,
                            state: "failed", reason: "device_lost")
        do {
            _ = try await reader.read()
            XCTFail("The terminal sample should stop this reader")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .terminalSession) }
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        do {
            _ = try await reader.read()
            XCTFail("A terminal reader must not resume an active feed")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .terminalSession) }
    }

    func testDuplicateKeysMismatchedIdentityAndTerminalFeedFailClosed() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let bytes = try XCTUnwrap(String(data: fixture.readBytes(), encoding: .utf8))
        let duplicate = bytes.replacingOccurrences(of: "\"source_id\":\"\(sourceID)\"",
                                                    with: "\"source_id\":\"\(sourceID)\",\"source_id\":\"other\"")
        try fixture.writeRaw(Data(duplicate.utf8))
        let fixedDate = fixture.startedAt
        do {
            _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                            clock: { fixedDate }, monotonicClock: { 100 })
            XCTFail("Duplicate JSON keys must be rejected before decoding")
        } catch {
            XCTAssertEqual(error as? NUTContinuousSampleReaderError, .duplicateJSONKey)
        }

        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt, sourceID: "other-source")
        do {
            let reader = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                                    clock: { fixedDate }, monotonicClock: { 100 })
            _ = try await reader.read()
        } catch { XCTFail("Connect pins the selected feed's source ID; it does not compare a prior fixture ID: \(error)") }

        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt, state: "failed", reason: "device_lost")
        do {
            _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                            clock: { fixedDate }, monotonicClock: { 100 })
            XCTFail("Terminal feeds cannot start a continuous reader")
        } catch {
            XCTAssertEqual(error as? NUTContinuousSampleReaderError, .terminalSession)
        }
    }

    func testUnsafeSymlinkSampleFileIsRejected() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let target = fixture.parentURL.appendingPathComponent("target.json")
        try Data("{}".utf8).write(to: target)
        chmod(target.path, 0o600)
        let sample = fixture.directoryURL.appendingPathComponent("sample.json")
        try FileManager.default.createSymbolicLink(at: sample, withDestinationURL: target)
        let fixedDate = fixture.startedAt
        do {
            _ = try await NUTContinuousSampleReader.connect(directoryURL: fixture.directoryURL,
                                                            clock: { fixedDate }, monotonicClock: { 100 })
            XCTFail("Symlink feed files must be rejected")
        } catch {
            XCTAssertEqual(error as? NUTContinuousSampleReaderError, .unsafeFile)
        }
    }

    func testClockRollbackAndPinnedIdentityFailClosed() async throws {
        let fixture = try Fixture()
        defer { fixture.remove() }
        let clock = LockedReaderClock(date: fixture.startedAt, uptime: 100)
        try fixture.publish(sample: Self.sample(), publishedAt: fixture.startedAt)
        let reader = try NUTContinuousSampleReader(sampleFileURL: fixture.directoryURL.appendingPathComponent("sample.json"),
                                                   expectedSourceID: "expected-source", expectedSessionID: sessionID,
                                                   clock: { clock.date }, monotonicClock: { clock.uptime })
        do {
            _ = try await reader.read()
            XCTFail("Pinned source ID mismatch must fail")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .wrongIdentity) }

        let pinnedReader = try NUTContinuousSampleReader(sampleFileURL: fixture.directoryURL.appendingPathComponent("sample.json"),
                                                         expectedSourceID: sourceID, expectedSessionID: sessionID,
                                                         clock: { clock.date }, monotonicClock: { clock.uptime })
        clock.set(date: fixture.startedAt.addingTimeInterval(-1), uptime: 99)
        do {
            _ = try await pinnedReader.read()
            XCTFail("Wall-clock rollback must fail closed")
        } catch { XCTAssertEqual(error as? NUTContinuousSampleReaderError, .clockDiscontinuity) }
    }

    private func metric(_ id: MonitorMetricID, in snapshot: MonitorSnapshot) -> MonitorMetric? {
        snapshot.metrics.first { $0.id == id }
    }

    private static func sample() -> [String: FieldFixture] {
        var fields = Dictionary(uniqueKeysWithValues: [
            "ups.status", "battery.charge", "battery.runtime", "battery.voltage", "battery.temperature",
            "ups.temperature", "input.voltage", "input.frequency", "output.voltage", "output.current",
            "output.frequency", "ups.load", "experimental.ups.load.apparent", "ups.realpower.nominal",
            "ups.power.nominal", "ups.realpower", "ups.power",
        ].map { ($0, FieldFixture.unavailable(kind: $0.hasSuffix("nominal") ? "static" : ($0 == "ups.realpower" || $0 == "ups.power" ? "driverDerived" : "reported"))) })
        fields["ups.status"] = .observed("OL", observedMS: 0, kind: "reported")
        fields["battery.charge"] = .observed("82", observedMS: 0, kind: "reported")
        fields["battery.runtime"] = .observed("1200", observedMS: 0, kind: "reported")
        fields["battery.temperature"] = .observed("25", observedMS: 0, kind: "reported")
        fields["ups.temperature"] = .observed("25", observedMS: 0, kind: "reported")
        fields["ups.load"] = .observed("10", observedMS: 0, kind: "reported")
        fields["experimental.ups.load.apparent"] = .observed("10", observedMS: 0, kind: "reported")
        fields["ups.realpower.nominal"] = .observed("1000", observedMS: 0, kind: "static")
        fields["ups.power.nominal"] = .observed("1500", observedMS: 0, kind: "static")
        fields["ups.realpower"] = .observed("100", observedMS: 0, kind: "driverDerived")
        fields["ups.power"] = .observed("150", observedMS: 0, kind: "driverDerived")
        return fields
    }
}

private struct FieldFixture {
    let value: String?
    let observedMS: Int?
    let kind: String
    let state: String

    static func observed(_ value: String, observedMS: Int, kind: String) -> Self {
        Self(value: value, observedMS: observedMS, kind: kind, state: "observed")
    }
    static func unavailable(kind: String) -> Self { Self(value: nil, observedMS: nil, kind: kind, state: "unavailable") }
}

private final class LockedReaderClock: @unchecked Sendable {
    private let lock = NSLock()
    private var storedDate: Date
    private var storedUptime: TimeInterval
    var date: Date { lock.lock(); defer { lock.unlock() }; return storedDate }
    var uptime: TimeInterval { lock.lock(); defer { lock.unlock() }; return storedUptime }
    init(date: Date, uptime: TimeInterval) { storedDate = date; storedUptime = uptime }
    func advance(seconds: TimeInterval) {
        lock.lock(); storedDate.addTimeInterval(seconds); storedUptime += seconds; lock.unlock()
    }
    func set(date: Date, uptime: TimeInterval) {
        lock.lock(); storedDate = date; storedUptime = uptime; lock.unlock()
    }
}

private final class Fixture {
    let parentURL: URL
    let directoryURL: URL
    let startedAt = Date(timeIntervalSince1970: 1_800_000_000)
    private let sourceID = "trial-source"
    private let sessionID = "session-1"

    init() throws {
        parentURL = FileManager.default.temporaryDirectory.appendingPathComponent("continuous-reader-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: parentURL, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        directoryURL = parentURL.appendingPathComponent("session", isDirectory: true)
        try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
    }

    func publish(sample: [String: FieldFixture], publishedAt: Date, sourceID: String? = nil,
                 state: String = "active", reason: String? = nil, startedAt: Date? = nil,
                 sequence: Int = 1, slot: Int = 0, elapsedMS: Int = 0) throws {
        let sampleObject: [String: Any] = [
            "protocol": "ups-monitor.continuous.v1", "schema_version": 1, "type": "sample",
            "sequence": sequence, "slot": slot, "elapsed_ms": elapsedMS,
            "missed_slots": slot + 1 - sequence,
            "fields": Dictionary(uniqueKeysWithValues: sample.map { ($0.key, fieldObject($0.value)) }),
        ]
        var envelope: [String: Any] = [
            "schema_version": 1, "protocol": "ups-monitor.continuous.v1",
            "source_id": sourceID ?? self.sourceID, "session_id": sessionID,
            "state": state, "started_at_unix_ms": milliseconds(startedAt ?? self.startedAt),
            "published_at_unix_ms": milliseconds(publishedAt), "sample": sampleObject,
        ]
        envelope["terminal_reason"] = reason.map { $0 as Any } ?? NSNull()
        try writeRaw(JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys]))
    }

    func readBytes() throws -> Data { try Data(contentsOf: directoryURL.appendingPathComponent("sample.json")) }
    func writeRaw(_ data: Data) throws {
        let file = directoryURL.appendingPathComponent("sample.json")
        try data.write(to: file, options: .atomic)
        chmod(file.path, 0o600)
    }
    func remove() { try? FileManager.default.removeItem(at: parentURL) }

    private func fieldObject(_ field: FieldFixture) -> [String: Any] {
        ["value": field.value as Any? ?? NSNull(), "observed_ms": field.observedMS as Any? ?? NSNull(),
         "kind": field.kind, "state": field.state]
    }
    private func milliseconds(_ date: Date) -> Int64 { Int64((date.timeIntervalSince1970 * 1_000).rounded()) }
}
