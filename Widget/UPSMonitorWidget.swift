import Foundation
import SwiftUI
import WidgetKit
import UPSWidgetBridge
import UPSWidgetData
import UPSWidgetUI

struct UPSWidgetEntry: TimelineEntry, Sendable {
    let date: Date
    let payload: WidgetSnapshot?
    let unavailableReason: String?
}

struct UPSWidgetProvider: TimelineProvider, Sendable {
    func placeholder(in context: Context) -> UPSWidgetEntry {
        UPSWidgetEntry(date: Date(), payload: nil, unavailableReason: "UPS snapshot")
    }

    func getSnapshot(in context: Context, completion: @escaping @Sendable (UPSWidgetEntry) -> Void) {
        Task { completion(await Self.load(at: Date())) }
    }

    func getTimeline(in context: Context, completion: @escaping @Sendable (Timeline<UPSWidgetEntry>) -> Void) {
        Task {
            let now = Date()
            let initial = await Self.load(at: now)
            let entries = WidgetTimelineSchedule.dates(for: initial.payload, from: now).map { date in
                UPSWidgetEntry(date: date, payload: initial.payload,
                               unavailableReason: initial.unavailableReason)
            }
            completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(900))))
        }
    }

    private static func load(at date: Date) async -> UPSWidgetEntry {
        let mode = WidgetGroupConfiguration.fixtureMode()
        guard mode != .invalid else {
            return UPSWidgetEntry(date: date, payload: nil, unavailableReason: "Widget configuration invalid")
        }
        do {
            let directory = try WidgetGroupConfiguration.directoryURL(fixtureMode: mode)
            let store = try WidgetSnapshotStore(directoryURL: directory, mode: .readOnly)
            let payload = try await store.read(now: date)
            return UPSWidgetEntry(date: date, payload: payload,
                                  unavailableReason: payload == nil ? "Awaiting first capture" : nil)
        } catch WidgetGroupError.notConfigured {
            return UPSWidgetEntry(date: date, payload: nil, unavailableReason: "Widget not configured")
        } catch {
            return UPSWidgetEntry(date: date, payload: nil, unavailableReason: "Shared data unavailable")
        }
    }
}

@main
struct UPSMonitorWidget: Widget {
    var body: some WidgetConfiguration {
        let mode = WidgetGroupConfiguration.fixtureMode()
        return StaticConfiguration(kind: WidgetGroupConfiguration.widgetKind(for: mode), provider: UPSWidgetProvider()) { entry in
            WidgetEntryView(entry: entry)
        }
        .configurationDisplayName(mode == .enabled ? "UPS Monitor Synthetic Test" : "UPS Monitor")
        .description("Last UPS capture, charge and measurements.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct WidgetEntryView: View {
    @Environment(\.widgetFamily) private var family
    let entry: UPSWidgetEntry

    var body: some View {
        UPSWidgetView(payload: entry.payload, date: entry.date, isMedium: family == .systemMedium,
                      unavailableReason: entry.unavailableReason,
                      isSyntheticFixture: WidgetGroupConfiguration.isSyntheticFixture())
            .containerBackground(for: .widget) { Color.primary.opacity(0.035) }
    }
}
