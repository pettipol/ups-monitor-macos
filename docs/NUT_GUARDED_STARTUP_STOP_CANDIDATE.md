# Guarded Startup/Stop Candidate

Date: 2026-10-11. Experimental source disclosure only; not installed, submitted,
or accepted upstream. This seventh incremental patch addresses RF-01 and RF-03
from the final review. It does not qualify the Microlink protocol, real USB
ownership, electrical behavior, or complete NUT process shutdown.

## Reproducible Input

Base NUT commit: `73c4502191d025e35122463986a80c676e734b04`. Apply the five
patches listed by [the observation-budget candidate](NUT_GUARD_DEADLINE_CANDIDATE.md),
then the sixth patch documented by [the ownership candidate](NUT_OWNER_RETENTION_CANDIDATE.md),
then this patch. The earlier original-base guarded-monitor patch is not part
of this stack. No dependency or version is changed.

Patch SHA-256:
`30c880bb014cdf1f904000d0c8980a5454aeefab8442bbc6f560f03d774ce87f`.

| Source file | Six-patch input SHA-256 | Seven-patch candidate SHA-256 |
|---|---|---|
| `drivers/main.c` | `a5bee8705ddb293c216ab57f03add7702cb967fd56d2b582187b2a164d0ba074` | `b40ccaef148aa0396d8a81bc83e961c4af8d286bccb5e26e745f0252b6709dba` |
| `drivers/main.h` | `d6891c0b86585cfa29dbdcaf9f3de7b797472fdbbb7a094ec1626cefc3e34ba8` | `19bb6da2a1a05434ad5d845baa26a2b2137c8eae02802f080261fe162883c7dc` |
| `drivers/apcmicrolink.c` | `3bc7eadc8e2fae657df1b8f0e37f3baf53fd9a6e20a7da3c029d218193d2177d` | `efdad6737c377931e5130f00d9e1257091584670d149d49015d06e2854fa14a5` |

The USB ownership source is unchanged at
`d6f61c595fd87e3f7d4e416ba8f8d6e04293ea3ff12c93dce60ad0384b4d056d`.
The seventh patch contains only the three tabled files. It applies cleanly to
a fresh copy of the six-patch input; after application, those three files
were byte-compared with the reviewed candidate.

## Behavior

The signal handler remains limited to setting the existing `sig_atomic_t`
flag. A POSIX-only read checkpoint is declared in `main.h` and implemented
in `main.c`; the Microlink driver uses it only in guarded mode. Startup
checks the flag before another STOP/INIT attempt, after STOP, after INIT, and
before receiving a startup report and again after receive returns, before
the next poll/NEXT step. The normal simple-control and descriptor writers
reject a new send after the flag is observed. Cleanup retains its separate
best-effort raw STOP path.

This is cooperative. It cannot interrupt an OUT call already in progress or
eliminate the race between checking the flag and beginning a call. STOP,
INIT, NEXT, reads and any applicable response/authentication traffic remain
part of the protocol. The change does not assert that these messages have no
firmware or electrical effect.

In guarded mode, `upsdrv_initups()` now requires `microlink_usb_open()` to
return exactly `1`. A different result calls the ownership-aware close before
`fatalx()`: when no async owner remains, the open handle is closed; when a
transfer is pending, the pinned close contract returns without releasing
the retained owner or handle. The ordinary non-guarded path and successful
guarded open are covered as controls. This fixture mocks close behavior from
the pinned USB contract; it does not execute the actual USB ownership
lifecycle.

## Synthetic Evidence

`extract_guarded_startup_stop.py` pins the four relevant source files, keeps
the upstream NUT notices in generated C, and extracts the actual signal
setup/handler/query, Microlink startup/writer/cleanup functions, and
`upsdrv_initups()` body. The C fixture uses local mocks and raises SIGTERM
only within its own bounded process, on its main thread or a fixture worker.
Its failure stub cannot return to the production callsite. The fixture models
the `initinfo` continuation immediately after the extracted `upsdrv_initups`
call; it does not execute `main()` or the NUT process.

The pinned six-patch baseline produced the expected RED: exit 1 and exactly
five failures, covering main-thread STOP, worker-thread STOP, signal after
INIT, pending-owner open failure, and no-owner handle close before fatal.
The seven-patch candidate produced GREEN: exit 0, exact stdout
`all guarded startup/stop synthetic checks passed`, and empty stderr. Seven
fixture checks cover these failures plus successful guarded open, ordinary
fallback, negative open return, receive suppression, the cleanup STOP
control, and pending versus no-owner close behavior.

Both C runs used `cc -std=c99 -Wall -Wextra -Werror -fsanitize=undefined
-fno-sanitize-recover=undefined -pthread`, with a 30-second compile bound and
10-second execution bound. `nm -u` and `otool -L` were inspected before each
run; no NUT, libusb, HID, or IOKit linkage was present. The Python extractor
contract suite passed six tests. Two scratch-only source mutations were also
caught after the same linkage checks: disabling the guarded stop checkpoint
produced three RF-01 assertion failures; bypassing the guarded open-result
check produced failures for both pending-owner retention and closing the
unowned handle.

The coordinator independently applied the seventh patch to a fresh
reconstruction of the six-patch source: file hashes matched and the complete
tree comparison was empty. Its independent seven-check GREEN also passed.
USB and serial source syntax checks returned zero using historical generated
configuration headers. These syntax-only checks did not build or link a new
NUT driver executable; full build provenance remains open.

To reproduce with a reconstructed candidate and baseline, set each scratch
variable to a different new directory outside the source tree and product
checkout:

```sh
python3 backend/nut/extract_guarded_startup_stop.py red \
  "$CANDIDATE" "$RED_SCRATCH" --baseline-source "$BASELINE"
python3 backend/nut/extract_guarded_startup_stop.py green \
  "$CANDIDATE" "$GREEN_SCRATCH"
```

These commands only compile and run the extracted synthetic C fixture after
linkage inspection; they do not invoke a NUT driver or device. Extract-only
mode prepares a scratch package without compiling or executing:

```sh
python3 backend/nut/extract_guarded_startup_stop.py extract \
  "$CANDIDATE" "$EXTRACT_SCRATCH"
```

## Limits and Status

These are source-extracted callsites with recording mocks, not full-driver
execution. The main call order is checked statically; `main()` is not run.
The fixture does not test kernel scheduling, actual signal delivery to NUT,
real libusb callback ordering, complete cleanup/atexit, blocked system calls,
or indefinite process lifetime. No NUT driver executable, UPS, USB/HID
interface, daemon, or hardware was run or accessed.

RF-01 and RF-03 have focused synthetic RED/GREEN evidence only. RF-02 has a
separate treatment in [process supervision](PROCESS_DEADLINE.md); its evidence
is not transferred by this candidate. Overall C01 remains PARTIAL because
the integrated `main()`/NUT process path is not executed here. The candidate
remains experimental and does not authorize a hardware test. No hard
deadline, successful dump, safe STOP, or electrical continuity claim follows
from these results.
