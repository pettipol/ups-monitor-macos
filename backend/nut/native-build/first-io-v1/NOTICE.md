# First-IO source profile notices

This profile records source provenance for the optional source-only delta dated
2026-11-21. It changes three NUT-derived native files under the NUT
GPL-2.0-or-later terms:

- `drivers/apcmicrolink-hidapi-session.h`
- `drivers/apcmicrolink-hidapi-shared.c`
- `drivers/apcmicrolink.c`

The two Python patches change project runtime modules that retain the
project's MIT licensing distinction:

- `cleanup_diagnostics.py`
- `process_deadline.py`

No vendor source, vendor notice, or selected HIDAPI license changes in this
profile. The eight HIDAPI 0.16 vendor files and their existing notices remain
as pinned in the referenced vendor profile. This provenance notice is not a
distribution-clearance determination. Before distributing a modified source
tree or binary, review the applicable changed-file notice and corresponding
source obligations separately. This profile does not add or rewrite notices
inside the patched files; the source patches preserve their upstream notices.

The manifest records this profile's public base locks and exact source deltas.
This notice does not assert independent upstream reconstruction or qualify
any private build or package evidence.
