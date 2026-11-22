# Continuous acquisition pacing candidate

This candidate separates acquisition from five-second publication in the native
continuous NUT collector. After the first bootstrap sample, pacing v2 calls
`upsdrv_updateinfo()` on each stream-loop iteration. The existing slot check
still decides whether to publish a sample. An acquisition burst may cross a slot
boundary; the collector uses the actual elapsed time and existing missed-slot
accounting, without synthesizing a sample to fill a gap.

The patch changes only `drivers/apcmicrolink.c` after the admitted baseline and
diagnostic patch chain. `MLINK_CONTINUOUS_PACING_V2` defaults to `0`; enabling it
requires the existing native continuous candidate. The wire protocol remains
`ups-monitor.continuous.v1`. Existing cancellation, session, clock, 120-second
acquisition cutoff and 130-second guard checks remain in place, as does ordinary
STOP/finish cleanup. No reconnect, reopen, reset, new transport or retry is added.
The OFF build retains reference slot-coupled scheduling semantics, but its debug
transcript is not byte-identical to the pre-patch driver: the existing update
debug message now follows the post-update elapsed-time checks.

## Offline comparison

`replay_continuous_pacing.py` reconstructs the admitted source offline and builds
the same patched driver twice. Both builds enable diagnostics v1. The only build
gate difference is pacing v2 `0` versus `1`. The fake host does not inspect that
gate; it responds only to protocol operations and a shared virtual clock.

The sole `next-gap-budget` fixture becomes silent for the remainder of a session
if a NEXT-to-NEXT gap exceeds **250 ms**. Each useful fake response advances the
virtual clock by **2 ms**; an empty read consumes its requested virtual timeout.
These are synthetic test choices, not measured device limits or a firmware
model. Timing and lifecycle counters summarize every NEXT gap; they are not a
lossless event trace. General per-operation tracing is disabled for this scenario
to retain the existing output cap.

The first fixture revision mistakenly repeated measurement page 1 after
bootstrap instead of completing the existing page cycle. Reviewed REV2 alternates
measurement page 1 and the unrelated final page 2, matching the admitted
same-payload fixture. Page 2 does not become a second measurement page. The
scheduler patch and assertions are unchanged by that fixture correction. The
runner admits only the REV2 host hash recorded in its public input manifest.

The OFF result must demonstrate an excessive gap, stalled field timestamps and
idle `session_lost` before 120 seconds. The ON result must demonstrate bounded
NEXT gaps, full-duration completion, no slot wait, and advancing observation
timestamps for every one of the fixture's 15 dynamic fields even when values do
not change. The validator also checks sequence/slot/observation accounting,
acquisition cutoff and cleanup counters. The fake has one initial STOP and one
cleanup STOP; these are counted separately. This single counterexample does not
replace the other CLI, freeze, cancellation or cleanup regression checks.

## Reproduce the candidate

Required inputs are macOS, Python **3.15.2**, Xcode **27.1** with macOS SDK
**27.0**, the pinned backend files, the three admitted pacing patch/host/test
files, and the exact source archive. The runner does not download inputs or
install anything. All paths are passed through `--backend-dir`,
`--new-files-dir`, `--nut-archive` and `--output-dir`; input paths must be absolute
and free of symlink components. Compilation dependency paths must also satisfy
the existing portable Make-dependency path grammar.

The source input is the exact uncompressed **git archive tar** of Network UPS
Tools commit `73c4502191d025e35122463986a80c676e734b04`, SHA-256
`e3ea175565c461a9e741df77dd91103d695b9c60f8d423d9b6ce6c778f98615f`.
A GitHub-generated source tarball, another tar container or a repacked tree is
not interchangeable. The archive hash is the admission criterion; matching a
revision name alone is insufficient.

With the reviewed public files installed under `repo/backend/nut`, for example:

```sh
python3.15 -I -S -B repo/backend/nut/replay_continuous_pacing.py \
  --backend-dir "$(cd repo/backend/nut && pwd -P)" \
  --new-files-dir "$(cd repo/backend/nut && pwd -P)" \
  --nut-archive "$(pwd -P)/upstream.tar" \
  --output-dir /private/tmp/ups-pacing-example-01 \
  --compile-only
```

The output directory must be new and strictly below the system temporary root;
it must not overlap any input. `--compile-only` is the default. To run the two
synthetic children, replace it with `--run-fake` and choose a new output directory.
The runner has no arbitrary command option and no hardware execution mode.

Python must run isolated, without site initialization or bytecode writes, and
without optimization (`-I -S -B`, no `-O`). Its executable SHA-256 is recorded in
the output manifest, not admitted against a machine-specific compiled binary.
That recorded hash identifies the interpreter used; it does not authenticate
the interpreter or establish its provenance. The script self-pin, canonical
runner/manifest pins, source chain, REV2 host, validator and source-after hash
remain enforced. The input manifest is a reviewable trust root, not a signature.

Before execution, both binaries undergo the reused symbol, linkage, exact-object
and dependency/include audits that reject real HID/USB linkage. Each fake is a
direct child of the same in-process supervisor, limited to 20 seconds and 1 MiB
combined capture, with a shared cancellation/storage guard. There are exactly
two fake children, a 60-second pair budget, 2-second termination grace,
1-second kill/reap budget, 2 MiB aggregate capture and 1 GiB generated-tree cap.
Binaries normally have mode `0600` and receive execution permission only around
their explicitly requested fake invocation. Caps and defaults are unchanged.

`manifest.json`, per-command receipts and `pacing-pair/run-receipt.json` record
the exact expanded commands, source and binary hashes, selected toolchain,
interpreter identity and supervisor/validator outcomes. They are local receipts
and may contain caller paths: inspect and redact them before publication. A new
output tree is required for each invocation; the runner does not silently reuse
a prior binary. On 2026-10-26, this public adapter completed 32 compile
invocations and two link/audit pairs; its two synthetic OFF/ON children then
completed one bounded replay, yielding `PASS_PACING_FAKE_ONLY`. OFF ended after
30 seconds with six stalled samples. ON completed 120 seconds with 24 samples
and advancing timestamps in all 15 dynamic fields. Total captured output was
55,902 bytes. No USB was used. The input manifest preserves the pre-run
admission state; execution outcomes belong to the generated receipts. This
offline result does not qualify hardware, GUI behavior, widget refresh, daily
use or a release.

## What the evidence supports

A separate bounded H07 observation on one **SMC1500I** sustained acquisition for
120 seconds, emitted 24 samples with renewed timestamps for all 15 dynamic
fields and completed ordinary collector cleanup. The user reported normal
operation. This supports that observed collector session; it does not qualify
other units or firmware, continuous daily use, calibration, GUI end/expiry
behavior, widget refresh, packaging or a release. Public offline reproduction
does not launch hardware and grants no authorization for a hardware session.

Field semantics remain important: W and VA are different quantities and the
real/apparent power outputs are driver-derived estimates. The battery and UPS
temperature labels alias the same descriptor observation, not two independent
sensors. Energy in Wh remains unavailable; it is not inferred from charge,
runtime, W or VA. The pacing change adds no new measurement capability.
