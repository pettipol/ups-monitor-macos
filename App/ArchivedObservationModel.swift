import Foundation
import Observation
import UPSModel
import UPSRuntime

@Observable
@MainActor
final class ArchivedObservationModel {
    typealias Loader = @Sendable (URL, NUTObservationOrigin, MonitorSource, String, Date) throws -> ImportedNUTObservation
    typealias Clock = @Sendable () -> Date

    var sessionDirectoryURL: URL? { didSet { inputsChanged() } }
    var origin: NUTObservationOrigin? { didSet { inputsChanged() } }
    var expectedExecutableSHA256 = "" { didSet { inputsChanged() } }
    private(set) var imported: ImportedNUTObservation?
    private(set) var isLoading = false
    private(set) var errorMessage: String?

    @ObservationIgnored private let loader: Loader
    @ObservationIgnored private let clock: Clock
    @ObservationIgnored private let source: MonitorSource
    @ObservationIgnored private var generation: UInt64 = 0
    @ObservationIgnored private var task: Task<Void, Never>?

    init(
        source: MonitorSource = MonitorSource(
            provider: .nut, id: "archive", sessionID: UUID().uuidString.lowercased(),
            identityStability: .configured
        ),
        clock: @escaping Clock = { Date() },
        loader: @escaping Loader = ArchivedObservationModel.readBundle
    ) {
        self.source = source
        self.clock = clock
        self.loader = loader
    }

    var sourceIdentity: MonitorSource { source }

    @discardableResult
    func importObservation() -> Task<Void, Never>? {
        clear()
        guard let sessionDirectoryURL,
              sessionDirectoryURL.isFileURL,
              isDirectory(sessionDirectoryURL) else {
            errorMessage = "Choose an archive directory"
            return nil
        }
        guard let origin else {
            errorMessage = "Choose a declared origin"
            return nil
        }
        let pin = expectedExecutableSHA256.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.isSHA256(pin) else {
            errorMessage = "Enter a 64-character SHA-256 pin"
            return nil
        }

        generation &+= 1
        let requestGeneration = generation
        let loader = self.loader
        let clock = self.clock
        let source = self.source
        isLoading = true
        let importTask = Task.detached(priority: .userInitiated) { [weak self, loader, clock, source] in
            let result = Result { try loader(sessionDirectoryURL, origin, source, pin, clock()) }
            await self?.finish(result, generation: requestGeneration)
        }
        task = importTask
        return importTask
    }

    func clear() {
        generation &+= 1
        task?.cancel()
        task = nil
        imported = nil
        isLoading = false
        errorMessage = nil
    }

    private func inputsChanged() {
        clear()
    }

    private func finish(_ result: Result<ImportedNUTObservation, Error>, generation requestGeneration: UInt64) {
        guard generation == requestGeneration else { return }
        task = nil
        isLoading = false
        switch result {
        case .success(let observation):
            imported = observation
            errorMessage = nil
        case .failure:
            imported = nil
            errorMessage = "The archived observation could not be imported"
        }
    }

    private func isDirectory(_ url: URL) -> Bool {
        var isDirectoryValue: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectoryValue) && isDirectoryValue.boolValue
    }

    private static func isSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0)
        }
    }

    nonisolated private static func readBundle(
        _ directory: URL,
        _ origin: NUTObservationOrigin,
        _ source: MonitorSource,
        _ pin: String,
        _ now: Date
    ) throws -> ImportedNUTObservation {
        let access = directory.startAccessingSecurityScopedResource()
        defer { if access { directory.stopAccessingSecurityScopedResource() } }
        return try NUTObservationBundleReader().read(
            sessionDirectoryURL: directory, origin: origin, source: source,
            expectedExecutableSHA256: pin, now: now
        )
    }
}
