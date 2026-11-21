import AppKit
import ApplePowerSource
import Foundation
import Observation
import NUTClient
import UniformTypeIdentifiers
import UPSEnergy
import UPSHistory
import UPSModel
import UPSMonitorUI
import UPSRuntime
import UPSWidgetBridge
import UPSWidgetData
import WidgetKit

enum MonitorBackend: String {
    case apple, nut, supervisedSession

    var title: String {
        switch self {
        case .apple: "Apple power sources"
        case .nut: "Local NUT"
        case .supervisedSession: "Supervised session · unqualified"
        }
    }
}

struct WidgetSharingBootstrap: Sendable {
    let directoryURL: @Sendable () throws -> URL
    let reload: @Sendable () async -> Void
}

private enum SessionLaunchMode {
    case none
    case supervised(URL)
    case synthetic(URL)
    case managedSynthetic
    case managedNative
    case managedOperational
    case managedBundledOperational
    case managedFrozenOperational
    case invalid

    static func parse(arguments: [String]) -> Self {
        let values = Array(arguments.dropFirst())
        if values.contains("--managed-frozen-operational-session") {
            return values == ["--managed-frozen-operational-session"] ? .managedFrozenOperational : .invalid
        }
        if values.contains("--managed-bundled-operational-session") {
            return values == ["--managed-bundled-operational-session"] ? .managedBundledOperational : .invalid
        }
        if values.contains("--managed-operational-session") {
            return values == ["--managed-operational-session"] ? .managedOperational : .invalid
        }
        if values.contains("--managed-native-session") {
            return values == ["--managed-native-session"] ? .managedNative : .invalid
        }
        if values.contains("--managed-synthetic-session") {
            return values == ["--managed-synthetic-session"] ? .managedSynthetic : .invalid
        }
        let realIndex = values.firstIndex(of: "--supervised-session-feed")
        let syntheticIndex = values.firstIndex(of: "--synthetic-session-feed")
        guard realIndex == nil || syntheticIndex == nil,
              !(realIndex != nil && values.contains("--synthetic-preview")),
              !(syntheticIndex != nil && values.contains("--synthetic-preview")) else { return .invalid }
        guard let index = realIndex ?? syntheticIndex else { return .none }
        guard values.count == 2, index == 0, values.count > index + 1,
              values[index + 1].hasPrefix("/"), !values[index + 1].contains("\0") else { return .invalid }
        let directory = URL(fileURLWithPath: values[index + 1], isDirectory: true).standardizedFileURL
        return realIndex != nil ? .supervised(directory) : .synthetic(directory)
    }
}

@Observable
@MainActor
final class MonitorAppModel {
    var sources: [MonitorSnapshot] = []
    var presentationNamesBySourceKey: [String: String] = [:]
    var selectedSourceKey: String?
    var readState: UPSReadState = .loading
    var now: Date
    var maximumAge: TimeInterval = 10
    var acquisitionSucceeded = false
    var recordsHistory = false
    var historyTransition = false
    var history: [MonitorSnapshot]?
    var historyBrowser: HistoryBrowserModel?
    var operationMessage: String?
    var widgetMessage: String?
    var backend: MonitorBackend = .apple
    var supervisedSessionDirectoryURL: URL?
    var supervisedSessionMessage: String?
    var connectionDraft = NUTConnectionDraft()
    var connectionMessage: String?
    var backendTransition = false
    var showsSupervisedSessionPicker = false
    var showsNUTSettings = false
    var showsAlertSettings = false
    var showsWidgetStatus = false
    let widgetInstallation = WidgetInstallationModel()
    let alerts: UPSAlertController
    var energyEstimates = MonitorEnergyTracker().summaries
    let isPreview: Bool
    let widgetFixtureMode: WidgetFixtureMode
    let managedSyntheticSession: ManagedSyntheticSessionController

    var isWidgetFixture: Bool { !isPreview && widgetFixtureMode == .enabled }
    var isWidgetConfigurationInvalid: Bool { !isPreview && widgetFixtureMode == .invalid }
    var isManagedSyntheticMode: Bool { if case .managedSynthetic = sessionLaunchMode { true } else { false } }
    var isManagedNativeMode: Bool { if case .managedNative = sessionLaunchMode { true } else { false } }
    var isManagedOperationalMode: Bool {
        switch sessionLaunchMode {
        case .managedOperational, .managedBundledOperational, .managedFrozenOperational: true
        default: false
        }
    }
    var isManagedMode: Bool { isManagedSyntheticMode || isManagedNativeMode || isManagedOperationalMode }
    private var managedOperationalDisplayLabel: String {
        isWidgetFixture ? "Synthetic frozen operational candidate · Unqualified"
            : "Operational session · unqualified · macOS 27+ arm64"
    }
    var managedSession: ManagedSyntheticSessionController { managedSyntheticSession }
    var managedSessionMessage: String {
        if isManagedOperationalMode && !managedSession.attempted { return "Operational · unqualified · macOS 27+ arm64 · idle" }
        if isManagedNativeMode && !managedSession.attempted { return "Native 120 s · unqualified · idle" }
        return managedSession.message
    }
    var managedSessionTitle: String {
        if isManagedOperationalMode { return managedOperationalDisplayLabel }
        return isManagedNativeMode ? "Native 120 s session · unqualified" : "Managed synthetic session · unqualified"
    }
    var managedSessionStartTitle: String {
        if isManagedOperationalMode {
            return isWidgetFixture ? "Start synthetic frozen operational session" : "Start operational session"
        }
        return isManagedNativeMode ? "Read 120 s" : "Start synthetic 120 s"
    }
    private var managedSessionKind: String {
        if isManagedOperationalMode { return "Operational" }
        return isManagedNativeMode ? "Native 120 s" : "Synthetic"
    }
    var isSyntheticSessionMode: Bool {
        if case .synthetic = sessionLaunchMode { return true }
        return isManagedSyntheticMode
    }
    var isSyntheticMode: Bool { isPreview || isWidgetFixture || isWidgetConfigurationInvalid || isSyntheticSessionMode }
    var isSupervisedSession: Bool {
        if backend == .supervisedSession { return true }
        switch sessionLaunchMode {
        case .supervised, .synthetic, .managedSynthetic, .managedNative, .managedOperational, .managedBundledOperational, .managedFrozenOperational: return true
        case .none, .invalid: return false
        }
    }
    var syntheticModeTitle: String {
        if isManagedOperationalMode { return managedOperationalDisplayLabel }
        if isManagedSyntheticMode { return "Managed synthetic session · unqualified" }
        if isSyntheticSessionMode { return "Synthetic session" }
        if isWidgetFixture { return "Synthetic widget test" }
        if isWidgetConfigurationInvalid { return "Synthetic preview · widget configuration invalid" }
        return "Synthetic preview"
    }

