# NUT APC Microlink Feasibility

Snapshot date: 2026-10-08

This is the initial unmodified-source baseline. Subsequent same-day work is
recorded separately in [driver guards](NUT_GUARDS.md) and
[client completion qualification](NUT_CLIENT_COMPLETION.md). Since this
baseline, `upsc` has run against synthetic loopback fixtures and GPL-covered
patches have been added; no UPS driver or hardware has been run.

## Verdict

`apcmicrolink` is available only in experimental NUT master at the pinned
revision below; NUT 2.8.5 does not include it. Source inspection shows that
driver startup and ordinary monitoring are not wire-read-only: they send
Microlink control and data frames, and may send an authentication response.
The driver also exposes UPS-changing commands, writable settings, a shutdown
handler, and a USB bus reset path. This offline build does not establish that
any of those operations are safe for a particular UPS.

An isolated offline compile now succeeds for `apcmicrolink` and `upsc` from
the pinned source. This supersedes the earlier bootstrap blocker; the first
two attempts had stopped before C compilation because `autoreconf` was absent.
Neither binary was executed. No driver, scanner, daemon, service, or hardware
interface was opened or run. No NUT source was copied into this repository.

## Source and Build Evidence

- The official GitHub API reported `networkupstools/nut` `master` HEAD as
  `1a8369f8688443a500527059167d2f66ca27535f`, matching the candidate already
  recorded in `DEPENDENCIES.md`. The cloned workbench checkout is detached at
  that full SHA and reports a clean Git status. The commit date is 2026-10-02.
- NUT 2.8.5 is the latest stable version recorded in the repository baseline;
  its release source does not contain `apcmicrolink`.
- Local build environment observed: macOS 27.0.1, Xcode 27.0 build 27A266a,
  Swift 6.4, macOS SDK 27.0, and libusb 1.0.30 via `pkg-config`.
- NUT is Autotools-based. `drivers/Makefile.am:238-242` defines
  `apcmicrolink`; USB transport files and libusb linkage are included when
  `WITH_USB` is enabled. `docs/configure.txt` documents
  `--with-drivers=<driver,...>` and `--with-usb=libusb-1.0`.
- The original two attempts failed before compilation: `./autogen.sh` returned
  1 with `autoreconf` absent, then `./configure` returned 127 because the
  script had not been generated. This was a toolchain blocker, not hardware
  incompatibility.
