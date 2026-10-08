import SwiftUI
import UPSRuntime

struct UPSAlertSettingsView: View {
    @Bindable var model: MonitorAppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Local Alerts").font(.title2.weight(.semibold))
                Spacer()
                if model.alerts.isBusy { ProgressView().controlSize(.small) }
                Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            Form {
                Toggle("Enable for this session", isOn: Binding(
                    get: { model.alerts.isEnabled },
                    set: { enabled in Task { await model.setAlertsEnabled(enabled) } }
                ))
                .toggleStyle(.switch)
                .disabled(model.isPreview || model.alerts.isBusy)
                Toggle("Battery and mains changes", isOn: policyBinding(\.lineChanges))
                Toggle("Low battery", isOn: policyBinding(\.lowBattery))
                Stepper(value: Binding(
                    get: { model.alerts.policy.lowChargeThreshold },
                    set: { threshold in
                        var policy = model.alerts.policy
                        policy.lowChargeThreshold = threshold
                        model.setAlertPolicy(policy)
                    }
                ), in: 5...50) {
                    LabeledContent("Charge threshold", value: "\(model.alerts.policy.lowChargeThreshold)%")
                }
                .disabled(!model.alerts.policy.lowBattery)
                Toggle("Monitoring unavailable", isOn: policyBinding(\.monitoringLoss))
            }
            .disabled(model.isPreview || model.alerts.isBusy)
            if let message = model.alerts.message {
                Label(message, systemImage: "bell.slash")
                    .font(.callout).foregroundStyle(.secondary)
            }
        }
        .padding(20)
        .frame(minWidth: 420, idealWidth: 460)
    }

    private func policyBinding(_ keyPath: WritableKeyPath<UPSAlertPolicy, Bool>) -> Binding<Bool> {
        Binding(get: { model.alerts.policy[keyPath: keyPath] }, set: { value in
            var policy = model.alerts.policy
            policy[keyPath: keyPath] = value
            model.setAlertPolicy(policy)
        })
    }
}
