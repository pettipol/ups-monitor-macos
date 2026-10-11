# Microlink Session and Power Boundaries

Checked 2026-10-11. **Source research, not a hardware safety qualification.**
No driver, USB claim, protocol exchange or electrical test was performed.

## What the Sources Support

The pinned [NUT Microlink source](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/drivers/apcmicrolink.c)
defines INIT/NAK as `0xFD` and STOP as `0xF7`. Comments describe STOP before
session recovery and cleanup after an observed protocol object. Separate
command paths implement outlet control and shutdown. This supports a semantic
distinction between tunnel teardown and power commands; it does not prove
the effects of every byte on every firmware.

The pinned [NUT changelog](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/NEWS.adoc)
reports that omitting STOP could leave the next client receiving pages from
the previous session until re-enumeration. That is a reported communication
failure, not a documented loss of outlet power. Avoid turning either fact
into an unconditional safety statement.

The open [NUT PR #3719](https://github.com/networkupstools/nut/pull/3719)
proposes removing STOP before INIT and at exit from the serial transport,
while explicitly leaving USB behavior unchanged. It also corrects stale
command documentation and unrelated control paths. The PR is not part of
the frozen candidate, and its serial results cannot qualify USB or a
different device/firmware combination.

The pinned [driver manual](https://github.com/networkupstools/nut/blob/73c4502191d025e35122463986a80c676e734b04/docs/man/apcmicrolink.txt)
still contains an older one-tester USB statement and says driver-assisted
shutdown is unimplemented. Those statements are not an exhaustive current
capability description: later upstream reports cover other models and the
pinned source has a shutdown implementation. The project's guarded patch
rejects control, but this does not make the underlying experimental driver
passive. Documentation drift must not be used to justify hardware access.

The official [libusb 1.0.30 asynchronous API](https://libusb.sourceforge.io/api-1.0/group__libusb__asyncio.html)
requires callback completion before freeing a pending transfer; requesting
cancellation is not completion. Data may already have transferred. On Darwin,
cancelling one transfer affects other transfers on the same endpoint. These
are USB lifecycle contracts, not guarantees about an UPS's output. Terminal
callbacks can also report completion, failure or device loss; CANCELLED is
not the sole terminal status to handle. The older ClearFeature caveat in the
same documentation is conditional on old macOS/libusb versions, not a reason
to reset a current device.

## Evidence Limits

A targeted Perplexity search supplied leads that were checked against the
primary sources above. Its summaries were not accepted as independent proof.
No manufacturer protocol specification or exact-target test establishing
electrical continuity for SMC1500I / UPS10.0 / ID1005 / macOS was found in this
bounded search. This does not establish that no such evidence exists.

The earlier Linux/other-firmware reports remain useful feasibility evidence,
not transferable qualification. The same applies to successful builds,
synthetic ownership tests and the [ownership candidate](NUT_OWNER_RETENTION_CANDIDATE.md).
Opening, claiming, INIT/STOP traffic, cancellation, process termination and
recovery still require a separately agreed test scope. Do not disconnect,
reset, calibrate or issue power commands as a consequence of this document.
