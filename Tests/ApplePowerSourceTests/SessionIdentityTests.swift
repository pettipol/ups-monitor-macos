import Foundation
import Testing
@testable import ApplePowerSource

private let powerSourceIDKey = "Power Source ID"

private func ups(_ id: Int32?, present: Bool = true) -> [String: Any] {
    var value: [String: Any] = ["Type": "UPS", "Is Present": present]
    if let id { value[powerSourceIDKey] = NSNumber(value: id) }
    return value
}

@Test func reorderingPreservesOpaqueSessionTokens() {
    var sequence = 0
    var mapper = AppleSessionIdentityMapper(makeToken: {
        sequence += 1
        return "opaque-\(sequence)"
    })
    let initial = mapper.assignments(for: [ups(11), ups(22)])
    let reordered = mapper.assignments(for: [ups(22), ups(11)])

    #expect(initial == ["opaque-1", "opaque-2"])
    #expect(reordered == ["opaque-2", "opaque-1"])
    #expect(!initial.contains("11"))
    #expect(!initial.contains("22"))
}

@Test func missingAbsentAndAmbiguousIdentitiesAreNotAssignedAndRetireTokens() {
    var sequence = 0
    var mapper = AppleSessionIdentityMapper(makeToken: {
        sequence += 1
        return "opaque-\(sequence)"
    })
    let initial = mapper.assignments(for: [ups(7)])
    #expect(initial == ["opaque-1"])

    let ambiguous = mapper.assignments(for: [ups(7), ups(7)])
    #expect(ambiguous == [nil, nil])

    let missing = mapper.assignments(for: [ups(nil)])
    #expect(missing == [nil])
    #expect(mapper.tokensByNativeID.isEmpty)
    #expect(mapper.assignments(for: [ups(7)]) == ["opaque-2"])

    let absent = mapper.assignments(for: [ups(7, present: false)])
    #expect(absent.isEmpty)
    #expect(mapper.tokensByNativeID.isEmpty)
}

@Test func aReappearingSourceReceivesANewTokenAfterAbsenceOrDiscoveryError() {
    var sequence = 0
    var mapper = AppleSessionIdentityMapper(makeToken: {
        sequence += 1
        return "opaque-\(sequence)"
    })
    let first = mapper.assignments(for: [ups(31)])[0]
    #expect(mapper.assignments(for: []).isEmpty)
    let second = mapper.assignments(for: [ups(31)])[0]
    #expect(first == "opaque-1")
    #expect(second == "opaque-2")

    mapper.reset()
    #expect(mapper.tokensByNativeID.isEmpty)
    #expect(mapper.assignments(for: [ups(31)])[0] == "opaque-3")
}

@Test func nonIntegerNativeIDsFailClosed() {
    var mapper = AppleSessionIdentityMapper(makeToken: { "opaque" })
    #expect(mapper.assignments(for: [["Type": "UPS", "Is Present": true, powerSourceIDKey: NSNumber(value: 4.5)]]) == [nil])
    #expect(mapper.assignments(for: [["Type": "UPS", "Is Present": true, powerSourceIDKey: NSNumber(value: true)]]) == [nil])
}

@Test func oversizedUnsignedNativeIDCannotWrapIntoValidInt32() {
    var mapper = AppleSessionIdentityMapper(makeToken: { "opaque" })
    let description: [String: Any] = [
        "Type": "UPS",
        "Is Present": true,
        powerSourceIDKey: NSNumber(value: UInt64.max),
    ]
    #expect(mapper.assignments(for: [description]) == [nil])
    #expect(mapper.tokensByNativeID.isEmpty)
}
