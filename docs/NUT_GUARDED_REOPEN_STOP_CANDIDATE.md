# NUT guarded reopen stop candidate

Status: candidate patch 8 has passed the bounded synthetic integration matrix
recorded below and four offline driver compile/link passes (USB and serial A/B).
No resulting driver executable has been run. This is limited to
the guarded-monitor source path; it is not hardware authorization or evidence
of device behavior. Root independently repeated the same matrix with
byte-identical result records; that repeat is confirmation of the same 15
scenarios, not another set of scenarios.

## Change

`nut-guarded-reopen-stop-73c4502.patch` adds cooperative stop checkpoints to
`drivers/apcmicrolink-usb.c`. The guarded stop query reads the existing
`nut_guarded_dump_signal_requested()` state. The ordinary, non-guarded profile
does not take these gates.

The reopen path checks at entry, before `open_dev()`, after a successful open,
and after async startup. Where a handle has already been opened, it routes
through `microlink_usb_close()` so existing ownership rules decide whether the
handle can be closed or must remain retained. Async startup checks the existing
owner before changing it, rejects a new generation before allocation when stop
is already requested, and rechecks under the publication lock after local
allocation. The last check frees only unpublished local allocations.

These are cooperative checkpoints, not an atomic stop transaction. A check
cannot interrupt an API call already in progress or eliminate the interval
between checking and entering an API. The change does not alter the protocol
STOP policy, add protocol writes, or change the pump/callback behavior.

## Synthetic replay

`extract_guarded_reopen_stop.py` is extract-only. Given separately prepared
base-7 and candidate-8 source trees, it validates pinned files and writes a
self-contained base/candidate fixture bundle into a new scratch directory:

```sh
python3 backend/nut/extract_guarded_reopen_stop.py \
  --mode extract \
  --base /path/to/base-7-source \
  --candidate /path/to/candidate-8-source \
  --scratch /path/to/new-scratch
```

The extractor validates the pinned base-7 and candidate-8 trees and writes
source-exact function bodies plus the existing ownership fixture into a new
scratch directory. Its manifest remains `EXTRACTED_NOT_RUN`; the separate
private replay used that extracted bundle.

The local build compiled the wrapper as the sole translation unit, with the
generated source and prior fixture included by that wrapper. Command template:

```sh
/usr/bin/clang -std=gnu11 -O0 -g -pthread -fsanitize=undefined \
  -fno-sanitize-recover=undefined -Wall -Wextra -I <bundle> \
  <bundle>/test_guarded_reopen_stop.c -o <new-binary>
```

The first two compile attempts incorrectly passed generated and wrapper files
as separate translation units and failed on missing mock type declarations.
Those invocation failures are not driver RED evidence. The corrected
wrapper-only command linked both base and candidate. It emitted one
signed/unsigned comparison warning in the fixture; no product source warning
was observed.

The executed matrix covered 15 distinct scenarios and 30 bounded child runs:
eight guarded-stop scenarios on base-7 produced the expected `EXITED`, rc 1,
`FAIL <case>` RED results; the corresponding eight candidate-8 scenarios
produced rc 0 and `PASS <case>`. Seven controls produced rc 0 and `PASS <case>`
on both base and candidate, for 22 positive runs total. The controls were
`ordinary-reopen-stop-flag`, `flush-active-race`, `guarded-reopen-no-reset`,
`pending-open-reopen-flush`, `open-start-pending`, `reopen-start-pending`, and
`open-fallback`. The aliases `healthy-guarded-reopen` and `ordinary-fallback`
were not counted or run. All 30 child runs exited normally within the bounded
runner, output capture byte counts matched the helper, and no UBSan marker,
timeout, crash, or unexpected result was observed.

The run used `process_deadline.py` with a 10-second timeout, 1-second
termination grace, 1 MiB output cap, and a minimal environment. The synthetic
processes use only the mock transport and local pthread barriers; no operational
NUT executable or real USB library was linked or run.

Root's independent repeat also completed with rc 0 and 30 matching records
(result-record SHA-256
`239367914c89f3d645c239ca5d148e007c50746cd0f34a498ed78b8900fbf1b2`).

Seven subsequent single-gate mutations were compiled in separate scratch
copies and inspected before execution. Every mutation was caught by its
named assertion (normal exit 1, exact FAIL marker, no timeout or UBSan), then
independently repeated with matching records. These are sensitivity checks of
the same scenarios, not seven additional functional scenarios. Reopen entry,
pre-open, post-open, post-start, active-owner, no-owner and prepublication
gates were removed individually. The post-start mutation uses
`start-stop-quiescent`: pending alone can be masked by the existing
`async_ret < 0` branch. Result-record SHA-256:
`b28da6ef0e3b7b8ed6cea6c7930394e62889246bfed9314896d7aa74e5a7ee12`.
The first mutation pass also had an outer 120-second limit, which did not
trigger; the independent repeat used only the reviewed per-child bounds.
Single-gate sensitivity is not coverage of combined faults or hardware races.

