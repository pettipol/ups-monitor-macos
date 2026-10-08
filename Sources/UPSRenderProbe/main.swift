import AppKit
import CoreGraphics
import Darwin
import Foundation
import ImageIO
import SwiftUI
import UPSEnergy
import UPSModel
import UPSMonitorUI
import UPSWidgetData
import UPSWidgetUI
import UniformTypeIdentifiers

private enum ProbeError: Error {
    case usage
    case invalidOutputParent
    case outputAlreadyExists
    case outputCreateFailed
    case renderFailed
    case pngWriteFailed
}

private struct RenderCase: Encodable {
    let file: String
    let scenario: String
    let widthPoints: Int
    let heightPoints: Int
    let scale: Int
    let colorScheme: String
    let capturedAtUnixSeconds: Int
    let presentationDateUnixSeconds: Int
    let textSizeEnvironment: String
}

private struct RenderItem {
    let metadata: RenderCase
    let view: AnyView
    let background: Color
}

private struct Manifest: Encodable {
    let schemaVersion: Int
    let renderer: String
    let renderedAtUnixSeconds: Int
    let localeIdentifier: String
    let timeZoneIdentifier: String
    let cases: [RenderCase]
    let limitations: [String]
}

@main
private struct UPSRenderProbe {
    @MainActor
    static func main() {
        do {
            let outputURL = try createOutputDirectory(arguments: Array(CommandLine.arguments.dropFirst()))
            let cases = try renderMatrix(to: outputURL)
            let manifest = Manifest(
                schemaVersion: 1,
                renderer: "SwiftUI ImageRenderer; offscreen; no application window",
                renderedAtUnixSeconds: Int(Date().timeIntervalSince1970),
                localeIdentifier: Locale.current.identifier,
                timeZoneIdentifier: TimeZone.current.identifier,
                cases: cases,
                limitations: [
                    "ImageRenderer omits or substitutes some controls and cannot faithfully render every AppKit, Core Animation, or complex SwiftUI element.",
                    "These canvases are chosen synthetic sizes, not claims about WidgetKit family dimensions.",
                    "This renders UPSWidgetView directly; it does not run WidgetKit, the provider, shared storage, or the extension container background.",
                    "ProgressView may appear as a renderer placeholder (including a yellow blocked bar); this is not evidence of a production view defect.",
                    "Relative-date labels use the actual rendering clock and current locale/time zone; per-case timestamps are synthetic presentation inputs, not render times.",
                    "The requested accessibility text-size environment may not be honored identically by ImageRenderer or macOS; paired images are a visual probe, not proof of accessibility-size behavior.",
                    "Pixels do not prove layout in the installed app, accessibility-tree behavior, or VoiceOver navigation.",
                ]
            )
            try writeManifest(manifest, to: outputURL)
            print("Rendered \(cases.count) synthetic images to \(outputURL.path)")
        } catch ProbeError.usage {
            fputs("Usage: ups-render-probe --output-directory /existing/parent/new-directory\n", stderr)
            exit(2)
        } catch {
            fputs("Render probe failed; output may be partial. No application or data source was opened.\n", stderr)
            exit(1)
        }
    }

    private static func createOutputDirectory(arguments: [String]) throws -> URL {
        guard arguments.count == 2,
              arguments[0] == "--output-directory",
              arguments[1].hasPrefix("/") else {
            throw ProbeError.usage
        }

        let requested = URL(fileURLWithPath: arguments[1], isDirectory: true).standardizedFileURL
        let name = requested.lastPathComponent
        guard !name.isEmpty, name != ".", name != ".." else { throw ProbeError.usage }
        let parent = requested.deletingLastPathComponent().resolvingSymlinksInPath().standardizedFileURL

        var parentInfo = stat()
        guard lstat(parent.path, &parentInfo) == 0,
              (parentInfo.st_mode & S_IFMT) == S_IFDIR else {
            throw ProbeError.invalidOutputParent
        }

        let destination = parent.appendingPathComponent(name, isDirectory: true)
        var existingInfo = stat()
        if lstat(destination.path, &existingInfo) == 0 || errno != ENOENT {
            throw ProbeError.outputAlreadyExists
        }
        guard mkdir(destination.path, 0o700) == 0 else { throw ProbeError.outputCreateFailed }

        var createdInfo = stat()
        guard lstat(destination.path, &createdInfo) == 0,
              (createdInfo.st_mode & S_IFMT) == S_IFDIR,
              createdInfo.st_uid == getuid(),
              (createdInfo.st_mode & 0o077) == 0 else {
            throw ProbeError.outputCreateFailed
        }
        return destination
    }

