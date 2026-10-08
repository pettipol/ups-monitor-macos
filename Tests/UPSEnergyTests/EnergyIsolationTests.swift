import Foundation
import Testing
import UPSEnergy

private func validated(_ t: Double, source: String = "ups-a") -> EnergySample {
    EnergySample(sourceID: source, continuityToken: "one-session", monotonicSeconds: t,
                 capturedAt: Date(timeIntervalSince1970: t), watts: 3_600,
                 eligibility: .validatedActive)
}

@Test func differentUPSCannotContributeToAnExistingEnergyTotal() {
    var integrator = EnergyIntegrator()
    integrator.add(validated(0))
    integrator.add(validated(1))
    integrator.add(validated(2, source: "ups-b"))
    let result = integrator.add(validated(3, source: "ups-b"))
    #expect(result.energyWh == 1, "The total belongs to UPS A, not A plus B")
    #expect(result.coveredDurationSeconds == 1)
}

@Test func reorderedSamplesCannotCountTheSameElapsedTimeTwice() {
    var integrator = EnergyIntegrator()
    integrator.add(validated(0))
    integrator.add(validated(10))
    integrator.add(validated(5))
    integrator.add(validated(6))
    let late = integrator.add(validated(7))
    #expect(late.energyWh == 10, "Old samples must not add already-covered time")
    #expect(late.coveredDurationSeconds == 10)
    integrator.add(validated(11))
    let resumed = integrator.add(validated(12))
    #expect(resumed.energyWh == 11, "Recovery starts a fresh segment beyond the watermark")
    #expect(resumed.coveredDurationSeconds == 11)
}

@Test func irregularSamplingMatchesTheAnalyticIntegralOfALinearLoad() {
    var integrator = EnergyIntegrator()
    let times = Array(stride(from: 0.0, through: 3_589.0, by: 37.0)) + [3_600.0]
    for t in times {
        integrator.add(EnergySample(
            sourceID: "synthetic-load", continuityToken: "one-session", monotonicSeconds: t,
            capturedAt: Date(timeIntervalSince1970: t), watts: 25 + 0.5 * t,
            eligibility: .validatedActive
        ))
    }
    let analyticWh = (25.0 * 3_600 + 0.25 * 3_600 * 3_600) / 3_600
    #expect(abs(integrator.result.energyWh - analyticWh) < 1e-9)
    #expect(integrator.result.coveredDurationSeconds == 3_600)
    #expect(integrator.result.gapOrBreakCount == 0)
}

@Test func measuredZeroAndUnknownEnergyHaveDifferentCoverage() {
    var measured = EnergyIntegrator()
    var missing = EnergyIntegrator()
    for t in [0.0, 60.0] {
        measured.add(EnergySample(sourceID: "ups-a", continuityToken: "one-session",
                                 monotonicSeconds: t, capturedAt: Date(timeIntervalSince1970: t),
                                 watts: 0, eligibility: .validatedActive))
        missing.add(EnergySample(sourceID: "ups-a", continuityToken: "one-session",
                                monotonicSeconds: t, capturedAt: Date(timeIntervalSince1970: t),
                                watts: nil, eligibility: .unvalidated))
    }
    #expect(measured.result.energyWh == 0)
    #expect(missing.result.energyWh == 0)
    #expect(measured.result.coveredDurationSeconds == 60)
    #expect(missing.result.coveredDurationSeconds == 0)
    #expect(missing.result.boundSourceID == nil)
}
