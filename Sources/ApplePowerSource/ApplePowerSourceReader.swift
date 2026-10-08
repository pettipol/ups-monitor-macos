import Foundation
import IOKit.ps
import UPSCore

public struct ApplePowerSourceReader {
    public init() {}

    public func snapshot(now: Date = Date()) -> PowerSourceSnapshot {
        guard let infoResult = IOPSCopyPowerSourcesInfo() else {
            return PowerSourceNormalizer.snapshot(from: [], capturedAt: now, availability: .unavailable)
        }
        let info = infoResult.takeRetainedValue()

        guard let listResult = IOPSCopyPowerSourcesList(info) else {
            return PowerSourceNormalizer.snapshot(from: [], capturedAt: now, availability: .unavailable)
        }
        let list = listResult.takeRetainedValue()

        let handles: [CFTypeRef] = (list as NSArray).map { $0 as CFTypeRef }
        var descriptions: [[String: Any]] = []

        for handle in handles {
            guard let descriptionResult = IOPSGetPowerSourceDescription(info, handle),
                  let description = descriptionResult.takeUnretainedValue() as? [String: Any] else {
                descriptions.append([:])
                continue
            }
            descriptions.append(description)
        }

        return PowerSourceNormalizer.snapshot(from: descriptions, capturedAt: now)
    }
}