    @ObservationIgnored private var started = false
    @ObservationIgnored private var stopped = false
    @ObservationIgnored private let reader = AppleSessionReader()
    @ObservationIgnored private var coordinator: MonitorCoordinator?
    @ObservationIgnored private var historyStore: UPSHistoryStore?
    @ObservationIgnored private let injectedRead: MonitorCoordinator.Read?
    @ObservationIgnored private let injectedReadWithPresentation: MonitorCoordinator.ReadWithPresentation?
    @ObservationIgnored private let clock: MonitorCoordinator.Clock
    @ObservationIgnored private let monotonicClock: MonitorCoordinator.MonotonicClock
    @ObservationIgnored private var energyTracker = MonitorEnergyTracker()
    @ObservationIgnored private var energyResetBoundary: (source: MonitorSource, capturedAt: Date)?
    @ObservationIgnored private let historyDirectoryURL: URL?
    @ObservationIgnored private let observesWorkspace: Bool
    @ObservationIgnored private var stateTask: Task<Void, Never>?
    @ObservationIgnored private var wakeObserver: NSObjectProtocol?
    @ObservationIgnored private var sleepObserver: NSObjectProtocol?
    @ObservationIgnored private var lastHistoryCapture: Date?
    @ObservationIgnored private var historyQueryGeneration = 0
    @ObservationIgnored private var widgetPublisher: WidgetSnapshotPublisher?
    @ObservationIgnored private let widgetSharingBootstrap: WidgetSharingBootstrap?
    @ObservationIgnored private var widgetSequence: UInt64 = 0
    @ObservationIgnored private var widgetAcquisition: WidgetAcquisition?
    @ObservationIgnored private var backendGeneration: UInt64 = 0
    @ObservationIgnored private var sleeping = false
    @ObservationIgnored private var alertSelectionGeneration: UInt64 = 0
    @ObservationIgnored private var alertSelectionTransition = false
    @ObservationIgnored private var alertObservationTask: Task<Void, Never>?
    @ObservationIgnored private let nutReadFactory: @Sendable (NUTConnectionDraft) async throws -> MonitorCoordinator.Read
    @ObservationIgnored private let supervisedSessionReadFactory: @Sendable (URL) async throws -> MonitorCoordinator.ReadWithPresentation
    @ObservationIgnored private let sessionLaunchMode: SessionLaunchMode
    @ObservationIgnored private let managedNativeConfiguration: ManagedNativeRuntimeConfiguration?
    @ObservationIgnored private let managedOperationalConfiguration: ManagedOperationalRuntimeConfiguration?
    @ObservationIgnored private let managedBundledOperationalConfiguration: ManagedBundledOperationalRuntimeConfiguration?
    @ObservationIgnored private let managedFrozenOperationalConfiguration: ManagedFrozenOperationalRuntimeConfiguration?
    @ObservationIgnored private let managedSyntheticConfiguration: ManagedSyntheticRuntimeConfiguration?
    @ObservationIgnored private let operationalSessionReadFactory: @Sendable (URL) async throws -> MonitorCoordinator.ReadWithPresentation
    @ObservationIgnored private let startupClock: @Sendable () -> TimeInterval
    @ObservationIgnored private let startupSleep: @Sendable (Duration) async throws -> Void
    @ObservationIgnored private let operationalStart: (@MainActor (ManagedSyntheticSessionController) throws -> URL)?

