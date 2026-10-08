# NUT Guarded Source Prototype

Status: **offline prototype, hardware NOT_RUN, live consent HOLD**. No candidate
driver, scanner, daemon, service, USB handle, or UPS was run or opened in this
work. This document does not identify or qualify a target model.

## Provenance

`backend/nut/nut-guarded-monitor.patch` applies to Network UPS Tools commit
`1a8369f8688443a500527059167d2f66ca27535f`. The patch and included
guarded C helper are derived from NUT source and remain GPL-2.0-or-later per
upstream headers, separate from the application's MIT code. The original
`source` and `build` snapshots were not changed. The patch applied cleanly to
a pristine archive at that commit, and all six affected files compared
byte-for-byte with the isolated `guarded-source` prototype.

## Opt-in behavior

The default NUT path is unchanged without `guarded_monitor`. The experimental
profile requires `port=auto`, a libusb-1.0-only build, exact four-digit hex
`guard_vid` and `guard_pid`, and `guard_deadline` from 1 to 300 seconds.
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
driver over the local socket. These guards are qualified only for the
`apcmicrolink` driver; use of `guarded_monitor` with another NUT USB driver is
unsupported and unreviewed. Normal protocol STOP, INIT, NEXT, authentication,
reads, and cleanup still transmit
to the device. This is **not wire-read-only** and the opt-in profile is not
permission to run it on hardware.

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

- `make -j2 -C drivers apcmicrolink`: **PASS** in isolated `guarded-build`.
- The same target with `--with-usb=no`: **PASS** in isolated
  `guarded-build-serial`, checking the unchanged serial-only default build.
- `make -j2 -C clients upsc`: **PASS** in isolated `guarded-build`.
- `cc -std=c99 -Wall -Wextra -Werror -I guarded-source/drivers \
  <app-repo>/backend/nut/test_guarded_policy.c \
  -o guarded-build/test_guarded_policy` followed by the test binary: **PASS**.
  This links the actual policy header with synthetic callbacks: wrong or
  duplicate IDs and descriptor failure cause zero opens; unique target opens
  once; open failure and busy claim do not retry; guarded reset and control
  callbacks are denied; synthetic continuous frames hit the deadline, and
  clock errors fail closed. No libusb calls occur in this test.
- `git apply --check` against the pristine source: **PASS**. Actual application
  to a separate pristine archive and byte comparisons: **PASS**.

The compiled C stubs exercise policy helpers, **not** the full NUT driver or
all source call paths. Static review found no guarded path to USB reset,
kernel-driver detach, or repeated claim in the reviewed files, but no
hardware/USB behavior is proven. USB interface claiming can itself have
system effects. The upstream `-dN` path skips PID-file creation and
`dstate_init()` (the control socket), but `-d1` still performs initialization,
an initial update, two loop updates, and atexit cleanup; it is not a single
USB exchange. A future bounded hardware plan needs separate explicit user
consent, a fixed private state directory and dump-only invocation, an
independent source review of remaining call paths and cleanup behavior, and
an external stop/timeout guard. No such invocation has been made.
