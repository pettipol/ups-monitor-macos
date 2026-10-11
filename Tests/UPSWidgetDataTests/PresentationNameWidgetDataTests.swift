import Foundation
import Testing
import UPSModel
@testable import UPSWidgetData

@Suite struct PresentationNameWidgetDataTests {
    private let date = Date(timeIntervalSince1970: 1_000)

    private func snapshot() -> MonitorSnapshot {
        MonitorSnapshot(
            source: MonitorSource(provider: .nut, id: "fixture-id", sessionID: "fixture-session",
                                  identityStability: .configured),
            capturedAt: date,
            status: MonitorStatus(quality: .unavailable),
            metrics: []
        )
    }

    private func encodedObject(name: String? = nil, includeName: Bool = true,
                               includeSnapshot: Bool = true) throws -> [String: Any] {
        let payload = WidgetSnapshot(publishedAt: date, acquisition: .active,
                                     maximumAge: 30, snapshot: includeSnapshot ? snapshot() : nil,
                                     presentationName: name)
        let data = try JSONEncoder().encode(payload)
        var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        if !includeName { object.removeValue(forKey: "presentationName") }
        if !includeSnapshot { object["acquisition"] = WidgetAcquisition.noSources.rawValue }
        return object
    }

    @Test func legacyPayloadWithoutPresentationNameDecodes() throws {
        let object = try encodedObject(includeName: false)
        let data = try JSONSerialization.data(withJSONObject: object)
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        #expect(decoded.presentationName == nil)
        try decoded.validate()
    }

    @Test func validPresentationNameRoundTrips() throws {
        let payload = WidgetSnapshot(publishedAt: date, acquisition: .active, maximumAge: 30,
                                    snapshot: snapshot(), presentationName: "Hall UPS")
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: JSONEncoder().encode(payload))
        #expect(decoded == payload)
        #expect(decoded.presentationName == "Hall UPS")
    }

    @Test(arguments: [" bad\u{0007}name ", "\u{202E}UPS", String(repeating: "x", count: 65),
                      String(repeating: "é", count: 81)])
    func malformedNamesAreRejected(_ name: String) throws {
        let object = try encodedObject(name: name)
        let data = try JSONSerialization.data(withJSONObject: object)
        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        }
    }

    @Test func presentationNameWithoutSnapshotIsRejected() throws {
        let object = try encodedObject(name: "Hall UPS", includeSnapshot: false)
        var changed = object
        changed["presentationName"] = "Hall UPS"
        let data = try JSONSerialization.data(withJSONObject: changed)
        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        }
    }
}
