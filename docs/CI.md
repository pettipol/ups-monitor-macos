# Continuous Integration

Configuration reviewed on 2026-10-08. **First hosted execution PASS** on source
commit `270ac3e8edb2ffd0548ff0927363a81dffdf5f81`:
[GitHub run 37788712924](https://github.com/pettipol/ups-monitor-macos/actions/runs/37788712924).
This is synthetic source/build evidence, not product or hardware qualification.

The workflow runs the same [validation entry point](VALIDATION.md) on pushes
to `main`, pull requests and manual dispatch. It has only `contents: read`,
does not persist checkout credentials, and references no repository secrets,
certificates, App Group, deployment environment or self-hosted runner. It uses
neither `pull_request_target` nor `workflow_run` to execute untrusted PR code.
No artifacts, credentials or release binaries are uploaded by this workflow.

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
| actions/setup-python | v7.0.0, `5fda3b95a4ea91299a34e894583c3862153e4b97`; [release](https://github.com/actions/setup-python/releases/tag/v7.0.0), [action inputs](https://github.com/actions/setup-python/blob/5fda3b95a4ea91299a34e894583c3862153e4b97/action.yml) |
| Python | 3.14.8, exact stable test-runtime baseline; no pip dependencies or package cache |
| Xcode | 27.0 build 27A266a, explicitly selected with `DEVELOPER_DIR`; Swift 6.4 is checked before tests |
| Hosted runner | `xcode-27` arm64; hosted image is public preview, not an immutable image pin |

The [official image inventory](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)
lists Xcode 27.0 build 27A266a and the selected path alias. Its observed image
was `20260928.0222.1`, macOS 27.0; it also contains prerelease Xcode versions,
which this workflow does not select. Apple's [release list](https://developer.apple.com/news/releases/)
still identifies Xcode 27.1 as RC and 27.2 as beta on the check date. The
hosted image's preview lifecycle is an explicit infrastructure limitation,
not permission to switch the app to a prerelease compiler.

The runner OS/image and Python acquisition infrastructure are not pinned
byte-for-byte by this YAML. The script prints its detected versions and fails
on toolchain mismatch instead of silently using a different compiler. Record
the actual `Set up job` image and setup-tool logs on the first remote run.
Action commit pins were checked against their official release pages and
input manifests; their entire bundled JavaScript/dependency graphs were not
independently audited. Refresh the pins and stable baseline before release.

## Scope and Follow-Up

The default job does not fetch/build NUT, discover local clients, or launch an
UPS driver. Two optional actual-client interop tests are skipped because a
separately qualified `upsc` bundle is deliberately absent. All other synthetic
Swift and Python tests, Release builds and ad-hoc signature checks run.
Full NUT qualification must retain its separate evidence; a green base job
cannot stand in for that check or for real UPS telemetry.

Before publication acceptance, run this workflow from the intended public
repository and record its revision, image, counts and skipped tests. The first
source-preview run is recorded below. Add a
separately reviewed reproducible NUT-client job before treating hosted CI as
full transport qualification. Signing, UI, widget registration, hardware,
privacy and distribution gates remain independent.

## First Hosted Result

The run above completed on 2026-10-08 with **229 Swift tests passed, 2 optional
interop tests skipped, and 11 Python tests passed**. The 14-case preflight harness,
SwiftPM Release build, plist checks, Xcode app/widget Release build and deep/strict
ad-hoc signature verification all passed. No app, probe or driver was launched.

Actual runner: `xcode-27-arm64`, image `20261006.0244.1`, macOS 27.0.1 build
26A434, runner 2.337.0. This is newer than the image inventory observed during
preparation above. The executed preflight confirmed Xcode 27.0 build 27A266a,
Apple Swift 6.4 and Python 3.14.8. Job token permissions were Contents/Metadata
read. No release binary was uploaded. A separate local clone of this public
commit passed the same default validation sequence.
