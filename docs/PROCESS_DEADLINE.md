# Bounded Process Runner

`backend/nut/process_deadline.py` is a stdlib-only helper for a future,
separately authorized test. It does not select or launch a driver by itself.
Callers must provide a fixed argv, an absolute executable path as `argv[0]`,
and that executable's expected SHA-256. It does not qualify consent, driver
arguments, USB behavior, or compatibility.

## Contract

`run_bounded(argv, *, executable_sha256, output_directory, timeout_seconds,
termination_grace_seconds=1, maximum_output_bytes=...,
private_nut_environment=False, cancel_event=None, dependency_pins=())`
validates parameters and the executable before spawning. It invokes an argv
array with no shell and stdin attached to `DEVNULL`. The executable must be an
absolute, non-symlink regular executable file whose hash matches.
`cancel_event`, when provided, must be a `threading.Event`.

`dependency_pins` is an optional immutable tuple of closed `DependencyPin`
records. The default empty tuple preserves the legacy no-dependency path.
Each pin identifies a specific loader symlink, its literal relative target,
the loader-relative path, the canonical regular-file path and the expected
SHA-256. With pins, the runner hashes and snapshots the executable and each
dependency before creating output. After private output preparation, it repeats
the hashes and then checks executable identity, symlink identity/target and
loader resolution immediately before the final cancellation check and `Popen`.
The monotonic child deadline starts only after this audit. A mismatch returns
the fixed `hash_mismatch`, `executable_rejected` or `dependency_rejected`
error code. A late rejection closes descriptors but intentionally retains the
already-created private output directory and files; the child is not spawned. Cancellation
checks and outcomes remain in their existing order. This reduces, but cannot
eliminate, time-of-check/time-of-use races.

This is path/hash checking, not a Mach-O parser or atomic loader binding. The
closed profile must attest that its pinned loader path and symlink relationship
is the one used by the exact hash-pinned Mach-O executable; verifying an
arbitrary dylib is insufficient. A replacement after the final scan and
before/during loader resolution remains a TOCTOU risk.

## Cancellation

### Capture Metadata

`BoundedRunResult` retains its original five fields and accepts an optional
trailing `observation: CapturedRunMetadata | None = None`. Existing positional
constructors remain valid. The metadata contains the configured output limit,
verified executable pin, stdout/stderr SHA-256 and original Unix-second wall
clock samples. It contains no raw output, paths, argv or hardware identifiers.

Hashes are updated after each successful `_write_all`, for the same byte slices
added to the captured counts, including normal post-exit draining. Output
discarded after timeout/cancellation/overflow does not enter those hashes.
These hashes describe the original captured byte sequence, not a later file
read or a guarantee of disk durability or resistance to same-user modification.

Start is sampled after the last cancellation check immediately before `Popen`;
finish is sampled after the supervision/drain/reap path, before returning. This
does not measure an exact first-byte or last-byte time. Deadline arithmetic
remains monotonic. Failed, non-finite or inverted clock samples suppress only
metadata, not the existing process status, trigger, return code or exceptions.
Pre-spawn cancellation returns no observation. Negative run outcomes must not
be promoted merely because their partial-output metadata exists.