    init(
        read: MonitorCoordinator.Read? = nil,
        readWithPresentation: MonitorCoordinator.ReadWithPresentation? = nil,
        clock: @escaping MonitorCoordinator.Clock = { Date() },
        monotonicClock: @escaping MonitorCoordinator.MonotonicClock = { ProcessInfo.processInfo.systemUptime },
        historyDirectoryURL: URL? = nil,
        observesWorkspace: Bool = true,
        isPreview: Bool = ProcessInfo.processInfo.arguments.contains("--synthetic-preview"),
        widgetFixtureMode: WidgetFixtureMode? = nil,
        widgetPublisher: WidgetSnapshotPublisher? = nil,
        widgetSharingBootstrap: WidgetSharingBootstrap? = nil,
        alerts: UPSAlertController? = nil,
        launchArguments: [String] = ProcessInfo.processInfo.arguments,
        managedSyntheticController: ManagedSyntheticSessionController? = nil,
        managedSyntheticConfiguration: ManagedSyntheticRuntimeConfiguration? = nil,
        managedNativeConfiguration: ManagedNativeRuntimeConfiguration? = nil,
        managedOperationalConfiguration: ManagedOperationalRuntimeConfiguration? = nil,
        managedBundledOperationalConfiguration: ManagedBundledOperationalRuntimeConfiguration? = nil,
        managedFrozenOperationalConfiguration: ManagedFrozenOperationalRuntimeConfiguration? = nil,
        operationalSessionReadFactory: @escaping @Sendable (URL) async throws -> MonitorCoordinator.ReadWithPresentation = MonitorAppModel.makeOperationalSessionRead,
        startupClock: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        startupSleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
        operationalStart: (@MainActor (ManagedSyntheticSessionController) throws -> URL)? = nil,
        nutReadFactory: @escaping @Sendable (NUTConnectionDraft) async throws -> MonitorCoordinator.Read = MonitorAppModel.makeNUTRead,
        supervisedSessionReadFactory: @escaping @Sendable (URL) async throws -> MonitorCoordinator.ReadWithPresentation = MonitorAppModel.makeSupervisedSessionRead
    ) {
        self.injectedRead = read
        self.injectedReadWithPresentation = readWithPresentation
        self.clock = clock
        self.monotonicClock = monotonicClock
        self.historyDirectoryURL = historyDirectoryURL
        self.observesWorkspace = observesWorkspace
        self.isPreview = isPreview
        self.sessionLaunchMode = SessionLaunchMode.parse(arguments: launchArguments)
        self.managedSyntheticSession = managedSyntheticController ?? ManagedSyntheticSessionController()
        self.managedSyntheticConfiguration = managedSyntheticConfiguration ?? (try? .bundled())
        self.managedNativeConfiguration = managedNativeConfiguration ?? (try? .bundled())
        self.managedOperationalConfiguration = managedOperationalConfiguration ?? (try? .bundled())
        self.managedBundledOperationalConfiguration = managedBundledOperationalConfiguration ?? (try? .bundled())
        self.managedFrozenOperationalConfiguration = managedFrozenOperationalConfiguration ?? (try? .bundled())
        self.operationalSessionReadFactory = operationalSessionReadFactory
        self.startupClock = startupClock
        self.startupSleep = startupSleep
        self.operationalStart = operationalStart
        self.widgetFixtureMode = widgetFixtureMode ?? WidgetGroupConfiguration.fixtureMode()
        self.now = clock()
        self.widgetPublisher = widgetPublisher
        self.widgetSharingBootstrap = widgetSharingBootstrap
        self.alerts = alerts ?? UPSAlertController()
        self.nutReadFactory = nutReadFactory
        self.supervisedSessionReadFactory = supervisedSessionReadFactory
    }

    var selected: MonitorSnapshot? {
        sources.first { UPSMonitorFormatters.sourceKey(for: $0) == selectedSourceKey } ?? sources.first
    }

    var menuTitle: String {
        guard let selected else { return "UPS" }
        guard acquisitionSucceeded,
              evaluateFreshness(snapshot: selected, now: now, maximumAge: maximumAge) == .fresh else { return "UPS ?" }
        guard let charge = selected.metrics.first(where: { $0.id == .batteryCharge }),
              charge.quality == .available, let value = charge.value,
              value.isFinite, (0...100).contains(value) else { return "UPS" }
        return "\(Int(value.rounded()))%"
    }

    var canExport: Bool { !stopped && !isSupervisedSession && historyStore != nil && !(history?.isEmpty ?? true) && !isSyntheticMode }
    var canExportEnergy: Bool { !stopped && !isSupervisedSession && !isSyntheticMode && energyEstimates.contains { $0.energyWh != nil } }

    func startIfNeeded() async {
        guard !started, !stopped else { return }
        started = true
        if case .invalid = sessionLaunchMode {
            readState = .failed
            operationMessage = "Session feed arguments invalid; monitoring disabled"
            return
        }
        if isPreview {
            applyPreview()
            return
        }
        if isWidgetConfigurationInvalid {
            applyPreview()
            acquisitionSucceeded = false
            readState = .failed
            operationMessage = "Widget fixture configuration invalid; live monitoring disabled"
            return
        }
        switch sessionLaunchMode {
        case .managedSynthetic, .managedNative, .managedOperational, .managedBundledOperational, .managedFrozenOperational:
            backend = .supervisedSession
            recordsHistory = false
            energyEstimates = []
            configureWidgetSharing()
            readState = .stopped
            operationMessage = "\(managedSessionKind) candidate ready; history, energy estimates and alerts are disabled"
            return
        case let .supervised(directory):
            await startSessionDirectory(directory, synthetic: false)
            return
        case let .synthetic(directory):
            await startSessionDirectory(directory, synthetic: true)
            return
        case .none, .invalid:
            break
        }
        configureWidgetSharing()
        do {
            let read = isWidgetFixture ? Self.withoutPresentation(widgetFixtureRead()) : appleRead()
            coordinator = try makeCoordinator(readWithPresentation: read, generation: backendGeneration)
            if observesWorkspace && !isWidgetFixture { installWorkspaceObservers() }
            await coordinator?.start()
            guard !stopped else { await coordinator?.stop(); return }
            startStateUpdates()
        } catch {
            guard !stopped else { return }
            readState = .failed
            operationMessage = "Monitoring unavailable"
        }
    }

    func refresh() {
        guard (!isSyntheticMode || isSyntheticSessionMode), !stopped, !backendTransition, !sleeping else { return }
        let generation = backendGeneration
        Task {
            guard !stopped, generation == backendGeneration, !backendTransition, !sleeping else { return }
            await coordinator?.refresh()
            guard generation == backendGeneration else { return }
            await updateState()
        }
    }

    func startManagedSyntheticSession() async { await startManagedSession() }

