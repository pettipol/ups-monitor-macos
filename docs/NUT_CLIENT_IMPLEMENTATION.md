# NUT Client Adapter

`NUTClient` runs one configured executable directly with Foundation `Process`.
It does not invoke a shell, discover an executable, probe available UPS names,
open a socket itself, start a driver, or issue UPS-changing commands. The
configured UPS name, caller-assigned source ID, and port are explicit. Hostnames
and remote addresses are rejected; the only endpoint accepted today is the
literal loopback address `127.0.0.1`.

## Required executable qualification

Configuration requires the caller to label the exact executable
`.completionHardened`. This is a declaration by the caller, not an automatic
binary inspection or a claim that any installed `upsc` has the required fix.
The qualified binary must support `-j`, `-A none`, and `-W`, and must reject
incomplete/stale list results. The adapter never retries without `-A none`,
switches to text output, or silently substitutes another executable.

This qualification requirement is necessary because the inspected upstream
`upsc` path can print syntactically valid partial JSON and exit zero after
truncated LIST input or an `ERR DATA-STALE` mid-list. Therefore successful
process exit plus parseable JSON alone does not prove that the server's full
variable listing was consumed. The adapter has no completion marker in the
`upsc -j` output with which to detect that condition. Only a separately
qualified completion-hardened executable is suitable for live use.

The stock stable NUT 2.8.5 client supports `-j` but does not support `-A none`,
so that release does not satisfy this adapter's required executable profile.
There is deliberately no fallback that would re-enable personal auth-file
discovery.

The separate [NUT client completion qualification](NUT_CLIENT_COMPLETION.md)
records a patched diagnostic `upsc` build passing six synthetic loopback
completion scenarios. The later opt-in integration test also passed these
scenarios through this Swift adapter. That is evidence for that build and
those cases only, not production packaging, TLS or physical UPS compatibility.

## Request and process bounds

The only argument vector is:

```text
-j -A none -W <connect-timeout-seconds> <ups-name>@127.0.0.1:<port>
```

The UPS name and source ID accept only ASCII letters, digits, `.`, `_`, and
`-`, up to 64 bytes. Ports are 1...65535; the connection timeout is 1...30
seconds. The total process deadline is separately bounded to 0.1...60 seconds
(default 8 seconds). Standard output is capped at 65,536 bytes by default and
cannot exceed the decoder's limit; standard error is capped at 4,096 bytes by
default. Both streams are drained concurrently without retaining stderr, in
bounded chunks so continuous output cannot starve deadline and termination
events. Standard input is `/dev/null`. An
output cap or deadline sends termination only to the `Process` child created
for that read; if it remains alive after 200 ms, the runner sends SIGKILL to
that same child PID and waits for its termination callback before returning.

The child receives a fixed minimal environment (`PATH`, `LANG`, `LC_ALL`, and
`NUT_DEBUG_LEVEL=0`) with no inherited HOME, authentication-discovery settings,
or debug verbosity. Errors are typed and do not include raw output, stderr,
arguments, environment, executable path, or host details. Nonzero exit, output
cap, deadline, cancellation, and invalid JSON reject the read. The caller must
keep a previous sample separately and mark it stale itself; this adapter never
returns a prior snapshot as success.

A shared in-process source gate permits one read at a time for each caller
source ID, even when multiple `UPSCClient` instances use that ID.

## Synthetic tests and remaining evidence

Tests compile a synthetic helper executable into a temporary directory and run
it directly. It checks the fixed argument vector, minimal environment, typed
snapshot mapping, nonzero exit redaction, partial JSON rejection, stdout cap,
deadline, cancellation, and overlapping-read rejection. It does not create a
socket or contact a NUT server.

These helper-only tests do not qualify real `upsc`. Separately, the opt-in
`UPSCInteropTests` exercised the actual patched client through this adapter
against six synthetic loopback scenarios, with observed read-only command
transcripts; see [the qualification record](NUT_CLIENT_COMPLETION.md).
Real-client timeout behavior, TLS/authentication, real-server freshness and
UPS compatibility still require separate qualification. No daemon, driver,
USB device or physical UPS command is run by the adapter tests.
