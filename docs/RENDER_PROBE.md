# Synthetic Offscreen Render Probe

`ups-render-probe` renders a small, fixed set of in-memory fixtures through
SwiftUI `ImageRenderer`. It is separate from the application and WidgetKit
provider. It does not instantiate `MonitorAppModel`, access IOKit or history,
open an App Group, request notification permission, create a window, or call
`NSApplication.run`.

## Run

Build and invoke the helper with a required new output directory beneath an
existing parent directory:

```sh
swift run ups-render-probe --output-directory /absolute/existing-parent/new-render-dir
```

The final directory must not exist, including as a symlink. The probe creates
it with owner-only permissions and refuses an existing destination. Output is
synthetic PNG images plus a JSON manifest. Choose a dedicated location for each
run; the helper never overwrites or cleans up prior output. It accepts no data
source, snapshot file, app configuration, or arbitrary scenario arguments.

The fixed matrix contains eight chosen canvases:

| File | Scenario | Canvas |
|---|---|---:|
| `widget-small-dark-stale-standard.png` | stale, dark, ordinary text-size environment | 180 x 180 points |
| `widget-small-dark-stale-accessibility.png` | same fixture with accessibility text-size environment requested | 180 x 180 points |
| `widget-medium-light-current.png` | current, light, ordinary text size | 380 x 180 points |
| `widget-medium-dark-large-power.png` | dark, very large synthetic W and VA readings | 380 x 180 points |
| `widget-small-light-no-sources.png` | light, no-source/missing-data state | 180 x 180 points |
| `menu-light-single-source-stale.png` | single-source menu with stale synthetic capture | 300 x 260 points |
| `energy-light-paused-missing.png` | input estimate paused; UPS channel missing | 420 x 220 points |
| `energy-dark-large-two-channels.png` | two channels with very large synthetic estimates | 420 x 240 points |

These dimensions are probe inputs, not claims about system WidgetKit family
dimensions. The manifest records the exact scenario and synthetic capture and
presentation timestamps used for each image, plus actual render time, locale,
and time zone. Relative-date text uses the host clock and locale, so pixels are
not deterministic even though fixture inputs are fixed. The accessibility size
is an environment request; the renderer or macOS may not honor it identically.

The widget/menu `ProgressView` can appear as a renderer placeholder (the
initial review showed a yellow blocked bar). That is an `ImageRenderer` limitation,
not evidence of a production widget defect. Apple documents that the renderer
may omit or substitute complex controls, Core Animation content, and AppKit
views in [`ImageRenderer`](https://developer.apple.com/documentation/swiftui/imagerenderer).
Do not change production controls to match a renderer placeholder.

The details screen is deliberately excluded: its scroll view, grid, history
chart and dialogs would make a flat offscreen image too weak a proxy for its
interactive window layout.

## Limits

`ImageRenderer` is a SwiftUI offscreen renderer, not a complete reproduction of
the app or system widget host. The menu and widget are rendered from their
public view initializers; no app host model or WidgetKit provider runs. This
probe does not invoke a WidgetKit timeline, shared storage provider, extension
container background, or system family sizing. It can help review raster
appearance and obvious fit problems at supplied sizes, but it does not establish
installed-app layout, full window/menu behavior, WidgetKit rendering,
accessibility-tree semantics, or VoiceOver navigation.

Rendered accessibility text size is only a requested environment variant.
Pixel images cannot prove spoken labels, control roles, reading order, keyboard
access, or focus behavior. Existing accessibility formatter and source-level
checks remain distinct from native VoiceOver review.

## Observed Check

On 2026-10-08 a local run produced eight correctly sized, nonblank PNGs with
owner-only output permissions. Text, units, missing-data and stale labels were
readable in the inspected canvases, including large W/VA and Wh values. This
is a bounded visual observation, not an exhaustive clipping or overlap test.
The ordinary and accessibility-requested small-widget images were byte-identical:
enlarged-text behavior remains unverified. Existing destinations and a dangling
symlink were refused, and the existing manifest remained unchanged.

The normal validation script builds this helper but does not run it. Rendering
is an explicit local operation; hosted CI does not provide raster, WidgetKit,
interaction or VoiceOver evidence.
