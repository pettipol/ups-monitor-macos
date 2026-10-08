import Foundation

public enum WidgetTimelineSchedule {
    private static let refreshOffsets: [TimeInterval] = [0, 300, 600, 900]

    public static func dates(for payload: WidgetSnapshot?, from now: Date) -> [Date] {
        guard now.timeIntervalSince1970.isFinite else { return [] }

        var dates = refreshOffsets
            .map { now.addingTimeInterval($0) }
            .filter { $0.timeIntervalSince1970.isFinite && $0 >= now }

        if let payload, !payload.isStale(at: now), let snapshot = payload.snapshot {
            // Freshness is inclusive at maximumAge, so schedule after that boundary.
            let expiry = snapshot.capturedAt.addingTimeInterval(payload.maximumAge + 1)
            if expiry.timeIntervalSince1970.isFinite, expiry >= now {
                dates.append(expiry)
            }
        }

        return Array(Set(dates)).sorted()
    }
}
