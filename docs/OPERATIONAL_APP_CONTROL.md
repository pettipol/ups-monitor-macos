# Operational app control: experimental component

The operational capture adapter and Swift session controller use an explicit v2
contract. The separately added [managed operational runtime](MANAGED_OPERATIONAL_RUNTIME.md)
supplies its fixed configuration, entrypoint and explicit UI mode. Native runtime
activation and app/widget or long-running hardware qualification remain separate.
The closed v1/H07 runtime and decoder remain separate.

## Python control and ownership

`app_controlled_operational.run_app_controlled_operational` accepts an immutable
`FixedOperationalProfile` (argv, executable SHA-256, dependency pins), one
read-only FIFO, private output/feed directories and a source ID. Rejected
admission leaves the descriptor owned by its caller. Accepted admission owns
one watcher and invokes `capture_operational` exactly once.

STOP followed by newline, EOF, invalid control input and SIGINT/SIGTERM request
the same cancellation Event. The watcher parses at most five bytes; it never
accepts a device command. No lifetime limit or cumulative output cap is added to
the operational runner's existing health/rate policy. There is no retry or
automatic reconnection.

A valid unresolved capture receipt is observed every 250 ms on the same call.
This wait can be indefinite when ownership cannot be resolved. Unknown capture
or observer outcomes cancel, attempt control cleanup and return unresolved while
retaining the capture owner. A future managed entrypoint must keep its process
alive in that case; it must not interpret a returned function as cleanup proof.
Watcher start exceptions are ambiguous: a possibly started watcher retains its
descriptor, including when `Thread.start()` starts the thread and then raises.

The adapter receipt contains the entire `OperationalCaptureResult` and nested
`StreamingRunResult`, plus `control_reason`, `adapter_error`,
`watcher_quiesced` and `ownership_resolved`. Capture resource cleanup, watcher
quiescence, control close and signal-handler restoration are independent facts.
Logical control or publication failure may coexist with proven resource cleanup.
Sample counts are bounded by `2**53-1`; cumulative runner byte counts use
`2**63-1`. Neither has the v1 24-sample/1-MiB lifetime ceiling.

## Swift managed receipt

The envelope has exactly `protocol`, `schema_version`, `launch_id`, `adapter`:
protocol `ups-monitor.managed-operational.v2`, schema 2 and the exact launch UUID.
Capture source identity is `apcmicrolink-hidapi-operational`. This is a separate
contract from the schema-2 sample file read by `NUTOperationalSampleReader`.

`ManagedOperationalReceipt` validates nested shapes, primitive types, integer
ranges, identities and known reasons. Clean Stop requires cancelled End,
cancelled runner/return code zero, successful terminal publication and every
cleanup fact. Failed publication can still settle ownership and remains failed
in the controller. Only null, `invalid_control` or `control_failed` adapter errors
can coexist with cleanup; setup/start/join/close/handler/unknown-result errors
cannot release the ownership marker through a contradictory receipt.

The existing process controller has an internal operational branch. Receipt
alone never clears its durable marker: valid receipt, process completion, both
pipe EOFs, output bounds and exit zero are required. The controller never retries.
The existing v1 receipt decoder and projection remain unchanged. The explicit v2
configuration/entrypoint is documented separately; there is no automatic profile
selection.

## Offline evidence

On 2026-10-27 the isolated final test runs passed 47 Python tests (20 operational,
27 unchanged v1) and 27 Swift tests (9 operational, 18 unchanged v1). Synthetic
capture/observer and process handles cover Stop, EOF, malformed control, delayed
cleanup, ambiguous watcher start, handler restoration, contradictory receipts,
failed-but-resolved publication and durable ownership. Source and captured test
outcomes were independently reviewed. An earlier 26-test Swift run predates the
added contradictory-adapter-error regression and is retained as intermediate
evidence, not added to the final unique test total.

These runs did not start an app, driver, USB session or widget. Runtime packaging,
an actual producer-to-app session, GUI Stop/Quit, WidgetKit rendering, bounded
hardware qualification and release remain separate work.
