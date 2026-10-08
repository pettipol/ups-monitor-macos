import Foundation
import Testing
import UPSModel
import UPSRuntime
@testable import UPSAppHost

private let alertSource = MonitorSource(
    provider: .nut,
    id: "alert-source",
    sessionID: "alert-session",
    identityStability: .configured
)

private func alertSnapshot(
    at seconds: TimeInterval,
    lineState: MonitorLineState = .onBattery,
    flags: Set<MonitorStatusFlag> = [],
    quality: MonitorStatusQuality = .available,
    source: MonitorSource = alertSource
) -> MonitorSnapshot {
    MonitorSnapshot(
        source: source,
        capturedAt: Date(timeIntervalSince1970: seconds),
        status: MonitorStatus(lineState: lineState, flags: flags, quality: quality),
        metrics: []
    )
}

@MainActor
private final class FakeAlertDelivery: UPSAlertDelivery {
    enum Failure: Error { case denied, submit }

    var authorizationGranted = true
    var currentlyAuthorized = true
    var failAuthorization = false
    var failSubmission = false
    var holdAuthorization = false
    var holdSubmission = false
    private(set) var authorizationStarted = false
    private(set) var submissionStarted = false
    private(set) var authorizationCalls = 0
    private(set) var authorizationChecks = 0
    private(set) var submitCalls = 0
    private(set) var clearCalls = 0
    private(set) var clearWhileAuthorizationPending = false
    private(set) var clearWhileSubmissionPending = false
    private(set) var submittedEvents: [UPSAlertEvent] = []
    private var authorizationContinuation: CheckedContinuation<Bool, Error>?
    private var submissionContinuation: CheckedContinuation<Void, Error>?
    private var earlyAuthorizationResult: Bool?
    private var submissionReleasedEarly = false

    func requestAuthorization() async throws -> Bool {
        authorizationCalls += 1
        authorizationStarted = true
        if holdAuthorization {
            return try await withCheckedThrowingContinuation { continuation in
                if let result = earlyAuthorizationResult {
                    earlyAuthorizationResult = nil
                    continuation.resume(returning: result)
                } else {
                    authorizationContinuation = continuation
                }
            }
        }
        if failAuthorization { throw Failure.denied }
        return authorizationGranted
    }

    func isAuthorized() async -> Bool {
        authorizationChecks += 1
        return currentlyAuthorized
    }

    func submit(_ event: UPSAlertEvent) async throws {
        submitCalls += 1
        submissionStarted = true
        submittedEvents.append(event)
        if holdSubmission {
            try await withCheckedThrowingContinuation { continuation in
                if submissionReleasedEarly {
                    submissionReleasedEarly = false
                    continuation.resume()
                } else {
                    submissionContinuation = continuation
                }
            }
        }
        if failSubmission { throw Failure.submit }
    }

    func clear() async {
        clearCalls += 1
        clearWhileAuthorizationPending = clearWhileAuthorizationPending || authorizationContinuation != nil
        clearWhileSubmissionPending = clearWhileSubmissionPending || submissionContinuation != nil
    }

    func waitForAuthorization(timeout: Duration = .seconds(2)) async -> Bool {
        await waitUntilStarted(authorization: true, timeout: timeout)
    }

    func waitForSubmission(timeout: Duration = .seconds(2)) async -> Bool {
        await waitUntilStarted(authorization: false, timeout: timeout)
    }

    private func waitUntilStarted(authorization: Bool, timeout: Duration) async -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !(authorization ? authorizationStarted : submissionStarted) {
            guard !Task.isCancelled, clock.now < deadline else { return false }
            do {
                try await Task.sleep(for: .milliseconds(1))
            } catch {
                return false
            }
        }
        return true
    }

    func releaseAuthorization(_ granted: Bool) {
        if let continuation = authorizationContinuation {
            authorizationContinuation = nil
            continuation.resume(returning: granted)
        } else {
            earlyAuthorizationResult = granted
        }
    }

    func releaseSubmission() {
        if let continuation = submissionContinuation {
            submissionContinuation = nil
            continuation.resume()
        } else {
            submissionReleasedEarly = true
        }
    }
}