### Reproducibility pins

| Input or artifact | SHA-256 |
| --- | --- |
| Base-7 USB source | `d6f61c595fd87e3f7d4e416ba8f8d6e04293ea3ff12c93dce60ad0384b4d056d` |
| Candidate-8 USB source | `6023981a06e8b1a3f2eb6db13c91b712060275d4566f398fcd7cb05cd3fe4f99` |
| Patch 8 | `250ce19f42caeee51127c063d595858349cb6c8695ca765372abca4c7b26a55f` |
| Prior ownership fixture | `c16666c10254405ca20cbc4b3c9c0642cb8048e2978a7e736a64134eaebd7326` |
| RF-04 wrapper | `30853976fc70948589b6bb3a8aab2dafe60098bb55b46be9069fcea2b7a18ba6` |
| Generated base-7 C | `6ac4babb3eadb406e524a53822b9175932a990cc13e9bd60968b0687881ad281` |
| Generated candidate-8 C | `cf68ae6b0736ad182a505459fcabe19515b9224b715730990a9b47c5faf3f932` |
| Replay runner | `a7dc1317f7ae59be1e26e88ecef80aea8d47783c62dd5c618fd6c1e38cc1c3d6` |
| Bounded-run helper | `45505a7d8cc6cbae6287ca6c995254da311aadac7130c237da2022b11a053efd` |
| NUT base revision | `73c4502191d025e35122463986a80c676e734b04` plus patches 1-7 |

Python verification recorded 8 focused extractor tests passing; root's
backend and privacy checks recorded 130 and 14 passing, respectively. The eight
extractor tests are included in the 130, not an additional count. The historical
generator default was independently confirmed byte-identical with SHA-256
`ac877280713977335f7b824ea84d4a8aef60014e23aa910bb8bfa20bc4db9850`, and root
confirmed extraction byte identity. Those synthetic results are separate from
the subsequent complete driver build recorded next.

## Complete offline build

On 2026-10-12, Luna built the eight-patch source with the previously generated,
pinned configure inputs. Sol reviewed preparation and execution gates, and root
independently repeated the preflight and checked archived files. The old source
manifests were changed only for the exact patch-8 USB source hash; all 1,285
frozen files, 72 generated additions and six reviewed symlinks were verified.
The build runner changed only paths and pins from the prior reviewed version.

Each profile was compiled twice at the same work path with an explicit clean
environment, pinned compiler/SDK/libusb, verbose commands, and separate archives.
All four compile/link passes succeeded. Root rehashed all recorded artifacts,
compiler prerequisites and the 1,357 source files of each archived copy, checked
symlink targets and compared the source-before/source-after manifests.

| Profile | Artifacts / prerequisites verified per pass | Executable SHA-256, identical in A/B |
| --- | --- | --- |
| USB | 518 / 294 | `e07ac1a09a51ec40770bb804457fb14f675fa9a01c2cbd92f697fd160c531473` |
| Serial | 508 / 273 | `de48741fe587ec9d70f9aa8b6b9da66d287ad8f76a3afb02dff0d7ec076326e1` |

Only `config.log` differed between A/B: process/load snapshots and temporary
conftest filenames. No prerequisite hash differed. Metadata inspection shows
libusb and libSystem for USB, and only libSystem for serial. The existing
unreachable-return and allocator-wrapper warnings remain visible in the logs.

Configure can run compiler feature conftests; this is not a zero-execution
claim. Its installed-NUT runtime probe is explicitly disabled with
`--disable-inplace-runtime`; libusb symbol checks compile/link without executing
USB calls. No autogen, install, check target, operational NUT executable, or
device probe was run. The new A/B observations show local repeatability, not
general reproducibility or exhaustive toolchain provenance. Installed versions
were pinned, not updated or claimed to be the latest official versions.
C02 remains PARTIAL; integrated main replay on this eight-patch combination
remains NOT_RUN, and the resulting executables are not authorized for hardware.

The atomic test flag is not a real signal delivery path. Mock libusb and local
pthread barriers do not qualify real libusb, kernel transfer cancellation,
macOS scheduling, NUT process shutdown, protocol output, or physical UPS
behavior. C03 retry policy remains open. The separate C07
[SIGINT library adapter](PROCESS_DEADLINE.md#operator-adapter) has synthetic
Python evidence, but no app, fixed-driver-profile or integrated-main evidence. Hardware
qualification remains HOLD. The new fixture is GPL-2.0-or-later derived test
material; the extractor and private runner are MIT licensed.
