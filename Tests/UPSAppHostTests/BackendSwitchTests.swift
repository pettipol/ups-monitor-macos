import Foundation
import XCTest
import UPSHistory
import UPSModel
import UPSMonitorUI
@testable import UPSAppHost

@MainActor
final class BackendSwitchTests: XCTestCase {
    private let date = Date(timeIntervalSince1970: 40_000)

    func testFailedPreflightKeepsAppleAndNeverAdmitsNUT() async throws {
        let apple = snapshot(provider: .apple)
        let model = MonitorAppModel(read: { [apple] }, clock: { apple.capturedAt },
                                    observesWorkspace: false, isPreview: false,
                                    nutReadFactory: { _ in throw SyntheticFailure.failed })
        await model.startIfNeeded()
        await waitUntil { model.selected == apple }
        model.connectionDraft = draft()
        await model.connectNUT()
        XCTAssertEqual(model.backend, .apple)
        XCTAssertEqual(model.selected, apple)
        XCTAssertNotNil(model.connectionMessage)
        XCTAssertFalse(model.backendTransition)
        await model.stop()
    }

    func testSwitchWaitsForOldReadAndExcludesLateOldHistory() async throws {
        let parent = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: parent) }
        let historyURL = parent.appendingPathComponent("history")
        let gate = BackendGate()
        let nutCalls = BackendCalls()
        let apple = snapshot(provider: .apple)
        let nut = snapshot(provider: .nut)
        let model = MonitorAppModel(read: { await gate.wait(); return [apple] },
                                    clock: { apple.capturedAt }, historyDirectoryURL: historyURL,
                                    observesWorkspace: false, isPreview: false,
                                    nutReadFactory: { _ in { await nutCalls.increment(); return [nut] } })
        await model.setHistoryRecording(true)
        await model.startIfNeeded()
        for _ in 0..<100 where await gate.entries == 0 { try await Task.sleep(for: .milliseconds(5)) }
        model.connectionDraft = draft()
        let switching = Task { await model.connectNUT() }
        await waitUntil { model.backendTransition }
        try await Task.sleep(for: .milliseconds(30))
        let beforeUnwind = await nutCalls.value
        XCTAssertEqual(beforeUnwind, 0, "A replacement must not read while its predecessor is still active")
        await gate.release()
        await switching.value
        model.refresh()
        await waitUntil { model.history == [nut] }
        XCTAssertEqual(model.backend, .nut)
        XCTAssertEqual(model.selected, nut)
        XCTAssertEqual(model.history, [nut])
        await model.stop()

        let store = try UPSHistoryStore(directoryURL: historyURL)
        let oldRecords = try await store.query(HistoryQuery(start: date, end: date, source: apple.source))
        let newRecords = try await store.query(HistoryQuery(start: date, end: date, source: nut.source))
        XCTAssertEqual(oldRecords, [])
        XCTAssertEqual(newRecords, [nut])
        try await store.close()
    }

    func testFailedNUTReadDoesNotFallBackAndAppleCanBeSelectedExplicitly() async throws {
        let apple = snapshot(provider: .apple)
        let appleCalls = BackendCalls()
        let model = MonitorAppModel(read: { await appleCalls.increment(); return [apple] },
                                    clock: { apple.capturedAt }, observesWorkspace: false, isPreview: false,
                                    nutReadFactory: { _ in { throw SyntheticFailure.failed } })
        await model.startIfNeeded()
        await waitUntil { model.selected == apple }
        model.connectionDraft = draft()
        await model.connectNUT()
        model.refresh()
        await waitUntil { model.readState == .failed }
        XCTAssertEqual(model.backend, .nut)
        XCTAssertNil(model.selected)
        let count = await appleCalls.value
        try await Task.sleep(for: .milliseconds(30))
        let afterFailure = await appleCalls.value
        XCTAssertEqual(afterFailure, count)
        await model.useAppleBackend()
        model.refresh()
        await waitUntil { model.selected == apple }
        XCTAssertEqual(model.backend, .apple)
        await model.stop()
    }

    func testStopDuringPreflightNeverStartsReplacement() async throws {
        let gate = BackendGate()
        let calls = BackendCalls()
        let model = MonitorAppModel(read: { [] }, observesWorkspace: false, isPreview: false,
                                    nutReadFactory: { _ in
                                        await gate.wait()
                                        return { await calls.increment(); return [] }
                                    })
        await model.startIfNeeded()
        model.connectionDraft = draft()
        let connecting = Task { await model.connectNUT() }
        for _ in 0..<100 where await gate.entries == 0 { try await Task.sleep(for: .milliseconds(5)) }
        await model.stop()
        await gate.release()
        await connecting.value
        let count = await calls.value
        XCTAssertEqual(count, 0)
        XCTAssertEqual(model.backend, .apple)
        XCTAssertEqual(model.readState, .stopped)
    }

    func testPendingPreflightDoesNotFreezeCurrentBackendClock() async throws {
        let gate = BackendGate()
        let model = MonitorAppModel(read: { [] }, observesWorkspace: false, isPreview: false,
                                    nutReadFactory: { _ in await gate.wait(); throw SyntheticFailure.failed })
        await model.startIfNeeded()
        await waitUntil { model.readState == .noSources }
        model.connectionDraft = draft()
        let connecting = Task { await model.connectNUT() }
        await waitUntil { model.backendTransition }
        let previous = model.now
        await waitUntil { model.now > previous }
        XCTAssertEqual(model.backend, .apple)
        await gate.release()
        await connecting.value
        await model.stop()
    }

    func testPreviewCannotSelectAnyLiveBackend() async throws {
        let calls = BackendCalls()
        let model = MonitorAppModel(read: { await calls.increment(); return [] },
                                    observesWorkspace: false, isPreview: true,
                                    nutReadFactory: { _ in await calls.increment(); return { [] } })
        await model.startIfNeeded()
        model.connectionDraft = draft()
        await model.connectNUT()
        await model.useAppleBackend()
        let count = await calls.value
        XCTAssertEqual(count, 0)
        XCTAssertEqual(model.selected?.source.id, "synthetic-ups")
        await model.stop()
    }

    private func waitUntil(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<300 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Expected synthetic state was not reached", file: file, line: line)
    }

    private func snapshot(provider: MonitorProvider) -> MonitorSnapshot {
        MonitorSnapshot(source: MonitorSource(provider: provider, id: "synthetic-" + provider.rawValue,
                                              sessionID: "test-session", identityStability: provider == .apple ? .sessionLocal : .configured),
                        capturedAt: date, status: MonitorStatus(quality: .unavailable), metrics: [])
    }

    private func draft() -> NUTConnectionDraft {
        NUTConnectionDraft(executablePath: "/synthetic/upsc", expectedSHA256: String(repeating: "a", count: 64),
                           upsName: "fixture", completionQualified: true)
    }

    private func makeDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ups-switch-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        return url
    }
}

private enum SyntheticFailure: Error { case failed }
private actor BackendCalls {
    var value = 0
    func increment() { value += 1 }
}
private actor BackendGate {
    var entries = 0
    private var released = false
    private var continuations: [CheckedContinuation<Void, Never>] = []
    func wait() async {
        entries += 1
        guard !released else { return }
        await withCheckedContinuation { continuations.append($0) }
    }
    func release() {
        released = true
        for continuation in continuations { continuation.resume() }
        continuations.removeAll()
    }
}