- GNU [Autoconf 2.73](https://ftp.gnu.org/gnu/autoconf/autoconf-2.73.tar.xz)
  (`autoconf-2.73.tar.xz`, SHA-256
  `9fd672b1c8425fac2fa67fa0477b990987268b90ff36d5f016dae57be0d6b52e`)
  and [Automake 1.19](https://ftp.gnu.org/gnu/automake/automake-1.19.tar.xz)
  (`automake-1.19.tar.xz`, SHA-256
  `e3e2c2e3abf37898138db5b6c1d1dc35c9160c5978be7947d2c741705251d445`)
  were downloaded from `ftp.gnu.org`, checked against their GNU release
  [Autoconf](https://www.mail-archive.com/autoconf@gnu.org/msg25059.html) and
  [Automake](https://www.mail-archive.com/autotools-announce@gnu.org/msg00164.html)
  announcements, built with `make -j2`, and installed only into a workbench
  prefix. GNU M4 1.4.21 and Libtool 2.6.2 were already available on the host.
  No global package installation or upgrade was performed.
- With that prefix on `PATH`, `ACLOCAL_PATH` pointing at the existing Libtool
  macros, and `LIBTOOLIZE` set to the existing `glibtoolize`, `./autogen.sh`
  returned 0 and generated `configure`. Its generated files stayed in the
  external source checkout, whose tracked Git status remained clean.
- Out-of-tree `configure` returned 0 with `--with-all=no
  --with-drivers=apcmicrolink --with-usb=libusb-1.0 --with-doc=no
  --with-ssl=no` and an unused workbench install prefix. Config headers report
  `WITH_USB=1` and `WITH_LIBUSB_1_0=1`.
- `make -j2 -C drivers apcmicrolink` and `make -j2 -C clients upsc` both
  returned 0. The driver is a Mach-O arm64 executable linked to the host's
  libusb 1.0.30; `clients/.libs/upsc` is a Mach-O arm64 executable and
  `clients/upsc` is its Libtool shell wrapper. The build emitted compiler
  warnings, including unsafe `/usr/local/include` search-path warnings, but
  no target failure. The `upsc` binary refers to the unused workbench install
  prefix for `libupsclient`; this is a compile result, not a portable package
  or a run test.

The bootstrap invocation regenerated ignored helper files in the external
checkout; its tracked Git status remained clean. All build output remained
outside the application repository. Preserve NUT's own GPL terms; the driver
source headers state GPL version 2 or later. Do not copy
or relabel the NUT driver as this project's MIT-licensed source.

## Swift Client Search

Bounded official GitHub API repository searches on 2026-10-08 found no Swift
repository matching Network UPS Tools. A macOS Swift UPS-monitor search found
three small MIT-licensed applications (`eliliu911/APCUPSMonitor`,
`VampirodeMerens/tripplite-avr-mac`, and
`VampirodeMerens/isb-intellisoft-mac`), but not a maintained general-purpose
Swift NUT client library. The APC monitor repository had been created on
2026-10-02 and is an application, not a library; this is not sufficient
maintenance or reuse evidence. No Swift client was implemented. Prefer an
existing NUT `upsc`/network-protocol bridge when a separately managed NUT
service is already present, subject to its own security and licensing review.

Search endpoints:

- <https://api.github.com/search/repositories?q=Network+UPS+Tools+language%3ASwift&sort=updated&per_page=10>
- <https://api.github.com/search/repositories?q=UPS+monitor+macOS+language%3ASwift&sort=updated&per_page=10>

## Driver Data and Side-Effect Paths

Line references below are relative to the pinned NUT revision. They describe
reachable source paths, not proof that every UPS reacts identically.

- USB selection calls `microlink_usb_open()` from `upsdrv_initups()` when
  `port=auto` or USB matching options are configured
  (`drivers/apcmicrolink.c:3717-3762`). Opening the HID interface is already
  outside a passive inventory and requires explicit user consent.
- Session initialization sends STOP (`0xF7`) and INIT (`0xFD`) control bytes
  (`drivers/apcmicrolink.c:3186-3245`). Poll setup and every poll send NEXT
  (`0xFE`) before receiving (`drivers/apcmicrolink.c:688-700`,
  `3088-3107`, `3125-3178`). The write helpers route those bytes to USB
  `microlink_usb_send_bytes()` (`drivers/apcmicrolink.c:2698-2739`), which
  emits an interrupt-OUT HID report (`drivers/apcmicrolink-usb.c:718-770`).
- If authentication is required and descriptors are available, startup
  constructs and writes a slave-password response
  (`drivers/apcmicrolink.c:2875-2910`, `3001-3030`). Debug trace calls in this
  function include serial-derived authentication inputs and payload bytes;
  debug-log handling therefore needs review before any live use.
- On a detected genuine USB disconnect, a later update may call
  `microlink_usb_reset_and_reopen()` (`drivers/apcmicrolink.c:3940-3960`);
  the helper sends a USB bus reset before reopening
  (`drivers/apcmicrolink-usb.c:541-589`). This is reachable during the
  monitor's recovery path, not just an operator command.
- `upsdrv_initinfo()` registers battery-test, panel-test, beeper, calibration,
  and bypass commands and attaches `instcmd`/`setvar`
  (`drivers/apcmicrolink.c:3908-3920`). Outlet/load and shutdown commands are
  also registered when outlet descriptors are available
  (`drivers/apcmicrolink.c:3765-3818`). The handlers can write outlet/load
  commands and settings (`1320-1391`, `1394-1458`, `3672-3715`); mappings
  include writable shutdown/reboot timers (`drivers/apcmicrolink-maps.c:331-360`).
- `upsdrv_shutdown()` invokes `shutdown.return`
  (`drivers/apcmicrolink.c:4034-4043`). Cleanup sends STOP after any protocol
  traffic (`drivers/apcmicrolink.c:4071-4100`). Thus a supervising service's
  lifecycle can cause device writes even without a user invoking an instant
  command.
- In the inspected paths, normal `upsdrv_updateinfo()` does not itself call
  the driver's `instcmd` or `setvar` handlers. Those handlers are reached
  through incoming `INSTCMD` or `SET` requests
  (`drivers/dstate.c:1130-1161`, `1250-1262`) or a shutdown
  path. The shared `shutdown.default` command invokes `upsdrv_shutdown()`, and
  `driver.killpower` can do so after its explicit allow flag is set
  (`drivers/main.c:1093-1113`). A driver launched with `-k` also takes the
  shutdown path (`drivers/main.c:2740-2780`). These are distinct from the
  protocol writes during ordinary startup, polling, recovery, and cleanup.

## Static Preflight for a Bounded Candidate Run

This is source analysis only; no candidate was launched.

- `-d 1` keeps the driver in the foreground, skips the state-socket creation
  and socket polling, and dumps data before normal process exit
  (`drivers/main.c:2402-2431`, `3272-3274`, `3463-3528`). Thus it would remove
  the ordinary incoming `INSTCMD`/`SET` channel for that process. It is not a
  single device update: `upsdrv_initinfo()` performs handshake and possibly
  repeated startup polls; `main` then calls `upsdrv_updateinfo()` once before
  the dump loop, which calls it twice more for `-d 1`
  (`drivers/main.c:3230-3250`, `3498-3514`).
- Even in dump mode, startup first probes for an existing driver with the same
  name and UPS ID and sends `INSTCMD driver.exit` if found
  (`drivers/main.c:2890-2970`). A fresh private `NUT_STATEPATH` and a unique
  `-s` ID would isolate that lookup from existing NUT instances; this must be
  checked before any run. A private `0700` directory also requires that the
  selected run-as user can access it. `-s` takes parameters from command-line
  `-x` options instead of an `ups.conf` section (`drivers/main.c:292-304`,
  `2494-2519`).
- Dump mode does not disable the driver's startup, polling, authentication,
  recovery, or cleanup writes. A libusb `NO_DEVICE` error can set
  `usb_device_gone` (`drivers/apcmicrolink-usb.c:761`, `932`, `1167`); the next
  failed-session update can call `microlink_usb_reset_and_reopen()`, which
  invokes `usb_reset()` (`drivers/apcmicrolink.c:3945-3951`,
  `drivers/apcmicrolink-usb.c:541-558`). This can occur in a bounded dump run.
- The USB read budget is 1 second per Microlink receive attempt, the initial
  handshake permits 10 attempts, and one later poll burst has a 10-second
  ceiling (`drivers/apcmicrolink.c:80-87`, `185`, `637-643`, `3148-3177`).
  Those local limits are not a global wall-clock limit: the startup loop
  continues while it gets intermittent successful frames but is not yet
  `microlink_startup_ready()` (`drivers/apcmicrolink.c:2006-2031`,
  `3849-3855`). An external hard timeout would skip orderly cleanup; it is
  not a proven safe substitute for a source-level bound.
- Once `upsdrv_initups()` returns, `main` registers `upsdrv_cleanup()` with
  `atexit` (`drivers/main.c:3206-3210`). Normal dump exit therefore reaches
  cleanup, which sends STOP if protocol traffic was seen and closes USB
  (`drivers/apcmicrolink.c:4071-4100`). A crash or forced termination does not
  have that guarantee. `-k` and `driver.killpower` enter the shutdown handler,
  not the normal cleanup path (`drivers/main.c:250-269`, `1093-1113`).

## Consent Boundary and Open Work

### Shared USB Open Path

The pinned arm64 build uses `drivers/libusb1.c` through
`comm_driver->open_dev()` (`drivers/apcmicrolink-usb.c:107`, `486`). This
shared backend enumerates the USB device list and calls `libusb_open()` on
each device before collecting string descriptors and applying the configured
vendor/product/serial matchers (`drivers/libusb1.c:374-402`, `406-574`).
Therefore, even exact `vendorid`/`productid` options do not confine handle
opens to the intended UPS. They do confine which opened device proceeds to
claim, subject to the matcher and callback. Before Microlink protocol traffic,
the backend attempts to claim the selected candidate's HID interface; this build includes
conditional kernel-driver active/auto-detach checks and a claim/detach retry
loop (`drivers/libusb1.c:586-687`). The explicit
`libusb_set_configuration()` call is inside `WIN32` guards, and
`libusb_set_interface_alt_setting()` is skipped unless
`usb_set_altinterface` is configured (`drivers/libusb1.c:218-247`, `613-620`).
The actual macOS/libusb responses and effects are `NOT RUN`. The shared open
path has no visible USB bus reset; the reset path identified above is in
`apcmicrolink` recovery. No existing NUT option in the inspected USB and
driver variable tables suppresses that reset or places a global deadline on
Microlink startup (`drivers/libusb1.c:147-193`,
`drivers/apcmicrolink.c:4045-4059`). A narrow experimental change would need
an exact-ID pre-open filter in the shared backend, a driver-specific no-reset
gate, and a monotonic startup deadline. The pre-open filter should fail closed
when IDs are absent, regex-based, or ambiguous; if multiple devices share the
same IDs, it still cannot isolate one physical UPS without another verified
selector. These are proposed controls, not implemented or tested here.

Before any live validation, a future request must name the exact UPS and
connection, authorize opening the interface and the specific startup/poll
frames, authentication response if required, cleanup STOP, and possible USB
bus reset on disconnect. It must separately address all registered `instcmd`,
writable `setvar`, and shutdown paths, including `-k`, `shutdown.default`, and
`driver.killpower`. Not launching `upsd` or `upsmon` would reduce command
ingress in regular mode, but the running driver still exposes a local protocol
socket and the source has no read-only switch visible in these paths. Dump
mode avoids that socket but still permits protocol writes and USB reset. A
minimal runtime configuration alone is therefore not an enforcement gate. A
reviewed monitor-only/no-reset change with a bounded startup loop, wrapper,
or different client architecture would need independent proof before claiming
these actions are excluded. The source-level feature gate must also keep a
future product API from exposing trusted UPS commands accidentally.

The offline build gate is complete. USB permissions, HID report behavior,
model/firmware compatibility, telemetry correctness, lifecycle effects, and
live safety remain `NOT RUN` or unqualified. Do not run these artifacts on
hardware under this report.
