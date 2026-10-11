import XCTest
import UPSWidgetBridge
@testable import UPSAppHost

final class WidgetInstallationTests: XCTestCase {
    @MainActor
    func testStartsUncheckedAndReportsNoWidgets() async {
        let reads = WidgetConfigurationReadCounter(result: [])
        let model = WidgetInstallationModel(read: { try await reads.read() })

        XCTAssertEqual(model.state, .notChecked)
        let initialReadCount = await reads.count
        XCTAssertEqual(initialReadCount, 0)

        await model.check()

        XCTAssertEqual(model.state, .noWidgetsAdded)
        let completedReadCount = await reads.count
        XCTAssertEqual(completedReadCount, 1)
    }

    @MainActor
    func testCountsOnlyProductionWidgetKindByFamily() async {
        let productionKind = WidgetGroupConfiguration.widgetKind(for: .disabled)
        let configurations = [
            WidgetInstallationConfiguration(kind: productionKind, family: .small),
            WidgetInstallationConfiguration(kind: productionKind, family: .small),
            WidgetInstallationConfiguration(kind: productionKind, family: .medium),
            WidgetInstallationConfiguration(kind: productionKind, family: .other),
            WidgetInstallationConfiguration(kind: WidgetGroupConfiguration.widgetKind(for: .enabled), family: .small),
            WidgetInstallationConfiguration(kind: "unrelated.widget", family: .medium),
        ]
        let model = WidgetInstallationModel(read: { configurations })

        await model.check()

        XCTAssertEqual(model.state, .counts(small: 2, medium: 1, other: 1))
    }

    @MainActor
    func testErrorDoesNotExposeUnderlyingMessageAndCanRecover() async {
        let reader = FlakyWidgetConfigurationReader()
        let model = WidgetInstallationModel(read: { try await reader.read() })

        await model.check()
        XCTAssertEqual(model.state, .unavailable)

        await model.check()
        XCTAssertEqual(model.state, .counts(small: 1, medium: 0, other: 0))
        let readCount = await reader.count
        XCTAssertEqual(readCount, 2)
    }

    @MainActor
    func testOverlappingCheckIsIgnoredAndClosedSheetRejectsLateResult() async {
        let gate = WidgetConfigurationReadGate()
        let model = WidgetInstallationModel(read: { try await gate.read() })
        let check = Task { @MainActor in await model.check() }
        await gate.waitUntilStarted()

        await model.check()
        let readCount = await gate.count
        XCTAssertEqual(readCount, 1)
        XCTAssertEqual(model.state, .checking)

        model.cancelCheck()
        XCTAssertEqual(model.state, .notChecked)
        await gate.succeed([WidgetInstallationConfiguration(
            kind: WidgetGroupConfiguration.widgetKind(for: .disabled), family: .small
        )])
        await check.value

        XCTAssertEqual(model.state, .notChecked)
    }

    @MainActor
    func testReopenedSheetQueuesOnlyOneCheckAndDiscardsOldSuccess() async {
        let gate = WidgetConfigurationReadGate()
        let model = WidgetInstallationModel(read: { try await gate.read() })
        let check = Task { @MainActor in await model.check() }
        await gate.waitUntilStarted()

        model.cancelCheck()
        await model.check()
        await model.check()
        let countBeforeOldResponse = await gate.count
        XCTAssertEqual(countBeforeOldResponse, 1)
        XCTAssertEqual(model.state, .checking)

        await gate.succeed([WidgetInstallationConfiguration(
            kind: WidgetGroupConfiguration.widgetKind(for: .disabled), family: .small
        )])
        await gate.waitUntilStarted(2)
        XCTAssertEqual(model.state, .checking)
        await gate.succeed([WidgetInstallationConfiguration(
            kind: WidgetGroupConfiguration.widgetKind(for: .disabled), family: .medium
        )])
        await check.value

        let finalReadCount = await gate.count
        let maximumActiveReadCount = await gate.maximumActiveReadCount
        XCTAssertEqual(finalReadCount, 2)
        XCTAssertEqual(maximumActiveReadCount, 1)
        XCTAssertEqual(model.state, .counts(small: 0, medium: 1, other: 0))
    }

    @MainActor
    func testReopenedSheetContinuesAfterDiscardingOldError() async {
        let gate = WidgetConfigurationReadGate()
        let model = WidgetInstallationModel(read: { try await gate.read() })
        let check = Task { @MainActor in await model.check() }
        await gate.waitUntilStarted()

        model.cancelCheck()
        await model.check()
        await gate.fail()
        await gate.waitUntilStarted(2)
        XCTAssertEqual(model.state, .checking)
        await gate.succeed([])
        await check.value

        let finalReadCount = await gate.count
        let maximumActiveReadCount = await gate.maximumActiveReadCount
        XCTAssertEqual(finalReadCount, 2)
        XCTAssertEqual(maximumActiveReadCount, 1)
        XCTAssertEqual(model.state, .noWidgetsAdded)
    }

    @MainActor
    func testClosingReopenedSheetCancelsPendingCheck() async {
        let gate = WidgetConfigurationReadGate()
        let model = WidgetInstallationModel(read: { try await gate.read() })
        let check = Task { @MainActor in await model.check() }
        await gate.waitUntilStarted()

        model.cancelCheck()
        await model.check()
        XCTAssertEqual(model.state, .checking)
        model.cancelCheck()
        await gate.succeed([WidgetInstallationConfiguration(
            kind: WidgetGroupConfiguration.widgetKind(for: .disabled), family: .small
        )])
        await check.value

        let finalReadCount = await gate.count
        XCTAssertEqual(finalReadCount, 1)
        XCTAssertEqual(model.state, .notChecked)
    }
}

private actor WidgetConfigurationReadCounter {
    private let result: [WidgetInstallationConfiguration]
    private(set) var count = 0

    init(result: [WidgetInstallationConfiguration]) { self.result = result }

    func read() throws -> [WidgetInstallationConfiguration] {
        count += 1
        return result
    }
}

private actor FlakyWidgetConfigurationReader {
    private(set) var count = 0

    func read() throws -> [WidgetInstallationConfiguration] {
        count += 1
        if count == 1 { throw NSError(domain: "private-widget-error", code: 17, userInfo: [NSLocalizedDescriptionKey: "private detail"]) }
        return [WidgetInstallationConfiguration(
            kind: WidgetGroupConfiguration.widgetKind(for: .disabled), family: .small
        )]
    }
}

private actor WidgetConfigurationReadGate {
    private(set) var count = 0
    private(set) var maximumActiveReadCount = 0
    private var activeReadCount = 0
    private var continuation: CheckedContinuation<[WidgetInstallationConfiguration], Error>?

    func read() async throws -> [WidgetInstallationConfiguration] {
        count += 1
        activeReadCount += 1
        maximumActiveReadCount = max(maximumActiveReadCount, activeReadCount)
        defer { activeReadCount -= 1 }
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    func waitUntilStarted(_ expectedCount: Int = 1) async {
        while count < expectedCount { await Task.yield() }
    }

    func succeed(_ value: [WidgetInstallationConfiguration]) {
        continuation?.resume(returning: value)
        continuation = nil
    }

    func fail() {
        continuation?.resume(throwing: NSError(domain: "private-widget-error", code: 17))
        continuation = nil
    }
}
