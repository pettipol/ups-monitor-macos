# Admitted Python payload staging

`backend/nut/stage_bundled_python_runtime.py` copies one pinned upstream Python
payload into a new private scratch directory. It never executes the acquired
interpreter, imports its modules, runs a subprocess, signs a binary, installs a
runtime, or changes the host-local operational v2 profile. It is an input to a
later packaging step, not an installable app or a hardware qualification.

## Fixed public inputs

The adjacent `bundled_python_runtime_inputs.json` is byte-pinned in the stager.
The CLI accepts only an archive path and a new destination, with no replacement
manifest, expected hash, interpreter, or environment override. It admits the
PBS `20261026` full CPython 3.15.2 aarch64 artifact with SHA-256
`17a41099bba8c18c45c527580014e75dc7a77300f619d7f5cdfecc57aca06f39`
and 69,311,061 bytes. The metadata is read from `python/PYTHON.json` inside that
same archive and must match the independently fixed hash
`6256d1667b03c2f582c7ba0b4c058f59acd02c8b1819ceca3ce904349e13e1bc`.
An external extracted metadata copy is not substituted for the archive member.

Expected metadata fields are Python 3.15.2, `aarch64-apple-darwin`, executable
`install/bin/python3.15`, and declared deployment target `11.0`. These are
upstream declarations. They do not lower the operational app's separate OS
gate, prove actual Mach-O deployment targets, or establish dylib closure.

The host running the stager needs the standard-library `compression.zstd`
module (Python 3.14 or later with that module available). It must be an already
admitted host interpreter; the archive's own Python is never used to stage it.

```text
python3.15 -I -S -B backend/nut/stage_bundled_python_runtime.py \
  --archive /path/to/pinned-full.tar.zst \
  --destination /private/tmp/private-parent/python-payload
```

The parent must already exist, be canonical, owned by the caller and not writable
by group or others. The destination must be new and strictly below a system
temporary root (`/private/tmp` or the canonical current TMPDIR). Existing files,
directories and symlinks are never overwritten or adopted. Inputs are not
deleted. Failed partial output remains for inspection, without a ready/adopted
status or automatic recursive cleanup.

## Admission before writes

The stager verifies the complete compressed archive size and hash, then scans
every logical tar member before creating the destination. It enforces at most
20,000 members, 4 GiB total file payload, 128 MiB per file and 1 GiB selected
output including the generated inventory. It checks a cooperative 120-second
deadline throughout streamed operations; callers may additionally use their
existing bounded outer supervisor. No new supervisor is included.

The full archive is checked even though `python/build/**` is excluded. The only
selected namespaces are `python/install/**`, `python/licenses/**` and
`python/PYTHON.json`; exactly the top `python/` prefix is removed in output.
The real admitted tar has no explicit directory members, so required parents
are derived and checked rather than assumed present in the tar.

Paths must be canonical relative POSIX names under `python/`; absolute paths,
NUL, backslash, dot traversal, duplicate members, case/Unicode aliases and
file-or-link parents are rejected. Special files, hardlinks, sparse members and
special permission bits are rejected. Directory payload size is zero.

Selected symlinks are permitted only below `install/`, with exact relative
targets that resolve through the admitted graph to a selected regular file or
directory within `install/`. Absolute/external targets, cycles and missing
targets fail before writes. Links are created only after all regular files.
No extraction helper follows a symlink to write a child. Destination operations
use directory descriptors, exclusive creation and `O_NOFOLLOW`.

Metadata validation includes the singular top-level `license_path` and each
plural `build_info.extensions.<name>[index].license_paths` list. Every declared
license path must identify a selected regular file under `licenses/`. All
selected license files are copied, including files not referenced by those
declarations. This records supplied licenses; it is not a legal or redistribution
review. The pinned metadata declares 15 unique license paths in the real asset.

## Output and evidence

The output preserves the selected file bytes and ordinary file permission
bits. Derived directories have mode 0700. Link records preserve the exact target,
resolved relative target, actual created mode and original `source_mode`. No
owner IDs, acquired build paths or private development receipts are inserted.

`runtime-tree.json` contains `schema`, `state`, `profile`, archive and metadata
hashes, expected metadata, public provenance, license declarations and an
`entries` map. Entry names are relative output names: `install/**`, `licenses/**`
and `PYTHON.json`, plus their derived parent directories. File entries record
type, size, mode and SHA-256; symlinks record their targets; directories record
their mode. The inventory does not recursively hash itself. The returned
`inventory_sha256` hashes its exact serialized bytes.

Both copy-time hashing and a complete filesystem comparison run before success.
The source archive's open/named identities and the exclusive destination
directory identity are rechecked. The final inventory and full payload are
verified again after the control file is written. A changing source or replaced
destination fails closed. These checks narrow filesystem races; they do not
claim protection against all concurrent changes by another process of the same
user after the operation returns.

Success is `STAGED_PYTHON_NOT_EXECUTED_NOT_ADOPTED`. The return value includes
regular-file, symlink and derived-directory counts, selected regular payload
bytes, inventory name/hash and the explicit states `closure_macho=NOT_RUN`,
`runtime_execution=NOT_RUN`, `adoption=NOT_ADOPTED`. `file_count` and
`selected_bytes` exclude symlinks and the separately generated control file.
The output cap still includes that generated file.

## Synthetic testing interface

`stage(archive: Path, destination: Path)` always uses the fixed public inputs.
The private `_stage_with_inputs(archive, destination, inputs)` seam accepts the
same closed input schema for small synthetic tar.zst fixtures only. It does not
change the CLI or expose runtime selection to the app. Tests can copy the public
input dict and replace fixture archive/metadata hashes and sizes. A minimal
fixture metadata object contains the four expected fields, `license_path`, a
nonempty `licenses` list and `build_info: {"extensions": {}}`.

`StageError.code` is a closed failure category: `invalid_inputs`, `archive_pin`,
`archive_size`, `deadline`, `member_limit`, `total_limit`, `file_limit`,
`selected_limit`, `unsafe_path`, `duplicate_member`, `unsupported_member`,
`member_parent_conflict`, `unsafe_symlink`, `symlink_cycle`, `missing_target`,
`metadata_pin`, `metadata_contract`, `missing_license`, `destination_rejected`,
`destination_exists`, `source_changed`, or `io_error`. A failed write may be
tested by raising an OSError from `os.write`; no acquired code is required.

## Packaging remains separate

Mach-O load commands, lazy extension dependencies, signing, the final Apple
bundle layout, relocation execution and a clean-host installation check remain
open. Apple TN2206 distinguishes script/data resources from nested Mach-O code;
copying an arbitrary Python directory into Helpers/Frameworks is not accepted as
a proven release layout. The new payload does not change the v2 Swift resolver,
operational entrypoint, native admission, ownership/Stop semantics or any signed
hardware-test candidate. Those require separately reviewed versioned changes.
