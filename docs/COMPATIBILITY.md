# Compatibility and Qualification

This table distinguishes a local observation from source settings, synthetic
tests and unqualified behavior. It does not promise support beyond the evidence.

| Area | Evidence | Status / limit |
|---|---|---|
| Build toolchain | Xcode 27.0, Swift 6.4, macOS SDK 27.0; local source/app build recorded in project docs | Build evidence only; not a release artifact or runtime matrix |
| Deployment setting | Swift package declares macOS 14+ | Deployment target is not proof of runtime compatibility on macOS 14 |
| Native Apple UPS read | One native read on a macOS host | One observation only. Apple status, battery charge (ratio) and battery voltage (V) were reported; AC voltage and active watts were unavailable. No device-specific compatibility, sustained, sleep/wake, accuracy or multi-device qualification |
| Intel Mac | No local runtime evidence recorded | Not qualified |
| NUT model/data path | Synthetic decoder and client fixtures; patched `upsc` interop fixture uses a temporary loopback server | Synthetic only; no live NUT server or UPS compatibility demonstrated |
| Experimental `apcmicrolink` driver | Pinned experimental NUT source and guarded patch reviewed/built offline | Hardware and USB behavior `NOT RUN`; not part of the app bundle, not a read-only path, not authorized for routine use |
| NUT stable 2.8.5 | Dependency baseline records that this version does not contain `apcmicrolink` | Does not imply compatibility for other NUT devices or drivers |
| Widget extension | Source builds, synthetic bridge tests; authorized local Apple Development SharedRelease signature verified and exact extension path listed in plug-in registry | Signing passed; App Group runtime access, intended extension selection, installed widget rendering and refresh remain unqualified. See [signing evidence](WIDGET_SIGNING.md) |
| Offscreen visual probe | Eight synthetic widget/menu/energy component canvases rendered locally with ImageRenderer | Partial raster review only. Progress controls are placeholders; the ordinary/accessibility-requested pair was pixel-identical. No installed widget, enlarged-text or VoiceOver qualification |
| Running synthetic app | Authorized restart and partial interactive check on 2026-10-08; [window captures](SCREENSHOTS.md) | Scrolling, history-metric selection, static Refresh and normal Quit/reopen observed. Not full UI, source/backend, export, menu-bar popover or VoiceOver qualification |
| Energy estimates | Synthetic active-watt integration and app-host tests passed in the 231-test local Swift suite; one synthetic app window visually checked | No live watt source, real-UPS energy result, meter comparison or accuracy claim has been qualified |

The qualitative one-read capability record is in
[`NATIVE_BASELINE.md`](NATIVE_BASELINE.md); it is not a device, USB or protocol
compatibility test.
NUT source/build and licensing boundaries are in
[`NUT_FEASIBILITY.md`](NUT_FEASIBILITY.md), [`NUT_GUARDS.md`](NUT_GUARDS.md),
[`NUT_UPSTREAM_STATUS.md`](NUT_UPSTREAM_STATUS.md), and
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

No compatibility claim should be inferred from the macOS SDK version, the
deployment target, synthetic fixtures, a successful compile, or a source-level
guard. Real driver work has additional safety and consent gates; see
[`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md).
