# Operational envelope reader

`NUTOperationalSampleReader` explicitly reads schema-2
`ups-monitor.continuous.v2` publication files. It does not autodetect, launch a
producer or replace the schema-1 `NUTContinuousSampleReader`.

The reader returns `MonitorSnapshot` values only for active sessions. Stopped
and failed envelopes are terminal even when they retain their last sample. A
reader that has observed a terminal cannot become active again. Callers still
need the session controller's completion/ownership receipt; the reader's fixed
`terminalSession` error does not expose the terminal reason.

Metric age comes from each observation timestamp, not a republished envelope.
Missing/invalid values are not zero. Derived W and VA depend on their respective
fresh load and static rating; battery runtime retains its estimated provenance.
The wire is validated before recovering an unavailable nominal from the cache.
Accepted exponent-form numbers are normalized only for this reader's projection,
without broadening the existing v1 text decoder. Nonfinite intermediate derived
calculations are rejected even if the underlying observations are stale.

The local reader checks ownership, permissions, file identity, symlinks, link
count and a 16-KiB payload limit. It preserves wide protocol counters through
`2^53 - 1`; conversion to `Date` has floating-point precision limits. The inherited
EINTR read loop has no explicit retry count/deadline. The byte bound is not a bound
on interrupted system calls.

## Focused tests

The new unit cases cover wide times, active/terminal states, stale observations,
derived dependencies, exponent values, malformed nominal fields after caching,
overflowing intermediate calculations, JSON errors, file size and symlinks.
The existing v1 reader tests remain unchanged.

`OperationalPublisherInteropTests` uses three byte-preserved outputs from the
real Python `AtomicOperationalPublisher`: active, stopped and failed. All input
identifiers, clock values and measurements are synthetic. The active fixture
contains exponent strings for charge and power; the terminal fixtures retain the
same sample and must not be exposed as active telemetry. Resources are bundled
only with the `UPSRuntimeTests` target.

Fixture generator input versions:

- `operational_publication.py`: `c84caa5eaa8519567247e6fadea939a951d052fed9fbdec1d1d74ba0a5e58ebe`
- `continuous_protocol.py`: `dceb66e08d937c582e34311b87f3f00fc1c333fb1c794aa75cea10951a13ab5e`

Run the focused repository tests with:

```sh
swift test --filter 'NUTOperationalSampleReaderTests|OperationalPublisherInteropTests|NUTContinuousSampleReaderTests'
```

The development qualification uses an isolated package containing the same
reader/model/data sources. It is distinct from a full application build, GUI or
WidgetKit verification, an operational producer/controller integration, and
hardware monitoring. No profile is enabled by adding this reader.
