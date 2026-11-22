import AppKit
import SwiftUI
import UPSModel
import UPSMonitorUI
import UPSRuntime

struct ArchivedObservationView: View {
    @Bindable var model: ArchivedObservationModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text("Archived observation")
                    .font(.title2.weight(.semibold))
                Spacer()
                Button("Close") {
                    model.clear()
                    dismiss()
                }
                    .keyboardShortcut(.cancelAction)
            }
            .padding(18)
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 10) {
                        Image(systemName: "archivebox")
                        Text("Archived · Unqualified")
                            .font(.headline)
                        Spacer(minLength: 0)
                    }
                    .accessibilityElement(children: .combine)

                    HStack(spacing: 10) {
                        Button {
                            chooseDirectory()
                        } label: {
                            Label("Choose archive folder", systemImage: "folder")
                        }
                        .help("Choose an archived observation directory")
                        let folderName = model.sessionDirectoryURL?.lastPathComponent ?? "No folder selected"
                        Text(folderName)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel("Archive folder")
                            .accessibilityValue(Text(folderName))
                            .accessibilityIdentifier("archived-observation-folder")
                    }

                    Picker("Declared origin", selection: originBinding) {
                        Text("Choose origin").tag(NUTObservationOrigin?.none)
                        Text("Synthetic driver dump").tag(NUTObservationOrigin?.some(.syntheticDriverDump))
                        Text("Archived supervised driver dump").tag(NUTObservationOrigin?.some(.archivedSupervisedDriverDump))
                    }
                    .frame(maxWidth: 460, alignment: .leading)

                    VStack(alignment: .leading, spacing: 5) {
                        Text("Expected executable SHA-256")
                            .font(.callout.weight(.medium))
                        TextField("64 hexadecimal characters", text: $model.expectedExecutableSHA256)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.body, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: 620)
                    }

                    HStack(spacing: 12) {
                        Button {
                            model.importObservation()
                        } label: {
                            Label("Import", systemImage: "square.and.arrow.down")
                        }
                        .disabled(model.isLoading)
                        if model.isLoading { ProgressView().controlSize(.small) }
                        if let error = model.errorMessage {
                            Label(error, systemImage: "exclamationmark.triangle")
                                .foregroundStyle(.orange)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }

                    if let imported = model.imported {
                        Divider().padding(.vertical, 2)
                        observation(imported)
                    }
                }
                .padding(20)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .frame(minWidth: 560, idealWidth: 740, maxWidth: 920, minHeight: 500, idealHeight: 680, maxHeight: 900)
    }

    private var originBinding: Binding<NUTObservationOrigin?> {
        Binding(get: { model.origin }, set: { model.origin = $0 })
    }

    private func chooseDirectory() {
        let panel = NSOpenPanel()
        panel.title = "Choose archived observation folder"
        panel.prompt = "Choose"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        if panel.runModal() == .OK {
            model.sessionDirectoryURL = panel.url
        }
    }

    private func observation(_ imported: ImportedNUTObservation) -> some View {
        let snapshot = imported.unqualifiedSnapshot
        return VStack(alignment: .leading, spacing: 12) {
            Text("Archived · Unqualified")
                .font(.headline)
            Text("Caller-declared origin: \(originLabel(imported.origin))")
                .foregroundStyle(.secondary)
            Text("Unsigned receipt · unauthenticated · no live freshness claim")
                .font(.caption)
                .foregroundStyle(.secondary)

            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 5) {
                timestampRow("Original start", imported.startedAt)
                timestampRow("Original end", imported.finishedAt)
                timestampRow("Original capture", snapshot.capturedAt)
                GridRow {
                    Text("Line state")
                    Text(UPSMonitorFormatters.lineStateLabel(snapshot.status.lineState))
                }
                GridRow {
                    Text("Status quality")
                    Text(UPSMonitorFormatters.statusQualityLabel(snapshot.status.quality))
                }
                if let health = snapshot.status.batteryHealth {
                    GridRow {
                        Text("Battery health")
                        Text(UPSMonitorFormatters.healthLabel(health))
                    }
                }
                if let charging = snapshot.status.isCharging {
                    GridRow {
                        Text("Charging")
                        Text(charging ? "Yes" : "No")
                    }
                }
                if let failure = snapshot.status.internalFailure {
                    GridRow {
                        Text("Internal failure")
                        Text(failure ? "Yes" : "No")
                    }
                }
                GridRow {
                    Text("Status flags")
                    Text(snapshot.status.flags.isEmpty ? "None reported" : snapshot.status.flags
                        .sorted { $0.rawValue < $1.rawValue }
                        .map(UPSMonitorFormatters.statusFlagLabel).joined(separator: ", "))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .font(.callout)
            .textSelection(.enabled)

            metricSection("Battery", ids: Self.batteryMetrics, snapshot: snapshot)
            metricSection("Input", ids: Self.inputMetrics, snapshot: snapshot)
            metricSection("Output", ids: Self.outputMetrics, snapshot: snapshot)
            metricSection("UPS", ids: Self.upsMetrics, snapshot: snapshot)
            metricSection("Other", ids: Self.otherMetrics, snapshot: snapshot)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func timestampRow(_ title: String, _ date: Date) -> some View {
        GridRow {
            Text(title)
            Text(UPSMonitorFormatters.timestamp(date))
        }
    }

    private func metricSection(_ title: String, ids: [MonitorMetricID], snapshot: MonitorSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.headline)
            ForEach(ids, id: \.self) { id in
                let metric = snapshot.metrics.first { $0.id == id }
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(UPSMonitorFormatters.metricName(id))
                        .frame(minWidth: 190, alignment: .leading)
                    Text(metric.map(UPSMonitorFormatters.metricValue) ?? "Not reported")
                        .monospacedDigit()
                    if let metric {
                        Text(UPSMonitorFormatters.provenanceLabel(metric.provenance))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(UPSMonitorFormatters.qualityLabel(metric.quality))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.top, 4)
    }

    private func originLabel(_ origin: NUTObservationOrigin) -> String {
        switch origin {
        case .syntheticDriverDump: "Synthetic driver dump"
        case .archivedSupervisedDriverDump: "Archived supervised driver dump"
        }
    }

    private static let batteryMetrics: [MonitorMetricID] = [
        .batteryCharge, .batteryRuntime, .batteryTimeToFull, .batteryVoltage,
        .batteryVoltageNominal, .batteryCurrent, .batteryTemperature,
    ]
    private static let inputMetrics: [MonitorMetricID] = [
        .inputVoltage, .inputVoltageNominal, .inputCurrent, .inputCurrentNominal,
        .inputFrequency, .inputFrequencyNominal, .inputRealPower, .inputRealPowerNominal,
        .inputApparentPower,
    ]
    private static let outputMetrics: [MonitorMetricID] = [
        .outputVoltage, .outputVoltageNominal, .outputCurrent, .outputCurrentNominal,
        .outputFrequency, .outputFrequencyNominal,
    ]
    private static let upsMetrics: [MonitorMetricID] = [
        .upsLoad, .upsRealPower, .upsRealPowerNominal, .upsApparentPower,
        .upsApparentPowerNominal, .upsTemperature,
    ]
    private static let otherMetrics: [MonitorMetricID] = [.appleSourceCurrent, .appleSourceTemperature]
}
