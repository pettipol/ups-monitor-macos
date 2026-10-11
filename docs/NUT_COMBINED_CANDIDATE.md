# Combined NUT Candidate

Status: **source, synthetic checks and USB/serial builds PASS, 2026-10-11;
driver execution and hardware NOT_RUN**. This is a qualification of two
existing patch artifacts together, not a new patch, a released backend, or
permission to run the driver.

## Inputs

The exact upstream base is
`73c4502191d025e35122463986a80c676e734b04`. Both inputs are GPL-2.0-or-later:

| Patch | SHA-256 |
|---|---|
| `backend/nut/nut-guarded-monitor-73c4502.patch` | `b30a046e9b49d917c137b4d59a27bd84798747d05094e3ff6471654e39d5c8ca` |
| `backend/nut/nut-hid-fallback-validation-73c4502.patch` | `80efa7d122e7f8248999a3d5633fcd994f6d1565e283c21afcec4818e45fe68b` |

No historical patch or replay expectation was changed. Apply only to a new
external checkout at the exact base. Do not install or execute the resulting
driver as part of this offline procedure.

```sh
git -C "$NUT_COMBINED_ROOT" apply --check "$APP_ROOT/backend/nut/nut-guarded-monitor-73c4502.patch"
git -C "$NUT_COMBINED_ROOT" apply "$APP_ROOT/backend/nut/nut-guarded-monitor-73c4502.patch"
git -C "$NUT_COMBINED_ROOT" apply --check "$APP_ROOT/backend/nut/nut-hid-fallback-validation-73c4502.patch"
git -C "$NUT_COMBINED_ROOT" apply "$APP_ROOT/backend/nut/nut-hid-fallback-validation-73c4502.patch"
```

The coordinator independently applied the patches in the reverse order in
another pristine-derived checkout. All six resulting files were byte-identical
between the two orders, including the untracked new policy header:

| Combined path | SHA-256 |
|---|---|
| `drivers/Makefile.am` | `1952fc515db284d628c4ab6578c9d7b3a45036386528cc8f0cf3d1bf66491bcc` |
| `drivers/apcmicrolink-usb.c` | `87b4554132782ee7104d4d18f2204a573d7f68e580129e2280df80fa6cc3fb4e` |
| `drivers/apcmicrolink.c` | `958919e06e333a1b7137711811f4984d65db51ff6988ec04d6f8105d1b438ee1` |
| `drivers/libusb1.c` | `91f973115337b5a5976676ff1cff5f0d706698f2af1014e5a7b4459abc83206f` |
| `drivers/main.c` | `113fd840bb22bc2d9dea9d6761a3e86e36c0eef60b2854ce12cfcc68373fe8ed` |
| `drivers/nut-guarded-policy.h` | `3abba1931d7608c60c4cfa5626ec9fe3b3abfc92b08220b8a15485bb19d5023b` |

## Independent Checks

The five non-USB files match the guard-only candidate exactly. The upstream
calibration map, USB header and report-padding function remain unchanged.
The existing extractor produced byte-identical fallback/getter/reset/publisher
fragments from the combined tree and the hash-qualified standalone HID
candidate, using the same revision-comment label for comparison.

The coordinating reviewer compiled and ran fresh synthetic policy and HID
validation harnesses from the combined source. Both passed; the HID harness
used C99, warnings-as-errors and non-recovering UBSan. Before execution, symbol
and library inspection showed only C runtime dependencies, plus UBSan for the
HID harness. Neither harness links or calls USB or executes a NUT driver.
The existing static guard call-site checker also passed, including its seven
in-memory mutation checks.

The older `check_guarded_merged_rebase.py` requires the fallback to remain
identical to upstream. It is intentionally **not a validator for this combined
tree**. Its six preservation-mutation checks were repeated successfully only
on the separate guard-only tree. The standalone HID runner likewise requires
its exact standalone hashes, not these combined hashes. Do not weaken either
historical source fence to accept a different artifact.

## Build Record

Fresh isolated USB and serial builds of only the `apcmicrolink` target passed.
The build-source copy's six affected files match the hashes above. Autotools
regeneration used existing Autoconf 2.73, Automake 1.19 and GNU libtool 2.6.2.
The first bootstrap failed on missing libtool macros; copying those macros
with `glibtoolize --copy` and setting `LIBTOOLIZE` to that installed executable
allowed the retry to complete. No packages were installed or updated.

Both configurations used a private prefix, `--with-all=no`,
`--with-drivers=apcmicrolink`, `--with-doc=no` and `--with-ssl=no`. The USB build
selected `--with-usb=libusb-1.0`; the serial build selected `--with-usb=no`.
Compilation used `make -j2 -C drivers apcmicrolink`, never `make install`.
The coordinator checked the source hashes, configuration logs and generated
headers, inspected binary linkage, then repeated both incremental build
commands successfully. This repetition was not another clean build.

The USB configuration enables libusb-1.0 and pthreads, and links the existing
libusb 1.0.30 plus libSystem. The serial binary links only libSystem. Both
configurations enable `HAVE_CLOCK_GETTIME` and `HAVE_CLOCK_MONOTONIC` for the
guard's existing timestamp helper. This does not make the HID cache clock
monotonic or test concurrent behavior. The serial build checks compilation
compatibility; it is not a supported guarded USB execution profile.

Warnings remained for the `/usr/local/include` search path, the generated
`common-nut_version.c` circular dependency and allocator wrappers in common
NUT code. Neither build had a compilation or link error. No NUT binary was
executed, including informational options; inspection used file tools only.
No local application, widget, UPS service or power setting was changed by this
build qualification.

## Limits

The [guard limitations](NUT_GUARDS_MERGED.md) and
[HID candidate limitations](NUT_HID_VALIDATION.md) both still apply. Combining
them does not make Microlink wire-read-only: startup, authentication, polling
and cleanup may send traffic. The deadline is not an absolute OS-call or
process-lifetime guarantee. Optional-field freshness, full runtime concurrency,
USB coexistence, accurate real measurements and electrical safety remain
unqualified. The local SMC1500I firmware-10/macOS case is not demonstrated by
these tests. No shutdown supervisor should consume this experimental candidate
as a safety mechanism.
