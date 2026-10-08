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
            let entries = [0.0, 300, 600, 900].map { offset in
                UPSWidgetEntry(date: now.addingTimeInterval(offset), payload: initial.payload,
                               unavailableReason: initial.unavailableReason)
            }
            completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(900))))
        }
    }

    private static func load(at date: Date) async -> UPSWidgetEntry {
        do {
            let directory = try WidgetGroupConfiguration.directoryURL()
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
        StaticConfiguration(kind: WidgetGroupConfiguration.widgetKind, provider: UPSWidgetProvider()) { entry in
            WidgetEntryView(entry: entry)
        }
        .configurationDisplayName("UPS Monitor")
        .description("Last UPS capture, charge and measurements.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct WidgetEntryView: View {
    @Environment(\.widgetFamily) private var family
    let entry: UPSWidgetEntry

    var body: some View {
        UPSWidgetView(payload: entry.payload, date: entry.date, isMedium: family == .systemMedium,
                      unavailableReason: entry.unavailableReason)
            .containerBackground(for: .widget) { Color.primary.opacity(0.035) }
    }
}
