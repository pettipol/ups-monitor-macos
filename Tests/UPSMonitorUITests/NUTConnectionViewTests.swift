import SwiftUI
import XCTest
@testable import UPSMonitorUI

final class NUTConnectionViewTests: XCTestCase {
    func testDraftDefaultsAndValidConfiguration() {
        XCTAssertEqual(NUTConnectionDraft(), NUTConnectionDraft(executablePath: "", expectedSHA256: "",
                                                                 upsName: "", port: "3493",
                                                                 completionQualified: false))
        XCTAssertFalse(NUTConnectionDraft().canConnect)
        XCTAssertTrue(validDraft().canConnect)
    }

    func testPathDigestAndQualificationAreRequired() {
        XCTAssertFalse(validDraft(executablePath: "usr/local/bin/upsc").canConnect)
        XCTAssertFalse(validDraft(executablePath: "/").canConnect)
        XCTAssertFalse(validDraft(executablePath: "/synthetic/\0upsc").canConnect)
        XCTAssertFalse(validDraft(executablePath: "   ").canConnect)
        XCTAssertFalse(validDraft(expectedSHA256: String(repeating: "a", count: 63)).canConnect)
        XCTAssertFalse(validDraft(expectedSHA256: String(repeating: "g", count: 64)).canConnect)
        XCTAssertFalse(validDraft(completionQualified: false).canConnect)
        XCTAssertTrue(validDraft(expectedSHA256: String(repeating: "A1", count: 32)).canConnect)
    }

    func testUPSNameUsesUPSCASCIINameRules() {
        for name in ["A", "ups-1", "UPS.name_2"] {
            XCTAssertTrue(validDraft(upsName: name).canConnect, "Expected \(name) to be valid")
        }
        for name in ["", "_ups", "-ups", ".ups", "ups name", "ups/1", "ups@host", "éclair", String(repeating: "a", count: 65)] {
            XCTAssertFalse(validDraft(upsName: name).canConnect, "Expected \(name) to be invalid")
        }
    }

    func testPortAcceptsOnlyDecimalIntegersInRange() {
        for port in ["1", "3493", "65535", "03493"] {
            XCTAssertTrue(validDraft(port: port).canConnect, "Expected \(port) to be valid")
        }
        for port in ["", "0", "65536", "3493x", "+3493", "-1", "3.4", "000001", "999999999999999999999999"] {
            XCTAssertFalse(validDraft(port: port).canConnect, "Expected \(port) to be invalid")
        }
    }

    @MainActor
    func testViewInitializesFromBindingWithoutExternalEffects() {
        _ = NUTConnectionView(
            draft: .constant(NUTConnectionDraft()),
            isConnecting: false,
            errorMessage: nil,
            onChooseExecutable: {},
            onConnect: {},
            onCancel: {}
        )
        _ = NUTConnectionView(
            draft: .constant(validDraft()),
            isConnecting: true,
            errorMessage: nil,
            onChooseExecutable: {},
            onConnect: {},
            onCancel: {}
        )
    }

    private func validDraft(
        executablePath: String = "/synthetic/bin/upsc",
        expectedSHA256: String = String(repeating: "a", count: 64),
        upsName: String = "ups-name",
        port: String = "3493",
        completionQualified: Bool = true
    ) -> NUTConnectionDraft {
        NUTConnectionDraft(executablePath: executablePath, expectedSHA256: expectedSHA256,
                           upsName: upsName, port: port, completionQualified: completionQualified)
    }
}
