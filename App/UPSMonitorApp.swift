import AppKit
import SwiftUI
import UPSMonitorUI

@main
struct UPSMonitorApp: App {
    @State private var model = MonitorAppModel()
    @NSApplicationDelegateAdaptor(MonitorApplicationDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("UPS Monitor", id: "details") {
            MonitorWindow(model: model)
                .task { appDelegate.model = model; await model.startIfNeeded() }
                .frame(minWidth: 640, minHeight: 520)
        }
        .defaultSize(width: 900, height: 740)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }

        MenuBarExtra {
            MonitorMenu(model: model)
                .task { await model.startIfNeeded() }
        } label: {
            Label(model.menuTitle, systemImage: "bolt.horizontal.circle")
                .task { appDelegate.model = model; await model.startIfNeeded() }
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
private final class MonitorApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var model: MonitorAppModel?
    private var terminating = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model else { return .terminateNow }
        guard !terminating else { return .terminateLater }
        terminating = true
        Task {
            await model.stop()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

private struct MonitorMenu: View {
    @Bindable var model: MonitorAppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(spacing: 0) {
            if model.isPreview { Text("Synthetic preview").font(.caption).foregroundStyle(.orange).padding(.top, 10) }
            UPSMenuContentView(
                sources: model.sources, selectedSourceKey: model.selectedSourceKey,
                readState: model.readState, now: model.now, maximumAge: model.maximumAge,
                acquisitionSucceeded: model.acquisitionSucceeded,
                onSelect: { model.select($0) }, onRefresh: { model.refresh() },
                onOpenDetails: {
                    openWindow(id: "details")
                    NSApplication.shared.activate(ignoringOtherApps: true)
                }
            )
            Divider()
            Button("Quit UPS Monitor", systemImage: "power") {
                NSApplication.shared.terminate(nil)
            }
            .buttonStyle(.plain)
            .padding(12)
        }
    }
}

private struct MonitorWindow: View {
    @Bindable var model: MonitorAppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                if model.isPreview {
                    Label("Synthetic preview", systemImage: "bolt.horizontal.circle")
                } else {
                    Picker("Backend", selection: Binding(
                        get: { model.backend },
                        set: { backend in
                            if backend == .nut { model.showsNUTSettings = true }
                            else { Task { await model.useAppleBackend() } }
                        }
                    )) {
                        Text("Apple").tag(MonitorBackend.apple)
                        Text("Local NUT").tag(MonitorBackend.nut)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 220)
                    .disabled(model.backendTransition)
                    Button {
                        model.showsNUTSettings = true
                    } label: { Image(systemName: "gearshape") }
                    .help("Local NUT settings")
                    .accessibilityLabel("Local NUT settings")
                    .disabled(model.backendTransition)
                    if model.backendTransition { ProgressView().controlSize(.small) }
                }
                Spacer(minLength: 8)
                Button { model.showsAlertSettings = true } label: {
                    Image(systemName: model.alerts.isEnabled ? "bell.badge" : "bell")
                }
                .help("Local alert settings")
                .accessibilityLabel("Local alert settings")
                .disabled(model.isPreview)
                Button { Task { await model.openHistoryBrowser() } } label: { Image(systemName: "clock") }
                    .help("Browse stored history")
                    .accessibilityLabel("Browse stored history")
                    .disabled(model.isPreview)
                Toggle("Record history", isOn: Binding(
                    get: { model.recordsHistory },
                    set: { enabled in Task { await model.setHistoryRecording(enabled) } }
                ))
                .toggleStyle(.switch)
                .disabled(model.isPreview || model.historyTransition)
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
            Divider()

            if let message = model.widgetMessage {
                Label(message, systemImage: "square.grid.2x2")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 6)
            }

            if let message = model.operationMessage {
                Label(message, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
                    .font(.callout)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 8)
            }

            if let message = model.alerts.message {
                Label(message, systemImage: "bell.slash")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 18).padding(.vertical, 6)
            }

            UPSDetailsView(
                sources: model.sources, selectedSourceKey: model.selectedSourceKey,
                readState: model.readState, now: model.now, maximumAge: model.maximumAge,
                acquisitionSucceeded: model.acquisitionSucceeded,
                history: model.history,
                energyEstimates: model.energyEstimates,
                onResetEnergy: !model.isPreview ? { @MainActor @Sendable [model] in model.resetEnergy() } : nil,
                onExportEnergy: model.canExportEnergy ? { @MainActor @Sendable [model] in model.exportEnergy() } : nil,
                onSelect: { model.select($0) }, onRefresh: { model.refresh() },
                onExportJSON: model.canExport ? { @MainActor @Sendable [model] in model.export(.json) } : nil,
                onExportCSV: model.canExport ? { @MainActor @Sendable [model] in model.export(.csv) } : nil,
                onClearHistory: model.canExport ? { @MainActor @Sendable [model] in Task { await model.clearHistory() } } : nil
            )
        }
        .sheet(isPresented: $model.showsNUTSettings) {
            NUTConnectionView(draft: $model.connectionDraft,
                              isConnecting: model.backendTransition,
                              errorMessage: model.connectionMessage,
                              onChooseExecutable: { model.chooseNUTExecutable() },
                              onConnect: { Task { await model.connectNUT() } },
                              onCancel: { model.showsNUTSettings = false })
                .interactiveDismissDisabled(model.backendTransition)
        }
        .sheet(item: $model.historyBrowser) { browser in
            HistoryBrowserView(model: browser)
        }
        .sheet(isPresented: $model.showsAlertSettings) {
            UPSAlertSettingsView(model: model)
        }
    }
}
