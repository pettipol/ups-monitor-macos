# Portable continuous diagnostic replay

This offline tool reconstructs a **fake-only** whole-NUT continuous replay.
It uses public sources and synthetic fixtures. It never compiles or links a
genuine HIDAPI implementation, opens USB/HID hardware, or runs an app or daemon.
Offline success does not qualify hardware compatibility, freshness on a real
UPS, or the cause of a previous live failure.

The default invocation and `--compile-only` compile and audit two non-executable
products (mode `0600`). Only `--run-fake` executes the pinned diagnostic suite;
it admits exactly 10 checks and 24 fake subprocesses with closed arguments.
Both products return to mode `0600` after execution, including failures.

## Inputs and reconstruction

`replay_continuous_portable_inputs.json` is the reviewable trust root. It pins
the public NUT archive for revision
`73c4502191d025e35122463986a80c676e734b04`, the ordered patches, and all local
helpers, synthetic configuration, fake host and OS seams. The archive SHA-256 is
`e3ea175565c461a9e741df77dd91103d695b9c60f8d423d9b6ce6c778f98615f`.
This is an exact `git archive --format=tar` serialization previously admitted
from that revision, not a pin for GitHub's dynamically generated tarball.
The tool does not fetch, run Git, or trust a privately configured build.

The first ten current public patches reconstruct the H03-compatible source.
The observation patch is the admission-diagnostic version with SHA-256
`5665093a972b760ea460863cdfefc4f8943065af34da606eeca49cad2bd945d0`;
the older `bf430070...` version reconstructs H01 and is insufficient here.
APC source checkpoints are:

| Stage | `drivers/apcmicrolink.c` SHA-256 |
| --- | --- |
| After the first ten patches | `d741aca668f078e13e97d701111e40d238455bcb3f831c961d5c0edf60dc9504` |
| After the continuous patch | `dc0b5b632883a45850fdfd54594c3abc9987914c8aca2347dfa6e1f8f534d081` |
| After the diagnostic patch | `3cfea88fa1424087fb14d6c857a9cd041a636d70e75321034ecda584f779c2bc` |

The selected archive pack contains the required common/driver units, public
headers and patch targets. Extraction refuses nonregular selected entries,
duplicates, traversal and more than 16 MiB of selected inputs. Before applying
any patch, seven pinned public project modules provide the H03-compatible
baseline absent from pristine upstream NUT: native `.c`/`.h`, shared `.c`,
shared-host/session headers and checked-parser `.c`/`.h`. The native source
baseline is included only to reconstruct the complete patch; it is never
compiled or linked into a fake product. No private H03 file is a runtime input.

All twelve complete patches then apply in order with zero fuzz, including the
native and shared module updates in the continuous patch. No module copy
occurs afterward. The final manifest checks every staged module as well as
the APC checkpoints above. In particular the three intentionally updated
modules must have these post-patch hashes:

| Module | Final SHA-256 |
| --- | --- |
| `apcmicrolink-hidapi-native.c` | `1fa086f34a5cfe46f987c44b1df6452aea0a979268b6e7724415343bfd743cde` |
| `apcmicrolink-hidapi-native.h` | `03555a828c4d159948b9919a8b7d743400d884725050f82e4513ee68e58cbba8` |
| `apcmicrolink-hidapi-shared.c` | `1f55072542e47bd335dc2aeccca7bb6894b5ab1911e62298acd40c4ad96117d7` |

Their input baseline pins are respectively `3a120574...`, `64853190...` and
`a87a7d00...`; the full values are in `local_pins`. These different input/output
pins prevent accidentally restoring an older module after patching. The
reconstruction-order contract test uses synthetic bytes and a simulated patch,
without requiring private sources or executing a native implementation.
Generated `config.h` and `nut_version.h` come only from the existing
synthetic full-replay configuration; shadow generated headers are refused.
No generated native configuration or prebuilt private archive participates.
HIDAPI 0.15.0 remains the production interface reference; this fake target needs
neither the HIDAPI library nor its headers.

## Compiler, confinement and audit

The admitted host is macOS with Python 3.15.2, Xcode 27.1 and macOS 27.0 SDK.
The runner respects an explicit `DEVELOPER_DIR`; otherwise it obtains the
active directory from the local `xcode-select -p`. Bounded local `xcrun` calls
resolve clang, xcodebuild and the selected macOS SDK. Each must resolve within
the selected developer directory, and version gates require the admitted
Xcode/SDK versions. Compiler, xcodebuild and SDKSettings hashes are recorded
and rechecked. Renamed installations such as `Xcode_27.1.app` use the same
policy. This is a macOS portable source reconstruction, not a Linux or
arbitrary Xcode compatibility claim; a particular CI host still needs a run.

