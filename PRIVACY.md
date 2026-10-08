# Privacy and Local Data

UPS Monitor Mac is designed to work without an account or cloud service. The
inspected app source contains no analytics or remote telemetry client. This
is not a guarantee about macOS services, an external executable, or runtime
network behavior that has not been measured. See the dated, bounded
[source audit](docs/PRIVACY_AUDIT.md).

## Data Used

The Apple backend reads the existing system power-source service. It keeps
only typed, allowlisted UPS measurements and status. Native power-source IDs
are replaced with opaque session-local IDs before application snapshots are
created. These IDs are not hardware serials, but exported timestamps and
session IDs can still correlate records from the same observation session.

The optional NUT backend runs an explicitly selected executable. Connection
settings and expected SHA-256 remain in memory and are not telemetry export
fields. This app constructs a read-only query to one loopback endpoint; an
external executable is nevertheless arbitrary local code. A matching hash
does not prove publisher identity, safety or absence of network access. The
local NUT service and its hardware driver have their own data and trust
boundaries. No client, driver or service is installed automatically.

## Persistence and Deletion

| Data | When stored | Removal / limits |
|---|---|---|
| Live measurements and energy accumulators | Memory during the app session | Source/backend changes reset energy; stopping pauses it until the process exits. Explicit energy reset clears the displayed accumulators. |
| History | Explicit recording opt-in; private local SQLite storage | Session/all-history deletion is available. Recording off does not erase existing rows. Retention is up to 90 days / 100,000 rows, enforced on append or explicit prune, not a background expiry timer. |
| JSON/CSV exports | Only on explicit save | Separate user-owned files; clearing app history does not delete them. Energy export is a separate session estimate, without absolute system uptime. |
| Widget snapshot | When a signed App Group is configured, independently of history opt-in | Latest selected snapshot persists in the shared container for the widget. There is no separate widget-cache purge control in the current UI; do not interpret history deletion as cache deletion. |
| Local notifications | Optional per-session enable plus macOS authorization | The app clears its own fixed notification identifiers on lifecycle transitions. OS surfaces, retention and delivery remain macOS-controlled and unqualified here. |

Owner-only file permissions reduce access by other users; they are not
encryption and do not isolate other processes running as the same user.
No deletion claim covers physical SSD blocks, filesystem snapshots, backups,
export copies or operating-system diagnostic/notification retention.

The default ad-hoc build has no App Group configured. Real shared-container
access, notification presentation and runtime egress are still unverified.
The app exports only modeled values; upstream raw errors are redacted in
user-facing failures. Do not attach raw hardware dumps or private build logs
to public issues. Apple's platform privacy-manifest requirements and final
distribution artifacts still need a release-specific review.
