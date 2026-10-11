import SwiftUI

struct WidgetStatusView: View {
    @Bindable var model: WidgetInstallationModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Widget status")
                    .font(.title2.weight(.semibold))
                Spacer()
                Button {
                    Task { await model.check() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Check widget status")
                .accessibilityLabel("Check widget status")
                .disabled(model.isChecking)
            }

            Group {
                switch model.state {
                case .notChecked:
                    Text("Not checked")
                case .checking:
                    Label("Checking…", systemImage: "arrow.clockwise")
                case .noWidgetsAdded:
                    Text("No widgets added")
                case let .counts(small, medium, other):
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Small: \(small)")
                        Text("Medium: \(medium)")
                        Text("Other sizes: \(other)")
                    }
                    .monospacedDigit()
                case .unavailable:
                    Text("Widget status unavailable")
                }
            }
            .font(.body)
            .frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)

            VStack(spacing: 6) {
                LabeledContent("Source", value: "WidgetKit configuration")
                LabeledContent("Rendering", value: "Not verified")
                LabeledContent("Shared data", value: "Not verified")
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            HStack {
                Spacer()
                Button("Close", systemImage: "xmark") {
                    model.cancelCheck()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
            }
        }
        .padding(22)
        .frame(minWidth: 350, idealWidth: 410, maxWidth: 480,
               minHeight: 240, idealHeight: 270)
        .task { await model.check() }
        .onDisappear { model.cancelCheck() }
    }
}
