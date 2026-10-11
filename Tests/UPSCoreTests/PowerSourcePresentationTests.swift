import Testing
@testable import UPSCore

@Test func PresentationNameTrimsAndRejectsEmptyValues() {
    #expect(PowerSourcePresentation.name("  SMC1500I\n") == "SMC1500I")
    #expect(PowerSourcePresentation.name(" \t\n ") == nil)
    #expect(PowerSourcePresentation.name(nil) == nil)
}

@Test func PresentationNameEnforcesCharacterAndUTF8Limits() {
    #expect(PowerSourcePresentation.name(String(repeating: "x", count: 64)) != nil)
    #expect(PowerSourcePresentation.name(String(repeating: "x", count: 65)) == nil)
    #expect(PowerSourcePresentation.name(String(repeating: "😀", count: 40)) != nil)
    #expect(PowerSourcePresentation.name(String(repeating: "😀", count: 41)) == nil)
}

@Test func PresentationNameRejectsControlFormatAndSeparators() {
    #expect(PowerSourcePresentation.name("UPS\u{0007}name") == nil)
    #expect(PowerSourcePresentation.name("UPS\u{200B}name") == nil)
    #expect(PowerSourcePresentation.name("UPS\u{2028}name") == nil)
    #expect(PowerSourcePresentation.name("UPS\u{2029}name") == nil)
}
