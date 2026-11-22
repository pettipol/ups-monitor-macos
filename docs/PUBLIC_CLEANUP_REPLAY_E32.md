# Public cleanup diagnostics replay E32

E32 derives from the frozen E31 public runner (`33889f35…`) and manifest
(`24990635…`). E31, its 33-case evidence, v1 inputs, baseline C modules, and any
separately prepared native candidate remain unchanged. Preparation, contract
execution, reconstruction, build, audit, and fake execution are separate states.
All execution states are `NOT_RUN` when this candidate is prepared.

## Local verification on 2026-10-28

The final standalone suite passed all 57 contracts. The first contract run had
56 passes and one error because a test expected the supervisor's original
exception instead of the runner's wrapped error; only the test and its pin were
corrected. The runtime did not change. The dependency-injected fixture was also
renamed before integration to keep it out of unrelated wildcard discovery.

A subsequent single public reconstruction and fake replay passed: two retained
190-file trees, three 17-unit builds with link/import/dependency audits, all 33
baseline cases and all eight diagnostic cases. The prebuild gate passed the
same 18 diagnostic/orchestration contracts; it is not 18 additional distinct
tests. The full runner took about 24 seconds and captured 663,431 bytes across
the 41 fake children. All three fake binaries ended non-executable (0600).

This is `PASS_FAKE_ONLY`. The full project check and hosted CI were not run in
this experiment. No app, widget, authentic HID driver or USB session was started;
there is no daily-use, hardware, distribution or release qualification from it.

## Source admission and two retained trees

The input manifest is schema 2 with the explicit public E32 source kind. It pins
the v1 runner/manifest, E31 runner/manifest, exact helper/protocol overrides,
every patch and local input, and three complete 190-file maps. No private E25
directory or admission document is a runtime dependency.

The production chain is the frozen v1 reconstruction (seven copied modules
before twelve patches), then the five operational production patches in E31
order, freshness copies, the full pre-E28 map, and the diagnostic production
patch. The complete post-E28 map is verified and retained at `output/source`.
All its C/H files are checked for operational E25/E29 replay markers. Historical
v1 source-only seams remain; this is not a claim that every test seam was removed.

A separate byte-verified 190-file fork at `output/fake-source` receives the E25
hook and E29 test-only hook, in that order. APC pins are `d7bb4930…`, then
`85670593…`, then `11c43efd…`. The remaining 189 files stay identical to the
production checkpoint. Every intermediate snapshot and the complete final map
must match. Both retained trees are rechecked before success.

The final fake map was prepared from the historical E29 expected map; matching
it is a comparison of bytes. Public origin is proved only by a successful new
archive reconstruction and admitted patch chain, not by changing the label of
the old E25 experiment.

## Fake compilation and validation

E32 uses the E31 supervisor, dependency/link/import audits, three-mode 17-TU
build, cleanup properties, and atomic final publication. The two renamed E29
C/header inputs preserve their exact bytes. Staging emits their original
basenames in `output/fake-units`, alongside the two existing fake C units.
This directory permits exactly three C files and one pinned test-hook header.
Native/session/shared-host headers must come from the reconstructed tree.
APC and the operational host must both depend on the staged E29 hook header;
the backend E31 hook header is rejected. Production C inputs are never replaced.

The fixed 33 baseline cases remain unchanged. For each, the E29 cleanup validator
first invokes the unchanged legacy validator, then validates the production
diagnostic record. Eight additional closed cases exercise result-copy faults,
failed diagnostic output, cleanup reentry, and pre-open atexit cleanup. There
are no new scenario aliases or relaxed legacy expectations. The five boolean
result-vector cases are explicitly fault injection, not real transport failures.

`REGRESSION_33` and `DIAGNOSTIC_8` have separate receipts and both must be complete.
Their shared deadline is 600 seconds from the first suite start. Each child has
15 seconds, 2 seconds termination grace and a 1 MiB capture cap; the shared
aggregate cap is 41 MiB, and the tree cap is 1 GiB. The final publication fence
checks that same suite deadline even after watcher cleanup and fsync. E32 does
not add the private E29 wrapper's separate global build deadline; per-command
and per-compile bounds are inherited from E31.

