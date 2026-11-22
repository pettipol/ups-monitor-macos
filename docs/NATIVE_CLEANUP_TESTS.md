# Native HIDAPI cleanup test

## Purpose

The E24 offline fix addresses a mismatch between the operational guard and the
native HIDAPI adapter. After Stop is latched, the guard may authorize one final
F7 cleanup report, while the adapter previously rejected every write because
the Stop callback remained true. The fix gives the adapter a narrowly scoped,
owner-bound cleanup capability. It accepts only one 64-byte report with the
verified output report ID, F7 payload, and zero padding. The attempt is consumed
before `hid_write`; later writes remain rejected, including when Stop was not
latched. Ordinary reads and writes remain blocked after Stop.

H08 motivated this work, but its exact internal failure path was not captured.
The synthetic test demonstrates the adapter/guard path and its correction; it
does not prove that this was the sole cause of H08.

## Isolated replay

`backend/nut/replay_hidapi_native.py --operational-v2` verifies pinned inputs,
reconstructs the existing v1 and operational sources in a temporary directory,
then applies the separate `nut-operational-cleanup-v2.patch`. The frozen v1
inputs and their source manifest remain unchanged. The command-line ABI header
is the pre-continuous input pinned at SHA-256
`b21b39bd218e29706db8a95fca8551f53b2539e507617a5f10e867d6c4f64f29`. The
reconstructed operational ABI is checked separately at
`3ef32b7ce9836c0497d0d09697f39862a6d018eca9656628eb951ab4b6a2ef5f`.

The operational fake test links the authentic native adapter, descriptor
parser, and shared guard to synthetic `hid_*` functions. It retains the nine
existing fake test groups and adds two operational groups, including the
sticky-Stop cleanup path and negative cases for ordinary I/O, unauthorized or
duplicate writes, owner mismatch, invalid report ID/length/opcode/padding,
short/error writes, late completion, and cleanup without a Stop latch.

Example on macOS, using a verified HIDAPI 0.15.0 source tree and the pinned
pre-continuous ABI header:

```sh
python3 backend/nut/replay_hidapi_native.py \
  --hidapi-source /path/to/hidapi-0.15.0 \
  --abi-header /path/to/apcmicrolink-usb.h \
  --operational-v2
```

The input pins are checked before the build. The synthetic test binary is
audited with `nm` and `otool` and is the only test binary executed by the
replay. The optional `--link-native-only` checks compilation and linkage
against authentic macOS `hid.c`; the resulting native binary is never run.

## Bounds and evidence

Each checked command has a 1 MiB output limit and a 60-second default timeout;
the synthetic test executable has a 10-second timeout. The termination grace
is 0.5 seconds. SIGTERM or SIGINT to the replay sets its cancellation event so
the bounded child runner can stop and reap its owned process group. These are
per-command limits, not an overall replay deadline or a promise of a global
output cap.

The local public-recipe verification passed nine groups in legacy mode and
eleven groups in operational mode. Authentic native `hid.c` was compiled and
linked successfully; its executable remained `NOT_RUN`. A synthetic child
that ignored SIGTERM was killed and reaped on harness cancellation, with its
PID and process group absent after about 1.44 seconds, before its 20-second
natural exit. This offline evidence does not qualify real USB behavior, the two
separate driver Stop race fixes, the widget, daily use, or release readiness;
those remain open.
