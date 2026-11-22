# App-owned capture adapter (offline candidate)

`run_app_controlled` is a synchronous main-thread adapter around the existing
`capture_continuous`. It creates one bounded control-reader thread and no process.
The capture supervisor remains responsible for its owned process group. The app
must keep the Python supervisor alive until it obtains a receipt; ordinary Stop
must never terminate Python.

The integrator supplies a frozen `FixedCaptureProfile` admitted independently by
executable hash. The adapter accepts only cancellation control frames from the pipe,
offers no CLI, and registers no operational or hardware profile. The public callable
injection is for synthetic testing. Admission is the integrator's responsibility;
constructing a dataclass is not proof of admission or a hardware authorization.

The app creates an anonymous pipe, transfers the sole read endpoint to this adapter,
and retains only the write endpoint. The supervisor must not retain a write duplicate:
EOF requires every writer to close. Both endpoints must be non-inheritable, and the app
must arrange descriptor transfer explicitly. The adapter marks its read endpoint
non-inheritable; the existing runner also uses `close_fds=True`. Pipe provenance and
the absence of writer duplicates are integration preconditions, not facts an fd can
prove.

The only accepted control frame is ASCII `STOP` followed by one newline. The first
exact five-byte frame requests cancellation and closes the read endpoint; all surplus
bytes are ignored regardless of transport fragmentation. For example, `STOP` plus
newline plus `X` requests Stop whether delivered together or one byte at a time. EOF
with no partial command requests cancellation for app loss. Any malformed prefix,
flood without a valid frame, or partial command at EOF cancels with a fixed
`invalid_control` error. A reader error cancels with `control_failed`. Reads are
nonblocking, at most five bytes, and buffered input never exceeds five bytes. Once a
complete command is accepted, no additional message is processed. Closing the reader
makes a blocked writer fail with broken-pipe semantics; the app must handle that
result without retry.

SIGINT and SIGTERM set a flag that the control reader converts to the same cancellation
event within its normal 25 ms poll, subject to OS scheduling. The original handlers
are restored after capture returns. Concurrent or recursive invocations are rejected
before descriptor transfer. Every API rejection before transfer raises
`AppCaptureAdmissionError`, a `RuntimeError` with a fixed `code`. Only that exception
proves that the caller still owns the read descriptor; the caller may then close it.
Unexpected pre-admission failures use `admission_failed`. After admission, the adapter
uses its failed-receipt path and retains ownership when cleanup is unproved. An invalid
`FixedCaptureProfile` constructor remains a separate `ValueError` before this API is
called. The capture settings are fixed: 120-second duration, 135-second supervisor
timeout, 2-second termination grace, 1 MiB combined output, and a 2-second tailer join
bound. Frozen baseline hashes and dependency pins are unchanged.

The limit is one active invocation, rather than one invocation for the lifetime of
the interpreter. A later explicitly requested invocation is permitted only after
resolved ownership; the adapter never starts one automatically. The Python latch
cannot prove that no session remains after restarting the app or supervisor. The
future app controller must preserve and reconcile unresolved ownership across that
lifecycle before permitting another launch.

Return is a receipt, not a cleanup promise. The original `CaptureResult` is preserved,
including `unreaped`, publication errors, and tailer quiescence. A clean runner receipt
plus a quiescent tailer and control reader and no publication error resolves ownership.
Any publication error conservatively retains ownership: the existing capture receipt's
tailer flag alone does not prove that its thread has terminated when publication
failed. An exception, unknown runner state, live worker, or control error also retains
failure and prevents another invocation for the lifetime of the process. There is no
reset/retry API. A resolved failure may still be displayed as failure: ownership
resolution does not mean successful data acquisition. In particular, Stop does not
rewrite the existing capture's `failed`/`cancelled` result as clean duration.

The reader join is bounded at two seconds and the caller must not close an fd still
owned by a live worker. There is no strict total wall-clock guarantee for an OS-blocked
capture operation: without a capture receipt the call remains pending, the supervisor
remains alive, and the app must continue showing stopping or unresolved ownership. No
retry or claim of successful cleanup is allowed.

