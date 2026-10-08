import Foundation
import UPSModel

public enum MonitorEnergyChannel: String, CaseIterable, Encodable, Sendable {
    case input
    case ups

    fileprivate var metricID: MonitorMetricID {
        switch self {
        case .input: .inputRealPower
        case .ups: .upsRealPower
        }
    }
}

public enum MonitorEnergyState: String, Encodable, Sendable {
    case unavailable
    case collecting
    case estimated
    case paused
}

public struct MonitorEnergyEstimate: Equatable, Encodable, Sendable {
    public let channel: MonitorEnergyChannel
    public let source: MonitorSource?
    public let state: MonitorEnergyState
    public let energyWh: Double?
    public let coveredDurationSeconds: Double
    public let gapOrBreakCount: Int
    public let firstCapturedAt: Date?
    public let lastCapturedAt: Date?
    public let powerProvenances: [MonitorMetricProvenance]

    public init(channel: MonitorEnergyChannel, source: MonitorSource?, state: MonitorEnergyState,
                energyWh: Double?, coveredDurationSeconds: Double, gapOrBreakCount: Int,
                firstCapturedAt: Date?, lastCapturedAt: Date?,
                powerProvenances: [MonitorMetricProvenance]) {
        self.channel = channel
        self.source = source
        self.state = state
        self.energyWh = energyWh
        self.coveredDurationSeconds = coveredDurationSeconds
        self.gapOrBreakCount = gapOrBreakCount
        self.firstCapturedAt = firstCapturedAt
        self.lastCapturedAt = lastCapturedAt
        self.powerProvenances = powerProvenances
    }
}

public struct MonitorEnergyTracker: Sendable {
    private static let maximumAgeSeconds = 10.0
    private static let maximumGapSeconds = 10.0
    private static let clockToleranceSeconds = 1.0

    private struct ChannelAccumulator: Sendable {
        var integrator = EnergyIntegrator(maximumGapSeconds: 10, clockDisagreementToleranceSeconds: 1)
        var hasObservedEligiblePower = false
        var continuityBroken = false
        var lastSampleCapture: Date?
        var lastSampleUptime: TimeInterval?
        var lastProvenance: MonitorMetricProvenance?
        var firstCapture: Date?
        var lastCapture: Date?
        var provenances = Set<MonitorMetricProvenance>()

        mutating func interrupt() {
            guard hasObservedEligiblePower, !continuityBroken else { return }
            integrator.interrupt()
            continuityBroken = true
            lastSampleCapture = nil
            lastSampleUptime = nil
        }

        mutating func reset() {
            self = ChannelAccumulator()
        }

        var state: MonitorEnergyState {
            guard hasObservedEligiblePower else { return .unavailable }
            if continuityBroken { return .paused }
            return integrator.result.coveredDurationSeconds > 0 ? .estimated : .collecting
        }

        var estimateEnergy: Double? {
            let result = integrator.result
            return result.coveredDurationSeconds > 0 ? result.energyWh : nil
        }
    }

    private var source: MonitorSource?
    private var captureHighWatermark: Date?
    private var lastSnapshot: MonitorSnapshot?
    private var monotonicHighWatermark: TimeInterval?
    private var input = ChannelAccumulator()
    private var ups = ChannelAccumulator()

    public init() {}

    public var summaries: [MonitorEnergyEstimate] {
        [summary(.input, input), summary(.ups, ups)]
    }

    public mutating func reset() {
        source = nil
        captureHighWatermark = nil
        lastSnapshot = nil
        monotonicHighWatermark = nil
        input.reset()
        ups.reset()
    }

    public mutating func pause() {
        input.interrupt()
        ups.interrupt()
    }