@Suite struct UPSAlertControllerTests {
    @MainActor @Test func defaultOffObserveSuspendAndStopDoNotTouchDelivery() async {
        let delivery = FakeAlertDelivery()
        let controller = UPSAlertController(delivery: delivery)

        await controller.observe(snapshot: alertSnapshot(at: 1), acquisitionSucceeded: true,
                                 now: Date(timeIntervalSince1970: 1), uptime: 1, maximumAge: 5)
        await controller.suspend()
        await controller.stop()

        #expect(!controller.isEnabled)
        #expect(controller.isStopped)
        #expect(delivery.authorizationCalls == 0)
        #expect(delivery.authorizationChecks == 0)
        #expect(delivery.submitCalls == 0)
        #expect(delivery.clearCalls == 0)
    }

    @MainActor @Test func explicitEnableRequestsAuthorizationAndDenialIsRedacted() async {
        let delivery = FakeAlertDelivery()
        delivery.currentlyAuthorized = false
        let controller = UPSAlertController(delivery: delivery)

        await controller.setEnabled(true)

        #expect(delivery.authorizationCalls == 1)
        #expect(delivery.authorizationChecks == 1)
        #expect(!controller.isEnabled)
        #expect(controller.message == "Alerts are not authorized")
    }

    @MainActor @Test func failedAuthorizationDoesNotExposeUnderlyingError() async {
        let delivery = FakeAlertDelivery()
        delivery.failAuthorization = true
        let controller = UPSAlertController(delivery: delivery)

        await controller.setEnabled(true)

        #expect(!controller.isEnabled)
        #expect(controller.message == "Could not enable alerts")
    }

    @MainActor @Test func disabledPolicyAndFailedDeliveryDoNotRetrySameTransition() async {
        let delivery = FakeAlertDelivery()
        delivery.failSubmission = true
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        controller.setPolicy(UPSAlertPolicy(lineChanges: false, lowBattery: false, monitoringLoss: false))

        await controller.observe(snapshot: alertSnapshot(at: 1), acquisitionSucceeded: true,
                                 now: Date(timeIntervalSince1970: 1), uptime: 1, maximumAge: 5)
        #expect(delivery.submitCalls == 0)

        controller.setPolicy(UPSAlertPolicy())
        await controller.observe(snapshot: alertSnapshot(at: 2), acquisitionSucceeded: true,
                                 now: Date(timeIntervalSince1970: 2), uptime: 2, maximumAge: 5)
        #expect(delivery.submitCalls == 1)
        #expect(controller.message == "An alert could not be delivered")

        await controller.observe(snapshot: alertSnapshot(at: 3), acquisitionSucceeded: true,
                                 now: Date(timeIntervalSince1970: 3), uptime: 3, maximumAge: 5)
        #expect(delivery.submitCalls == 1)
    }

    @MainActor @Test func delayedAuthorizationCannotReenableAfterDisableAndIsDrainedBeforeClear() async {
        let delivery = FakeAlertDelivery()
        delivery.holdAuthorization = true
        let controller = UPSAlertController(delivery: delivery)
        let enable = Task { await controller.setEnabled(true) }
        let authorizationStarted = await delivery.waitForAuthorization()
        #expect(authorizationStarted)
        let releaseAuthorization = Task {
            let started = await delivery.waitForAuthorization()
            #expect(started)
            try? await Task.sleep(for: .milliseconds(1))
            delivery.releaseAuthorization(true)
        }
        await controller.setEnabled(false)
        await releaseAuthorization.value
        await enable.value

        #expect(!controller.isEnabled)
        #expect(!controller.isBusy)
        #expect(delivery.clearCalls == 1)
        #expect(!delivery.clearWhileAuthorizationPending)
    }