The runner reuses the pinned full-driver dependency checks. Its link-map
adapter preserves the full-driver exact-object policy while allowing only the
verified selected developer root and system libraries. It
compiles selected NUT common units directly, without autotools or static NUT
libraries. Every project include must belong to the reconstructed archive pack
or the pinned local files. Each OFF/ON product uses AddressSanitizer and
UndefinedBehaviorSanitizer. The link map must contain exactly the newly compiled
objects and system toolchain libraries. The symbol audit requires the fake
factory, cleanup, clocks and wait implementations and rejects genuine HID,
USB, IOKit, CoreFoundation, network, process-launch and privilege imports.

`replay_continuous_os.c` explicitly reuses the existing full-driver OS, serial
and peer-query sentinel bodies, with provenance in the input manifest.
Forbidden operations print `FORBIDDEN:` and exit 125. User lookup, privilege
changes and the dump-mode directory change are suppressed locally. NUT's
`common.c` also contains directory changes inside its chroot helper; therefore
every guarded translation unit uses `-Dchdir=fixture_chdir`, in addition to
main's existing `FULL_FAKE_MAIN` aliases. The audit retains `chdir` as a
forbidden import and requires the defined no-op `fixture_chdir` seam. A missing
seam has its own negative contract against otherwise complete fake definitions.
Production sources retain their original behavior and the default diagnostic feature gate
remains OFF. This is a narrow fake target with inspected imports, not an OS
sandbox or proof that arbitrary source code is safe.

Every build/audit command uses the canonical `process_deadline.py` with an
owned process group (`Event`), a maximum of 120 seconds, two seconds of
termination grace and 1 MiB of captured output. Discovery commands use 30
seconds. There is no suite subprocess. The exact pinned unittest module is
imported in the runner, keeping its assertions and protocol parser unchanged;
its supervisor call is injected with a narrow closed-argument adapter.

All 24 fake processes are direct children of the runner. One runner-owned
Event is shared by their canonical supervisor and the storage/600-second suite
deadline monitor. The adapter replaces each fresh Event requested by the
unchanged test module, and each child retains an owned process group with a
maximum of 20 seconds, two seconds of grace, and 1 MiB of captured output.
The remaining suite budget can shorten a child's timeout. No later child can
start after cancellation or a non-completed supervisor result. `UNREAPED`
always yields HOLD and is recorded explicitly; it can never qualify cleanup.
The suite permits exactly 24 children, 32 MiB aggregate capture, a 1 MiB
unittest report and exactly 10 tests. The wrapper delegates all decoding and
assertions to the pinned existing module rather than duplicating them.

Generated files stay in a new private directory below the system temporary
root. An independent storage monitor cancels the currently owned command when
the tree crosses 1 GiB, with pre/post-command checks; this is a sampled
software guard, not a filesystem quota. The manifest records actual temporary
bytes. Direct ownership closes the nested-session cancellation gap, within
the canonical supervisor's observable result; abrupt external termination of
the runner is not independently qualified here. The tool does not remove an
output tree automatically.

## Invocation

Use an admitted Python 3.15.2 interpreter. Substitute the archive path and a
new output directory beneath `/private/tmp` or the resolved system `TMPDIR`:

```text
python3.15 -B backend/nut/replay_continuous_portable.py \
  --nut-archive /path/to/admitted/upstream.tar \
  --output-dir /private/tmp/ups-continuous-compile-new --compile-only

python3.15 -B backend/nut/replay_continuous_portable.py \
  --nut-archive /path/to/admitted/upstream.tar \
  --output-dir /private/tmp/ups-continuous-fake-new --run-fake
```

The tool emits a build manifest, bounded command receipts, dependency files,
link maps, symbol/linkage reports and, only with `--run-fake`, the diagnostic
suite receipt. Contract tests cover pin drift, path/symlink/output refusals,
closed arguments, default no-execution behavior and forbidden import rejection
against a passing complete symbol baseline. Independent linkage negatives,
renamed developer-root link maps, shared Event substitution, immediate abort
after a simulated UNREAPED child, and restoration to mode 0600 are also covered.
Network acquisition and legacy replay/CI changes are separate work.
