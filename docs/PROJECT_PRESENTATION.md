# Project Presentation

This note records the public README's identity, visual, and evidence choices.
The README is for people deciding whether to inspect, build, or contribute to a
source preview; it is not an installation or compatibility promise.

## Identity and Badges

The project is presented as a local-first, read-only macOS UPS monitor. Its
header badges link to the actual GitHub Actions workflow, the original-code MIT
license, the package's declared macOS deployment target, and the source-preview
status. The macOS badge explicitly says “target”: macOS 14 is a package setting,
not runtime qualification. The source version `0.1.0-preview.1` follows the
canonical version file and is not a release tag or downloadable app.

The README includes [`images/project-mark.svg`](images/project-mark.svg), an
original MIT-licensed project identity mark, at 72 pixels. It is not the app
icon and is not an Apple, APC or NUT logo. The Apple glyph in the deployment-
target badge is only an indicator.

## App Images

The README includes two reviewed macOS application captures, with the complete
three-view gallery and provenance in [`SCREENSHOTS.md`](SCREENSHOTS.md):

- `images/app-details-synthetic.jpg` shows battery and input details.
- `images/app-power-synthetic.jpg` shows output, W, VA, and partial energy rows.
- `images/app-energy-history-synthetic.jpg` shows energy estimates and the
  charge-history chart.

All app captures show the running app's explicit Synthetic preview. Their readings
come from fixtures: they are not data from a UPS, and they do not depict an
installed WidgetKit extension. Keep that qualifier in captions and alt text if
the images are moved into another project document. Do not crop away the
synthetic-preview indicator in any derivative capture.

The offscreen probe batch remains separate under `.build`; the gallery contains
one representative medium canvas copied from that render with an explicit
placeholder warning. `ImageRenderer` can replace controls and does not reproduce
the widget host; see [`RENDER_PROBE.md`](RENDER_PROBE.md) and
[`SCREENSHOTS.md`](SCREENSHOTS.md). No installed-widget screenshot is available
or implied.

The visual-evidence document also records a partial synthetic interaction check:
details scrolling, the history-metric picker with a missing-data state, static
Refresh, and normal Quit/reopen. It is not full GUI acceptance; do not imply
menu-bar popover, source/backend selection, accessibility, VoiceOver or widget
interaction proof.

## Update Rules

- Keep a live GUI image only when its reviewed capture and provenance are in
  the repository; do not add broken placeholder links.
- Label synthetic content as fixture data and distinguish app screenshots from
  offscreen render output and system-hosted widget images.
- Keep live-device capability claims tied to the compatibility matrix and native
  baseline; a visual image is not telemetry or accuracy evidence.
- Keep version text synchronized with [`VERSION`](../VERSION) and
  [`VERSIONING.md`](VERSIONING.md). Never call a source-preview value a public
  app release.
- Preserve original project licensing separately from third-party notices.
