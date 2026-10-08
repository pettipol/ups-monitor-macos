import Foundation
import Testing
import UPSModel
import UPSEnergy
@testable import UPSMonitorUI

private func energyEstimate(
    channel: MonitorEnergyChannel,
    state: MonitorEnergyState = .estimated,
    energyWh: Double? = 12.5,
    coverage: Double = 3_600,
    breaks: Int = 1,
    first: Date? = Date(timeIntervalSince1970: 1),
    last: Date? = Date(timeIntervalSince1970: 3_601),
    provenances: [MonitorMetricProvenance] = [.reported]
) -> MonitorEnergyEstimate {
    MonitorEnergyEstimate(
        channel: channel,
        source: nil,
        state: state,
        energyWh: energyWh,
        coveredDurationSeconds: coverage,
        gapOrBreakCount: breaks,
        firstCapturedAt: first,
        lastCapturedAt: last,
        powerProvenances: provenances
    )
}

@Suite struct UPSEnergySummaryViewTests {
    @Test func zeroEnergyIsDistinctFromMissingEnergy() {
        let zero = energyEstimate(channel: .input, energyWh: 0, coverage: 30)
        let missing = energyEstimate(channel: .ups, state: .collecting, energyWh: nil, coverage: 0)

        #expect(UPSEnergySummaryFormatters.energyLabel(zero) == "0 Wh estimated")
        #expect(UPSEnergySummaryFormatters.energyLabel(missing) == "Energy not available")
        #expect(UPSEnergySummaryFormatters.coverageLabel(zero).contains("30 s covered"))
    }

    @Test func nonfiniteAndNegativeEnergyAreDefensivelyUnavailable() {
        for value in [Double.nan, .infinity, -.infinity, -0.1] {
            let estimate = energyEstimate(channel: .ups, energyWh: value)
            #expect(UPSEnergySummaryFormatters.energyLabel(estimate) == "Energy not available")
        }

        let invalidCoverage = energyEstimate(channel: .input, coverage: .nan, breaks: -1)
        #expect(UPSEnergySummaryFormatters.coverageLabel(invalidCoverage) == "Coverage unavailable")

        let noCoveredInterval = energyEstimate(channel: .input, energyWh: 0, coverage: 0)
        let invalidCoverageWithEnergy = energyEstimate(channel: .input, energyWh: 1, coverage: .infinity)
        #expect(UPSEnergySummaryFormatters.energyLabel(noCoveredInterval) == "Energy not available")
        #expect(UPSEnergySummaryFormatters.energyLabel(invalidCoverageWithEnergy) == "Energy not available")
    }

    @Test func extremeFiniteValuesUseCompactScientificNotation() {
        let hugeEnergy = energyEstimate(channel: .ups, energyWh: .greatestFiniteMagnitude)
        let tinyEnergy = energyEstimate(channel: .input, energyWh: .leastNonzeroMagnitude)
        let hugeCoverage = energyEstimate(channel: .ups, coverage: .greatestFiniteMagnitude)
        let labels = [
            UPSEnergySummaryFormatters.energyLabel(hugeEnergy),
            UPSEnergySummaryFormatters.energyLabel(tinyEnergy),
            UPSEnergySummaryFormatters.coverageLabel(hugeCoverage),
        ]

        #expect(labels.allSatisfy { $0.count < 80 })
        #expect(labels.allSatisfy { !$0.localizedCaseInsensitiveContains("inf") })
    }

    @Test func labelsKeepChannelsUnitsStateAndProvenanceExplicit() {
        let input = energyEstimate(channel: .input, provenances: [.reported, .derived])
        let ups = energyEstimate(channel: .ups, state: .paused, provenances: [.estimated])

        #expect(UPSEnergySummaryFormatters.channelLabel(input.channel) == "Input")
        #expect(UPSEnergySummaryFormatters.channelLabel(ups.channel) == "UPS")
        #expect(UPSEnergySummaryFormatters.stateLabel(ups.state) == "Paused")
        #expect(UPSEnergySummaryFormatters.energyLabel(input).contains("Wh estimated"))
        #expect(UPSEnergySummaryFormatters.provenanceLabel(input) == "Watt data: Reported, Derived")
        #expect(UPSEnergySummaryFormatters.provenanceLabel(ups) == "Watt data: Estimated")
    }

    @Test func sampleDatesAndAccessibilityLabelRetainQualityContext() {
        let estimate = energyEstimate(
            channel: .ups,
            state: .collecting,
            energyWh: nil,
            provenances: [.driverDerived]
        )
        let dates = UPSEnergySummaryFormatters.sampleDatesLabel(estimate)
        let label = UPSEnergySummaryFormatters.accessibilityLabel(estimate)

        #expect(dates.hasPrefix("Samples:"))
        #expect(label.contains("UPS"))
        #expect(label.contains("Collecting"))
        #expect(label.contains("Energy not available"))
        #expect(label.contains("Watt data: Driver-derived"))

        let invalidDates = energyEstimate(
            channel: .input,
            first: Date(timeIntervalSince1970: .infinity),
            last: Date(timeIntervalSince1970: 2)
        )
        #expect(UPSEnergySummaryFormatters.sampleDatesLabel(invalidDates) == "Sample dates unavailable")

        let reversedDates = energyEstimate(
            channel: .input,
            first: Date(timeIntervalSince1970: 3),
            last: Date(timeIntervalSince1970: 2)
        )
        #expect(UPSEnergySummaryFormatters.sampleDatesLabel(reversedDates) == "Sample dates unavailable")
    }

    @MainActor @Test func viewRetainsEstimatesAndOptionalActionsWithoutVisualClaim() {
        let estimates = [
            energyEstimate(channel: .input, state: .unavailable, energyWh: nil),
            energyEstimate(channel: .ups, energyWh: 0, coverage: 15),
        ]
        let view = UPSEnergySummaryView(estimates: estimates, onReset: {}, onExport: {})
        let noActionsView = UPSEnergySummaryView(estimates: estimates)

        #expect(view.estimates.count == 2)
        #expect(view.estimates.map(\.channel) == [.input, .ups])
        #expect(view.onReset.map { _ in true } == true)
        #expect(view.onExport.map { _ in true } == true)
        #expect(noActionsView.onReset.map { _ in true } == nil)
        #expect(noActionsView.onExport.map { _ in true } == nil)
    }
}