    @MainActor
    private static func renderMatrix(to directory: URL) throws -> [RenderCase] {
        let capturedAt = Date(timeIntervalSince1970: 1_800_000_000)
        let staleDate = capturedAt.addingTimeInterval(120)
        let freshDate = capturedAt.addingTimeInterval(5)
        let staleSnapshot = syntheticSnapshot(capturedAt: capturedAt, charge: 11, largeReadings: true)
        let freshSnapshot = syntheticSnapshot(capturedAt: capturedAt, charge: 74, largeReadings: false)
        let stalePayload = WidgetSnapshot(publishedAt: capturedAt, acquisition: .active,
                                          maximumAge: 30, snapshot: staleSnapshot)
        let freshPayload = WidgetSnapshot(publishedAt: capturedAt, acquisition: .active,
                                          maximumAge: 30, snapshot: freshSnapshot)
        let missingPayload = WidgetSnapshot(publishedAt: freshDate, acquisition: .noSources,
                                            maximumAge: 30, snapshot: nil)

        let menu = UPSMenuContentView(
            sources: [staleSnapshot],
            selectedSourceKey: UPSMonitorFormatters.sourceKey(for: staleSnapshot),
            readState: .ready,
            now: staleDate,
            maximumAge: 30,
            acquisitionSucceeded: true,
            onSelect: { _ in },
            onRefresh: {},
            onOpenDetails: {}
        )

        let items = [
            widgetCase(file: "widget-small-dark-stale-standard.png", scenario: "widget-small-dark-stale-standard",
                       width: 180, height: 180, scheme: "dark", capturedAt: capturedAt,
                       presentationDate: staleDate, textSize: "standard", payload: stalePayload, medium: false),
            widgetCase(file: "widget-small-dark-stale-accessibility.png", scenario: "widget-small-dark-stale-accessibility",
                       width: 180, height: 180, scheme: "dark", capturedAt: capturedAt,
                       presentationDate: staleDate, textSize: "accessibility2-requested", payload: stalePayload,
                       medium: false, accessibilityTextSize: true),
            widgetCase(file: "widget-medium-light-current.png", scenario: "widget-medium-light-current",
                       width: 380, height: 180, scheme: "light", capturedAt: capturedAt,
                       presentationDate: freshDate, textSize: "standard", payload: freshPayload, medium: true),
            widgetCase(file: "widget-medium-dark-large-power.png", scenario: "widget-medium-dark-large-W-VA",
                       width: 380, height: 180, scheme: "dark", capturedAt: capturedAt,
                       presentationDate: freshDate, textSize: "standard",
                       payload: WidgetSnapshot(publishedAt: capturedAt, acquisition: .active, maximumAge: 30,
                                               snapshot: syntheticSnapshot(capturedAt: capturedAt, charge: 74,
                                                                           largeReadings: true)), medium: true),
            widgetCase(file: "widget-small-light-no-sources.png", scenario: "widget-small-light-missing-data",
                       width: 180, height: 180, scheme: "light", capturedAt: capturedAt,
                       presentationDate: freshDate, textSize: "standard", payload: missingPayload, medium: false),
            viewCase(file: "menu-light-single-source-stale.png", scenario: "menu-light-single-source-stale",
                     width: 300, height: 260, scheme: "light", capturedAt: capturedAt,
                     presentationDate: staleDate, textSize: "standard", view: AnyView(menu), background: .white),
            viewCase(file: "energy-light-paused-missing.png", scenario: "energy-light-input-paused-ups-missing",
                     width: 420, height: 220, scheme: "light", capturedAt: capturedAt,
                     presentationDate: freshDate, textSize: "standard",
                     view: AnyView(UPSEnergySummaryView(estimates: [energyEstimate(.input, state: .paused,
                                                                                   energyWh: nil, coverage: 0,
                                                                                   breaks: 1, source: nil)])),
                     background: .white),
            viewCase(file: "energy-dark-large-two-channels.png", scenario: "energy-dark-large-values-two-channels",
                     width: 420, height: 240, scheme: "dark", capturedAt: capturedAt,
                     presentationDate: freshDate, textSize: "standard",
                     view: AnyView(UPSEnergySummaryView(estimates: [
                        energyEstimate(.input, state: .estimated, energyWh: 987_654_321.125,
                                       coverage: 99_999_999, breaks: 2, source: freshSnapshot.source),
                        energyEstimate(.ups, state: .estimated, energyWh: 1_234_567_890.5,
                                       coverage: 88_888_888, breaks: 1, source: freshSnapshot.source),
                     ])),
                     background: Color(red: 0.10, green: 0.10, blue: 0.10)),
        ]

        precondition(items.count <= 16)
        return try items.map { item in
            var view = AnyView(item.view
                .frame(width: CGFloat(item.metadata.widthPoints), height: CGFloat(item.metadata.heightPoints))
                .background(item.background)
                .environment(\.colorScheme, item.metadata.colorScheme == "dark" ? .dark : .light))
            if item.metadata.textSizeEnvironment == "accessibility2-requested" {
                view = AnyView(view.environment(\.dynamicTypeSize, .accessibility2))
            }
            let renderer = ImageRenderer(content: view)
            renderer.proposedSize = ProposedViewSize(width: CGFloat(item.metadata.widthPoints),
                                                     height: CGFloat(item.metadata.heightPoints))
            renderer.scale = CGFloat(item.metadata.scale)
            renderer.isOpaque = true
            guard let image = renderer.cgImage else { throw ProbeError.renderFailed }
            try writePNG(image, to: directory.appendingPathComponent(item.metadata.file))
            return item.metadata
        }
    }