    func startManagedSession() async {
        guard isManagedMode, !stopped, !backendTransition, !managedSyntheticSession.attempted else { return }
        backendTransition = true
        defer { backendTransition = false }
        readState = .loading
        operationMessage = "Starting \(managedSessionKind.lowercased()) session"
        do {
            let directory: URL
            if isManagedOperationalMode {
                if let operationalStart {
                    directory = try operationalStart(managedSession)
                } else if case .managedFrozenOperational = sessionLaunchMode {
                    guard let configuration = managedFrozenOperationalConfiguration else { throw ManagedSyntheticError.configuration }
                    directory = try managedSession.start(frozenOperationalConfiguration: configuration)
                } else if case .managedBundledOperational = sessionLaunchMode {
                    guard let configuration = managedBundledOperationalConfiguration else { throw ManagedSyntheticError.configuration }
                    directory = try managedSession.start(bundledOperationalConfiguration: configuration)
                } else {
                    guard let configuration = managedOperationalConfiguration else { throw ManagedSyntheticError.configuration }
                    directory = try managedSession.start(operationalConfiguration: configuration)
                }
            } else if isManagedNativeMode {
                guard let configuration = managedNativeConfiguration else { throw ManagedSyntheticError.configuration }
                directory = try managedSession.start(nativeConfiguration: configuration)
            } else {
                guard let configuration = managedSyntheticConfiguration else { throw ManagedSyntheticError.configuration }
                directory = try managedSession.start(configuration: configuration)
            }
            let deadline = startupClock() + (isManagedOperationalMode ? 40 : 10)
            while startupClock() < deadline {
                guard !stopped else { return }
                guard managedSyntheticSession.state == .starting else { projectManagedStartupEnd(); return }
                let candidateRead: MonitorCoordinator.ReadWithPresentation?
                if isManagedOperationalMode {
                    candidateRead = try? await operationalSessionReadFactory(directory)
                } else {
                    candidateRead = try? await supervisedSessionReadFactory(directory)
                }
                if let baseRead = candidateRead {
                    guard !stopped else { return }
                    guard managedSyntheticSession.state == .starting else { projectManagedStartupEnd(); return }
                    let label = isManagedOperationalMode ? managedOperationalDisplayLabel
                        : isManagedNativeMode ? "Smart-UPS C 1500 · Native 120 s · Unqualified" : "Simulated UPS · Unqualified"
                    let read: MonitorCoordinator.ReadWithPresentation = {
                        try await baseRead().map { MonitorReading(snapshot: $0.snapshot, presentationName: label) }
                    }
                    try await replaceBackend(.supervisedSession, readWithPresentation: read)
                    guard managedSyntheticSession.state == .starting else {
                        await coordinator?.stopAndWait(); projectManagedStartupEnd(); return
                    }
                    managedSyntheticSession.markFeedReady()
                    operationMessage = "\(managedSessionKind) local session; history, energy estimates and alerts are disabled"
                    return
                }
                try await startupSleep(.milliseconds(50))
            }
            operationMessage = "\(managedSessionKind) feed unavailable; stopping the owned session"
            _ = await stopManagedSession()
            readState = .failed
        } catch {
            readState = .failed
            operationMessage = "\(managedSessionKind) session unavailable or ownership unresolved; automatic restart is disabled"
        }
    }

    private func projectManagedStartupEnd() {
        acquisitionSucceeded = false
        readState = [.failed, .unresolved].contains(managedSyntheticSession.state) ? .failed : .stopped
        operationMessage = managedSessionMessage
    }

    @discardableResult
    func stopManagedSyntheticSession() async -> Bool { await stopManagedSession() }

    @discardableResult
    func stopManagedSession() async -> Bool {
        guard isManagedMode else { return true }
        let didLaunch = managedSyntheticSession.launchInvoked
        operationMessage = didLaunch ? "Stopping \(managedSessionKind.lowercased()) session; waiting for cleanup receipt and supervisor exit"
            : "No \(managedSessionKind.lowercased()) session was started"
        let resolved = await managedSyntheticSession.stopAndWait()
        await coordinator?.stopAndWait()
        stateTask?.cancel(); stateTask = nil
        acquisitionSucceeded = false
        let operationalCaptureFailed = isManagedOperationalMode && managedSyntheticSession.state == .failed
        readState = resolved && !operationalCaptureFailed ? .stopped : .failed
        operationMessage = !didLaunch ? "\(managedSessionKind) session not started; existing session records are retained"
            : operationalCaptureFailed ? "Operational capture failed; ownership cleanup resolved; hardware remains unqualified"
            : resolved ? "\(managedSessionKind) session stopped; hardware remains unqualified"
            : "Ownership unresolved; session retained and Quit cancelled. No automatic restart."
        await updateWidget(acquisition: .stopped)
        return resolved
    }

    func prepareToQuit() async -> Bool {
        if isManagedMode, !(await stopManagedSession()) { return false }
        await stop()
        return true
    }

    private func startSessionDirectory(_ directory: URL, synthetic: Bool) async {
        if !synthetic {
            backend = .supervisedSession
            configureWidgetSharing()
        }
        do {
            let baseRead = try await supervisedSessionReadFactory(directory)
            guard !stopped else { return }
            let label = synthetic ? "Simulated UPS · Trial" : "Smart-UPS C 1500 · Trial"
            let read: MonitorCoordinator.ReadWithPresentation = {
                try await baseRead().map { MonitorReading(snapshot: $0.snapshot, presentationName: label) }
            }
            try await replaceBackend(.supervisedSession, readWithPresentation: read)
            if synthetic {
                operationMessage = "Synthetic local session; history, energy estimates and alerts are disabled"
            }
        } catch {
            guard !stopped else { return }
            readState = .failed
            operationMessage = synthetic ? "Synthetic session unavailable" : "Supervised session unavailable"
            if !synthetic {
                sources = []
                presentationNamesBySourceKey = [:]
                selectedSourceKey = nil
                history = nil
                acquisitionSucceeded = false
                recordsHistory = false
                resetEnergyState()
                energyEstimates = []
                widgetAcquisition = .readFailed
                await alerts.suspend()
                await updateWidget(acquisition: .readFailed)
            }
        }
    }

    func chooseSupervisedSessionDirectory() {
        guard !isSyntheticMode, !isManagedMode, !stopped, !backendTransition else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose an already-running supervised session"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        supervisedSessionDirectoryURL = url
        supervisedSessionMessage = nil
        showsSupervisedSessionPicker = true
    }

    func connectSupervisedSession() async {
        guard !isSyntheticMode, !isManagedMode, !stopped, !backendTransition else { return }
        guard let directory = supervisedSessionDirectoryURL else {
            supervisedSessionMessage = "Choose a session directory"
            return
        }
        backendTransition = true
        defer { backendTransition = false }
        supervisedSessionMessage = nil
        do {
            let read = try await supervisedSessionReadFactory(directory)
            guard !stopped else { return }
            try await replaceBackend(.supervisedSession, readWithPresentation: read)
            guard !stopped else { return }
            showsSupervisedSessionPicker = false
        } catch {
            guard !stopped else { return }
            supervisedSessionMessage = "Supervised session unavailable"
        }
    }

