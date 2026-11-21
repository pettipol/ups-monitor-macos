# Operational formatter v2 candidate

`backend/nut/nut-operational-formatter-v2.patch` adds isolated `mlink_operational_*` APIs to the existing continuous formatter. Apply it only in a separately prepared operational source stage. The canonical v1 helper files and the pinned v1 replay profile remain unchanged; this patch is not selected by an app or driver entry point.

The patch expects these baseline helper hashes:

| File | SHA-256 |
|---|---|
| `drivers/apcmicrolink-continuous.c` | `13f0facff36b46e783aad6279f364efcf2151ea0422896dc7098d4c4a40a5094` |
| `drivers/apcmicrolink-continuous.h` | `1fd7211d2872211a3ba19f908803e12482462cd628d6912b9798e0103b7adcc8` |

V2 uses separate field types, unsigned 64-bit counters and observation times, bounded to the exact JSON integer range `0..2^53-1`. Sequence starts at 1; slot, elapsed time and missed-slot arithmetic must agree. Observation time cannot exceed sample elapsed time. The 17-field allowlist, value/state/kind validation, temperature alias and derived-power dependencies agree with the Python v2 parser. A record is capped at 8,192 bytes. Operational End accepts cancellation and the four fixed failure reasons; it has no duration-complete reason.

Local validation with Apple clang 21 and an explicit macOS SDK passed the existing v1 helper assertions and four groups in `test_operational_formatter.c`. `test_operational_formatter_interop.c` additionally emitted four samples and five End records, all accepted by the strict Python v2 parser. Cases include 600 seconds, an observation beyond the 32-bit time range, and the maximum exact JSON integer. The C fixtures are finite and link only the formatter, with no driver or USB transport.

This is a formatter-only result. The operational native guard, capture refresh, driver CLI admission, new staging manifest and Swift decoder still require integration. Existing replay pins must not be silently changed to select the candidate. The new tests are not yet part of ordinary CI; a future operational staging check must compile them against the patched helpers and run them with the existing bounded process supervisor.