    public mutating func observe(snapshot: MonitorSnapshot?, acquisitionSucceeded: Bool,
                                 now: Date, monotonicSeconds: TimeInterval) {
        let snapshotIsValid = snapshot.map { (try? $0.validate()) != nil } ?? false
        let snapshotSourceIsValid = snapshot.map { (try? $0.source.validate()) != nil } ?? false

        guard now.timeIntervalSince1970.isFinite,
              monotonicSeconds.isFinite, monotonicSeconds >= 0 else {
            pause()
            return
        }

        if let lastMonotonic = monotonicHighWatermark, monotonicSeconds < lastMonotonic {
            pause()
            return
        }

        let isHarmlessCachedSnapshot: Bool
        if let snapshot, snapshot.capturedAt == captureHighWatermark, snapshot == lastSnapshot,
           acquisitionSucceeded, snapshotIsValid,
           snapshot.status.quality == .available,
           !snapshot.status.flags.contains(.sourceOffline),
           evaluateFreshness(snapshot: snapshot, now: now, maximumAge: Self.maximumAgeSeconds,
                             acquisitionSucceeded: true) == .fresh {
            isHarmlessCachedSnapshot = true
        } else {
            isHarmlessCachedSnapshot = false
        }

        if let lastMonotonic = monotonicHighWatermark, monotonicSeconds == lastMonotonic {
            if isHarmlessCachedSnapshot { return }
            pause()
            return
        }
        monotonicHighWatermark = monotonicSeconds
        if isHarmlessCachedSnapshot { return }

        guard let snapshot else {
            pause()
            return
        }
        guard snapshot.capturedAt.timeIntervalSince1970.isFinite else {
            pause()
            return
        }
        guard snapshotIsValid, snapshotSourceIsValid else {
            pause()
            return
        }
        guard snapshot.capturedAt <= now else {
            pause()
            return
        }

        guard acquisitionSucceeded,
              evaluateFreshness(snapshot: snapshot, now: now,
                                maximumAge: Self.maximumAgeSeconds,
                                acquisitionSucceeded: true) == .fresh,
              snapshot.status.quality == .available,
              !snapshot.status.flags.contains(.sourceOffline) else {
            pause()
            return
        }

        if source != snapshot.source {
            reset()
            source = snapshot.source
            monotonicHighWatermark = monotonicSeconds
        }

        if let highWatermark = captureHighWatermark {
            if snapshot.capturedAt == highWatermark {
                pause()
                return
            }
            if snapshot.capturedAt < highWatermark {
                pause()
                return
            }
        }

        captureHighWatermark = snapshot.capturedAt
        lastSnapshot = snapshot
        source = snapshot.source

        Self.process(.input, snapshot: snapshot, monotonicSeconds: monotonicSeconds, into: &input)
        Self.process(.ups, snapshot: snapshot, monotonicSeconds: monotonicSeconds, into: &ups)
    }

    private static func process(_ channel: MonitorEnergyChannel, snapshot: MonitorSnapshot,
                                monotonicSeconds: TimeInterval, into accumulator: inout ChannelAccumulator) {
        guard let metric = snapshot.metrics.first(where: { $0.id == channel.metricID }),
              metric.unit == .watts, metric.quality == .available,
              let watts = metric.value, watts.isFinite, watts >= 0 else {
            accumulator.interrupt()
            return
        }

        if let previousCapture = accumulator.lastSampleCapture,
           let previousUptime = accumulator.lastSampleUptime,
           let previousProvenance = accumulator.lastProvenance {
            let wallDelta = snapshot.capturedAt.timeIntervalSince(previousCapture)
            let monotonicDelta = monotonicSeconds - previousUptime
            if previousProvenance != metric.provenance
                || !wallDelta.isFinite || wallDelta <= 0 || wallDelta > Self.maximumGapSeconds
                || !monotonicDelta.isFinite || monotonicDelta <= 0 || monotonicDelta > Self.maximumGapSeconds
                || abs(wallDelta - monotonicDelta) > Self.clockToleranceSeconds {
                accumulator.interrupt()
            }
        }

        let sourceKey = "\(snapshot.source.provider.rawValue):\(snapshot.source.id)"
        let sample = EnergySample(sourceID: sourceKey, continuityToken: snapshot.source.sessionID,
                                  monotonicSeconds: monotonicSeconds, capturedAt: snapshot.capturedAt,
                                  watts: watts, eligibility: .validatedActive)
        _ = accumulator.integrator.add(sample)
        accumulator.hasObservedEligiblePower = true
        accumulator.continuityBroken = false
        accumulator.lastSampleCapture = snapshot.capturedAt
        accumulator.lastSampleUptime = monotonicSeconds
        accumulator.lastProvenance = metric.provenance
        accumulator.firstCapture = accumulator.firstCapture ?? snapshot.capturedAt
        accumulator.lastCapture = snapshot.capturedAt
        accumulator.provenances.insert(metric.provenance)
    }

    private func summary(_ channel: MonitorEnergyChannel, _ accumulator: ChannelAccumulator) -> MonitorEnergyEstimate {
        let result = accumulator.integrator.result
        return MonitorEnergyEstimate(
            channel: channel,
            source: source,
            state: accumulator.state,
            energyWh: accumulator.estimateEnergy,
            coveredDurationSeconds: result.coveredDurationSeconds,
            gapOrBreakCount: result.gapOrBreakCount,
            firstCapturedAt: accumulator.firstCapture,
            lastCapturedAt: accumulator.lastCapture,
            powerProvenances: accumulator.provenances.sorted { $0.rawValue < $1.rawValue }
        )
    }
}
