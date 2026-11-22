# Offline continuous file-feed bridge

This document describes the Python side of the experimental v1 continuous-feed
contract. The API is opt-in and has no operational profile registry or command
line entry point for real executables. Hardware access, candidate installation,
and a live campaign are outside its scope.

## Components

- `backend/nut/continuous_protocol.py` accepts only complete UTF-8 NDJSON lines
  with the frozen protocol discriminator, exact keys, 17-field allowlist,
  duplicate-key rejection, numeric and status validation, alias and dependency
  checks, sequence/slot rules, and a terminal record.
- `backend/nut/continuous_capture.py` provides `capture_continuous(...)`. It
  samples wall and monotonic anchors immediately before invoking its supplied
  runner function, invokes `run_bounded` synchronously on the caller thread,
  and starts a daemon tailer that reads only the owned `stdout.bin`. Tailer
  failures set the same cancellation event consumed by the supervisor. The
  tailer cannot launch a process. A terminal phase blocks any later active
  publication, then the caller performs a bounded join and writes the terminal
  envelope.
- `backend/nut/synthetic_continuous_feed.py` writes visibly simulated feed
  files for interface work. It reuses the atomic publisher, sets the
  `synthetic-ups-feed` logical ID, and contains no hardware discovery or
  process-launch path.

## Caller-owned paths and API

The caller creates an owner-only `0700` output root and feed directory. The
capture function creates only the unique output child through `run_bounded` and
publishes `sample.json` in the supplied feed directory. The configured source
identifier is a logical label. A fresh session identifier is generated for
each invocation. The consumer must pin both identifiers out of band.

On macOS the publisher checks extended ACLs through `acl_get_fd_np` and rejects
nonempty or unreadable ACL state. It pins the feed directory and its parent by
descriptors, checking owner, mode, identity and ACL before and after each
replacement. Temporary and final files must be owner-only, single-link regular
files with no extended ACL.

Production defaults are the frozen 135-second supervisor timeout, 2-second
termination grace, 1 MiB combined captured-output cap, and 120-second driver
duration requirement. Tests can inject a synthetic runner, clocks, and shorter
duration budget; those seams do not register or activate an operational profile.
The API accepts a caller-supplied fixed argv and executable hash because a later
private profile owner supplies those values after its own gate. The API itself
does not choose an executable or construct a command.

The tailer waits for the supervisor-created stdout file, opens it with
no-follow semantics, pins its file identity and metadata, checks that consumed
bytes remain an unchanged prefix, and reads only appended bytes. Truncation,
replacement, unsafe metadata, partial final lines, protocol violations,
and output overflow cancel the owned run. stderr remains drained by
`run_bounded` and never enters the sample parser. No stdout or stderr content is
copied into errors or returned diagnostic strings.

The terminal envelope uses `stopped` only for a clean, reaped zero exit with a
`duration_complete` end record at or beyond the configured duration and a
quiesced tailer. The tailer cannot replace an active sample after the terminal
latch. If it does not quiesce or its publication lock cannot be acquired within
the bound, the API returns a failed receipt and does not close a descriptor in
use or claim that a terminal file replacement succeeded. Other outcomes use `failed` and one of the fixed terminal
reason tokens. A terminal publication error is returned separately as the
fixed `publication_failed` token; no success is reported for it. An OS-level
blocked file operation cannot be given a strict kernel completion guarantee;
the bounded join therefore reports failure when the tailer remains alive.

## Synthetic feed

Create an existing private directory, then run the helper with `--directory
PATH`. Its maximum duration is 120 seconds and its interval is fixed at five
seconds. `--once` writes one active synthetic sample for interop checks. Values
are deliberately declared synthetic and differ from hardware evidence. The
helper does not import or invoke USB or NUT driver modules, and it launches no
process.

## Boundaries

This bridge does not qualify native descriptor provenance, device lifecycle,
Swift parsing, GUI projection, WidgetKit cadence, actual UPS compatibility, or
physical release. A successful synthetic test demonstrates only the Python
parser, owned-file tail, supervisor integration seam, and atomic publication
for the tested fixture.