    @MainActor @Test func delayedSubmissionIsDrainedBeforeSuspendClearAndOptInIsPreserved() async {
        let delivery = FakeAlertDelivery()
        delivery.holdSubmission = true
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        let observation = Task {
            await controller.observe(snapshot: alertSnapshot(at: 10), acquisitionSucceeded: true,
                                     now: Date(timeIntervalSince1970: 10), uptime: 10, maximumAge: 5)
        }
        let submissionStarted = await delivery.waitForSubmission()
        #expect(submissionStarted)
        let releaseSubmission = Task {
            let started = await delivery.waitForSubmission()
            #expect(started)
            try? await Task.sleep(for: .milliseconds(1))
            delivery.releaseSubmission()
        }
        await controller.suspend()
        await releaseSubmission.value
        await observation.value

        #expect(controller.isEnabled)
        #expect(!controller.isBusy)
        #expect(delivery.submitCalls == 1)
        #expect(delivery.clearCalls == 1)
        #expect(!delivery.clearWhileSubmissionPending)
    }

    @MainActor @Test func policyChangeDuringBatchFencesRemainingEvents() async {
        let delivery = FakeAlertDelivery()
        delivery.holdSubmission = true
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        let observation = Task {
            await controller.observe(snapshot: alertSnapshot(at: 15, flags: [.lowBattery]), acquisitionSucceeded: true,
                                     now: Date(timeIntervalSince1970: 15), uptime: 15, maximumAge: 5)
        }
        let submissionStarted = await delivery.waitForSubmission()
        #expect(submissionStarted)
        controller.setPolicy(UPSAlertPolicy(lineChanges: false, lowBattery: false, monitoringLoss: false))
        delivery.releaseSubmission()
        await observation.value

        #expect(delivery.submittedEvents.map(\.kind) == [.onBattery])
        #expect(controller.isEnabled)
        #expect(!controller.isBusy)
    }

    @MainActor @Test func revokedAuthorizationDisablesAlertsWithoutSubmitting() async {
        let delivery = FakeAlertDelivery()
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        delivery.currentlyAuthorized = false

        await controller.observe(snapshot: alertSnapshot(at: 16), acquisitionSucceeded: true,
                                 now: Date(timeIntervalSince1970: 16), uptime: 16, maximumAge: 5)

        #expect(!controller.isEnabled)
        #expect(controller.message == "Alerts are not authorized")
        #expect(delivery.submitCalls == 0)
        #expect(delivery.clearCalls == 1)
    }

    @MainActor @Test func stopDuringSubmissionIsTerminalAndClearsAfterCompletion() async {
        let delivery = FakeAlertDelivery()
        delivery.holdSubmission = true
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        let observation = Task {
            await controller.observe(snapshot: alertSnapshot(at: 20), acquisitionSucceeded: true,
                                     now: Date(timeIntervalSince1970: 20), uptime: 20, maximumAge: 5)
        }
        let submissionStarted = await delivery.waitForSubmission()
        #expect(submissionStarted)
        let releaseSubmission = Task {
            let started = await delivery.waitForSubmission()
            #expect(started)
            try? await Task.sleep(for: .milliseconds(1))
            delivery.releaseSubmission()
        }
        await controller.stop()
        await releaseSubmission.value
        await observation.value
        await controller.setEnabled(true)

        #expect(controller.isStopped)
        #expect(!controller.isEnabled)
        #expect(!controller.isBusy)
        #expect(delivery.clearCalls == 1)
        #expect(!delivery.clearWhileSubmissionPending)
        #expect(delivery.authorizationCalls == 1)
    }

    @MainActor @Test func observationsAreSkippedWhileAnAdmittedSubmissionIsBusy() async {
        let delivery = FakeAlertDelivery()
        delivery.holdSubmission = true
        let controller = UPSAlertController(delivery: delivery)
        await controller.setEnabled(true)
        let first = Task {
            await controller.observe(snapshot: alertSnapshot(at: 30), acquisitionSucceeded: true,
                                     now: Date(timeIntervalSince1970: 30), uptime: 30, maximumAge: 5)
        }
        let submissionStarted = await delivery.waitForSubmission()
        #expect(submissionStarted)

        await controller.observe(snapshot: alertSnapshot(at: 31, flags: [.lowBattery]), acquisitionSucceeded: true,
                                 now: Date(timeIntervalSince1970: 31), uptime: 31, maximumAge: 5)
        #expect(delivery.submitCalls == 1)

        delivery.releaseSubmission()
        await first.value
        #expect(delivery.submitCalls == 1)
    }
}
