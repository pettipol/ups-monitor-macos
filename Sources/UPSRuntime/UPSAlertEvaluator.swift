import Foundation
import UPSModel

public struct UPSAlertPolicy: Equatable, Sendable {
    public var lineChanges: Bool
    public var lowBattery: Bool
    public var monitoringLoss: Bool
    public var lowChargeThreshold: Int

    public init(lineChanges: Bool = true, lowBattery: Bool = true, monitoringLoss: Bool = true,
                lowChargeThreshold: Int = 20) {
        self.lineChanges = lineChanges
        self.lowBattery = lowBattery
        self.monitoringLoss = monitoringLoss
        self.lowChargeThreshold = lowChargeThreshold
    }

    fileprivate var isValid: Bool { (5...50).contains(lowChargeThreshold) }
}

public enum UPSAlertKind: Hashable, Sendable {
    case onBattery
    case powerRestored
    case lowBattery
    case monitoringUnavailable
}

public struct UPSAlertEvent: Equatable, Sendable {
    public let kind: UPSAlertKind
    public let capturedAt: Date

    public init(kind: UPSAlertKind, capturedAt: Date) {
        self.kind = kind
        self.capturedAt = capturedAt
    }
}

public struct UPSAlertEvaluator: Sendable {
    private struct ObservationState: Sendable {
        var source: MonitorSource?
        var lastCapturedAt: Date?
        var lineState: MonitorLineState?
        var lowBatteryLatched = false
        var hasEverBeenUsable = false
        var lastUsableCapture: Date?
        var unusableSince: TimeInterval?
        var monitoringLossReported = false
    }

    private var observation = ObservationState()
    private var lastUptime: TimeInterval?
    private var lastPolicy: UPSAlertPolicy?
    private var lastEventUptime: [UPSAlertKind: TimeInterval] = [:]

    public init() {}

    public mutating func reset() {
        resetObservations()
        lastEventUptime.removeAll(keepingCapacity: false)
    }

    public mutating func resetObservations() {
        observation = ObservationState()
        lastUptime = nil
        lastPolicy = nil
    }

    public mutating func evaluate(
        snapshot: MonitorSnapshot?,
        acquisitionSucceeded: Bool,
        now: Date,
        uptime: TimeInterval,
        maximumAge: TimeInterval,
        policy: UPSAlertPolicy
    ) -> [UPSAlertEvent] {
        guard policy.isValid, now.timeIntervalSince1970.isFinite,
              uptime.isFinite, uptime >= 0, maximumAge.isFinite, maximumAge >= 0 else {
            resetContinuity()
            lastUptime = nil
            return []
        }
        if let lastUptime, uptime < lastUptime {
            resetContinuity()
            self.lastUptime = uptime
            return []
        }
        lastUptime = uptime

        if let lastPolicy, lastPolicy != policy {
            resetContinuity()
            lastUptime = uptime
        }
        lastPolicy = policy

        let validatedSnapshot: MonitorSnapshot?
        if let snapshot, (try? snapshot.validate()) != nil {
            validatedSnapshot = snapshot
        } else {
            validatedSnapshot = nil
        }

        if let validatedSnapshot, observation.source != validatedSnapshot.source {
            resetContinuity()
            lastUptime = uptime
            observation.source = validatedSnapshot.source
        }

        let usable: MonitorSnapshot?
        if acquisitionSucceeded, let validatedSnapshot,
           evaluateFreshness(snapshot: validatedSnapshot, now: now, maximumAge: maximumAge,
                             acquisitionSucceeded: true) == .fresh,
           validatedSnapshot.status.quality == .available,
           !validatedSnapshot.status.flags.contains(.sourceOffline) {
            usable = validatedSnapshot
        } else {
            usable = nil
        }

        guard let usable else {
            observation.lineState = nil
            if observation.hasEverBeenUsable, observation.unusableSince == nil {
                observation.unusableSince = uptime
                observation.monitoringLossReported = false
            }
            guard observation.hasEverBeenUsable,
                  let unusableSince = observation.unusableSince,
                  !observation.monitoringLossReported,
                  uptime - unusableSince >= 30 else { return [] }
            observation.monitoringLossReported = true
            guard policy.monitoringLoss, let capture = observation.lastUsableCapture else { return [] }
            return emit(.monitoringUnavailable, capturedAt: capture, uptime: uptime)
        }

        if let lastCapture = observation.lastCapturedAt, usable.capturedAt <= lastCapture {
            return []
        }
        if let lastCapture = observation.lastCapturedAt {
            let captureGap = usable.capturedAt.timeIntervalSince(lastCapture)
            if !captureGap.isFinite || captureGap > maximumAge {
                observation.lineState = nil
            }
        }

        observation.source = usable.source
        observation.lastCapturedAt = usable.capturedAt
        observation.hasEverBeenUsable = true
        observation.lastUsableCapture = usable.capturedAt
        observation.unusableSince = nil
        observation.monitoringLossReported = false

        var events: [UPSAlertEvent] = []
        switch usable.status.lineState {
        case .onBattery:
            if observation.lineState != .onBattery, policy.lineChanges {
                events += emit(.onBattery, capturedAt: usable.capturedAt, uptime: uptime)
            }
            observation.lineState = .onBattery
        case .onLine:
            if observation.lineState == .onBattery, policy.lineChanges {
                events += emit(.powerRestored, capturedAt: usable.capturedAt, uptime: uptime)
            }
            observation.lineState = .onLine
        case .unknown:
            observation.lineState = nil
        }

        let batteryFlag = usable.status.flags.contains(.lowBattery)
        let charge = usable.metrics.first(where: { $0.id == .batteryCharge })
        let availableCharge: Double?
        if charge?.quality == .available, let value = charge?.value, value.isFinite {
            availableCharge = value
        } else {
            availableCharge = nil
        }
        if !batteryFlag, let availableCharge,
           availableCharge >= Double(policy.lowChargeThreshold + 5) {
            observation.lowBatteryLatched = false
        }
        let lowCondition = batteryFlag || (availableCharge.map { $0 <= Double(policy.lowChargeThreshold) } ?? false)
        if lowCondition, !observation.lowBatteryLatched {
            observation.lowBatteryLatched = true
            if policy.lowBattery {
                events += emit(.lowBattery, capturedAt: usable.capturedAt, uptime: uptime)
            }
        }
        return events
    }

    private mutating func emit(_ kind: UPSAlertKind, capturedAt: Date, uptime: TimeInterval) -> [UPSAlertEvent] {
        if let previous = lastEventUptime[kind], uptime - previous < 60 { return [] }
        lastEventUptime[kind] = uptime
        return [UPSAlertEvent(kind: kind, capturedAt: capturedAt)]
    }

    private mutating func resetContinuity() {
        observation = ObservationState()
    }
}
