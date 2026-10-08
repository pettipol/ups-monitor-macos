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
    case apple, nut

    var title: String { self == .apple ? "Apple power sources" : "Local NUT" }
}

@Observable
@MainActor
final class MonitorAppModel {
    var sources: [MonitorSnapshot] = []
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
    var connectionDraft = NUTConnectionDraft()
    var connectionMessage: String?
    var backendTransition = false
    var showsNUTSettings = false
    var showsAlertSettings = false
    let alerts: UPSAlertController
    var energyEstimates = MonitorEnergyTracker().summaries
    let isPreview: Bool

    @ObservationIgnored private var started = false
    @ObservationIgnored private var stopped = false
    @ObservationIgnored private let reader = AppleSessionReader()
    @ObservationIgnored private var coordinator: MonitorCoordinator?
    @ObservationIgnored private var historyStore: UPSHistoryStore?
    @ObservationIgnored private let injectedRead: MonitorCoordinator.Read?
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
    @ObservationIgnored private var widgetSequence: UInt64 = 0
    @ObservationIgnored private var widgetAcquisition: WidgetAcquisition?
    @ObservationIgnored private var backendGeneration: UInt64 = 0
    @ObservationIgnored private var sleeping = false
    @ObservationIgnored private var alertSelectionGeneration: UInt64 = 0
    @ObservationIgnored private var alertSelectionTransition = false
    @ObservationIgnored private var alertObservationTask: Task<Void, Never>?
    @ObservationIgnored private let nutReadFactory: @Sendable (NUTConnectionDraft) async throws -> MonitorCoordinator.Read

    init(
        read: MonitorCoordinator.Read? = nil,
        clock: @escaping MonitorCoordinator.Clock = { Date() },
        monotonicClock: @escaping MonitorCoordinator.MonotonicClock = { ProcessInfo.processInfo.systemUptime },
        historyDirectoryURL: URL? = nil,
        observesWorkspace: Bool = true,
        isPreview: Bool = ProcessInfo.processInfo.arguments.contains("--synthetic-preview"),
        widgetPublisher: WidgetSnapshotPublisher? = nil,
        alerts: UPSAlertController? = nil,
        nutReadFactory: @escaping @Sendable (NUTConnectionDraft) async throws -> MonitorCoordinator.Read = MonitorAppModel.makeNUTRead
    ) {
        self.injectedRead = read
        self.clock = clock
        self.monotonicClock = monotonicClock
        self.historyDirectoryURL = historyDirectoryURL
        self.observesWorkspace = observesWorkspace
        self.isPreview = isPreview
        self.now = clock()
        self.widgetPublisher = widgetPublisher
        self.alerts = alerts ?? UPSAlertController()
        self.nutReadFactory = nutReadFactory
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

    var canExport: Bool { !stopped && historyStore != nil && !(history?.isEmpty ?? true) && !isPreview }
    var canExportEnergy: Bool { !stopped && !isPreview && energyEstimates.contains { $0.energyWh != nil } }

    func startIfNeeded() async {
        guard !started, !stopped else { return }
        started = true
        if isPreview {
            applyPreview()
            return
        }
        configureWidgetSharing()
        do {
            coordinator = try makeCoordinator(read: appleRead(), generation: backendGeneration)
            if observesWorkspace { installWorkspaceObservers() }
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
        guard !isPreview, !stopped, !backendTransition, !sleeping else { return }
        let generation = backendGeneration
        Task {
            guard !stopped, generation == backendGeneration, !backendTransition, !sleeping else { return }
            await coordinator?.refresh()
            guard generation == backendGeneration else { return }
            await updateState()
        }
    }

    func select(_ key: String) {
        guard !stopped,
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
        guard !isPreview, !stopped else { return }
        await alerts.setEnabled(enabled)
    }

    func setAlertPolicy(_ policy: UPSAlertPolicy) {
        guard !isPreview, !stopped else { return }
        alerts.setPolicy(policy)
    }

    func stop() async {
        guard !stopped else { return }
        stopped = true
        pauseEnergy()
        backendGeneration &+= 1
        stateTask?.cancel()
        stateTask = nil
        acquisitionSucceeded = false
        readState = .stopped
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
        guard !isPreview, !stopped, !historyTransition else { return }
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
        guard !isPreview, !stopped else { return }
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
        guard let historyStore, !isPreview, !stopped else { return }
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
        guard let historyStore, let selected, !isPreview, !stopped else { return }
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
        guard !stopped, generation == backendGeneration, recordsHistory, let historyStore else { return }
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
        guard !isPreview, !stopped, !sleeping, !alertSelectionTransition,
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
        guard !isPreview, !stopped, !sleeping else { return }
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
        energyEstimates = energyTracker.summaries
    }

    private func resetEnergyState() {
        energyTracker.reset()
        energyResetBoundary = nil
        energyEstimates = energyTracker.summaries
    }

    func resetEnergy() {
        guard !isPreview, !stopped else { return }
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
            let directory = try WidgetGroupConfiguration.directoryURL()
            let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readWrite)
            widgetPublisher = WidgetSnapshotPublisher(store: store) {
                await MainActor.run {
                    WidgetCenter.shared.reloadTimelines(ofKind: WidgetGroupConfiguration.widgetKind)
                }
            }
        } catch WidgetGroupError.notConfigured {
            widgetMessage = "Widget sharing not configured"
        } catch {
            widgetMessage = "Widget sharing unavailable"
        }
    }