    func select(_ key: String) {
        guard !isSyntheticMode, !stopped,
              sources.contains(where: { UPSMonitorFormatters.sourceKey(for: $0) == key }) else { return }
        let changesSelection = selectedSourceKey != key
        selectedSourceKey = key
        if changesSelection { resetEnergyState() }
        if changesSelection {
            alertSelectionGeneration &+= 1
            alertSelectionTransition = true
        }
        let generation = alertSelectionGeneration
        lastHistoryCapture = nil
        history = nil
        Task {
            guard !stopped else { return }
            if changesSelection {
                await alerts.suspend()
                guard !stopped, generation == alertSelectionGeneration else { return }
                alertSelectionTransition = false
            }
            await updateHistory()
            if let widgetAcquisition { await updateWidget(acquisition: widgetAcquisition) }
        }
    }

    func setAlertsEnabled(_ enabled: Bool) async {
        guard !isSyntheticMode, !isSupervisedSession, !stopped else { return }
        await alerts.setEnabled(enabled)
    }

    func setAlertPolicy(_ policy: UPSAlertPolicy) {
        guard !isSyntheticMode, !isSupervisedSession, !stopped else { return }
        alerts.setPolicy(policy)
    }

    func stop() async {
        guard !stopped else { return }
        if isManagedMode, !(await stopManagedSession()) { return }
        stopped = true
        pauseEnergy()
        backendGeneration &+= 1
        stateTask?.cancel()
        stateTask = nil
        acquisitionSucceeded = false
        let operationalCaptureFailed = isManagedOperationalMode && managedSyntheticSession.state == .failed
        readState = operationalCaptureFailed ? .failed : .stopped
        recordsHistory = false
        historyQueryGeneration += 1
        historyBrowser?.close()
        historyBrowser = nil
        if wakeObserver != nil || sleepObserver != nil {
            let center = NSWorkspace.shared.notificationCenter
            if let wakeObserver { center.removeObserver(wakeObserver) }
            if let sleepObserver { center.removeObserver(sleepObserver) }
        }
        wakeObserver = nil
        sleepObserver = nil
        await coordinator?.stopAndWait()
        await alerts.stop()
        await alertObservationTask?.value
        alertObservationTask = nil
        await updateWidget(acquisition: .stopped, allowStopped: true)
        if let historyStore { try? await historyStore.close() }
        historyStore = nil
    }

    func setHistoryRecording(_ enabled: Bool) async {
        guard !isSyntheticMode, !isSupervisedSession, !stopped, !historyTransition else { return }
        historyTransition = true
        defer { historyTransition = false }
        if !enabled {
            recordsHistory = false
            return
        }
        do {
            _ = try openHistoryStore()
            recordsHistory = true
            operationMessage = nil
        } catch {
            recordsHistory = false
            operationMessage = "History storage unavailable"
        }
    }

    func openHistoryBrowser() async {
        guard !isSyntheticMode, !isSupervisedSession, !stopped else { return }
        do {
            let store = try openHistoryStore()
            historyBrowser?.close()
            let browser = HistoryBrowserModel(store: store, onMutation: { [weak self] in
                guard let self, !self.stopped else { return }
                self.historyQueryGeneration += 1
                self.history = nil
                self.lastHistoryCapture = nil
                await self.updateHistory(force: true)
            })
            historyBrowser = browser
            await browser.refresh()
        } catch {
            guard !stopped else { return }
            operationMessage = "History storage unavailable"
        }
    }

