import Foundation

public enum WattsEligibility: Sendable {
    /// The caller has validated this as active load power for this source.
    case validatedActive
    case unvalidated
}

public struct EnergySample: Sendable {
    public let sourceID: String
    public let continuityToken: String
    public let monotonicSeconds: Double
    public let capturedAt: Date
    public let watts: Double?
    public let eligibility: WattsEligibility

    public init(
        sourceID: String,
        continuityToken: String,
        monotonicSeconds: Double,
        capturedAt: Date,
        watts: Double?,
        eligibility: WattsEligibility
    ) {
        self.sourceID = sourceID
        self.continuityToken = continuityToken
        self.monotonicSeconds = monotonicSeconds
        self.capturedAt = capturedAt
        self.watts = watts
        self.eligibility = eligibility
    }
}

public struct EnergyIntegrationResult: Equatable, Sendable {
    public let boundSourceID: String?
    public let energyWh: Double
    public let coveredDurationSeconds: Double
    /// Number of rejected boundaries or samples; excluded time is never counted as zero-load coverage.
    public let gapOrBreakCount: Int
}

/// Integrates validated active watts using trapezoids within a single source continuity.
/// This does not establish that a watt reading is available or valid for any UPS.
public struct EnergyIntegrator: Sendable {
    public let maximumGapSeconds: Double
    public let clockDisagreementToleranceSeconds: Double

    private var previous: EnergySample?
    private var boundSourceID: String?
    private var activeContinuityToken: String?
    private var seenContinuityTokens = Set<String>()
    private var monotonicHighWatermark: Double?
    private var accumulatedWh = 0.0
    private var coveredSeconds = 0.0
    private var gapOrBreakCount = 0

    /// Defaults cap a bridged interval at two minutes and tolerate up to five seconds of wall-clock drift.
    public init(maximumGapSeconds: Double = 120, clockDisagreementToleranceSeconds: Double = 5) {
        precondition(maximumGapSeconds.isFinite && maximumGapSeconds > 0)
        precondition(clockDisagreementToleranceSeconds.isFinite && clockDisagreementToleranceSeconds >= 0)
        self.maximumGapSeconds = maximumGapSeconds
        self.clockDisagreementToleranceSeconds = clockDisagreementToleranceSeconds
    }

    @discardableResult
    public mutating func add(_ sample: EnergySample) -> EnergyIntegrationResult {
        guard hasValidIdentityAndClock(sample) else {
            breakContinuity()
            return result
        }

        guard let boundSourceID else {
            guard hasValidatedWatts(sample) else {
                breakContinuity()
                return result
            }
            self.boundSourceID = sample.sourceID
            activeContinuityToken = sample.continuityToken
            seenContinuityTokens.insert(sample.continuityToken)
            monotonicHighWatermark = sample.monotonicSeconds
            self.previous = sample
            return result
        }

        guard sample.sourceID == boundSourceID else {
            if let activeContinuityToken,
               sample.continuityToken == activeContinuityToken,
               sample.monotonicSeconds > (monotonicHighWatermark ?? -1) {
                monotonicHighWatermark = sample.monotonicSeconds
            }
            breakContinuity()
            return result
        }

        guard let activeContinuityToken else {
            breakContinuity()
            return result
        }

        if sample.continuityToken != activeContinuityToken {
            guard !seenContinuityTokens.contains(sample.continuityToken), hasValidatedWatts(sample) else {
                breakContinuity()
                return result
            }
            seenContinuityTokens.insert(sample.continuityToken)
            self.activeContinuityToken = sample.continuityToken
            monotonicHighWatermark = sample.monotonicSeconds
            previous = sample
            gapOrBreakCount += 1
            return result
        }

        guard let highWatermark = monotonicHighWatermark,
              sample.monotonicSeconds > highWatermark else {
            breakContinuity()
            return result
        }
        monotonicHighWatermark = sample.monotonicSeconds

        guard hasValidatedWatts(sample) else {
            breakContinuity()
            return result
        }

        guard let previous else {
            self.previous = sample
            return result
        }

        let monotonicDelta = sample.monotonicSeconds - previous.monotonicSeconds
        let wallDelta = sample.capturedAt.timeIntervalSince(previous.capturedAt)
        guard monotonicDelta.isFinite,
              monotonicDelta > 0,
              monotonicDelta <= maximumGapSeconds,
              wallDelta.isFinite,
              wallDelta > 0,
              abs(wallDelta - monotonicDelta) <= clockDisagreementToleranceSeconds else {
            breakContinuity(reprimeWith: monotonicDelta > maximumGapSeconds ? sample : nil)
            return result
        }

        guard let previousWatts = previous.watts,
              let currentWatts = sample.watts else {
            breakContinuity()
            return result
        }

        let meanWatts = previousWatts / 2 + currentWatts / 2
        let segmentWh = meanWatts * (monotonicDelta / 3_600)
        let newEnergyWh = accumulatedWh + segmentWh
        let newCoveredSeconds = coveredSeconds + monotonicDelta
        guard meanWatts.isFinite,
              segmentWh.isFinite,
              newEnergyWh.isFinite,
              newCoveredSeconds.isFinite else {
            breakContinuity(reprimeWith: sample)
            return result
        }

        accumulatedWh = newEnergyWh
        coveredSeconds = newCoveredSeconds
        self.previous = sample
        return result
    }

    /// Clears the integration window, prior sample, coverage and break count.
    public mutating func reset() {
        previous = nil
        boundSourceID = nil
        activeContinuityToken = nil
        seenContinuityTokens.removeAll()
        monotonicHighWatermark = nil
        accumulatedWh = 0
        coveredSeconds = 0
        gapOrBreakCount = 0
    }

    /// Breaks the current interval without adding a sample; callers should coalesce interruptions per outage.
    public mutating func interrupt() {
        breakContinuity()
    }

    public var result: EnergyIntegrationResult {
        EnergyIntegrationResult(
            boundSourceID: boundSourceID,
            energyWh: accumulatedWh,
            coveredDurationSeconds: coveredSeconds,
            gapOrBreakCount: gapOrBreakCount
        )
    }

    private func hasValidIdentityAndClock(_ sample: EnergySample) -> Bool {
        guard !sample.sourceID.isEmpty,
              !sample.continuityToken.isEmpty,
              sample.monotonicSeconds.isFinite,
              sample.monotonicSeconds >= 0,
              sample.capturedAt.timeIntervalSince1970.isFinite else { return false }
        return true
    }

    private func hasValidatedWatts(_ sample: EnergySample) -> Bool {
        guard case .validatedActive = sample.eligibility,
              let watts = sample.watts,
              watts.isFinite,
              watts >= 0 else { return false }
        return true
    }

    private mutating func breakContinuity(reprimeWith sample: EnergySample? = nil) {
        gapOrBreakCount += 1
        previous = sample
    }
}
