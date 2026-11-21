# Public operational replay E31

E31 is a versioned candidate of the E27 operational replay. It keeps the
frozen continuous v1 runner and manifest, preserves the E27 patch/scenario
contract, admits the current
`process_deadline.py` hash through one explicit baseline override, and uses the
existing pinned `continuous_protocol.py` override. The runner and its input
manifest have E31 filenames; the v1 baseline inputs remain unchanged.

The candidate reconstructs the pinned public NUT source, builds three fake-only
driver modes, audits their dependencies and imports, and can run the fixed
33-case synthetic matrix. Build-only is the default; `--run-fake` explicitly
enables the matrix. Its limits, fake-host audit, scenario set, and other input
pins remain those of E27.

The first local build attempt reconstructed all 190 source files, then failed
at the operational fake-host compilation before any fake child ran. Its quote
includes selected frozen backend preimage headers beside the original fake TU.
The corrected candidate stages byte-identical, hash-pinned copies of the three
fake TUs in a new header-free `output/fake-units` directory. It compiles those
copies with reconstructed source include directories preceding the backend.
Before each compilation it verifies the exact staged directory and pins; the
dependency gate requires reconstructed host headers and rejects corresponding
backend preimage headers. The 190-file source map, C inputs, 17-TU matrix,
33-case suite, limits, and frozen baseline files remain unchanged.

Three additional synthetic contracts cover staged-byte/directory integrity,
patched-header provenance, and the actual fake-host compile argument path.
They preserve the prior 29 contracts. These additions and the corrected build
are `NOT_RUN` at preparation time; the failed first attempt remains separate.

E31 does not include new E30 production diagnostics or E29 formatter scenarios.
On 2026-10-28, the local candidate passed 32 synthetic contract tests and a
complete reconstruction from the pinned public NUT archive: 190 source files,
three builds of 17 translation units each, and all 33 fixed fake cases. The
run completed in about 26 seconds with 632,088 bytes of captured fake output.
The initial compilation attempt remains a failure: compiling a fake host from
the backend directory selected an older local header. The corrected candidate
stages byte-identical fake translation units separately and verifies that their
dependency files select the reconstructed headers.

This is local `PASS_FAKE_ONLY` evidence for the admitted inputs. It does not
establish real USB, GUI/widget or daily-use behavior, apply the E30 diagnostic
delta, or prove a hosted CI run. The current hosted execution remains `NOT_RUN`.

The runner requires macOS Python 3.15.2 in isolated, no-site, no-bytecode mode.
Use an admitted public NUT archive and a new private temporary output directory:

```text
python3.15 -I -S -B replay_operational_portable_e31.py \
  --backend-dir /path/to/public/backend/nut \
  --nut-archive /path/to/admitted/nut.tar \
  --output-dir /private/tmp/ups-operational-e31-compile

python3.15 -I -S -B replay_operational_portable_e31.py \
  --backend-dir /path/to/public/backend/nut \
  --nut-archive /path/to/admitted/nut.tar \
  --output-dir /private/tmp/ups-operational-e31-replay --run-fake
```
