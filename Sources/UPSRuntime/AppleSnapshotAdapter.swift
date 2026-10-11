import ApplePowerSource
import Foundation
import UPSModel

public enum AppleSnapshotRuntimeError: Error, Equatable {
    case unavailable
    case unidentifiedPresentSource
}

public enum AppleSnapshotRuntimeAdapter {
    public static func readings(from session: AppleSessionSnapshot) throws -> [MonitorReading] {
        try snapshots(from: session).map { snapshot in
            MonitorReading(snapshot: snapshot,
                           presentationName: session.presentationNamesByOpaqueSourceID[snapshot.source.id])
        }
    }

    public static func snapshots(from session: AppleSessionSnapshot) throws -> [MonitorSnapshot] {
        guard session.snapshot.availability == .available else { throw AppleSnapshotRuntimeError.unavailable }
        guard session.unidentifiedPresentSourceCount == 0 else {
            throw AppleSnapshotRuntimeError.unidentifiedPresentSource
        }

        return try session.snapshot.sources.map { powerSource in
            let source = MonitorSource(
                provider: .apple,
                id: powerSource.id,
                sessionID: session.sessionID,
                identityStability: .sessionLocal
            )
            return try MonitorSnapshotAdapter.fromApple(session.snapshot, source: source, powerSourceID: powerSource.id)
        }
    }
}
