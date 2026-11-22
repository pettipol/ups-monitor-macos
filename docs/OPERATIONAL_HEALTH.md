# Operational native health components

These are separately opted-in source components for the schema-2 continuous
monitor. They do not enable a driver, change the bounded v1 profiles or qualify
an operational app. The full driver loop, app integration and real hardware
qualification remain separate work.

## Source chain

`nut-operational-health-v2.patch` applies only to `drivers/apcmicrolink-hidapi-shared.c`
and `drivers/apcmicrolink-hidapi-session.h` in the admitted continuous source
tree described in [the pacing reproduction](NUT_CONTINUOUS_PACING.md). Its
preimage hashes are respectively:

```text
1f55072542e47bd335dc2aeccca7bb6894b5ab1911e62298acd40c4ad96117d7
50104ad0660fbd3c77fa185b0d8e00269f59775a1e123d3b548cb6c86f77d5ae
```

They are not interchangeable with the earlier standalone shared-transport
source in this directory. Apply the patch to a separate staged tree with
zero fuzz; never overwrite a frozen v1 build or substitute its hash pins.
The tested postimages are:

```text
99f3f7fb8db9e1df4a1790803daa5f7ac2a15d92848caac05d9363c23c25f896
c81be418cf4510bc41868b8a61c8fd90a4de7c28670ac1ab16c80253a237515b
```

The separate [formatter v2 patch](OPERATIONAL_FORMATTER.md) supplies the
64-bit operational field type used by `apcmicrolink-operational-freshness.h`.
Neither patch is selected by the existing v1 replay/staging profiles.

## Health and freshness

`MLINK_HIDAPI_OPERATIONAL_V2` adds a separate opt-in API. STARTING has a fixed
35-second budget. ACTIVE renews a 15-second health lease only after a complete,
eligible publication succeeds. Original elapsed time is never reset. There is
one connection attempt and no automatic retry, reset or reconnect.

The fixed-size freshness helper requires observed UPS status no older than
10 seconds, an advancing minimum observation timestamp, and preservation of
the accumulated set of observed dynamic fields. Missing measurements can stay
unavailable; dropping an earlier field cannot manufacture progress. Preparing
a candidate does not move the successful-publication watermark. Any later
prepare attempt revokes the old candidate; commit follows successful output
and a live native guard. The helper neither performs I/O nor renews the guard.

Stop or failure enters irreversible CLEANING with a separate two-second
budget. Ordinary I/O is refused. Only the existing one-shot protocol STOP is
allowed before close/release; it is not a power-off command. Cleanup errors,
late returns and unresolved ownership remain failures. After native disposal,
the captured finish-clock observation supplies terminal elapsed time without
accessing a released host. These are cooperative checks, not hard deadlines
for kernel calls; the outer process supervisor is still required.

## Verified component scope, 2026-10-27

Luna authored the bounded freshness helper and review corrections; Sol
authored the lifecycle guard and an independent Sol reviewed source and test
plans. Local verification compiled seven standalone variants with Apple
clang 21, AddressSanitizer, UndefinedBehaviorSanitizer and strict warnings,
then completed 15 test-process invocations with exit code zero:

- Freshness assertions, including timestamp/generation bounds, stale status,
  disappearing fields and rejected stale/foreign publication candidates.
- The unchanged 11-case v1 suite with the operational macro both absent and
  present, while the runtime opt-in stays unused.
- Five operational guard groups, including 300,000 virtual milliseconds and
  61 renewals with one open/close, clock transitions within a call, expiry,
  overflow and cleanup boundaries.
- Unbound fail-closed builds with and without the operational macro.
- Nine native-lifecycle scenarios using local binding/disposal/clock stubs:
  clean release, expired lease, invalid/regressing/overflowed finish clock,
  late finish, failed disposal, failed close and failed cleanup STOP.

The stub fixture compiles shared transport plus
`test_hidapi_operational_native_finish.c`; it must never link the actual native
host or HIDAPI. Each scenario runs in its own process because native admission
is one-shot. Undefined-symbol and library audits preceded execution and found
no HIDAPI, libusb, IOKit or network linkage. Each build had a 45-second limit,
each test a 10-second limit, and each command a 64-KiB capture cap. Five virtual
minutes do not mean five physical minutes or a real device session.

These C tests are staged-component checks, not yet part of the ordinary CI
discovery. A public operational staging/replay adapter remains to be completed.
No full native driver, USB device, Swift application or WidgetKit rendering
was exercised by this component verification.
