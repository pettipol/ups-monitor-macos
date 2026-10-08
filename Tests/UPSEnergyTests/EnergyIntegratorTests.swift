import Foundation
import Testing
import UPSEnergy

private func sample(
    _ t: Double,
    watts: Double?,
    source: String = "ups-a",
    continuity: String = "session-1",
    wallOffset: Double? = nil,
    eligibility: WattsEligibility = .validatedActive
) -> EnergySample {
    let wallTime = wallOffset ?? t
    return EnergySample(
        sourceID: source,
        continuityToken: continuity,
        monotonicSeconds: t,
        capturedAt: Date(timeIntervalSince1970: wallTime),
        watts: watts,
        eligibility: eligibility
    )
}

@Test func integratesConstantLoad() {
    var integrator = EnergyIntegrator(maximumGapSeconds: 3_600)
    _ = integrator.add(sample(0, watts: 120))
    let result = integrator.add(sample(60, watts: 120))

    #expect(result.energyWh == 2)
    #expect(result.coveredDurationSeconds == 60)
    #expect(result.gapOrBreakCount == 0)
}

@Test func integratesRampWithTrapezoidalRule() {
    var integrator = EnergyIntegrator(maximumGapSeconds: 3_600)
    _ = integrator.add(sample(0, watts: 0))
    let result = integrator.add(sample(3_600, watts: 200))

    #expect(result.energyWh == 100)
    #expect(result.coveredDurationSeconds == 3_600)
}

@Test func missingOrUnvalidatedPowerBreaksContinuityWithoutBridging() {
    var integrator = EnergyIntegrator()
    _ = integrator.add(sample(0, watts: 100))
    let missing = integrator.add(sample(10, watts: nil))
    #expect(missing.energyWh == 0)
    #expect(missing.coveredDurationSeconds == 0)
    #expect(missing.gapOrBreakCount == 1)

    _ = integrator.add(sample(20, watts: 100))
    let unvalidated = integrator.add(sample(30, watts: 100, eligibility: .unvalidated))
    #expect(unvalidated.energyWh == 0)
    #expect(unvalidated.coveredDurationSeconds == 0)
    #expect(unvalidated.gapOrBreakCount == 2)
}

@Test func rejectsNonFiniteAndNegativeWatts() {
    for watts in [Double.nan, Double.infinity, -1] {
        var integrator = EnergyIntegrator()
        _ = integrator.add(sample(0, watts: 10))
        let result = integrator.add(sample(1, watts: watts))
        #expect(result.energyWh == 0)
        #expect(result.coveredDurationSeconds == 0)
        #expect(result.gapOrBreakCount == 1)
    }
}

@Test func sourceOrSessionChangesStartANewSegment() {
    var integrator = EnergyIntegrator()
    _ = integrator.add(sample(0, watts: 100))
    _ = integrator.add(sample(10, watts: 100))
    _ = integrator.add(sample(20, watts: 100, source: "ups-b"))
    _ = integrator.add(sample(30, watts: 100, continuity: "session-2"))
    let result = integrator.add(sample(40, watts: 100, continuity: "session-2"))

    #expect(result.energyWh == 200.0 / 360.0)
    #expect(result.coveredDurationSeconds == 20)
    #expect(result.gapOrBreakCount == 2)
    #expect(result.boundSourceID == "ups-a")
}

@Test func duplicateOrReplayedMonotonicSamplesCannotCountCoveredTimeTwice() {
    var integrator = EnergyIntegrator()
    _ = integrator.add(sample(0, watts: 3_600))
    _ = integrator.add(sample(10, watts: 3_600))
    let duplicate = integrator.add(sample(10, watts: 3_600))
    #expect(duplicate.energyWh == 10)
    #expect(duplicate.coveredDurationSeconds == 10)
    #expect(duplicate.gapOrBreakCount == 1)

    _ = integrator.add(sample(11, watts: 3_600))
    let recovered = integrator.add(sample(12, watts: 3_600))
    #expect(recovered.energyWh == 11)
    #expect(recovered.coveredDurationSeconds == 11)
}

@Test func invalidPointKeepsWatermarkSoOldSamplesCannotReprime() {
    var integrator = EnergyIntegrator()
    _ = integrator.add(sample(0, watts: 3_600))
    _ = integrator.add(sample(10, watts: 3_600))
    _ = integrator.add(sample(11, watts: nil))
    _ = integrator.add(sample(9, watts: 3_600))
    _ = integrator.add(sample(10, watts: 3_600))
    _ = integrator.add(sample(12, watts: 3_600))
    let recovered = integrator.add(sample(13, watts: 3_600))

    #expect(recovered.energyWh == 11)
    #expect(recovered.coveredDurationSeconds == 11)
    #expect(recovered.boundSourceID == "ups-a")
}

