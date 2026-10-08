# NUT Guarded Source Prototype

Status: **offline prototype, hardware NOT_RUN, live consent HOLD**. No candidate
driver, scanner, daemon, service, USB handle, or UPS was run or opened in this
work. This document does not identify or qualify a target model.

## Provenance

`backend/nut/nut-guarded-monitor.patch` applies to Network UPS Tools commit
`1a8369f8688443a500527059167d2f66ca27535f`. The patch and included
guarded C helper are derived from NUT source and remain GPL-2.0-or-later per
upstream headers, separate from the application's MIT code. The original
`source`, `build`, and earlier `guarded-source` snapshots were not changed.
The v2 patch was generated from a separate pristine-derived source tree and
applies cleanly to the pinned commit.

## Opt-in behavior

The default NUT path is unchanged without `guarded_monitor`. The experimental
profile requires `port=auto`, a libusb-1.0-only build, exact four-digit hex
`guard_vid` and `guard_pid`, and `guard_deadline` from 1 to 300 seconds.
The shared `main.c` also requires a positive dump count and effective
`foreground == 1`, and rejects `-c`, `-k`, or explicit `-P` before sibling
socket or PID-signal paths can run. With this upstream parser, positive `-d`
defaults to `foreground == 1`. The gate checks the final parser state, not a
literal flag allowlist: for example, one `-F` after `-d` sets the state to 2,
`-B` sets it to 0, and mixed flags can change the result according to option
order. Windows is rejected because this guard does not neutralize its process
coordination path. The guarded profile skips the usual competing `driver.exit`
request; default-mode startup remains unchanged.
The shared libusb1 path reads every device descriptor before opening a handle;
it refuses descriptor errors, zero or duplicate ID matches, and opens only the
unique matching descriptor. It refuses unreadable configuration descriptors.
One claim attempt is made with no auto-detach, explicit detach, or claim retry.
The profile rejects `usb_set_altinterface`, and disconnect recovery omits
`usb_reset()` while still closing and reopening the handle.

The driver's `instcmd`, `setvar`, and `upsdrv_shutdown` entry points reject
guarded-profile control requests. This includes `shutdown.default` and
`driver.killpower` when they delegate to `upsdrv_shutdown`; no such entry
reaches a device-modifying command frame in the guarded profile. The `-k`
option is rejected in the shared `main.c` before it can contact a sibling
driver over the local socket. A libusb interrupt-read PIPE error is returned
without the default-profile `libusb_clear_halt()` recovery. These guards are
reviewed only for the `apcmicrolink` driver; use of `guarded_monitor` with
another NUT USB driver is unsupported and unreviewed. Normal protocol STOP,
INIT, NEXT, authentication, reads, and cleanup still transmit to the device.
This is **not wire-read-only** and the opt-in profile is not permission to
run it on hardware.

This patch does not change NUT's generic HID fallback interpretation. A
separately reported upstream case describes a false on-battery result when
`PresentStatus` is not decoded despite fresh charge/runtime fields; that risk
is tracked separately in [NUT_UPSTREAM_STATUS.md](NUT_UPSTREAM_STATUS.md) and
is not fixed or qualified by this guarded profile.

The startup and receive loops use NUT's `state_get_timestamp()` helper. The
inspected macOS build defines both `HAVE_CLOCK_GETTIME=1` and
`HAVE_CLOCK_MONOTONIC=1`, selecting `CLOCK_MONOTONIC`. Upstream falls back to
wall time on other configurations; those builds are not qualified by this
prototype and must not be assumed to have a monotonic deadline.
Clock failure fails closed; expiration is
checked before frame extraction and before startup STOP/INIT and poll NEXT
writes; cleanup STOP remains best-effort even after expiration. A fresh
deadline is created for each later poll or reconnect. A single blocking
libusb/OS call can outlast the deadline; the guard limits loop continuation,
not absolute process lifetime or USB bus effects.
The initial USB open and HID-descriptor exchange happen before that session
deadline starts, so the deadline does not bound device discovery or claim.

## Offline evidence

- `make -j2 -C drivers apcmicrolink`: **PASS** in new isolated
  `guarded-build-v2-20261008` configured from the v2 patched source tree.
  The binary was not executed.
- The same target with `--with-usb=no`: **PASS** in separate
  `guarded-build-v2-serial-20261008`; the binary was not executed.
- `cc -std=c99 -Wall -Wextra -Werror -I guarded-source-v2-20261008/drivers \
  <app-repo>/backend/nut/test_guarded_policy.c \
  -o <temporary-directory>/test_guarded_policy` followed by the synthetic test
  binary: **PASS**.
  This links the actual policy header with synthetic callbacks: wrong or
  duplicate IDs and descriptor failure cause zero opens; unique target opens
  once; open failure and busy claim do not retry; guarded reset and control
  callbacks are denied; synthetic continuous frames hit the deadline, and
  clock errors fail closed. No libusb calls occur in this test.
- The same C policy test also covers positive dump/foreground admission and
  rejection of zero/negative dump count, background mode, command mode,
  forced shutdown, and explicit PID path: **PASS** against v2 patched source.
- `python3 backend/nut/test_guarded_source_paths.py <patched-source-root>`:
  **PASS**. This static source-path regression checks that the production
  `main()` gate precedes sibling socket/PID signaling, requires the policy
  inputs, skips the guarded competitor `driver.exit` block, and returns
  interrupt PIPE errors before `libusb_clear_halt()`. It does not compile or
  execute the NUT driver and is not runtime integration evidence. Its mutation
  self-check removes the startup gate/fail-closed path, `-P` recording, Windows
  rejection, command-state input, competitor-exit suppression, and guarded
  PIPE return in memory; the static check rejects each mutant.
- `git apply --check` against the pristine source and actual application to a
  separate pristine-derived v2 replay tree: **PASS**. Its six-file diff
  matches the source tree used to regenerate the patch byte-for-byte.

The compiled C stubs exercise policy helpers, **not** the full NUT driver or
all source call paths. The static call-site test checks selected source
structure only; it cannot prove behavior of the compiled executable or
interactions outside those checked paths. Static review found no guarded path
to USB reset, kernel-driver detach, or repeated claim in the reviewed files, but no
hardware/USB behavior is proven. USB interface claiming can itself have
system effects. The upstream `-dN` path skips PID-file creation and
`dstate_init()` (the control socket), but `-d1` still performs initialization,
an initial update, two loop updates, and atexit cleanup; it is not a single
USB exchange. A future bounded hardware plan needs separate explicit user
consent, a fixed private state directory and dump-only invocation, an
independent source review of remaining call paths and cleanup behavior, and
an external stop/timeout guard. No such invocation has been made.
