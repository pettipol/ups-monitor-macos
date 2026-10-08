# Bounded Process Runner

`backend/nut/process_deadline.py` is a stdlib-only helper for a future,
separately authorized test. It does not select or launch a driver by itself.
Callers must provide a fixed argv, an absolute executable path as `argv[0]`,
and that executable's expected SHA-256. It does not qualify consent, driver
arguments, USB behavior, or compatibility.

## Contract

`run_bounded(argv, *, executable_sha256, output_directory, timeout_seconds,
termination_grace_seconds=1, maximum_output_bytes=...,
private_nut_environment=False)` validates parameters and the executable before
spawning. It invokes an argv array with no shell and stdin attached to
`DEVNULL`. The executable must be an absolute, non-symlink regular executable
file whose hash matches.

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
only to that same child if still running. It closes the parent's pipes when the
direct child exits, even if a descendant inherited the write end. If EOF was
not observed on both pipes before closure, the result is `OUTPUT_INCOMPLETE`,
even when the direct child's return code is zero. The runner does not signal
descendants. It attempts bounded reaping after KILL and returns `UNREAPED` if
the OS does not report child exit within that bound. If an output I/O error
occurs and cleanup cannot reap the child, it raises the fixed
`child_unreaped` error code instead of hiding that state.

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
- Output files intentionally preserve raw private fixture or future test data.
  The caller owns their retention and deletion policy.
- Synthetic `sys.executable` tests prove only this subprocess boundary. A
  future caller still needs a fixed, reviewed argument set and separate
  authorization and hardware-safety qualification.
