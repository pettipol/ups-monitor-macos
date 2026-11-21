# Continuous Integration

## Hosted candidate attempt: 2026-11-21

[Run 44923796013](https://github.com/pettipol/ups-monitor-macos/actions/runs/44923796013)
tested PR head `03919651765827aa1116cb714a4e7c5e2067a0df` through merge
commit `6150d969d90feb281077395b73e40c70d341d352`. Its tree
`035c3ee59c3e8f0cb3c6c28e2cc7bf04157363b3` exactly matches the reviewed
local source candidate. Offline reader contracts passed. The build job
provisioned Python 3.15.2 and passed both the synthetic preflight guards and
the real Xcode 27.2/27B52, Swift 6.4.2 and Python preflight on image
`xcode-27-arm64`, version `20261104.0337.1`.

The build job then failed in the Python runtime normalizer fixtures, before
Swift tests or app compilation. The runner's temporary directory used a
`/var` alias, while the fixture passed that noncanonical path to a production
API that deliberately rejects aliased source paths. A local reproduction
using the equivalent `/tmp` alias produced the same 12 failures and one error
among 14 tests. The follow-up canonicalizes only the synthetic fixture root;
15 local tests pass, including a new check that an explicitly symlinked source
is still rejected before destination creation. Production checks are unchanged.
The correction requires its own hosted result; the failed run is not a build PASS.

The dated records below describe earlier checkpoints. Their `NOT RUN` claims
do not override this hosted attempt. Consult the checks on
[PR #1](https://github.com/pettipol/ups-monitor-macos/pull/1) for later revisions;
hardware Stop, desktop-widget behavior and sustained monitoring remain separate.

## Previous source review: 2026-11-19

The documented Xcode mismatch is resolved at the image-inventory level.
The [official image at commit c0f5743a](https://github.com/actions/runner-images/blob/c0f5743aeac97a0d687047af9f309b34c254b261/images/macos/xcode-27-arm64-Readme.md)
identifies image `20261104.0337.1` and maps `/Applications/Xcode_27.2.app`
to stable build `27B52`. The workflow keeps its exact preflight because the
hosted label is mutable. This source observation is not a hosted execution.

The proposed workflow now pins `actions/setup-python` v7.1.0 at
`6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`, matching the official release
tag. Its new optional mirror inputs are not configured; CPython uses the
upstream default and the existing read-only GitHub token behavior. There is
no new secret, permission, package cache, custom mirror or dispatch in this
change. The action continues to use Node 24. Review covered the release,
tag, action inputs and affected Python acquisition source, not the entire
bundled JavaScript/dependency graph.

At that review, the latest recorded public [workflow run](https://github.com/pettipol/ups-monitor-macos/actions/runs/38159191972)
passed on 2026-10-11 at `b214a72547d43d677c180af4f7b7352a2360623d`.
It does not exercise the current working tree or updated workflow. Hosted
provisioning and validation of the intended release revision remain **NOT RUN**.
No new workflow was dispatched as part of this review. The dated local results
and earlier image observations below retain their historical scope.

## Earlier validation

Configuration reviewed on 2026-10-08. **First hosted execution PASS** on source
commit `270ac3e8edb2ffd0548ff0927363a81dffdf5f81`:
[GitHub run 37788712924](https://github.com/pettipol/ups-monitor-macos/actions/runs/37788712924).
This is synthetic source/build evidence, not product or hardware qualification.
The local pin was refreshed on 2026-11-04 to Xcode 27.2 build 27B52 and Apple
Swift 6.4.2. No hosted run has exercised the refreshed selection. The linked
run and its counts below are historical and do not validate the updated pins.

The candidate workflow has two jobs. `reader-contracts` runs the six offline
reader suites with Python 3.15.2 on the GitHub-hosted `macos-26` arm64 label,
without selecting or checking Xcode. `macos` retains the existing build job
name and `xcode-27` runner; it requires the reader job to succeed and runs the
synthetic preflight harness followed by `scripts/check.sh`, whose real toolchain
preflight rejects a mismatched Xcode/Swift/Python before its test suite. A
reader-only PASS never represents a successful build. This is a candidate
configuration: provisioning and execution on either hosted runner are
`NOT RUN`. See the [validation procedure and result](VALIDATION.md).

The local check on 2026-11-05 covered 723 Python tests across the main and
separate suites and 453 distinct Swift cases including two opt-in client tests
against localhost fixtures. The Swift build resumed after an interruption of
the local process monitor. This is local evidence, separate from the proposed
hosted jobs.

A [complete local run on 2026-10-29](LOCAL_VALIDATION_2026-10-29.md) passed
on a frozen working-tree copy: 617 Python tests and 447 Swift tests passed,
with two expected optional-client skips, followed by Release builds and local
metadata/signature checks. It includes uncommitted changes and supersedes the
[2026-10-28 local integration checkpoint](LOCAL_VALIDATION_2026-10-28.md) for
the configured check. It does not replace hosted provisioning or validation
of the intended release commit.

The refreshed local baseline passed the complete configured check on
2026-11-04 using Xcode 27.2 build 27B52, Apple Swift 6.4.2 and Python 3.15.2:
640 Python tests passed; 447 Swift tests passed and two optional NUT-client
tests were skipped. The run also completed Swift and Xcode Release builds,
metadata/privacy-manifest checks and ad-hoc signature verification on a frozen
503-file source copy. This is local synthetic/build evidence only. The image
inventory checked at that checkpoint mapped Xcode 27.2 to RC build 27B48,
which the exact preflight rejected. That mismatch held hosted qualification
at the time; the November 19 inventory update is recorded above. See the [dated
local result](LOCAL_VALIDATION_2026-11-04.md). Historical E31/E32 replay pins
remain unqualified against the current source; no automatic repinning is claimed.
The full Python runtime packaging recipe also remains pending.

Both jobs use the same workflow triggers: pushes to `main`, pull requests and
manual dispatch. Permissions remain `contents: read`; checkout credentials are
not persisted. The workflow references no repository secrets, certificates,
App Group, deployment environment or self-hosted runner. It uses neither
`pull_request_target` nor `workflow_run` to execute untrusted PR code. No
artifacts, credentials or release binaries are uploaded by this workflow.

The reader job uses the documented GitHub-hosted `macos-26` arm64 label; see
[GitHub-hosted runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories).
The explicit runtime assertion checks Python 3.15.2, Darwin and `arm64`; the
[official Python 3.15.2 build release](https://github.com/actions/python-versions/releases/tag/3.15.2-40340363276)
lists the matching macOS arm64 build. These source records support the proposed
selection only. They do not prove setup-python provisioning or a hosted run.

Pull requests can execute their changed tests on the disposable GitHub-hosted
runner. On 2026-10-08 the repository API confirmed approval required for all
external contributors, default workflow permissions read-only and no workflow
permission to approve pull requests. This YAML does not configure those
account-side settings. Repository-wide action permissions still allow all
actions and do not mandate SHA pins for future workflows; the pins below are
enforced in this workflow only. GitHub's temporary read-only token is used by
the checkout/tool-setup actions, not a personal credential.

## Pinned Inputs

| Input | Pin and evidence |
|---|---|
| actions/checkout | v7.0.1, `3d3c42e5aac5ba805825da76410c181273ba90b1`; [release](https://github.com/actions/checkout/releases/tag/v7.0.1), [action inputs](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml) |
| actions/setup-python | v7.1.0, `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`; [release](https://github.com/actions/setup-python/releases/tag/v7.1.0), [action inputs](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/action.yml), checked 2026-11-19 |
| Python | 3.15.2; hosted provisioning and runtime checks passed in run 44923796013; no pip dependencies or package cache |
| Xcode | 27.2 build 27B52 at `/Applications/Xcode_27.2.app`; hosted exact-version preflight passed in run 44923796013 |
| Swift | Apple Swift 6.4.2 confirmed by the hosted preflight in run 44923796013 |
| Reader runner | `macos-26`, arm64; hosted runtime assertion and offline reader suites passed in run 44923796013 |
| Build runner | `xcode-27` arm64; [generally available since 2026-10-15](https://github.blog/changelog/2026-10-15-xcode-27-runner-image-generally-available/), not an immutable image pin |

The earlier [official xcode-27 image inventory reviewed on 2026-11-05](https://github.com/actions/runner-images/blob/9329c776c4a38d3dcb31fc78b8180005041c07fb/images/macos/xcode-27-arm64-Readme.md)
lists `/Applications/Xcode_27.2.app`, but maps it to Xcode 27.2 build 27B48
(Release Candidate), not Apple's stable 27B52. The build job selects that
alias explicitly. Its exact preflight requires 27B52 and therefore rejects
that earlier image before its test suite. The compatible inventory observed
on 2026-11-19 superseded that mismatch at the source-review level; the November
21 attempt also passed the hosted exact-version preflight. The reader job uses
`macos-26` and does not require Xcode. Its hosted suites passed; the separate
build-job failure is recorded above. Inventories and release manifests alone
are configuration/source evidence, and runner images remain mutable.

The runner OS/image and Python acquisition infrastructure are not pinned
byte-for-byte by this YAML. The script prints its detected versions and fails
on toolchain mismatch instead of silently using a different compiler. Record
the actual `Set up job` image and setup-tool logs on the first remote run.
Action commit pins were checked against their official release pages and
input manifests; their entire bundled JavaScript/dependency graphs were not
independently audited. Refresh the pins and stable baseline before release.

## Scope and Follow-Up

The validation entry point pins Python 3.15.2. SwiftPM scratch, cache,
configuration and security paths, Xcode DerivedData, and compiler module caches
are placed in a dedicated directory under `${TMPDIR:-/tmp}`. SwiftPM is invoked
with explicit `--scratch-path`, `--cache-path`, `--config-path` and
`--security-path` values, plus `--manifest-cache none` and
`--disable-dependency-cache`. The script
prints that path and leaves it for its caller to clean after all child processes
have exited. It does not attempt automatic removal while descendants might
still be active. The preflight harness checks the requested paths and exact
Swift command arguments using stubs; this is a contract check, not proof that a
real toolchain confines every write to that directory.

Three additional offline suites cover the continuous protocol parser, synthetic
capture path and diagnostic staging ownership. They use synthetic fixtures and
do not run a public replay runner or qualify real NUT binaries or hardware. The
diagnostic staging tests cover the Python stager's ownership and cleanup
decisions; they do not validate an end-to-end build of the staged candidate.

The E31 integration adds one synthetic contract-test suite to
`scripts/check.sh` for the public full-driver operational replay adapter. It
checks the adapter and manifest contract, including the admitted helper pin and
bounded fake-suite contract. The suite does not invoke the replay runner, fetch
or build NUT, execute a driver, or run the 33-case fake matrix. It is intended to
run after the E31 adapter, manifest and tests are admitted under `backend/nut`.
The E31 runner build and fake replay remain separate, explicit offline steps.
E30 production diagnostics and new E29 formatter scenarios are not included in
this runner. Local E31 validation on 2026-10-28 passed 32 contracts and a separate
33-case fake replay over a reconstructed 190-file source tree. At that E31 checkpoint the full updated check and hosted CI were **NOT RUN**.
The subsequent complete local E33 check passed, including the E31 and E32
contracts; hosted CI remains **NOT RUN**. Neither local result is remote CI
or hardware evidence.

E32 adds a separate isolated contract entrypoint for the public cleanup
diagnostics replay. Its 57 contracts include the unchanged ten diagnostic
validator tests, eight orchestration contracts, and source/header/admission
checks. `cleanup_replay_contracts_e32.py` is a dependency-injected fixture module,
not a separately discovered test entrypoint; the public E32 test loads it after
checking its dependencies. The existing `test_cleanup*.py` discovery remains
unchanged. This CI step performs no NUT reconstruction, compilation, fake-driver
execution or USB access. The separate E32 runner reconstructs production
diagnostics and a distinct fake tree, and can explicitly run 33 baseline plus
eight diagnostic cases. See [E32 scope](PUBLIC_CLEANUP_REPLAY_E32.md). Neither
this addition nor a local replay implies a hosted CI result or product release.

The build job does not fetch/build NUT, discover local clients, or launch an
UPS driver. Two optional actual-client interop tests are skipped because a
separately qualified `upsc` bundle is deliberately absent. The historical run
below passed the then-configured synthetic Swift and Python tests, Release
builds and ad-hoc signature checks. The refreshed toolchain has no hosted build
result; the image inventory now matches its Xcode pin, but provisioning and
the exact preflight still need a hosted execution. A
successful reader job is a distinct result and cannot clear this hold.
Full NUT qualification must retain its separate evidence; a green base job
cannot stand in for that check or for real UPS telemetry.

Before publication acceptance, run this workflow from the intended public
repository and record its revision, image, counts and skipped tests. The first
source-preview run is recorded below. Add a
separately reviewed reproducible NUT-client job and public replay runner before
treating hosted CI as full transport qualification. The fake preflight does not
execute SwiftPM, verify filesystem writes, or test process-tree cleanup; these
remain explicit validation gaps. Signing, UI, widget registration, hardware,
privacy and distribution gates remain independent.

## First Hosted Result

The run above completed on 2026-10-08 with **229 Swift tests passed, 2 optional
interop tests skipped, and 11 Python tests passed**. The 14-case preflight harness,
SwiftPM Release build, plist checks, Xcode app/widget Release build and deep/strict
ad-hoc signature verification all passed. No app, probe or driver was launched.

Actual runner: `xcode-27-arm64`, image `20261006.0244.1`, macOS 27.0.1 build
26A434, runner 2.337.0. The executed preflight confirmed Xcode 27.0 build 27A266a,
Apple Swift 6.4 and Python 3.14.8. Job token permissions were Contents/Metadata
read. No release binary was uploaded. A separate local clone of this public
commit passed the same default validation sequence.
