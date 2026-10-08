import Foundation
import Testing
@testable import ApplePowerSource

@Test func nativeIdentityRejectsOverflowBooleanFloatAndTextWithoutAliasing() {
    var token = 0
    var mapper = AppleSessionIdentityMapper(makeToken: { token += 1; return "source-\(token)" })
    func description(_ value: Any, type: String = "UPS") -> [String: Any] {
        ["Type": type, "Is Present": true, "Power Source ID": value]
    }
    let invalid: [Any] = [NSNumber(value: UInt64.max), NSNumber(value: Int64(Int32.max) + 1),
                          NSNumber(value: Int64(Int32.min) - 1), NSNumber(value: true),
                          NSNumber(value: 1.5), "1"]
    for value in invalid {
        #expect(mapper.assignments(for: [description(value)]) == [nil])
        #expect(mapper.tokensByNativeID.isEmpty)
    }
    #expect(mapper.assignments(for: [description(NSNumber(value: Int32.min)),
                                    description(NSNumber(value: Int32.max))]) == ["source-1", "source-2"])
    #expect(mapper.assignments(for: [description(NSNumber(value: 4)),
                                    description(NSNumber(value: 4), type: "InternalBattery")]) == [nil])
}

@Test func sessionIdentityNeverReusesRetiredOpaqueToken() {
    var mapper = AppleSessionIdentityMapper(makeToken: { "same-token" })
    let description: [String: Any] = ["Type": "UPS", "Is Present": true, "Power Source ID": NSNumber(value: 1)]
    #expect(mapper.assignments(for: [description]) == ["same-token"])
    mapper.reset()
    #expect(mapper.assignments(for: [description]) == [nil])
}