    private func updateWidget(acquisition: WidgetAcquisition, allowStopped: Bool = false) async {
        guard !isPreview, (!stopped || allowStopped), let widgetPublisher else { return }
        let date = clock()
        widgetSequence &+= 1
        let value = WidgetSnapshot(publishedAt: date, acquisition: acquisition, maximumAge: maximumAge,
                                   snapshot: acquisition == .noSources ? nil : selected)
        let result = await widgetPublisher.publish(value, now: date,
                                                   uptime: ProcessInfo.processInfo.systemUptime, sequence: widgetSequence)
        guard !stopped || allowStopped else { return }
        switch result {
        case .shared, .unchanged: widgetMessage = nil
        case .rejected, .unavailable: widgetMessage = "Widget sharing unavailable"
        }
    }

    private func updateHistory(force: Bool = false) async {
        guard !stopped, let historyStore, let selected,
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
        guard !isPreview, !stopped, !backendTransition else { return }
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
        guard !isPreview, !stopped, !backendTransition else { return }
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
            try await replaceBackend(.nut, read: read)
            guard !stopped else { return }
            showsNUTSettings = false
        } catch {
            guard !stopped else { return }
            connectionMessage = "Client validation failed"
        }
    }

    func useAppleBackend() async {
        guard !isPreview, !stopped, !backendTransition, backend != .apple else { return }
        backendTransition = true
        defer { backendTransition = false }
        do {
            await reader.resetIdentity()
            guard !stopped else { return }
            try await replaceBackend(.apple, read: appleRead())
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

    private func appleRead() -> MonitorCoordinator.Read {
        let reader = self.reader
        return injectedRead ?? {
            let observation = await reader.snapshot()
            return try AppleSnapshotRuntimeAdapter.snapshots(from: observation)
        }
    }

    private func makeCoordinator(read: @escaping MonitorCoordinator.Read, generation: UInt64) throws -> MonitorCoordinator {
        try MonitorCoordinator(read: read, clock: clock, monotonicClock: monotonicClock, sink: { [weak self] snapshot, date in
            guard let self else { return }
            try await self.persist(snapshot, now: date, generation: generation)
        })
    }

    private func replaceBackend(_ backend: MonitorBackend, read: @escaping MonitorCoordinator.Read) async throws {
        let nextGeneration = backendGeneration &+ 1
        let replacement = try makeCoordinator(read: read, generation: nextGeneration)
        backendGeneration = nextGeneration
        stateTask?.cancel()
        stateTask = nil
        historyQueryGeneration += 1
        history = nil
        lastHistoryCapture = nil
        sources = []
        resetEnergyState()
        selectedSourceKey = nil
        acquisitionSucceeded = false
        readState = .loading
        widgetAcquisition = nil
        await alerts.suspend()
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