@Test func otherSourceAdvancesSameSessionWatermarkButAddsNoEnergy() {
    var integrator = EnergyIntegrator()
    _ = integrator.add(sample(0, watts: 3_600))
    _ = integrator.add(sample(10, watts: 3_600))
    _ = integrator.add(sample(12, watts: 3_600, source: "ups-b"))
    _ = integrator.add(sample(11, watts: 3_600))
    _ = integrator.add(sample(13, watts: 3_600))
    let result = integrator.add(sample(14, watts: 3_600))

    #expect(result.energyWh == 11)
    #expect(result.coveredDurationSeconds == 11)
    #expect(result.boundSourceID == "ups-a")
}

@Test func retiredContinuityTokenCannotBeReplayed() {
    var integrator = EnergyIntegrator()
    _ = integrator.add(sample(0, watts: 3_600, continuity: "session-a"))
    _ = integrator.add(sample(10, watts: 3_600, continuity: "session-a"))
    _ = integrator.add(sample(5, watts: 3_600, continuity: "session-b"))
    _ = integrator.add(sample(6, watts: 3_600, continuity: "session-b"))
    _ = integrator.add(sample(7, watts: 3_600, continuity: "session-a"))
    _ = integrator.add(sample(8, watts: 3_600, continuity: "session-b"))
    let result = integrator.add(sample(9, watts: 3_600, continuity: "session-b"))

    #expect(result.energyWh == 12)
    #expect(result.coveredDurationSeconds == 12)
    #expect(result.boundSourceID == "ups-a")
}

@Test func rejectsBackwardMonotonicTimeAndWallClockDisagreement() {
    var backward = EnergyIntegrator()
    _ = backward.add(sample(10, watts: 100))
    let regressed = backward.add(sample(9, watts: 100))
    #expect(regressed.energyWh == 0)
    #expect(regressed.coveredDurationSeconds == 0)
    #expect(regressed.gapOrBreakCount == 1)

    var disagreement = EnergyIntegrator(clockDisagreementToleranceSeconds: 1)
    _ = disagreement.add(sample(0, watts: 100))
    let jumped = disagreement.add(sample(10, watts: 100, wallOffset: 30))
    #expect(jumped.energyWh == 0)
    #expect(jumped.coveredDurationSeconds == 0)
    #expect(jumped.gapOrBreakCount == 1)
}

@Test func maximumGapIsInclusiveAndLongGapsDoNotBridge() {
    var boundary = EnergyIntegrator(maximumGapSeconds: 10)
    _ = boundary.add(sample(0, watts: 100))
    let atBoundary = boundary.add(sample(10, watts: 100))
    #expect(atBoundary.energyWh == 100.0 / 360.0)
    #expect(atBoundary.coveredDurationSeconds == 10)

    var longGap = EnergyIntegrator(maximumGapSeconds: 10)
    _ = longGap.add(sample(0, watts: 100))
    let afterGap = longGap.add(sample(11, watts: 100))
    #expect(afterGap.energyWh == 0)
    #expect(afterGap.coveredDurationSeconds == 0)
    #expect(afterGap.gapOrBreakCount == 1)
}

@Test func resetClearsTotalsContinuityAndBreakCount() {
    var integrator = EnergyIntegrator(maximumGapSeconds: 3_600)
    _ = integrator.add(sample(0, watts: 100))
    _ = integrator.add(sample(10, watts: 100))
    _ = integrator.add(sample(20, watts: nil))
    integrator.reset()

    #expect(integrator.result.energyWh == 0)
    #expect(integrator.result.coveredDurationSeconds == 0)
    #expect(integrator.result.gapOrBreakCount == 0)
    #expect(integrator.result.boundSourceID == nil)
    _ = integrator.add(sample(0, watts: 50))
    let afterReset = integrator.add(sample(3_600, watts: 50))
    #expect(afterReset.energyWh == 50)
    #expect(afterReset.coveredDurationSeconds == 3_600)
}

@Test func invalidTimesAndArithmeticOverflowBreakWithoutNonFiniteResults() {
    for time in [Double.nan, Double.infinity, -1] {
        var integrator = EnergyIntegrator()
        let result = integrator.add(sample(time, watts: 100))
        #expect(result.energyWh == 0)
        #expect(result.coveredDurationSeconds == 0)
        #expect(result.gapOrBreakCount == 1)
    }

    var overflow = EnergyIntegrator(maximumGapSeconds: 7_200)
    _ = overflow.add(sample(0, watts: Double.greatestFiniteMagnitude))
    let result = overflow.add(sample(7_200, watts: Double.greatestFiniteMagnitude))
    #expect(result.energyWh.isFinite)
    #expect(result.coveredDurationSeconds == 0)
    #expect(result.gapOrBreakCount == 1)
}