The separate pure `observation_receipt.encode_observation_receipt` validates
and serializes this metadata for the offline Swift bridge, with an output limit
of at most 1 MiB. The runner's existing larger limit is unchanged; receipts above
the bridge limit are rejected separately. No automatic JSON file is written,
and the operator CLI's seven-field response and empty profile registry remain
unchanged. See the [application contract](NUT_APP_CONTRACT.md#supervisor-receipt-bridge)
for the exact wire fields and qualification limits.

### Event Semantics

With no `cancel_event`, the legacy launch and timeout/output-limit behavior is
unchanged. A pre-set event is checked after argument validation and before
hashing or creating output files; it returns `CANCELLED` for both status and
trigger, with no child, no output directory, `returncode=None`, and zero byte
counts. The event is checked again after hash verification and immediately
before `Popen`, so cancellation observed in either interval avoids the spawn.
If it is set during output setup, the already-created empty output files remain
as the record of that attempted run.

When an event is supplied, only that child is started in a new session. This
does not enable process-group signalling: cancellation still targets only the
direct `Popen` child. Once `Popen` has returned and both pipe handles and the
selector are set up, the event is checked before the first child poll. If set,
the runner marks the trigger `CANCELLED` and uses the existing TERM, grace,
drain, KILL, and bounded-reap path. If cleanup reaps the child, status is
`CANCELLED`; if the child remains unreaped, status is `UNREAPED` while trigger
remains `CANCELLED`. A naturally exited child can therefore have its exit code
reported as cancelled when the event is observed before the first poll; this
does not claim that TERM was delivered.

The event check and `Popen` cannot be atomic. Cancellation during a blocking
hash, filesystem operation, process creation, or OS scheduling delay is only
observed at the next documented check. If timeout or output overflow was
already selected, that first trigger is preserved while the existing cleanup
runs; a later event does not rewrite it. This is cooperative cancellation, not
a hard deadline, process-tree cancellation, or guarantee that cleanup runs.

Do not call `Event.set()` directly from a SIGINT/SIGTERM handler; deliver the
request from normal execution context. Starting a new session when an event
is supplied does not close the check-to-`Popen` gap and does not make
`KeyboardInterrupt` inside process creation, `fork`, or `setsid` recoverable.
Any real NUT/USB use remains on `HOLD` pending its separate review and consent.

## Operator Adapter

`backend/nut/operator_stop.py` supplies the library function
`run_operator_controlled` with the same explicit bounded-run options except
`cancel_event`, which it owns internally. It is not a CLI, app integration, or
driver profile. It still requires the caller's fixed argv and executable hash.

The call must run on the main thread, cannot be nested, and requires SIGINT's
current handler to be `default_int_handler` or `SIG_DFL`. Custom handlers and
`SIG_IGN` are rejected before launching work. The adapter temporarily owns
SIGINT; its handler only sets a local flag. A normal main-thread loop translates
that flag into the cancellation Event while a non-daemon worker runs
`run_bounded`. Repeated requests are idempotent. It joins the worker before
restoring the prior handler, clearing its active guard before that restoration
so an interruption there cannot poison later invocations. Setup exceptions also
clear the guard. A main-loop exception requests cleanup and joins the worker
before propagation; the worker's result or BaseException is not reclassified.

The bounded helper remains responsible for first-trigger priority, TERM/grace,
draining, KILL and reaping of its direct child. `UNREAPED` remains `UNREAPED`;
a late stop does not rewrite an already returned result. The adapter does not
handle SIGTERM or signal a process group. Waiting for a worker in a stuck OS
operation is not a hard deadline. It does not close the check/spawn gap, prove
physical terminal Ctrl-C behavior during fork/setsid, undo USB effects, or
authorize any hardware use. App integration and a closed operational profile
remain absent.

### Historical Synthetic Evidence

The following counts and digests record earlier source snapshots only; they
are not evidence for the current dependency-pin integration or current file
hashes.

On 2026-10-12, Luna ran 39 process tests successfully: 11 adapter tests and
28 existing bounded-helper regressions. Root independently ran all 141 backend
tests and 14 privacy tests successfully; the 39 are included in 141, not added.
Sol reviewed source and fixtures before execution. No operational NUT executable,
USB/HID/IOKit access, service, app lifecycle or electrical test was involved.

Two tests use actual SIGINT sent only to their owned Python controller PID:
one holds executable verification behind a barrier until cancellation delivery
is acknowledged, then confirms no child/output directory; the other interrupts
a ready synthetic child, sends repeated requests during grace and observes
cooperative exit and its `atexit` marker. The test Event explicitly checks main
thread and execution outside the signal handler. Repeated sends do not prove a
particular number of delivered POSIX signals. Remaining tests cover mocked
result/error preservation, `UNREAPED`, non-main/nested/custom/ignored-handler
rejection and interrupted setup/restoration. This is not physical terminal
Ctrl-C or process-group testing, nor evidence of a real driver's cleanup.

Reviewed adapter SHA-256:
`b1dca13936ff00bdd5a1cd8e7464e7c2bfa651d87f17879e7c8d6c1b8ef4ed12`.
Tests SHA-256:
`740802f9e07b152045a0ce0fe1140057952259eb432c25266c0c71ebbae357fd`.
The underlying helper is unchanged from the prior cancellation candidate:
`45505a7d8cc6cbae6287ca6c995254da311aadac7130c237da2022b11a053efd`.

## Closed Operator CLI

`backend/nut/operator_session.py` connects a one-shot `main()` to the operator
adapter. The distributed `PROFILES` registry is empty and immutable. There is
no admitted UPS profile: this entry point cannot select an operational driver
without a separately reviewed source change. The app does not call this CLI.

The only session syntax is `--profile ID [--execute]`, in that order. No
arguments, or a known profile without `--execute`, returns `not_run`. Unknown
profiles, missing IDs and additional arguments are rejected without hashing,
creating output or invoking the adapter. Help is fixed content. Arbitrary
commands, paths, environment variables, NUT options and bounds cannot be supplied
through the CLI. The registry is a trusted-code boundary, not a Python sandbox.

An admitted profile must freeze a tuple argv, executable SHA-256, pre-existing
output parent, timeout, grace and output cap. The helper requires an owned,
non-group/world-writable parent (0755 is accepted); the fresh run directory
and its state/config subdirectories are 0700, with capture files 0600.
Execution calls the adapter once, with a fresh output-directory name and the
private NUT environment forced on.

The optional `dependency_pins` field defaults to the empty tuple. When present,
`OperatorProfile` requires an exact tuple of frozen `DependencyPin` records.
The CLI passes that same tuple object through `run_operator_controlled` to
`run_bounded`; neither layer reconstructs or widens it. The empty default
retains legacy behavior. The registry remains empty, so no private executable,
loader path or operational profile is embedded or approved by the product.
There is no retry, restart, fallback or automatic creation of the parent.
Raw output remains in the helper's private files. The JSON response contains
only status, trigger, return code, byte counts, `data_qualified=false` and a
fixed error code; it never includes raw child output, argv or paths.

Exit 0 means only a delivered `not_run`/help response or a delivered result
with `exited`, `completed` and child return code 0. It never qualifies UPS data.
Rejected arguments return 2; execution failures return nonzero, preserving
`unreaped`. Failure to write or flush the response must also return nonzero,
without rerunning the child. No error text is copied to stderr as a fallback.

Future hardware use still requires a separately admitted profile, values and
data-acceptance criteria, review of that exact executable and explicit consent
for the individual session. The empty registry is intentional, not permission
to enable a profile. Synthetic SIGINT-to-PID tests are not evidence of physical
terminal Ctrl-C, a hard OS deadline, USB recovery or electrical safety.

### Dependency-Pin Synthetic Evidence

Status: `PASS`, limited to synthetic local tests. Luna reports all 15 new
dependency-pin tests passing. Root independently ran all 168 backend tests
successfully (rc=0), including 54 process tests (the 15 new tests are included)
and 12 CLI tests; 14 privacy tests also passed separately (rc=0). These results
do not exercise an operational NUT executable, real loader behavior, USB,
IOKit, or hardware. No real compiler or TSan run was performed in this tranche;
any compiler-like strings in logs are mock test data. Final Sol source,
evidence and documentation review found no blocker in this synthetic scope.

Frozen source/test SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/nut/process_deadline.py` | `56f25ba1511b947ff9a54534cfa7b0f30e6c2ed531c000920e6951568620dc92` |
| `backend/nut/operator_stop.py` | `8eecb35587503463739871f2a0c2a4020d76cb66915e7a3f04e3210ac9766316` |
| `backend/nut/operator_session.py` | `95c3c032a31e0dc835194f3c938f192e877a55b28652c6d74cfb0a6f16818444` |
| `backend/nut/test_process_deadline_dependencies.py` | `4240ce4a05cb5aea036b080ca8b9524a698bff1e15c8eea2334bb481362fb658` |

The 141/153 backend-suite totals and adapter/CLI hashes in the historical
sections below belong to earlier source snapshots; they are not evidence for
these current files.

### CLI Synthetic Evidence

On 2026-10-12, Luna ran all 12 CLI tests successfully; root independently
ran all 153 backend tests and 14 privacy tests successfully. The 12 CLI and
39 existing process/adapter tests are included in 153, not added to it.
Sol reviewed the source and synthetic-process boundaries before execution.
Final Sol evidence/documentation review found no blocker in this offline scope.
The distributed profile registry remained empty. Tests call the real `main`,
adapter and helper using a registry containing only a synthetic Python child.

A source-review finding was fixed before runtime: a failed JSON write/flush
must not produce exit 0. The first runtime pass then exposed an incorrect
fixture expectation, reproduced by root: TERM-handler output is drained and
discarded after cancellation, not captured. Only the fixture changed. It now
waits for exactly `ready\n` to be captured before sending SIGINT to the owned
controller PID, then checks the preserved six bytes, zero stderr, cancelled
status/trigger, one spawn, TERM and `atexit` markers, restored signal handler,
private output modes and a single JSON response. The failed pass is retained
in the private evidence; it is not counted as a successful run.

CLI SHA-256: `3493b093605693093f99ec6586e0ac9f5cf9221504bf6334b341eb6f70d535c1`.
Final tests: `7915821c53d949f377bed654cce696356cf06d0ccebe2c3ee64ac5055e57ee00`.
Adapter/helper hashes above are unchanged. `scripts/check.sh` includes the
new test module, but the full Swift/Xcode validation entry point was not run
in this tranche. No operational driver, device or app lifecycle was involved.

## Output And Cleanup

The caller names a new output directory below an existing explicit parent. The
runner requires the parent to be a regular directory owned by the caller and
not group- or world-writable, checks that again on its open descriptor, rejects
an existing output directory, and creates the new directory as mode 0700. It
creates `stdout.bin` and `stderr.bin` exclusively as mode 0600 with no-follow
flags. Raw output remains there; result and error objects contain only status,
return code, byte counts, or fixed error codes, never argv, paths, or stderr
text.

The default child environment is a small fixed set (`PATH`, `LANG`, `LC_ALL`);
the parent environment is never inherited. With `private_nut_environment=True`,
the runner creates new mode-0700 `state/` and `conf/` directories below the
output directory and passes exactly `NUT_STATEPATH`, `NUT_CONFPATH`,
`NUT_DEBUG_LEVEL=0`, and `NUT_DEBUG_SYSLOG=stderr`. The pinned NUT source's
`common/common.c` `syslog_is_disabled()` supports this stderr-only setting;
it is not a guarantee against operating-system, crash or third-party logs.
The helper does not accept arbitrary environment overrides.

The monotonic deadline and combined output cap are enforced while draining
nonblocking pipes in bounded chunks. Timeout or output overflow signals only
the `Popen` child with TERM, waits for the configured grace, then sends KILL
only to that same child if still running. During grace/reaping, the parent keeps
known pipe handles open and drains/discards output with a per-turn byte budget;
bytes after the trigger are not persisted, so the capture cap remains in force
while a cooperative child's TERM handler can finish without encountering a
closed pipe. A bounded post-exit drain observes EOF where available. Only a
natural exit without a prior timeout/output-limit trigger can become
`OUTPUT_INCOMPLETE` when EOF was not observed on both pipes before closure;
post-trigger drain/discard preserves the original trigger (unless reaping
fails). Discarded output is not evidence that the child's application-level
cleanup ran. Cleanup can use direct readiness checks on known streams if
selector/nonblocking setup failed partway through. When no streams remain,
grace polling sleeps rather than spinning. The runner does not signal
descendants. It attempts bounded reaping after KILL and returns `UNREAPED` if
the OS does not report child exit within that bound. If an output I/O error
occurs and cleanup cannot reap the child, it raises the fixed `child_unreaped`
error code instead of hiding that state.

## Limits and Tradeoffs

- Hash verification and process creation are separate path operations. A
  hostile actor able to replace the executable in its containing directory can
  race the check; use a protected, immutable executable location. This helper
  does not claim descriptor-pinned execution. The hash covers the executable
  file only; it does not attest dynamically loaded libraries or runtime inputs.
- Hash preflight and output-directory setup occur before the process deadline.
  Hashing and regular-file writes can block, and a stuck OS call, process
  creation, or kernel scheduling cannot be made hard real-time by Python. The
  bounded reap path prevents an intentional unbounded `wait()` but cannot
  guarantee that the parent survives an OS hang or crash.
- Signalling this process does not undo USB claims, device state, child-driver
  effects, or external side effects. Closing inherited pipes is not process-tree
  management. Do not treat timeout as hardware recovery.
- An operator event is only a request to cancel this direct child. It does not
  authorize hardware access, undo child effects, cancel descendants, or prove
  that a caller's argv or operating procedure is safe.
- Output files intentionally preserve raw private fixture or future test data.
  The caller owns their retention and deletion policy.
- Synthetic `sys.executable` tests prove only this subprocess boundary. A
  future caller still needs a fixed, reviewed argument set and separate
  authorization and hardware-safety qualification.
