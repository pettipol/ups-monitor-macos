# Managed native runtime — H07 host-local candidate

This document describes an offline, host-local candidate for the H07 collector’s
bounded 120-second capture path. It does not describe a distributable Python runtime
or a qualified daily monitoring service.

## Staged package

The copy-only stager takes an explicitly supplied native binary, five named Python
modules, and a new destination. It rejects an existing destination, links, special
files, oversized inputs, and a native binary whose SHA-256 differs from the fixed
H07 pin. It copies bytes without executing inputs, writes files with mode `0600`,
re-reads the staged files, and records their hashes. The staged native file is
intentionally non-executable. Its result is `STAGED_NOT_EXECUTABLE` with
`runtime_ready=false`; this staging result cannot be launched as-is.

The five Python modules are:

- `managed_native_entrypoint.py`
- `app_controlled_capture.py`
- `continuous_capture.py`
- `continuous_protocol.py`
- `process_deadline.py`

The staged runtime also contains the fixed native file
`apcmicrolink-hidapi-continuous` and a local `runtime.json`. The manifest has exactly
seven keys: `schema_version`, `profile`, `python_path`, `python_sha256`,
`module_sha256`, `native_name`, and `native_sha256`. It pins the five modules and the
native executable. `python_path` and its hash identify a host-local interpreter; the
manifest can therefore contain private local information and must not be published or
committed. The stager does not copy a Python distribution or prove that the external
interpreter and its standard library form a portable runtime.

## Runtime admission and fixed profile

The entrypoint validates the closed manifest, interpreter identity and mode, every
module hash, and the fixed native name and SHA-256 before importing project modules.
It then constructs the native argument vector internally. Neither the manifest nor
the app supplies arbitrary commands, a native path, or a duration override.

The fixed profile is `apc-smc1500i-120s-v1`. Its native executable is pinned to
SHA-256 `2dae6874c8cb99469a9def4a9f584898e815656d87b93dcc6fd67dba5b7d6183`. The
runtime protocol is `ups-monitor.managed-native.v1`; its source identity is
`apcmicrolink-hidapi-continuous`. Native receipts remain distinct from the synthetic
protocol and source identity. The fixed profile uses the H07 120-second stream and
24-sample ceiling. The existing decoder, capture adapter, and runner retain the
120,000 ms duration, 135-second supervisor timeout, two-second termination grace,
1 MiB combined output cap, and two-second tailer join bound. This path does not require
`ups.conf`, a NUT server, or a background service.

The app candidate validates the manifest and pins before it can form the fixed
capture profile. Native mode requires the exclusive developer flag
`--managed-native-session`; capture begins only after the explicit 120-second Read
action, with no automatic start. It uses the existing owned-session lifecycle: Stop
requests cancellation through the control pipe; ownership remains unresolved until
the matching receipt and process/pipe cleanup are established. An unresolved session
blocks another start. There is no retry or termination shortcut.

## Evidence and limits

The staging receipt records the local copy as `STAGED_NOT_EXECUTABLE`, with stable
hashes and native execution `NOT_RUN`. The selected tests for this lot passed: 36
Swift cases (12 native additions plus 24 existing regression cases) and 12 Python v2
cases. The Python v2 result supersedes the earlier 11-case result; it is not an
additional 11 cases. These injected tests do not run the native collector. The full
test suite was not run.

The app/widget Xcode build passed with return code 0 and unchanged sources.

A local developer bundle is packaged and signature-verified. Relocation of its Python
runtime passed with 3,225 entries unchanged by signing. The manifest stores the
absolute path to the Python interpreter inside that local bundle, so moving the app
requires a manifest update and a new outer signature. Python extensions also depend
on host Homebrew libraries; the standard-library probe loaded external `libcrypto`.
It is therefore not a portable or self-contained runtime. The original staging remains
`STAGED_NOT_EXECUTABLE`; it is distinct from the signed local workbench bundle.

The app and native collector were not launched. Real process transport, app Stop/EOF
behavior, GUI and widget rendering, hardware behavior, daily operation, and release
qualification remain unverified. A targeted scan found 22 occurrences of local build
path prefixes in the native binary. The binary remains a host-local candidate until a
separate distribution derivative has its privacy and identity checked. H07 remains a
separate real bounded capture of 120 seconds and 24 samples; the user reported no
anomaly during that observation. It does not qualify daily operation or general
device compatibility.
