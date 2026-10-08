import CoreFoundation
import Foundation
import IOKit.ps
import UPSCore

public struct AppleSessionSnapshot: Equatable, Sendable {
    public let sessionID: String
    public let snapshot: PowerSourceSnapshot
    public let unidentifiedPresentSourceCount: Int
}

/// A process-local identity layer. Native power-source IDs never leave this actor.
public actor AppleSessionReader {
    private let sessionID = "apple-session-\(UUID().uuidString.lowercased())"
    private var identityMapper = AppleSessionIdentityMapper()

    public init() {}

    public func resetIdentity() {
        identityMapper.reset()
    }

    public func snapshot(now: Date = Date()) -> AppleSessionSnapshot {
        guard let infoResult = IOPSCopyPowerSourcesInfo() else {
            return unavailableSnapshot(now: now)
        }
        let info = infoResult.takeRetainedValue()
        guard let listResult = IOPSCopyPowerSourcesList(info) else {
            return unavailableSnapshot(now: now)
        }

        let handles: [CFTypeRef] = (listResult.takeRetainedValue() as NSArray).map { $0 as CFTypeRef }
        var descriptions: [[String: Any]] = []
        var descriptionFailed = false
        descriptions.reserveCapacity(handles.count)
        for handle in handles {
            guard let result = IOPSGetPowerSourceDescription(info, handle),
                  let description = result.takeUnretainedValue() as? [String: Any] else {
                descriptionFailed = true
                descriptions.append([:])
                continue
            }
            descriptions.append(description)
        }
        guard !descriptionFailed else { return unavailableSnapshot(now: now) }
        return sanitizedSnapshot(descriptions, now: now)
    }

    private func unavailableSnapshot(now: Date) -> AppleSessionSnapshot {
        identityMapper.reset()
        let normalized = PowerSourceNormalizer.snapshot(from: [], capturedAt: now, availability: .unavailable)
        return AppleSessionSnapshot(sessionID: sessionID, snapshot: normalized, unidentifiedPresentSourceCount: 0)
    }

    private func sanitizedSnapshot(_ descriptions: [[String: Any]], now: Date) -> AppleSessionSnapshot {
        let mappedIDs = identityMapper.assignments(for: descriptions)
        let normalized = PowerSourceNormalizer.snapshot(from: descriptions, capturedAt: now)
        var unidentifiedCount = 0
        var safeSources: [PowerSource] = []
        for (source, token) in zip(normalized.sources, mappedIDs) {
            guard let token else {
                unidentifiedCount += 1
                continue
            }
            safeSources.append(source.replacingID(with: token))
        }
        let safeSnapshot = PowerSourceSnapshot(
            capturedAt: normalized.capturedAt,
            provider: normalized.provider,
            availability: normalized.availability,
            discovery: normalized.discovery,
            sources: safeSources
        )
        return AppleSessionSnapshot(
            sessionID: sessionID,
            snapshot: safeSnapshot,
            unidentifiedPresentSourceCount: unidentifiedCount
        )
    }
}

private extension PowerSource {
    func replacingID(with id: String) -> PowerSource {
        PowerSource(
            id: id,
            kind: kind,
            isPresent: isPresent,
            state: state,
            isCharging: isCharging,
            charge: charge,
            timeToEmpty: timeToEmpty,
            timeToFullCharge: timeToFullCharge,
            batteryVoltage: batteryVoltage,
            sourceCurrent: sourceCurrent,
            sourceTemperature: sourceTemperature,
            internalFailure: internalFailure,
            batteryHealth: batteryHealth
        )
    }
}

struct AppleSessionIdentityMapper {
    private(set) var tokensByNativeID: [Int32: String] = [:]
    private var usedTokens = Set<String>()
    private let makeToken: () -> String

    init(makeToken: @escaping () -> String = { "apple-\(UUID().uuidString.lowercased())" }) {
        self.makeToken = makeToken
    }

    mutating func assignments(for descriptions: [[String: Any]]) -> [String?] {
        let nativeIDs = descriptions.map { nativeID(in: $0) }
        var counts: [Int32: Int] = [:]
        for id in nativeIDs.compactMap({ $0 }) { counts[id, default: 0] += 1 }

        let presentUPSIndices = descriptions.indices.filter { index in
            let description = descriptions[index]
            let source = PowerSourceNormalizer.normalize(description, id: "")
            return source.kind == .ups && source.isPresent == true
        }
        let presentUPSIDs = presentUPSIndices.map { nativeIDs[$0] }
        let eligibleIDs: Set<Int32> = Set(presentUPSIDs.compactMap { optionalID -> Int32? in
            guard let id = optionalID, counts[id] == 1 else { return nil }
            return id
        })
        tokensByNativeID = tokensByNativeID.filter { eligibleIDs.contains($0.key) }

        return presentUPSIDs.map { nativeID in
            guard let nativeID, counts[nativeID] == 1 else { return nil }
            if let existing = tokensByNativeID[nativeID] { return existing }
            let token = makeToken()
            guard Self.isValidToken(token), usedTokens.insert(token).inserted else { return nil }
            tokensByNativeID[nativeID] = token
            return token
        }
    }

    mutating func reset() {
        tokensByNativeID.removeAll()
    }

    private func nativeID(in description: [String: Any]) -> Int32? {
        guard let number = description[kIOPSPowerSourceIDKey] as? NSNumber,
              CFGetTypeID(number) == CFNumberGetTypeID(),
              !CFNumberIsFloatType(number) else { return nil }
        return Int32(number.stringValue)
    }

    private static func isValidToken(_ value: String) -> Bool {
        guard (1...64).contains(value.utf8.count), let first = value.utf8.first,
              isAlphaNumeric(first) else { return false }
        return value.utf8.allSatisfy { isAlphaNumeric($0) || $0 == 46 || $0 == 95 || $0 == 45 }
    }

    private static func isAlphaNumeric(_ byte: UInt8) -> Bool {
        (48...57).contains(byte) || (65...90).contains(byte) || (97...122).contains(byte)
    }
}