    private func openHistoryStore() throws -> UPSHistoryStore {
        if let historyStore { return historyStore }
        let directory: URL
        if let historyDirectoryURL {
            directory = historyDirectoryURL
        } else {
            let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                   appropriateFor: nil, create: true)
            directory = base.appendingPathComponent("UPSMonitorMac", isDirectory: true)
        }
        let store = try UPSHistoryStore(directoryURL: directory)
        historyStore = store
        return store
    }

    func clearHistory() async {
        guard let historyStore, !isSyntheticMode, !isSupervisedSession, !stopped else { return }
        do {
            _ = try await historyStore.clear()
            guard !stopped else { return }
            historyQueryGeneration += 1
            history = []
            lastHistoryCapture = nil
            operationMessage = nil
            await historyBrowser?.refresh()
        } catch {
            guard !stopped else { return }
            operationMessage = "History could not be cleared"
        }
    }

    func export(_ format: HistoryExportFormat) {
        guard let historyStore, let selected, !isSyntheticMode, !isSupervisedSession, !stopped else { return }
        let capturedSource = selected.source
        let end = now
        Task {
            guard !stopped else { return }
            do {
                let query = try HistoryQuery(start: end.addingTimeInterval(-3_600), end: end, source: capturedSource)
                let data = try await historyStore.export(query, format: format)
                guard !stopped else { return }
                let panel = NSSavePanel()
                panel.allowedContentTypes = format == .json ? [.json] : [.commaSeparatedText]
                panel.nameFieldStringValue = format == .json ? "ups-history.json" : "ups-history.csv"
                panel.title = "Export Current Source: Past Hour"
                guard panel.runModal() == .OK, !stopped, let url = panel.url else { return }
                try data.write(to: url, options: [.atomic])
                guard !stopped else { return }
                operationMessage = nil
            } catch {
                guard !stopped else { return }
                operationMessage = "History export unavailable"
            }
        }
    }

    private func persist(_ snapshot: MonitorSnapshot, now: Date, generation: UInt64) async throws {
        guard !stopped, !isSupervisedSession, generation == backendGeneration, recordsHistory, let historyStore else { return }
        try await historyStore.append(snapshot, now: now)
        guard !stopped, generation == backendGeneration else { return }
        if operationMessage == "History storage unavailable" { operationMessage = nil }
        let snapshotKey = UPSMonitorFormatters.sourceKey(for: snapshot)
        guard selectedSourceKey == snapshotKey else { return }
        await updateHistory(force: true)
    }

    private func updateState() async {
        guard !stopped, let coordinator else { return }
        let generation = backendGeneration
        let state = await coordinator.currentState()
        guard !stopped, generation == backendGeneration else { return }
        now = clock()
        sources = state.sources.map(\.snapshot)
        presentationNamesBySourceKey = Dictionary(uniqueKeysWithValues: state.sources.compactMap { source in
            source.presentationName.map { (UPSMonitorFormatters.sourceKey(for: source.snapshot), $0) }
        })
        maximumAge = state.maximumAge
        if !sources.contains(where: { UPSMonitorFormatters.sourceKey(for: $0) == selectedSourceKey }) {
            selectedSourceKey = sources.first.map(UPSMonitorFormatters.sourceKey(for:))
            history = nil
            lastHistoryCapture = nil
        }
        switch state.acquisition {
        case .idle, .refreshing: readState = .loading
        case .succeeded: readState = .ready; widgetAcquisition = .active
        case .noSources: readState = .noSources; widgetAcquisition = .noSources
        case .failed: readState = .failed; widgetAcquisition = .readFailed
        case .stopped: readState = .stopped; widgetAcquisition = .stopped
        }
        let selectedState = state.sources.first { UPSMonitorFormatters.sourceKey(for: $0.snapshot) == selectedSourceKey }
        acquisitionSucceeded = selectedState?.freshness == .fresh
        updateEnergy(receivedUptime: state.lastSuccessUptime)
        if state.storageFailure {
            operationMessage = "History storage unavailable"
        }
        updateAlerts()
        if let widgetAcquisition { await updateWidget(acquisition: widgetAcquisition) }
        await updateHistory()
    }

    private func updateAlerts() {
        guard !isSyntheticMode, !isSupervisedSession, !stopped, !sleeping, !alertSelectionTransition,
              alerts.isEnabled, !alerts.isBusy, alertObservationTask == nil else { return }
        let snapshot = selected
        let succeeded = acquisitionSucceeded
        let date = now
        let uptime = ProcessInfo.processInfo.systemUptime
        let age = maximumAge
        let generation = backendGeneration
        let selectionGeneration = alertSelectionGeneration
        // OS notification delivery must not hold up the live freshness clock.
        alertObservationTask = Task { [weak self] in
            guard let self else { return }
            defer { self.alertObservationTask = nil }
            guard !self.stopped, !self.sleeping, generation == self.backendGeneration,
                  selectionGeneration == self.alertSelectionGeneration else { return }
            await self.alerts.observe(snapshot: snapshot, acquisitionSucceeded: succeeded,
                                     now: date, uptime: uptime, maximumAge: age)
        }
    }

    private func updateEnergy(receivedUptime: TimeInterval?) {
        guard !isSyntheticMode, !isSupervisedSession, !stopped, !sleeping else {
            if isSupervisedSession {
                energyTracker.reset()
                energyEstimates = []
            }
            return
        }
        if let boundary = energyResetBoundary, let selected {
            if selected.source == boundary.source && selected.capturedAt <= boundary.capturedAt { return }
            energyResetBoundary = nil
        }
        energyTracker.observe(snapshot: selected, acquisitionSucceeded: acquisitionSucceeded,
                              now: now, monotonicSeconds: receivedUptime ?? .nan)
        energyEstimates = energyTracker.summaries
    }

    private func pauseEnergy() {
        energyTracker.pause()
        energyEstimates = isSupervisedSession ? [] : energyTracker.summaries
    }

    private func resetEnergyState() {
        energyTracker.reset()
        energyResetBoundary = nil
        energyEstimates = energyTracker.summaries
    }

    func resetEnergy() {
        guard !isSyntheticMode, !isSupervisedSession, !stopped else { return }
        resetEnergyState()
        energyResetBoundary = selected.map { ($0.source, $0.capturedAt) }
    }

    func energyExportData() throws -> Data {
        guard canExportEnergy else { throw HistoryError.invalidRequest }
        let generatedAt = clock()
        guard generatedAt.timeIntervalSince1970.isFinite else { throw MonitorValidationError.invalidDate }
        let payload = EnergyExport(generatedAt: generatedAt, estimates: energyEstimates)
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(payload)
    }

    func exportEnergy() {
        guard canExportEnergy else { return }
        do {
            let data = try energyExportData()
            let panel = NSSavePanel()
            panel.allowedContentTypes = [.json]
            panel.nameFieldStringValue = "ups-session-energy-estimates.json"
            panel.title = "Export Session Energy Estimates"
            guard panel.runModal() == .OK, !stopped, let url = panel.url else { return }
            try data.write(to: url, options: .atomic)
        } catch { if !stopped { operationMessage = "Energy export unavailable" } }
    }

    private func configureWidgetSharing() {
        guard widgetPublisher == nil else { return }
        do {
            let directory: URL
            let reload: @Sendable () async -> Void
            if let widgetSharingBootstrap {
                directory = try widgetSharingBootstrap.directoryURL()
                reload = widgetSharingBootstrap.reload
            } else {
                directory = try WidgetGroupConfiguration.directoryURL(bundle: .main, fixtureMode: widgetFixtureMode)
                let widgetKind = WidgetGroupConfiguration.widgetKind(for: widgetFixtureMode)
                reload = {
                    await MainActor.run { WidgetCenter.shared.reloadTimelines(ofKind: widgetKind) }
                }
            }
            let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
            widgetPublisher = WidgetSnapshotPublisher(store: store, reload: reload)
        } catch WidgetGroupError.notConfigured {
            widgetMessage = "Widget sharing not configured"
        } catch {
            widgetMessage = "Widget sharing unavailable"
        }
    }

    private func updateWidget(acquisition: WidgetAcquisition, allowStopped: Bool = false) async {
        guard (!isSyntheticMode || isWidgetFixture || (isSyntheticSessionMode && widgetPublisher != nil)),
              (!stopped || allowStopped), let widgetPublisher else { return }
        let date = clock()
        widgetSequence &+= 1
        let value = WidgetSnapshot(publishedAt: date, acquisition: acquisition, maximumAge: maximumAge,
                                   snapshot: acquisition == .noSources ? nil : selected,
                                   presentationName: acquisition == .noSources ? nil : selected.flatMap {
                                       presentationNamesBySourceKey[UPSMonitorFormatters.sourceKey(for: $0)]
                                   })
        let result = await widgetPublisher.publish(value, now: date,
                                                   uptime: ProcessInfo.processInfo.systemUptime, sequence: widgetSequence)
        guard !stopped || allowStopped else { return }
        switch result {
        case .shared, .unchanged: widgetMessage = nil
        case .rejected, .unavailable: widgetMessage = "Widget sharing unavailable"
        }
    }

    private func updateHistory(force: Bool = false) async {
        guard !isSupervisedSession, !stopped, let historyStore, let selected,
              force || selected.capturedAt != lastHistoryCapture else { return }
        let key = UPSMonitorFormatters.sourceKey(for: selected)
        historyQueryGeneration += 1
        let generation = historyQueryGeneration
        do {
            let query = try HistoryQuery(start: now.addingTimeInterval(-3_600), end: now, source: selected.source)
            let records = try await historyStore.query(query)
            guard !stopped, selectedSourceKey == key, generation == historyQueryGeneration else { return }
            history = records
            lastHistoryCapture = selected.capturedAt
            if operationMessage == "History unavailable" { operationMessage = nil }
        } catch {
            guard !stopped, selectedSourceKey == key, generation == historyQueryGeneration else { return }
            operationMessage = "History unavailable"
        }
    }

    private func installWorkspaceObservers() {
        let center = NSWorkspace.shared.notificationCenter
        sleepObserver = center.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self, !self.stopped else { return }
                self.sleeping = true
                self.pauseEnergy()
                await self.alerts.suspend()
                await self.coordinator?.stopAndWait()
                await self.updateState()
            }
        }
        wakeObserver = center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self, !self.stopped else { return }
                self.sleeping = false
                let generation = self.backendGeneration
                if self.backend == .apple { await self.reader.resetIdentity() }
                guard !self.stopped, !self.backendTransition, generation == self.backendGeneration else { return }
                await self.coordinator?.start()
                if self.stopped { await self.coordinator?.stop() }
            }
        }
    }

    func chooseNUTExecutable() {
        guard !isSyntheticMode, !isManagedMode, !stopped, !backendTransition else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose Completion-Qualified UPSC Client"
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        connectionDraft.executablePath = url.path
        connectionDraft.expectedSHA256 = ""
        connectionDraft.completionQualified = false
        connectionMessage = nil
    }

    func connectNUT() async {
        guard !isSyntheticMode, !isManagedMode, !stopped, !backendTransition else { return }
        guard connectionDraft.canConnect else {
            connectionMessage = "Client qualification and valid settings required"
            return
        }
        backendTransition = true
        defer { backendTransition = false }
        connectionMessage = nil
        do {
            let read = try await nutReadFactory(connectionDraft)
            guard !stopped else { return }
            try await replaceBackend(.nut, readWithPresentation: Self.withoutPresentation(read))
            guard !stopped else { return }
            showsNUTSettings = false
        } catch {
            guard !stopped else { return }
            connectionMessage = "Client validation failed"
        }
    }

    func useAppleBackend() async {
        guard !isSyntheticMode, !isManagedMode, !stopped, !backendTransition, backend != .apple else { return }
        backendTransition = true
        defer { backendTransition = false }
        do {
            await reader.resetIdentity()
            guard !stopped else { return }
            try await replaceBackend(.apple, readWithPresentation: appleRead())
            connectionMessage = nil
        } catch {
            connectionMessage = "Monitoring unavailable"
        }
    }

    nonisolated static func makeNUTRead(_ draft: NUTConnectionDraft) async throws -> MonitorCoordinator.Read {
        guard draft.canConnect, let port = Int(draft.port) else { throw MonitorAdapterError.invalidSource }
        let configuration = try UPSCClientConfiguration(
            executableURL: URL(fileURLWithPath: draft.executablePath), executableQualification: .completionHardened,
            upsName: draft.upsName, sourceID: "nut-" + UUID().uuidString.lowercased(), port: port)
        let reader = try NUTSnapshotReader(configuration: configuration, expectedSHA256: draft.expectedSHA256)
        try await reader.validateExecutable()
        return { try await reader.read() }
    }

    nonisolated static func makeSupervisedSessionRead(_ directoryURL: URL) async throws -> MonitorCoordinator.ReadWithPresentation {
        let reader = try await NUTContinuousSampleReader.connect(directoryURL: directoryURL)
        return {
            try await reader.read().map {
                MonitorReading(snapshot: $0, presentationName: "Smart-UPS C 1500 · Trial")
            }
        }
    }

    nonisolated static func makeOperationalSessionRead(_ directoryURL: URL) async throws -> MonitorCoordinator.ReadWithPresentation {
        let reader = try await NUTOperationalSampleReader.connect(directoryURL: directoryURL)
        return {
            try await reader.read().map {
                MonitorReading(snapshot: $0, presentationName: "Smart-UPS C 1500 · Operational · Unqualified · macOS 27+ arm64")
            }
        }
    }

    nonisolated private static func withoutPresentation(_ read: @escaping MonitorCoordinator.Read) -> MonitorCoordinator.ReadWithPresentation {
        { try await read().map { MonitorReading(snapshot: $0) } }
    }

    private func appleRead() -> MonitorCoordinator.ReadWithPresentation {
        let reader = self.reader
        if let injectedReadWithPresentation { return injectedReadWithPresentation }
        if let injectedRead { return Self.withoutPresentation(injectedRead) }
        return {
            let observation = await reader.snapshot()
            return try AppleSnapshotRuntimeAdapter.readings(from: observation)
        }
    }

    private func widgetFixtureRead() -> MonitorCoordinator.Read {
        let clock = self.clock
        return { [clock] in [Self.makeWidgetFixture(at: clock())] }
    }

    nonisolated private static func makeWidgetFixture(at date: Date) -> MonitorSnapshot {
        let source = MonitorSource(provider: .nut, id: "synthetic-widget-fixture",
                                  sessionID: "synthetic-widget-session", identityStability: .configured)
        let metrics = [
            MonitorMetric(id: .batteryCharge, value: 74, unit: .percent,
                          quality: .available, provenance: .reported),
            MonitorMetric(id: .batteryRuntime, value: 2_100, unit: .seconds,
                          quality: .available, provenance: .estimated),
            MonitorMetric(id: .upsRealPower, value: 180, unit: .watts,
                          quality: .available, provenance: .driverDerived),
            MonitorMetric(id: .upsApparentPower, value: 215, unit: .voltAmps,
                          quality: .available, provenance: .driverDerived),
        ]
        return MonitorSnapshot(source: source, capturedAt: date,
                               status: MonitorStatus(lineState: .onLine, quality: .available), metrics: metrics)
    }

    private func makeCoordinator(readWithPresentation read: @escaping MonitorCoordinator.ReadWithPresentation, generation: UInt64) throws -> MonitorCoordinator {
        try MonitorCoordinator(readWithPresentation: read, clock: clock, monotonicClock: monotonicClock, sink: { [weak self] snapshot, date in
            guard let self else { return }
            try await self.persist(snapshot, now: date, generation: generation)
        })
    }

    private func replaceBackend(_ backend: MonitorBackend, readWithPresentation read: @escaping MonitorCoordinator.ReadWithPresentation) async throws {
        let nextGeneration = backendGeneration &+ 1
        let replacement = try makeCoordinator(readWithPresentation: read, generation: nextGeneration)
        backendGeneration = nextGeneration
        stateTask?.cancel()
        stateTask = nil
        historyQueryGeneration += 1
        history = nil
        lastHistoryCapture = nil
        sources = []
        presentationNamesBySourceKey = [:]
        resetEnergyState()
        selectedSourceKey = nil
        acquisitionSucceeded = false
        readState = .loading
        widgetAcquisition = nil
        await alerts.suspend()
        if backend == .supervisedSession {
            recordsHistory = false
            historyBrowser?.close()
            historyBrowser = nil
            resetEnergyState()
            energyEstimates = []
            operationMessage = "Supervised session is unqualified; history, energy estimates and alerts are disabled"
        } else {
            operationMessage = nil
        }
        await updateWidget(acquisition: .stopped)
        await coordinator?.stopAndWait()
        guard !stopped else { return }
        coordinator = replacement
        self.backend = backend
        if !sleeping { await replacement.start() }
        guard !stopped else { await replacement.stopAndWait(); return }
        startStateUpdates()
    }

    private func startStateUpdates() {
        stateTask?.cancel()
        let generation = backendGeneration
        stateTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, generation == self.backendGeneration else { return }
                if self.isManagedMode,
                   [.completed, .stopped, .failed, .unresolved].contains(self.managedSyntheticSession.state) {
                    await self.coordinator?.stopAndWait()
                    self.acquisitionSucceeded = false
                    self.readState = self.managedSyntheticSession.state == .unresolved
                        || (self.isManagedOperationalMode && self.managedSyntheticSession.state == .failed) ? .failed : .stopped
                    self.operationMessage = self.managedSessionMessage
                    await self.updateWidget(acquisition: .stopped)
                    return
                }
                await self.updateState()
                do { try await Task.sleep(for: .seconds(1)) } catch { return }
            }
        }
    }

    private func applyPreview() {
        let date = clock()
        let source = MonitorSource(provider: .nut, id: "synthetic-ups", sessionID: "synthetic-session", identityStability: .configured)
        let metrics = [
            MonitorMetric(id: .batteryCharge, value: 82, unit: .percent, quality: .available, provenance: .reported),
            MonitorMetric(id: .batteryRuntime, value: 1_980, unit: .seconds, quality: .available, provenance: .estimated),
            MonitorMetric(id: .inputVoltage, value: 230.4, unit: .volts, quality: .available, provenance: .reported),
            MonitorMetric(id: .outputVoltage, value: 229.8, unit: .volts, quality: .available, provenance: .reported),
            MonitorMetric(id: .upsRealPower, value: 184.5, unit: .watts, quality: .available, provenance: .driverDerived),
            MonitorMetric(id: .upsApparentPower, value: 212.7, unit: .voltAmps, quality: .available, provenance: .driverDerived),
            MonitorMetric(id: .upsLoad, value: 19, unit: .percent, quality: .available, provenance: .reported),
        ]
        let snapshot = MonitorSnapshot(source: source, capturedAt: date, status: MonitorStatus(lineState: .onLine, quality: .available), metrics: metrics)
        let firstEnergy = MonitorSnapshot(source: source, capturedAt: date.addingTimeInterval(-5),
                                          status: snapshot.status, metrics: metrics)
        energyTracker.observe(snapshot: firstEnergy, acquisitionSucceeded: true,
                              now: firstEnergy.capturedAt, monotonicSeconds: 0)
        energyTracker.observe(snapshot: snapshot, acquisitionSucceeded: true, now: date, monotonicSeconds: 5)
        energyEstimates = energyTracker.summaries
        sources = [snapshot]
        selectedSourceKey = UPSMonitorFormatters.sourceKey(for: snapshot)
        now = date
        readState = .ready
        acquisitionSucceeded = true
        history = (0..<12).map { index in
            MonitorSnapshot(source: source, capturedAt: date.addingTimeInterval(Double(index - 11) * 300),
                            status: snapshot.status,
                            metrics: [MonitorMetric(id: .batteryCharge, value: Double(71 + index), unit: .percent,
                                                   quality: .available, provenance: .reported)])
        }
    }
}

private struct EnergyExport: Encodable {
    let schemaVersion = 1
    let quality = "applicationEstimated"
    let generatedAt: Date
    let estimates: [MonitorEnergyEstimate]
}