    @MainActor
    private static func widgetCase(file: String, scenario: String, width: Int, height: Int,
                                   scheme: String, capturedAt: Date, presentationDate: Date,
                                   textSize: String, payload: WidgetSnapshot, medium: Bool,
                                   accessibilityTextSize: Bool = false) -> RenderItem {
        viewCase(file: file, scenario: scenario, width: width, height: height, scheme: scheme,
                 capturedAt: capturedAt, presentationDate: presentationDate, textSize: textSize,
                 view: AnyView(UPSWidgetView(payload: payload, date: presentationDate, isMedium: medium)),
                 background: scheme == "dark" ? Color(red: 0.10, green: 0.10, blue: 0.10) : .white,
                 accessibilityTextSize: accessibilityTextSize)
    }

    @MainActor
    private static func viewCase(file: String, scenario: String, width: Int, height: Int,
                                 scheme: String, capturedAt: Date, presentationDate: Date,
                                 textSize: String, view: AnyView, background: Color,
                                 accessibilityTextSize: Bool = false) -> RenderItem {
        let metadata = RenderCase(file: file, scenario: scenario, widthPoints: width, heightPoints: height,
                                  scale: 2, colorScheme: scheme, capturedAtUnixSeconds: Int(capturedAt.timeIntervalSince1970),
                                  presentationDateUnixSeconds: Int(presentationDate.timeIntervalSince1970),
                                  textSizeEnvironment: accessibilityTextSize ? "accessibility2-requested" : textSize)
        return RenderItem(metadata: metadata, view: view, background: background)
    }

    private static func energyEstimate(_ channel: MonitorEnergyChannel, state: MonitorEnergyState,
                                       energyWh: Double?, coverage: Double, breaks: Int,
                                       source: MonitorSource?) -> MonitorEnergyEstimate {
        let start = Date(timeIntervalSince1970: 1_799_900_000)
        let end = Date(timeIntervalSince1970: 1_800_000_000)
        return MonitorEnergyEstimate(channel: channel, source: source, state: state,
                                     energyWh: energyWh, coveredDurationSeconds: coverage,
                                     gapOrBreakCount: breaks, firstCapturedAt: start, lastCapturedAt: end,
                                     powerProvenances: [.driverDerived])
    }

    private static func syntheticSnapshot(capturedAt: Date, charge: Double, largeReadings: Bool) -> MonitorSnapshot {
        let source = MonitorSource(provider: .nut, id: "render-probe-source", sessionID: "render-probe-session",
                                   identityStability: .configured)
        let large = largeReadings ? 987_654_321.125 : 184.5
        let metrics = [
            MonitorMetric(id: .batteryCharge, value: charge, unit: .percent, quality: .available, provenance: .reported),
            MonitorMetric(id: .batteryRuntime, value: 1_980, unit: .seconds, quality: .available, provenance: .estimated),
            MonitorMetric(id: .inputVoltage, value: 231.5, unit: .volts, quality: .available, provenance: .reported),
            MonitorMetric(id: .upsRealPower, value: large, unit: .watts, quality: .available, provenance: .driverDerived),
            MonitorMetric(id: .upsApparentPower, value: large + 10, unit: .voltAmps, quality: .available, provenance: .driverDerived),
        ]
        return MonitorSnapshot(
            source: source,
            capturedAt: capturedAt,
            status: MonitorStatus(lineState: .onLine, quality: .available),
            metrics: metrics
        )
    }

    private static func writePNG(_ image: CGImage, to url: URL) throws {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else {
            throw ProbeError.pngWriteFailed
        }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { throw ProbeError.pngWriteFailed }
        try (data as Data).write(to: url, options: .withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private static func writeManifest(_ manifest: Manifest, to directory: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(manifest)
        let url = directory.appendingPathComponent("manifest.json")
        try data.write(to: url, options: .withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}
