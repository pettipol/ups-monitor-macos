import Foundation
import Testing
import UPSModel
@testable import UPSWidgetData

private let scheduleNow = Date(timeIntervalSince1970: 100_000)

private func schedulePayload(
    capturedAt: Date = scheduleNow,
    publishedAt: Date? = nil,
    acquisition: WidgetAcquisition = .active,
    maximumAge: TimeInterval = 10,
    includeSnapshot: Bool = true
) -> WidgetSnapshot {
    let source = MonitorSource(provider: .nut, id: "synthetic", sessionID: "session", identityStability: .configured)
    let snapshot = includeSnapshot
        ? MonitorSnapshot(source: source, capturedAt: capturedAt,
                          status: MonitorStatus(quality: .unavailable), metrics: [])
        : nil
    return WidgetSnapshot(
        publishedAt: publishedAt ?? capturedAt,
        acquisition: acquisition,
        maximumAge: maximumAge,
        snapshot: snapshot
    )
}

@Test func addsExpiryAfterInclusiveFreshnessBoundaryAndKeepsStandardDates() {
    let payload = schedulePayload()
    let atBoundary = scheduleNow.addingTimeInterval(10)
    let dates = WidgetTimelineSchedule.dates(for: payload, from: atBoundary)

    #expect(dates == [atBoundary, scheduleNow.addingTimeInterval(11),
                      atBoundary.addingTimeInterval(300), atBoundary.addingTimeInterval(600),
                      atBoundary.addingTimeInterval(900)])
    #expect(!payload.isStale(at: atBoundary))
    #expect(payload.isStale(at: scheduleNow.addingTimeInterval(11)))
}

@Test func stalePayloadGetsOnlyStandardFutureDates() {
    let now = scheduleNow.addingTimeInterval(11)
    let dates = WidgetTimelineSchedule.dates(for: schedulePayload(), from: now)
    #expect(dates == [now, now.addingTimeInterval(300), now.addingTimeInterval(600), now.addingTimeInterval(900)])
}

@Test func maximumAgeSixHundredSchedulesTransitionAfterRegularTenMinuteDate() {
    let payload = schedulePayload(maximumAge: 600)
    let dates = WidgetTimelineSchedule.dates(for: payload, from: scheduleNow)
    #expect(dates == [scheduleNow, scheduleNow.addingTimeInterval(300), scheduleNow.addingTimeInterval(600),
                      scheduleNow.addingTimeInterval(601), scheduleNow.addingTimeInterval(900)])
}

@Test func onlyFreshActiveValidPayloadAddsTransition() {
    let now = scheduleNow.addingTimeInterval(4)
    let standard = [now, now.addingTimeInterval(300), now.addingTimeInterval(600), now.addingTimeInterval(900)]

    #expect(WidgetTimelineSchedule.dates(for: nil, from: now) == standard)
    #expect(WidgetTimelineSchedule.dates(
        for: schedulePayload(publishedAt: now, acquisition: .stopped), from: now
    ) == standard)
    #expect(WidgetTimelineSchedule.dates(
        for: schedulePayload(publishedAt: now, acquisition: .readFailed), from: now
    ) == standard)
    #expect(WidgetTimelineSchedule.dates(
        for: schedulePayload(publishedAt: now, acquisition: .noSources, includeSnapshot: false), from: now
    ) == standard)

    let invalid = WidgetSnapshot(schemaVersion: 2, publishedAt: now, acquisition: .active,
                                 maximumAge: 10, snapshot: schedulePayload().snapshot)
    #expect(WidgetTimelineSchedule.dates(for: invalid, from: now) == standard)

    let stale = schedulePayload(capturedAt: scheduleNow.addingTimeInterval(-11), publishedAt: now)
    #expect(WidgetTimelineSchedule.dates(for: stale, from: now) == standard)
}

@Test func freshnessUsesCaptureTimeAndDoesNotRefreshOrAdmitFutureCapture() {
    let now = scheduleNow.addingTimeInterval(4)
    let payload = schedulePayload(publishedAt: scheduleNow.addingTimeInterval(1))
    let dates = WidgetTimelineSchedule.dates(for: payload, from: now)
    #expect(dates == [now, scheduleNow.addingTimeInterval(11), now.addingTimeInterval(300),
                      now.addingTimeInterval(600), now.addingTimeInterval(900)])

    let futureCapture = schedulePayload(capturedAt: now.addingTimeInterval(1),
                                        publishedAt: now.addingTimeInterval(2))
    #expect(WidgetTimelineSchedule.dates(for: futureCapture, from: now)
            == [now, now.addingTimeInterval(300), now.addingTimeInterval(600), now.addingTimeInterval(900)])
}

@Test func datesAreSortedUniqueAndInvalidNowReturnsEmpty() {
    let payload = schedulePayload(maximumAge: 299)
    let now = scheduleNow
    let dates = WidgetTimelineSchedule.dates(for: payload, from: now)
    #expect(dates == [now, now.addingTimeInterval(300), now.addingTimeInterval(600), now.addingTimeInterval(900)])
    #expect(Set(dates).count == dates.count)
    #expect(WidgetTimelineSchedule.dates(for: payload, from: Date(timeIntervalSince1970: .infinity)).isEmpty)
    #expect(WidgetTimelineSchedule.dates(for: payload, from: Date(timeIntervalSince1970: -.infinity)).isEmpty)
}