## Contracts and the E29 mapping

The standalone public test entrypoint loads pinned dependencies from the same
complete backend package. It includes the 32 applicable E31 contracts, eight
adapted orchestration contracts, seven new public-derivation contracts, and the
ten E29 validator contracts. No private orchestrator is imported or tested.
The ten injected validator contracts live in `cleanup_replay_contracts_e32.py`,
outside the generic `test_cleanup*.py` discovery pattern. The public standalone
entrypoint and runner explicitly load and bind that pinned module; generic
cleanup-test discovery therefore cannot collect it with uninitialized globals.
The ten validator method bodies retain the E29 assertions, including mutation
of all 18 diagnostic fields and the natural-stop rule: at least 10000 ms,
activity, and two publications. A positive wait count is not required.

Before its first compiler call, the runner independently requires all ten
validator contracts and all eight actual E32 orchestration contracts to pass,
with no skips, expected failures, or unexpected successes. This prebuild gate
does not substitute for the full standalone contract suite.

| E29 orchestration contract | Actual E32 contract boundary |
|---|---|
| supervisor exception/timeout stops followup and resets 0600 | `OrchestratorContracts.test_supervisor_exception_and_timeout_stop_before_next_child_and_reset0600` |
| cancelled loop starts no supervisor | `test_cancel_before_loop_starts_no_supervisor` |
| exact eight, same event, hashes, capture and modes | `test_exact_eight_loop_uses_same_event_hashes_real_capture_and_private_modes` |
| storage failure cancels and watcher joins | `test_storage_oserror_cancels_actual_storage_gate`, plus retained E31 watcher-join contracts |
| exact source maps and shadow rejection | `test_public_source_maps_reject_additions_removals_and_unrelated_changes`, plus staged-header/public-derivation contracts |
| output inside protected input rejected | `test_output_inside_protected_public_input_is_rejected_before_creation` uses the pinned public v1 output gate |
| deadline crossed at final recheck cannot pass | `test_deadline_crossed_during_atomic_final_write_cannot_publish_pass` uses the E32 publication fence |
| bounded private failure metadata | `test_failure_metadata_is_closed_bounded_and_private` |

The original private admission schema is deliberately not recreated. New tests
instead exercise public-origin/order gates, independent production/fake trees,
operational-hook absence, parser pins and preloaded-module rejection, staged
hook-header provenance, incomplete 33+8 success, and shared capture/deadline caps.

The supervisor-exception contract asserts the public E31/E32 error boundary:
an underlying exception is recorded in a `SUPERVISOR_FAILED` row and converted
to `ReplayError("fake supervisor failed")`. It also requires cancellation, one
attempt only, zero validated cases, and restored 0600 permissions. The initial
standalone attempt passed 56 contracts and errored on that contract's obsolete
raw-`OSError` expectation; no build ran. The corrected assertion is pending rerun
and leaves the runtime unchanged.

## Execution

Use a complete staged public backend containing both frozen baseline versions
and all admitted E32 inputs. The standalone contracts do not compile or launch
a driver:

```text
python3.15 -I -S -B /path/to/backend/nut/test_replay_operational_portable_e32.py -v

python3.15 -I -S -B /path/to/backend/nut/replay_operational_portable_e32.py \
  --backend-dir /path/to/backend/nut --nut-archive /path/to/admitted/nut.tar \
  --output-dir /private/tmp/ups-e32-compile

python3.15 -I -S -B /path/to/backend/nut/replay_operational_portable_e32.py \
  --backend-dir /path/to/backend/nut --nut-archive /path/to/admitted/nut.tar \
  --output-dir /private/tmp/ups-e32-fake --run-fake
```

Compilation-only is the default. A successful fake result proves only this
offline public-source experiment. Native compatibility, hardware behavior,
application integration, everyday use and any H10 trial remain unqualified.
