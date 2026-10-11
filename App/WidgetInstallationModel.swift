import Foundation
import Observation
import WidgetKit
import UPSWidgetBridge

enum WidgetInstallationFamily: Sendable, Equatable {
    case small
    case medium
    case other
}

struct WidgetInstallationConfiguration: Sendable, Equatable {
    let kind: String
    let family: WidgetInstallationFamily
}

enum WidgetInstallationState: Equatable {
    case notChecked
    case checking
    case noWidgetsAdded
    case counts(small: Int, medium: Int, other: Int)
    case unavailable
}

@Observable
@MainActor
final class WidgetInstallationModel {
    typealias Read = @Sendable () async throws -> [WidgetInstallationConfiguration]

    private(set) var state: WidgetInstallationState = .notChecked
    @ObservationIgnored private let read: Read
    @ObservationIgnored private var requestID: UInt64 = 0
    @ObservationIgnored private var readingRequestID: UInt64 = 0
    @ObservationIgnored private var isReading = false
    @ObservationIgnored private var hasPendingCheck = false

    init() {
        self.read = Self.readCurrentConfigurations
    }

    init(read: @escaping Read) {
        self.read = read
    }

    var isChecking: Bool { state == .checking }

    func check() async {
        guard !isReading else {
            if readingRequestID != requestID {
                hasPendingCheck = true
            }
            state = .checking
            return
        }
        isReading = true
        defer { isReading = false }

        repeat {
            hasPendingCheck = false
            requestID &+= 1
            let request = requestID
            readingRequestID = request
            state = .checking

            do {
                let configurations = try await read()
                if request == requestID {
                    let kind = WidgetGroupConfiguration.widgetKind(for: .disabled)
                    let matching = configurations.filter { $0.kind == kind }
                    state = matching.isEmpty ? .noWidgetsAdded : .counts(
                        small: matching.filter { $0.family == .small }.count,
                        medium: matching.filter { $0.family == .medium }.count,
                        other: matching.filter { $0.family == .other }.count
                    )
                }
            } catch {
                if request == requestID {
                    state = .unavailable
                }
            }
        } while hasPendingCheck
    }

    func cancelCheck() {
        guard state == .checking else { return }
        requestID &+= 1
        hasPendingCheck = false
        state = .notChecked
    }

    private static func readCurrentConfigurations() async throws -> [WidgetInstallationConfiguration] {
        try await withCheckedThrowingContinuation { continuation in
            WidgetCenter.shared.getCurrentConfigurations { result in
                continuation.resume(with: result.map { widgets in
                    widgets.map { widget in
                        let family: WidgetInstallationFamily
                        switch widget.family {
                        case .systemSmall: family = .small
                        case .systemMedium: family = .medium
                        default: family = .other
                        }
                        return WidgetInstallationConfiguration(kind: widget.kind, family: family)
                    }
                })
            }
        }
    }
}
