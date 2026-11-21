# Operational streaming runner v2

`run_streaming` is an opt-in, isolated process-runner API. It does not change the v1 entry points and does not claim daily-operation qualification or integration with capture, native driver, Swift, or USB paths.

## API and bounds

`run_streaming` accepts the fixed executable and dependency pins, output location, cancellation event, and stdout sink. Its default phase budgets are 35 seconds for startup, 15 seconds without accepted progress, and 2 seconds for termination grace. Startup and progress budgets must be positive and may each be configured up to 600 seconds; termination grace cannot exceed 2 seconds. There is no overall session timeout or duration argument; 600 seconds is an input ceiling, not a session lifetime.

The runner starts one process group and combines stdout and stderr against a fixed 262,144-byte window anchored at spawn, with one-second windows. The result reports bounded byte counts and incremental SHA-256 digests of bytes read from the pipes. Counter overflow is an error; the saturated counter does not represent later bytes. The raw stdout/stderr files created for the streaming path remain empty; their hashes are not used as substitutes for the pipe-stream hashes.

The runner does not retry or replace a session. At most one unresolved owner is retained. `retained_streaming_ownership()` is observational: it does not send signals or retry. Ownership is released only after the leader is reaped, the process group is absent, both pipes reach observed EOF, and the consumer is quiescent. If any condition remains unproved, ownership stays retained and blocks another operational spawn.

The caller and sink share the cancellation event. The runner can request cancellation and manage process cleanup, but it cannot interrupt a callback already publishing. The sink must use the shared event to freeze active publication while still handling the terminal record and pipe EOF consistently.

## Evidence and limits

The isolated runner reports **17 policy tests** and **8 real-child lifecycle tests** passing. The separate legacy regression set reports **110 tests passing**. Two additional opt-in macOS probes passed against the same runner: a real inherited writer kept stdout open after the leader exited, then released it so observation could resolve ownership; a real forked descendant acknowledged a request after its leader exited, then production cleanup produced a registered NOTE_EXIT event, group absence, both EOFs, leader reap and consumer quiescence. These close those two previously simulated cases for the tested synthetic paths.

The opt-in probes use persistent owning hosts and finite synthetic children; they are separate from ordinary test discovery. Their results do not prove all possible OS failures, arbitrary descendant trees, or hardware behavior. An unresolved owner must remain retained, and a process exit alone is not evidence of full cleanup.

Full operational, native, Swift, and USB qualification is **NOT_RUN**. These results do not establish daily-operation readiness or hardware compatibility.
