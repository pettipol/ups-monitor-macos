# Widget UI

`UPSWidgetUI` provides `UPSWidgetView`, a pure SwiftUI view over an optional
validated `WidgetSnapshot`. It performs no file access, acquisition, history
queries, `WidgetCenter` calls, or hardware operations. A missing shared payload
can be accompanied by a redacted, user-facing unavailable reason.

The small presentation shows a generic provider label, battery charge, line
state at capture, capture timestamp, and relative age. The medium presentation
adds estimated runtime and UPS real/apparent power with their W/VA units and
provenance. Missing measurements remain “Not reported”; zero remains a value.
No source identifiers or provider metadata beyond the provider category are
rendered.

Read failure, stopped acquisition, no sources, stale capture, and unavailable
shared data remain distinct. A retained sample is labeled as a capture, not a
live reading. Relative age uses SwiftUI's system-updating relative date text;
staleness is evaluated against the provider's entry date. WidgetKit still
controls when entries are presented, so no exact refresh cadence is promised.
The view has no refresh or control actions.

`UPSWidgetViewTests` uses only synthetic model and payload fixtures. These tests
cover presentation state, missing versus zero charge, age/staleness, and metric
units/provenance. WidgetKit container appearance, extension registration,
timeline scheduling, signing, App Group access, and visual rendering have not
been verified by this target.
