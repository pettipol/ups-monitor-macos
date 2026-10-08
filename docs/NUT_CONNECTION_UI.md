# Local NUT Connection UI

`NUTConnectionView` edits an in-memory `NUTConnectionDraft` and delegates file
selection, preflight, connection, and cancellation to callbacks. The view and
draft perform no filesystem access, hashing, persistence, process launch, or
network access. The host remains fixed at `127.0.0.1`; no remote host field is
provided.

`canConnect` is a syntax gate only. It requires an absolute nonblank executable
path other than `/`, with no NUL byte; a 64-character ASCII hexadecimal SHA-256;
an UPS name matching the NUT client's ASCII name allowlist; a one-to-five-digit
decimal port from 1 through 65535; and explicit completion-qualification
acknowledgment. While connecting, all editable controls and cancellation are
disabled. The syntax gate does not establish that a path
exists, is executable, matches the digest, or has passed client qualification.
The controller checks the file and digest during preflight; semantic client
qualification remains the caller's explicit attestation, not an automatic test.

`NUTConnectionViewTests` use synthetic paths, names, ports, and digests only.
They cover draft defaults, syntax boundaries, and view construction; they do not
open a file picker or connect to a NUT server.
