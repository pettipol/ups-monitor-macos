# Lifecycle and Write Candidate

Status, 2026-10-11: **offline candidate only; hardware HOLD**. F4 (write
completion) is corrected within the tested function boundary. F1 (cooperative
termination) is **PARTIAL**, not a guaranteed cleanup path. The two concurrency
findings, F2/F3, remain open. This is not integrated into the application.

## Exact Inputs

Apply `backend/nut/nut-guarded-lifecycle-write-73c4502.patch` only after the
two patches in [Combined NUT Candidate](NUT_COMBINED_CANDIDATE.md), on upstream
`73c4502191d025e35122463986a80c676e734b04`. Upstream master was rechecked
against the official GitHub API on 2026-10-11 and still matched this pin.
The new GPL-2.0-or-later patch has SHA-256
`f80f8012f20494f473a268ef16d65efc71f021de0b615a29a3bb8b34509bcd00`.
Historical patches and their source fences are unchanged.

| File | Resulting SHA-256 |
|---|---|
| `drivers/main.c` | `a5bee8705ddb293c216ab57f03add7702cb967fd56d2b582187b2a164d0ba074` |
| `drivers/apcmicrolink-usb.c` | `6b81bac1498ce4868a96bca9ee98682155cc1f063eb36c72c4cb29c21bcf01f9` |
| `drivers/usb-common.h` (unchanged wrapper) | `6a5cee01ca1b0a0d31992983f061d55e62ca8da37d4559b800a228ebb957325f` |

The other four files in the combined candidate and `drivers/main.h` are
unchanged. Source, independent patch-application checkout and build-source
copy were compared byte for byte, including the untracked policy header.

## Changes and Evidence

**F4:** `microlink_usb_send_bytes()` accepts a successful write only when the
reported length equals its 64-byte output buffer. Other nonnegative lengths
are logged and rejected. The function adds no retry. This does not prevent
higher-level session retries or reopen attempts elsewhere in the driver.

The offline replay extracts both the complete send function and the actual
`usb_interrupt_write()` wrapper from hash-pinned sources, retaining source
notices. A static fake `libusb_interrupt_transfer()` independently controls
status and actual length. Baseline RED produces exactly four expected failures
for successful completions of 0, 1, 63 and 65 bytes. Candidate GREEN also
covers 64-byte success, timeout with 0/1/63 bytes transferred, negative errors,
device removal, preserved report/padding, one transfer per failed call and
zero transfers for invalid handle/report ID/oversized payload. The fake never
links or calls libusb. libusb-0.1 was not independently simulated.

**F1:** guarded POSIX dump mode installs dedicated TERM/INT/QUIT handlers after
mode admission and before device initialization. The handler only assigns a
private `volatile sig_atomic_t`. Normal-context checkpoints before initialization,
after cleanup registration, after callbacks, before dumping and after the main
loop request `exit(EXIT_FAILURE)` when cancellation is observed. The ordinary
daemon handler and public `exit_flag` declaration are unchanged.

The signal RED is explicitly a synthetic POSIX default/ignored-disposition
model after verifying that baseline dump mode skips normal signal setup; it
does **not** execute the original NUT `main()`. GREEN executes only the exact
candidate helper in owned single-thread child processes and observes an
`atexit` marker for TERM/INT/QUIT and inherited ignored TERM. It does not run
NUT cleanup. Readiness waits, child lifetimes and harness execution are bounded.
Both C replays use UBSan and inspect undefined symbols before execution; the
signal replay also inspects linked libraries. The coordinator repeated both
RED/GREEN pairs independently.

Source checks cover checkpoint placement and POSIX guards. Review found and
corrected a Windows compile-reference regression and a missing post-loop
cancellation checkpoint before freezing the patch. No Windows cross-build was
performed. The existing guarded call-site checker and its seven mutations pass.
Seventeen new Python runner-contract tests pass (eight signal, nine write);
they run in normal app validation without compiling C or launching a driver.

Fresh out-of-tree USB and serial builds of the sole `apcmicrolink` target pass.
They reuse the previously regenerated build templates from the same pin;
no new bootstrap/toolchain or dependency was installed. USB links the existing
libusb 1.0.30 and libSystem; serial links only libSystem. Neither driver binary
was executed, including informational options. Warnings include the existing
include path/allocator diagnostics and an unreachable `sigemptyset` error
return on macOS, where the platform macro expands to constant success.

## Reproduction

Use separate external checkouts and an empty external scratch directory.
`NUT_BASELINE_ROOT` must contain the two-patch combined candidate;
`NUT_CANDIDATE_ROOT` must contain that same candidate plus this incremental
patch. Neither is a runnable or installed backend for this procedure.

```sh
git -C "$NUT_CANDIDATE_ROOT" apply --check "$APP_ROOT/backend/nut/nut-guarded-lifecycle-write-73c4502.patch"
git -C "$NUT_CANDIDATE_ROOT" apply "$APP_ROOT/backend/nut/nut-guarded-lifecycle-write-73c4502.patch"
python3 "$APP_ROOT/backend/nut/replay_usb_write_completion.py" --baseline-root "$NUT_BASELINE_ROOT" --candidate-root "$NUT_CANDIDATE_ROOT" --scratch "$SCRATCH/write" --mode red
python3 "$APP_ROOT/backend/nut/replay_usb_write_completion.py" --baseline-root "$NUT_BASELINE_ROOT" --candidate-root "$NUT_CANDIDATE_ROOT" --scratch "$SCRATCH/write" --mode green
python3 "$APP_ROOT/backend/nut/replay_guarded_dump_signals.py" --baseline-root "$NUT_BASELINE_ROOT" --candidate-root "$NUT_CANDIDATE_ROOT" --scratch "$SCRATCH/signals-red" --mode red
python3 "$APP_ROOT/backend/nut/replay_guarded_dump_signals.py" --baseline-root "$NUT_BASELINE_ROOT" --candidate-root "$NUT_CANDIDATE_ROOT" --scratch "$SCRATCH/signals-green" --mode green
```

Each replay hashes only its declared source files; it is not a whole-driver
integrity or compatibility audit. Historical HID runners still require their
own exact artifacts and are not relaxed to admit this different candidate.

## Remaining Gates

- F1 remains partial: driver callbacks do not observe the new private flag
  while running. OS calls, cleanup and STOP are not bounded or guaranteed;
  the external runner may still need KILL before a checkpoint is reached.
- Signal delivery to the USB pump thread and thread synchronization are not
  qualified by the single-thread child test. A volatile signal flag alone is
  not proof of inter-thread synchronization. Cancellation during final cleanup
  can also retain an earlier exit status, including libusb's emergency exit.
- F2/F3 remain open: unsynchronized shared async state and async resubmission
  independent of the guarded receive deadline need dedicated fixes and tests.
- A complete frame/session/process budget, protocol effects on SMC1500I
  firmware 10, Apple/libusb coexistence and electrical continuity are not
  established. Startup/authentication/cleanup can still send protocol traffic.
- Real driver execution requires a separate, informed hardware test decision.
  Accepting communication loss is not consent to interrupt power. No driver
  startup command, deployment instructions or shutdown supervisor is provided.
