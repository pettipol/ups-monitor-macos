import Foundation
import Observation
import UPSModel
import UPSRuntime

@MainActor
protocol UPSAlertDelivery: AnyObject {
    func requestAuthorization() async throws -> Bool
    func isAuthorized() async -> Bool
    func submit(_ event: UPSAlertEvent) async throws
    func clear() async
}

enum UPSAlertDeliveryError: Error {
    case notAuthorized
    case failed
}

@Observable
@MainActor
final class UPSAlertController {
    private enum AuthorizationResult: Sendable {
        case authorized
        case denied
        case failed
    }

    private enum SubmissionResult: Sendable {
        case completed
        case invalidated
        case notAuthorized
        case failed
    }

    private(set) var isEnabled = false
    private(set) var isBusy = false
    private(set) var message: String?
    private(set) var policy = UPSAlertPolicy()
    private(set) var isStopped = false

    @ObservationIgnored private let delivery: any UPSAlertDelivery
    @ObservationIgnored private var evaluator = UPSAlertEvaluator()
    @ObservationIgnored private var generation: UInt64 = 0
    @ObservationIgnored private var policyGeneration: UInt64 = 0
    @ObservationIgnored private var deliveryWasUsed = false
    @ObservationIgnored private var authorizationTask: Task<AuthorizationResult, Never>?
    @ObservationIgnored private var submissionTask: Task<SubmissionResult, Never>?
    @ObservationIgnored private var clearTask: Task<Void, Never>?

    init(delivery: (any UPSAlertDelivery)? = nil) {
        self.delivery = delivery ?? SystemUPSAlertDelivery()
    }

    func setEnabled(_ enabled: Bool) async {
        guard !isStopped else { return }
        if !enabled {
            isEnabled = false
            message = nil
            evaluator.reset()
            generation &+= 1
            await drainAndClear(for: generation)
            return
        }

        guard !isEnabled, !isBusy else { return }
        generation &+= 1
        let requestGeneration = generation
        evaluator.reset()
        message = nil
        isBusy = true
        deliveryWasUsed = true

        let delivery = self.delivery
        let task = Task { @MainActor in
            do {
                guard try await delivery.requestAuthorization(), await delivery.isAuthorized() else {
                    return AuthorizationResult.denied
                }
                return AuthorizationResult.authorized
            } catch {
                return AuthorizationResult.failed
            }
        }
        authorizationTask = task
        let result = await task.value
        guard requestGeneration == generation else { return }
        authorizationTask = nil
        isBusy = false

        switch result {
        case .authorized:
            isEnabled = true
        case .denied:
            isEnabled = false
            message = "Alerts are not authorized"
        case .failed:
            isEnabled = false
            message = "Could not enable alerts"
        }
    }

    func setPolicy(_ policy: UPSAlertPolicy) {
        guard !isStopped else { return }
        guard (5...50).contains(policy.lowChargeThreshold) else {
            message = "Alert settings are invalid"
            return
        }
        self.policy = policy
        evaluator.resetObservations()
        policyGeneration &+= 1
        message = nil
    }

    func observe(
        snapshot: MonitorSnapshot?,
        acquisitionSucceeded: Bool,
        now: Date,
        uptime: TimeInterval,
        maximumAge: TimeInterval
    ) async {
        guard !isStopped, isEnabled, !isBusy else { return }
        let events = evaluator.evaluate(
            snapshot: snapshot,
            acquisitionSucceeded: acquisitionSucceeded,
            now: now,
            uptime: uptime,
            maximumAge: maximumAge,
            policy: policy
        )
        guard !events.isEmpty else { return }

        let submissionGeneration = generation
        let submissionPolicyGeneration = policyGeneration
        isBusy = true
        message = nil
        let delivery = self.delivery
        let task: Task<SubmissionResult, Never> = Task { @MainActor [weak self] in
            for event in events {
                guard let controller = self,
                      controller.generation == submissionGeneration,
                      controller.policyGeneration == submissionPolicyGeneration,
                      controller.isEnabled,
                      !controller.isStopped else { return .invalidated }
                guard await delivery.isAuthorized() else { return .notAuthorized }
                guard controller.generation == submissionGeneration,
                      controller.policyGeneration == submissionPolicyGeneration,
                      controller.isEnabled,
                      !controller.isStopped else { return .invalidated }
                do {
                    try await delivery.submit(event)
                } catch UPSAlertDeliveryError.notAuthorized {
                    return .notAuthorized
                } catch {
                    return .failed
                }
            }
            return .completed
        }
        submissionTask = task
        let result = await task.value
        guard submissionGeneration == generation else { return }
        submissionTask = nil
        switch result {
        case .completed, .invalidated:
            isBusy = false
        case .failed:
            isBusy = false
            message = "An alert could not be delivered"
        case .notAuthorized:
            isEnabled = false
            evaluator.reset()
            message = "Alerts are not authorized"
            generation &+= 1
            await drainAndClear(for: generation)
        }
    }

    func suspend() async {
        guard !isStopped else { return }
        evaluator.resetObservations()
        generation &+= 1
        await drainAndClear(for: generation)
    }

    func stop() async {
        guard !isStopped else { return }
        isStopped = true
        isEnabled = false
        evaluator.reset()
        generation &+= 1
        await drainAndClear(for: generation)
    }

    private func drainAndClear(for expectedGeneration: UInt64) async {
        guard deliveryWasUsed else {
            if expectedGeneration == generation { isBusy = false }
            return
        }
        isBusy = true

        if let authorizationTask {
            _ = await authorizationTask.value
            self.authorizationTask = nil
        }
        if let submissionTask {
            _ = await submissionTask.value
            self.submissionTask = nil
        }
        guard expectedGeneration == generation else { return }

        if let clearTask {
            await clearTask.value
            guard expectedGeneration == generation else { return }
            self.clearTask = nil
            isBusy = false
            return
        }

        let task = Task { @MainActor in await delivery.clear() }
        clearTask = task
        await task.value
        guard expectedGeneration == generation else { return }
        clearTask = nil
        isBusy = false
    }
}
