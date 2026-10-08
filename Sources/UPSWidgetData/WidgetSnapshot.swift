import Foundation
import UPSModel

public enum WidgetAcquisition: String, Codable, Sendable {
    case active
    case noSources
    case readFailed
    case stopped
}

public enum WidgetSnapshotValidationError: Error, Equatable {
    case unsupportedSchemaVersion
    case invalidDate
    case invalidAcquisition
    case invalidAge
    case invalidSnapshot
}

public struct WidgetSnapshot: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let publishedAt: Date
    public let acquisition: WidgetAcquisition
    public let maximumAge: TimeInterval
    public let snapshot: MonitorSnapshot?

    public init(
        schemaVersion: Int = 1,
        publishedAt: Date,
        acquisition: WidgetAcquisition,
        maximumAge: TimeInterval,
        snapshot: MonitorSnapshot?
    ) {
        self.schemaVersion = schemaVersion
        self.publishedAt = publishedAt
        self.acquisition = acquisition
        self.maximumAge = maximumAge
        self.snapshot = snapshot
    }

    public func validate() throws {
        guard schemaVersion == 1 else { throw WidgetSnapshotValidationError.unsupportedSchemaVersion }
        guard publishedAt.timeIntervalSince1970.isFinite else { throw WidgetSnapshotValidationError.invalidDate }
        guard maximumAge.isFinite, (1...600).contains(maximumAge) else {
            throw WidgetSnapshotValidationError.invalidAge
        }

        switch acquisition {
        case .active:
            guard snapshot != nil else { throw WidgetSnapshotValidationError.invalidAcquisition }
        case .noSources:
            guard snapshot == nil else { throw WidgetSnapshotValidationError.invalidAcquisition }
        case .readFailed, .stopped:
            break
        }

        if let snapshot {
            do { try snapshot.validate() } catch { throw WidgetSnapshotValidationError.invalidSnapshot }
            guard snapshot.capturedAt <= publishedAt else { throw WidgetSnapshotValidationError.invalidDate }
        }
    }

    public func isStale(at date: Date) -> Bool {
        do { try validate() } catch { return true }
        guard acquisition == .active,
              let snapshot,
              date.timeIntervalSince1970.isFinite,
              publishedAt <= date,
              snapshot.capturedAt.timeIntervalSince1970.isFinite,
              maximumAge.isFinite,
              (1...600).contains(maximumAge) else { return true }
        let age = date.timeIntervalSince(snapshot.capturedAt)
        return !age.isFinite || age < 0 || age > maximumAge
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case publishedAt
        case acquisition
        case maximumAge
        case snapshot
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        publishedAt = try values.decode(Date.self, forKey: .publishedAt)
        acquisition = try values.decode(WidgetAcquisition.self, forKey: .acquisition)
        maximumAge = try values.decode(TimeInterval.self, forKey: .maximumAge)
        snapshot = try values.decodeIfPresent(MonitorSnapshot.self, forKey: .snapshot)
        do {
            try validate()
        } catch {
            throw DecodingError.dataCorruptedError(forKey: .schemaVersion, in: values, debugDescription: "Invalid widget snapshot")
        }
    }
}
