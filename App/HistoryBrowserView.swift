import SwiftUI
import UPSHistory
import UPSModel
import UPSMonitorUI

struct HistoryBrowserView: View {
    @Bindable var model: HistoryBrowserModel
    @Environment(\.dismiss) private var dismiss
    @State private var deleteSession = false
    @State private var clearAll = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Stored History").font(.title2.weight(.semibold))
                Spacer()
                Button { Task { await model.refresh() } } label: { Image(systemName: "arrow.clockwise") }
                    .help("Refresh stored sessions").accessibilityLabel("Refresh stored sessions")
                    .disabled(model.isLoading)
                Button("Done") { model.close(); dismiss() }.keyboardShortcut(.cancelAction)
            }
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            }
            if !model.sessions.isEmpty {
                Picker("Session", selection: Binding(get: { model.selectedKey ?? "" },
                                                      set: { key in Task { await model.selectSession(key) } })) {
                    ForEach(Array(model.sessions.enumerated()), id: \.offset) { index, session in
                        Text(sessionLabel(session, index: index)).tag(HistoryBrowserModel.key(session.source))
                    }
                }
                .disabled(model.isLoading)
                if model.sessionsTruncated {
                    Text("Showing the 100 most recent sessions").font(.caption).foregroundStyle(.secondary)
                }
                HStack(spacing: 16) {
                    Picker("Range", selection: Binding(get: { model.range },
                                                       set: { value in Task { await model.selectRange(value) } })) {
                        ForEach(HistoryBrowserRange.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 260)
                    .disabled(model.isLoading)
                    Picker("Metric", selection: $model.metric) {
                        ForEach(MonitorMetricID.allCases, id: \.self) {
                            Text(UPSMonitorFormatters.metricName($0)).tag($0)
                        }
                    }
                }
            }
            Group {
                if model.isLoading {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 260)
                } else if let session = model.selectedSession, let page = model.page {
                    UPSHistoryChart(snapshots: page.records, source: session.source, metric: model.metric)
                    HStack {
                        Text("Page \(model.pageNumber) · \(page.records.count) samples")
                        if page.hasMore { Text("More samples available").foregroundStyle(.secondary) }
                        Spacer()
                        Button { Task { await model.previousPage() } } label: { Image(systemName: "chevron.left") }
                            .help("Previous page").accessibilityLabel("Previous history page").disabled(!model.canGoBack)
                        Button { Task { await model.nextPage() } } label: { Image(systemName: "chevron.right") }
                            .help("Next page").accessibilityLabel("Next history page").disabled(!model.canGoForward)
                    }
                    .font(.callout)
                    if let first = page.records.first, let last = page.records.last {
                        Text("\(first.capturedAt.formatted(date: .abbreviated, time: .standard)) – \(last.capturedAt.formatted(date: .abbreviated, time: .standard))")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else {
                    ContentUnavailableView(model.errorMessage == nil ? "No stored samples" : "History unavailable",
                                           systemImage: model.errorMessage == nil ? "clock" : "exclamationmark.triangle")
                        .frame(maxWidth: .infinity, minHeight: 260)
                }
            }
            Divider()
            HStack {
                Menu {
                    Button("JSON", systemImage: "curlybraces") { model.export(.json) }
                    Button("CSV", systemImage: "tablecells") { model.export(.csv) }
                } label: { Label("Export Page", systemImage: "square.and.arrow.up") }
                .disabled(!model.canExport)
                Spacer()
                Button("Delete Session", systemImage: "trash", role: .destructive) { deleteSession = true }
                    .disabled(model.isLoading || model.selectedSession == nil)
                Button("Clear All", systemImage: "trash.slash", role: .destructive) { clearAll = true }
                    .disabled(model.isLoading || model.sessions.isEmpty)
            }
        }
        .padding(20)
        .frame(minWidth: 720, idealWidth: 820, minHeight: 540)
        .confirmationDialog("Delete the selected stored session?", isPresented: $deleteSession, titleVisibility: .visible) {
            Button("Delete Session", role: .destructive) { Task { await model.deleteSelectedSession() } }
        }
        .confirmationDialog("Clear all stored history?", isPresented: $clearAll, titleVisibility: .visible) {
            Button("Clear All History", role: .destructive) { Task { await model.clearAllHistory() } }
        }
        .onDisappear { model.close() }
    }

    private func sessionLabel(_ session: HistorySessionSummary, index: Int) -> String {
        let provider = session.source.provider == .apple ? "Apple" : "NUT"
        return "Session \(index + 1) · \(provider) · \(session.lastCapturedAt.formatted(date: .abbreviated, time: .shortened))"
    }
}
