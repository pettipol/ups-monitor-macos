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

The current source matrix contains sixteen chosen canvases:

| File | Scenario | Canvas |
|---|---|---:|
| `widget-small-dark-stale-standard.png` | stale, dark, ordinary text-size environment | 180 x 180 points |
| `widget-small-dark-stale-accessibility.png` | same fixture with accessibility text-size environment requested | 180 x 180 points |
| `widget-medium-light-current.png` | current, light, ordinary text size | 380 x 180 points |
| `widget-medium-dark-large-power.png` | dark, very large synthetic W and VA readings | 380 x 180 points |
| `widget-small-light-no-sources.png` | light, no-source/missing-data state | 180 x 180 points |
| `widget-medium-compact-rich.png` | compact medium, light, populated readings, inset 16 points | 329 x 155 points |
| `widget-medium-compact-partial.png` | compact medium, dark, partial data, inset 16 points | 329 x 155 points |
| `widget-medium-compact-large-stale.png` | compact medium, dark, large readings and stale data, inset 16 points | 329 x 155 points |
| `widget-medium-named-short.png` | named medium, short synthetic name, inset 16 points, plus 30-point synthetic-fixture banner | 329 x 185 points |
| `widget-medium-named-long.png` | named medium, 64-character synthetic name, inset 16 points, plus 30-point synthetic-fixture banner | 329 x 185 points |
| `widget-small-named.png` | named small, short synthetic name, inset 16 points, plus wrapping 40-point synthetic-fixture banner | 180 x 220 points |
| `widget-small-compact-apple-title.png` | Apple name with recognized technical suffix, compact visible title, 40-point synthetic-fixture banner | 180 x 220 points |
| `widget-medium-compact-apple-title.png` | same compact Apple title, partial readings, dark, 30-point synthetic-fixture banner | 329 x 185 points |
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

On 2026-10-11 the probe generated eleven PNGs. The coordinator visually
reviewed the three compact medium canvases listed above: six cells were visible;
load, input and output readings, units and provenance, and the not-reported or
stale states were legible without observed overlap in those canvases. This is a
bounded visual inspection only. No automated pixel checks were run, and this
does not establish WidgetKit layout, installation, or VoiceOver behavior. The
fixtures use a January 2027 presentation date while relative-date text follows
the host clock; that date mismatch remains a limitation.

### Named-Widget Source Cases (2026-10-11)

The three named cases use fixture snapshots and names beginning with
`Synthetic`; the long name is exactly 64 ASCII characters (64 UTF-8 bytes).
Each canvas displays `Synthetic fixture - not a connected UPS` above the
widget, while the widget view uses `isSyntheticFixture: false` so the named
production presentation branch is exercised. The banner is part of the canvas,
not the widget body. No UPS is connected or queried by these fixtures.

After offline tests and builds passed, a fresh run generated all fourteen
images. The coordinator inspected the three named canvases: the short medium
name, provider and six measurement cells were legible without observed overlap;
the long medium and small names were abbreviated with an ellipsis. The small
canvas still has the documented unsupported-control placeholder and abbreviated
footer. No automated pixel or VoiceOver checks were run. These remain offscreen
synthetic previews, not installed WidgetKit appearance or accessibility proof.

### Compact Apple Title (2026-10-11)

A subsequent run produced sixteen images. The two added cases use the complete
synthetic name `Synthetic Tower 1500 FW:UPS 9.9 / ID=9999` and an Apple fixture.
Root visually inspected both: the medium title shows `Synthetic Tower 1500`
and its provider without the technical suffix, with no observed overlap. The
small title still abbreviates the end of its provider and its footer; the
documented unsupported-control placeholder remains. This is not a WidgetKit
or VoiceOver test. No real reading is present in these images.
