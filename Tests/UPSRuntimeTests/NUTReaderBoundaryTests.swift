import Foundation
import NUTClient
import XCTest
@testable import UPSRuntime

final class NUTReaderBoundaryTests: XCTestCase {
    func testOpaqueIdentityMayCoincidentallyContainShortUPSName() throws {
        let configuration = try UPSCClientConfiguration(
            executableURL: URL(fileURLWithPath: "/usr/bin/true"),
            executableQualification: .completionHardened,
            upsName: "u", sourceID: "nut-opaque-session")
        // Construction must not reject random token collisions; no file validation or execution here.
        XCTAssertNoThrow(try NUTSnapshotReader(configuration: configuration,
                                              expectedSHA256: String(repeating: "a", count: 64)))
    }
}
