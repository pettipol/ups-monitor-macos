# Widget Shared Data

`UPSWidgetData` contains the versioned payload and the host-side file store. It
has no WidgetKit, IOKit, network, database or driver dependency. The extension
reads only `WidgetSnapshot` values supplied by its app integration.

## Payload

`WidgetSnapshot` is schema version 1 and carries publication time, acquisition
state, a 1...600 second maximum age, and at most one validated `MonitorSnapshot`.
An active acquisition requires a sample; `noSources` requires none. A failed or
stopped acquisition may retain the last good sample, but validation requires
that sample's capture time not exceed publication time. The payload contains no
source name, native identifier, serial, endpoint, history or arbitrary
metadata.

Custom Codable decoding runs the same validation as the public `validate()`
method. `isStale(at:)` fails closed for invalid payloads or clocks, is always
true for non-active acquisition, and uses the capture timestamp. A sample is
fresh at exactly `maximumAge` and becomes stale only when its age is greater.
Store reads and writes require an explicit finite `now` and reject future
publication times; a read returns an old but valid payload so its caller can
render it explicitly as stale.

## Store

`WidgetSnapshotStore` uses one fixed `snapshot.json` file beneath a caller-
selected private child directory. The caller must supply the intended location;
the store does not infer an App Group container or fall back to another path.
Read-only initialization never creates or repairs anything. A writer may
create only the requested final directory, with mode 0700; its parent must
already exist. Existing directories must be owned by the current user and
exactly private.

The store uses directory-relative descriptors, refuses symlink, non-regular,
foreign-owned, non-private or hard-linked files, and caps encoded and read
payloads at 64 KiB. Reads check size before reserving memory and enforce the
limit while reading. Writes validate and encode before touching the destination,
write to an exclusive same-directory 0600 temporary file, then atomically
rename it over a safe target. A failed write leaves the previous target in
place. Errors are typed and contain no paths or operating-system details.

Dates use JSONEncoder's numeric `deferredToDate` representation: fractional
seconds from Foundation's reference date (2001-01-01 00:00:00 UTC). This keeps
subsecond capture and publication times intact across a store round trip.

This design does not claim protection from a malicious same-user process
racing directory entries, power-loss durability, rollback protection or secure
erasure from storage snapshots. The injected parent directory must be an
existing, current-user-owned directory without group/world write permission;
only its final path component is opened without following a symlink. Ancestor
path components remain caller-trusted. App Group entitlement, container availability,
signing and WidgetKit presentation remain separate integration gates. Tests
use only synthetic payloads and fresh temporary directories; they do not access
the real shared container or hardware.
