import Foundation
import Testing
@testable import ApplePowerSource

private func description(_ id: Int32?, _ name: String?, type: String = "UPS", present: Bool = true) -> [String: Any] {
    var result: [String: Any] = ["Type": type, "Is Present": present]
    if let id { result["Power Source ID"] = NSNumber(value: id) }
    if let name { result["Name"] = name }
    return result
}

@Test func PresentationNameFollowsOpaqueTokensAcrossMultiSourceReordering() async throws {
    let reader = AppleSessionReader()
    let initial = await reader.sanitizedSnapshot([
        description(11, "  APC SMC1500I  "),
        description(99, "Internal", type: "InternalBattery"),
        description(22, "Backup UPS"),
        description(33, "Absent UPS", present: false),
    ], now: Date(timeIntervalSince1970: 10))
    let initialSources = initial.snapshot.sources
    #expect(initialSources.count == 2)
    #expect(initial.presentationNamesByOpaqueSourceID[initialSources[0].id] == "APC SMC1500I")
    #expect(initial.presentationNamesByOpaqueSourceID[initialSources[1].id] == "Backup UPS")

    let reordered = await reader.sanitizedSnapshot([
        description(22, "Backup UPS"),
        description(11, "APC SMC1500I"),
    ], now: Date(timeIntervalSince1970: 11))
    #expect(reordered.presentationNamesByOpaqueSourceID[reordered.snapshot.sources[0].id] == "Backup UPS")
    #expect(reordered.presentationNamesByOpaqueSourceID[reordered.snapshot.sources[1].id] == "APC SMC1500I")
    #expect(reordered.snapshot.sources.map(\.id) == [initialSources[1].id, initialSources[0].id])
}

@Test func PresentationNameOmitsInvalidNamesAndAmbiguousTokens() async throws {
    let reader = AppleSessionReader()
    let initial = await reader.sanitizedSnapshot([
        description(11, "\u{200B}"),
        description(22, "First"),
    ], now: Date(timeIntervalSince1970: 10))
    #expect(initial.presentationNamesByOpaqueSourceID.count == 1)

    let ambiguous = await reader.sanitizedSnapshot([
        description(7, "One"),
        description(7, "Two"),
    ], now: Date(timeIntervalSince1970: 11))
    #expect(ambiguous.snapshot.sources.isEmpty)
    #expect(ambiguous.unidentifiedPresentSourceCount == 2)
    #expect(ambiguous.presentationNamesByOpaqueSourceID.isEmpty)

    await reader.resetIdentity()
    let reset = await reader.sanitizedSnapshot([], now: Date(timeIntervalSince1970: 12))
    #expect(reset.presentationNamesByOpaqueSourceID.isEmpty)

    _ = await reader.sanitizedSnapshot([description(4, "Present")], now: Date(timeIntervalSince1970: 13))
    let unavailable = await reader.unavailableSnapshot(now: Date(timeIntervalSince1970: 14))
    #expect(unavailable.presentationNamesByOpaqueSourceID.isEmpty)
}

@Test func PresentationNameRemainsOutsideNormalizedPowerSourceSchema() async throws {
    let observation = await AppleSessionReader().sanitizedSnapshot([
        description(5, "Private model label"),
    ], now: Date(timeIntervalSince1970: 10))
    let source = try #require(observation.snapshot.sources.first)
    let data = try JSONEncoder().encode(source)
    let encoded = String(decoding: data, as: UTF8.self)
    #expect(encoded.contains("Private model label") == false)
    #expect(observation.presentationNamesByOpaqueSourceID[source.id] == "Private model label")
}
