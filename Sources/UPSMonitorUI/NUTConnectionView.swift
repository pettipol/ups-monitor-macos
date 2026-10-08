import SwiftUI

public struct NUTConnectionDraft: Equatable, Sendable {
    public var executablePath: String
    public var expectedSHA256: String
    public var upsName: String
    public var port: String
    public var completionQualified: Bool

    public init(
        executablePath: String = "",
        expectedSHA256: String = "",
        upsName: String = "",
        port: String = "3493",
        completionQualified: Bool = false
    ) {
        self.executablePath = executablePath
        self.expectedSHA256 = expectedSHA256
        self.upsName = upsName
        self.port = port
        self.completionQualified = completionQualified
    }

    public var canConnect: Bool {
        Self.isAbsoluteNonemptyPath(executablePath)
            && Self.isSHA256(expectedSHA256)
            && Self.isSafeUPSName(upsName)
            && Self.isValidPort(port)
            && completionQualified
    }

    private static func isAbsoluteNonemptyPath(_ path: String) -> Bool {
        !path.isEmpty
            && path != "/"
            && !path.utf8.contains(0)
            && path.hasPrefix("/")
            && !path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private static func isSHA256(_ digest: String) -> Bool {
        digest.utf8.count == 64 && digest.utf8.allSatisfy(isASCIIHexDigit)
    }

    private static func isSafeUPSName(_ name: String) -> Bool {
        let bytes = Array(name.utf8)
        guard (1...64).contains(bytes.count), isASCIIAlphaNumeric(bytes[0]) else { return false }
        return bytes.dropFirst().allSatisfy {
            isASCIIAlphaNumeric($0) || $0 == 45 || $0 == 46 || $0 == 95
        }
    }

    private static func isValidPort(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 5,
              value.utf8.allSatisfy({ (48...57).contains($0) }),
              let port = Int(value) else { return false }
        return (1...65_535).contains(port)
    }

    private static func isASCIIAlphaNumeric(_ byte: UInt8) -> Bool {
        (48...57).contains(byte) || (65...90).contains(byte) || (97...122).contains(byte)
    }

    private static func isASCIIHexDigit(_ byte: UInt8) -> Bool {
        (48...57).contains(byte) || (65...70).contains(byte) || (97...102).contains(byte)
    }
}

public struct NUTConnectionView: View {
    @Binding public var draft: NUTConnectionDraft
    public let isConnecting: Bool
    public let errorMessage: String?
    public let onChooseExecutable: @MainActor @Sendable () -> Void
    public let onConnect: @MainActor @Sendable () -> Void
    public let onCancel: @MainActor @Sendable () -> Void

    public init(
        draft: Binding<NUTConnectionDraft>,
        isConnecting: Bool,
        errorMessage: String?,
        onChooseExecutable: @escaping @MainActor @Sendable () -> Void,
        onConnect: @escaping @MainActor @Sendable () -> Void,
        onCancel: @escaping @MainActor @Sendable () -> Void
    ) {
        self._draft = draft
        self.isConnecting = isConnecting
        self.errorMessage = errorMessage
        self.onChooseExecutable = onChooseExecutable
        self.onConnect = onConnect
        self.onCancel = onCancel
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Local NUT", systemImage: "network")
                .font(.title3.weight(.semibold))

            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                GridRow {
                    Text("UPS name")
                    TextField("UPS name", text: $draft.upsName)
                        .accessibilityLabel("UPS name")
                        .disabled(isConnecting)
                }

                GridRow {
                    Text("Port")
                    TextField("3493", text: $draft.port)
                        .frame(width: 110, alignment: .leading)
                        .monospacedDigit()
                        .accessibilityLabel("Local NUT port")
                        .disabled(isConnecting)
                }

                GridRow {
                    Text("Host")
                    Text("127.0.0.1")
                        .foregroundStyle(.secondary)
                        .accessibilityLabel("Host 127.0.0.1")
                }

                GridRow {
                    Text("Executable")
                    HStack(spacing: 8) {
                        Text(draft.executablePath.isEmpty ? "Not selected" : draft.executablePath)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                            .accessibilityLabel("UPSC executable path")
                        Spacer(minLength: 0)
                        Button(action: onChooseExecutable) {
                            Image(systemName: "folder")
                        }
                        .buttonStyle(.borderless)
                        .help("Choose UPSC executable")
                        .accessibilityLabel("Choose UPSC executable")
                        .disabled(isConnecting)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                GridRow {
                    Text("SHA-256")
                    TextField("64 hexadecimal characters", text: $draft.expectedSHA256)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.body, design: .monospaced))
                        .accessibilityLabel("Expected UPSC SHA-256")
                        .disabled(isConnecting)
                }
            }

            Toggle("Completion-qualified client", isOn: $draft.completionQualified)
                .accessibilityHint("Confirms the selected client rejects incomplete or stale NUT lists")
                .disabled(isConnecting)

            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack {
                Spacer()
                Button("Cancel", action: onCancel)
                    .keyboardShortcut(.cancelAction)
                    .disabled(isConnecting)
                Button(action: onConnect) {
                    if isConnecting {
                        ProgressView()
                            .controlSize(.small)
                            .accessibilityLabel("Connecting")
                    } else {
                        Text("Connect")
                    }
                }
                .frame(minWidth: 84, minHeight: 22)
                .keyboardShortcut(.defaultAction)
                .disabled(isConnecting || !draft.canConnect)
            }
        }
        .padding()
        .frame(minWidth: 520, idealWidth: 600, maxWidth: 680)
    }
}
