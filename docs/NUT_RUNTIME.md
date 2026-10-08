# NUT Runtime Reader

`NUTSnapshotReader` adapts one explicitly configured `UPSCClient` read to the
common `MonitorSnapshot` model. The public API accepts an
`UPSCClientConfiguration`, an expected 64-character SHA-256 hexadecimal digest,
and an opaque session ID. Its source uses the configured source ID, provider
`nut`, and identity stability `configured`.

Construction validates the digest syntax and source/session identifiers. The
caller must supply opaque IDs rather than UPS names or hardware identifiers;
substring comparisons cannot establish this property. `validateExecutable()` hashes
only and never launches a process. Every `read()` repeats that check before
calling the existing bounded, loopback-only `UPSCClient`, then validates and
returns a one-element snapshot collection. Concurrent reads on one reader are
rejected. Failures are typed and redacted; file paths, raw output, UPS names,
and digest values are not included in error descriptions.

Hashing opens the configured final path component with `O_NOFOLLOW` and
`O_NONBLOCK`, then uses `fstat` on that descriptor. The file must be a regular,
executable file owned by the current user, not group/world writable, without
setuid/setgid bits, and have exactly one link. Reads are limited to 64 MiB.
Device, inode, owner, mode, link count, size, modification time, and change
time are compared directly before and after hashing; cancellation is checked
between reads. The size bound is not a hard deadline for filesystem system calls.
This does not defend against a
malicious same-user path swap between validation and process launch, validate
intermediate path components, or hash/qualify loaded libraries. A matching
digest binds the configured expected bytes; it does not establish that the
caller correctly qualified the executable or that its NUT behavior is safe.

The reader adds no service discovery, credentials, environment customization,
history, fallback, or hardware access. `UPSCClient` remains the only process
launcher and only issues its fixed read-only query. Synthetic tests cover
preflight, rejection, cancellation, and adaptation. They are not evidence of
compatibility with a physical UPS or a live NUT server.