The candidate tests use only synthetic receipts, threads, and owned anonymous pipes.
They launch no child process and do not touch driver or USB code. Capture injection
checks adapter routing; it does not requalify the existing supervisor, hash
verification, tailer, GUI, packaging, or hardware behavior. Tests are not executed by
the author before coordinator review.

## Coordinator results (2026-10-26)

The offline focused set passed 59 tests: 8 managed-workspace tests, 12 managed-root
resolver tests, 27 adapter v2 tests, and 12 synthetic stream tests. The v2 adapter set
supersedes the earlier 24-test v1 result. The full suite was not run.

A separate synthetic integration exercised Stop, EOF, and normal completion. Stop
finished at 5.144 seconds with two samples; EOF at 5.201 seconds with two samples;
completion at 120.173 seconds with 24 samples. Each scenario reported resolved
cleanup, with watchers and tailers quiesced. Captured producer output totaled 48,029
bytes. Thirteen result files totaling 59,372 bytes were archived and their hashes
verified. Stop and EOF retain their `failed/cancelled` terminal outcomes; completion
ends as `stopped/duration_complete`.

The managed-root resolver, adapter v2, tests, and an eight-file managed synthetic
developer candidate have been integrated into the canonical source tree. The focused
injected test count is 95: the previous 59 plus 24 Swift and 12 Python tests for the
managed candidate. Within that Swift result, the current 10 core tests supersede an
earlier 7-test core run; those earlier tests are not added again. The full suite was
not run.

## Managed synthetic developer path

The candidate is enabled only by the explicit developer launch flag
`--managed-synthetic-session`. The UI action is labeled **Start synthetic 120 s**.
Stop and Quit send the cancellation frame through the supervisor input pipe; the app
does not terminate the Python process, signal it, or apply a termination timer. An
unresolved owner marker keeps the session blocked and can keep Quit cancelled.

Before signing the developer build, package a local `ManagedSyntheticRuntime`
resource containing exactly seven reviewed Python source files:

- `managed_synthetic_entrypoint.py`
- `app_controlled_capture.py`
- `continuous_capture.py`
- `continuous_protocol.py`
- `process_deadline.py`
- `synthetic_continuous_feed.py`
- `synthetic_continuous_stream.py`

The candidate's `runtime.json` has exactly `python_path`, `python_sha256`, and
`module_sha256`; the last field maps those seven filenames to their SHA-256 values.
The manifest and local interpreter are verified before launch. There is no path
chooser, environment override, or runtime command field.

The existing App Group reader and publisher path is unchanged. The developer mode
feeds a synthetic, explicitly unqualified presentation through that path. The
developer flag is not a hardware profile, does not enable operational capture, and
does not change the default-off behavior. The signed developer bundle is prepared,
but GUI, WidgetKit rendering, real process transport, EOF-on-app-exit behavior, and
hardware qualification are not established by the injected tests or static review.

Two small edits after the injected-test freeze were reviewed from their diffs:
removing three redundant pipe closes after process launch and hiding the hardware
caption in managed mode. The current source then passed an Xcode build (return code 0,
60.19 seconds, unchanged sources, no storage-guard errors), and the prepared signed
bundle passed its seven recorded verification steps. One developer app launch was
observed, but UI interaction was unavailable and Start was not pressed. GUI,
real process transport, Stop/EOF behavior, WidgetKit rendering, and hardware remain
NOT_RUN; the build and bundle verification do not establish an end-to-end app session
or hardware qualification.

The same lifecycle now also supports a separate fixed native profile. Its receipt
protocol and source must match the selected profile before ownership can resolve.
The native app branch, injected tests and host-local packaging are described in
[Managed native runtime](MANAGED_NATIVE_RUNTIME.md); none of those software checks
extends the collector's bounded hardware observation to daily operation.
