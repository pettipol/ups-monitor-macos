# Bundled operational runtime (experimental, disabled by default)

The bundled runtime is a separate experimental packaging path for the managed
operational profile. The existing host-managed schema v2 remains unchanged.
The public release pin is still `nil` in
[`BundledOperationalReleasePins.swift`](../Sources/UPSRuntime/BundledOperationalReleasePins.swift),
so this source checkout does not enable or admit a bundled runtime by default.

## Package layout and admission

The candidate stages a complete CPython 3.15.2 arm64 runtime under
`Contents/Resources/PythonRuntime`, alongside the managed backend, manifest and
native producer. Staging and normalization check a closed file/link inventory
and preserve the source. A compiled Swift manifest pin admits the complete
bundle; the runtime cannot supply or override that pin.

The [candidate preparation utility](BUNDLED_CANDIDATE_PACKAGER.md) creates the
managed backend, inventory, manifest and derived Swift pin from an explicitly
prepared staging tree. It preserves the runtime, native producer and checkout
sources. It does not build or sign an app, verify signatures, or execute the
payload. Its small synthetic contract suite is part of `scripts/check.sh`.

The local package used ad hoc signatures for the runtime Mach-O files, the
synthetic producer and the assembled app/widget bundle. Local signature
verification succeeded after assembly and after relocation. Ad hoc signing is
not an Apple Developer identity, notarization or a distribution signature.
The full runtime deliberately places some Mach-O code below `Resources`.
[Apple TN2206](https://developer.apple.com/library/archive/technotes/tn2206/_index.html)
recommends `Contents/Resources` for scripts and other non-Mach-O executables;
code outside expected nested-code locations is sealed as resource data as well
as by its inner signature. This full-runtime layout remains a packaging
exception under review. Local signature success does not establish Apple's
approval of the layout or guarantee future acceptance by verification or the
Mac App Store. Validate this design and its whole-app update behavior before
release.

## Local synthetic evidence

A separate, bounded Foundation/AppModel host exercised the managed consumer
path against the assembled bundle and its synthetic C producer. It received two
samples, resolved Stop and Quit, completed the managed receipt and cleanup, and
did not relaunch the session. The same host passed with the bundle at its
original location and after copies to paths containing spaces and Unicode; the
relocated copies passed signature verification. This host is not the main app.

`MonitorCoordinator` schedules producer refreshes at five-second intervals.
`MonitorAppModel` projects the coordinator's cached state about once per
second; the qualification host observes it in a bounded approximately
50-millisecond polling loop. Neither cadence is a latency guarantee. In the
local run, the feed had advanced at the historical eight-second checkpoint
while the AppModel still exposed the prior sample; the second sample was
validated later. The eight-second second-sample target is **not qualified**.
The candidate must not be described as providing immediate UI updates.

The evidence is a local synthetic qualification, not a public reproducible
packaging command. The candidate checkout's public test entry point runs
synthetic contracts, but it does not reproduce signing, complete bundle
assembly or the Foundation/AppModel session.

## Not qualified

The main app and live widget were not launched or rendered. No real UPS,
hardware driver or USB interface was used. This does not qualify daily
monitoring, clean-host behavior, Gatekeeper, notarization, Intel, older macOS
releases, or distribution. The bundled profile remains disabled by the public
default until those separate release gates are completed.

The bundled `serve()` path does not include the separate 180-second fuse used
by the bounded hardware candidate. A live diagnostic candidate needs its own
reviewed execution limit and hardware qualification; this packaging output
does not supply them.
