# NUT Client Contract

This describes the application reader to be implemented and tested. It does not
authorize launching an UPS driver or an existing system service.

## Reuse

Use NUT's read-only `upsc` client as the initial protocol implementation instead
of introducing a new networking stack. The pinned upstream source exposes JSON
variable output through `-j` (`clients/upsc.c`, lines 175-234) and opt-out from
automatic authentication-file discovery through `-A none` (lines 509-530).
Do not assume an arbitrary older executable supports those flags.

The inspected upstream revision has a reproduced completion bug: `upsc` can
exit successfully with valid partial JSON when a variable list is interrupted.
The client must use a completion-hardened, explicitly qualified build, not merely
an executable with the right version string. See [the reproduction and patch](NUT_CLIENT_COMPLETION.md).

The app adapter must invoke one configured, validated executable directly, not
through a shell. Its argument builder has one operation: read the variables of
one explicit UPS. There is no caller-supplied argument list or command string,
nor an interface for `upscmd`, `upsrw`, a driver, or an UPS shutdown daemon.

## Initial Connection Boundary

- Enable loopback-only endpoints first, with literal address validation.
- Select an UPS by explicit safe name, not by subnet scanning or automatic access
  to every available host. Reject option-like names and protocol separators.
- Use `-A none` on the qualified client to avoid loading personal authentication
  files. Do not silently retry without this option on older versions.
- Disable inherited debug verbosity and define a minimal process environment.
  Do not emit raw stdout, stderr, environment, arguments or host identifiers to logs.
- Enforce an overall deadline, bounded stdout/stderr and one in-flight read per
  configured source. Connection timeout alone does not bound response reading.
- On nonzero exit, truncation, timeout, malformed output or an upstream error,
  reject the new sample. Preserve any last snapshot only as explicitly stale.
- The current offline diagnostic `upsc` build has SSL disabled and is not a
  portable package. It must not be used as a remote TLS client or silently
  substituted for a qualified installation.

Remote connections remain disabled until transport security and certificate
validation are implemented and tested. A remote feature must never downgrade TLS
or send credentials because opportunistic encryption failed.

## Data Boundary

Decode native `upsc -j` JSON through a structured parser. Any text compatibility
path is explicit, separately bounded and independently tested. The server may
report untrusted values. Allowlist known measurement keys and typed status flags;
drop names, serials, descriptions, addresses and arbitrary vendor data.

Raw server dictionaries are transient input, not persistence or export format.
Keep W, VA and nominal ratings distinct. Do not promote experimental energy to
Wh or infer input energy from generic UPS power. Mapping to a typed snapshot
does not prove sensor accuracy, reading freshness inside the backend, or active
power eligibility for energy integration.

## Qualification

First use an ephemeral, loopback-only synthetic NUT fixture server, with no
driver and no physical UPS. Verify observed client requests, structured output,
error/partial-response handling, credentials opt-out, environment sanitization,
size bounds, cancellation and deadlines. Test fixtures must not connect to an
existing server or inspect a real USB device.

Only then qualify the adapter against a specifically authorized real server.
The separate Microlink hardware consent boundary remains unchanged.
