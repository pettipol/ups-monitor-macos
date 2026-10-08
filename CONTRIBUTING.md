# Contributing

UPS Monitor Mac is an early-development, read-only monitor. Contributions
should preserve the separation between Apple telemetry, NUT, the shared model,
history, widgets and app presentation.

## Before Sending a Change

- Read [`README.md`](README.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
  and the relevant component contract.
- Keep examples and tests synthetic. Do not use credentials, real serials,
  persistent device identifiers, network addresses or unredacted system dumps.
- Do not add UPS control, driver launch, USB/HID access, shutdown, self-test,
  calibration or configuration behavior. These require a separate reviewed
  design and explicit user authorization; a read-only UI label is not proof of
  a read-only protocol path.
- Preserve upstream license notices. Do not move NUT-derived code or patch
  content into files covered only by the repository's MIT notice. Record source,
  revision and license before proposing reused code; see
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
- Keep missing, stale, invalid, derived and estimated data distinct. Do not
  conflate W, VA, Wh, battery percentage or nominal ratings.

## Validation

Use the repository's synthetic Swift tests for code changes. Do not run tests
that discover installed NUT services or hardware. The opt-in NUT interop suite
requires explicit paths to a separately built fixture bundle and Python
interpreter; without those explicit fixture inputs it is skipped. It uses a
synthetic loopback server, not a physical UPS.

The pinned, sequential `bash scripts/check.sh` entry point also validates
Python helpers, Release builds and ad-hoc signatures; see
[validation scope](docs/VALIDATION.md). Hosted CI status and limitations are
recorded separately in [CI.md](docs/CI.md).

Build or run the GUI only when the task calls for it. The documented
`--synthetic-preview` mode uses fixed sample data and should not be presented as
live telemetry or visual acceptance. Do not ask users to disable Gatekeeper,
reduce system security or launch an experimental USB driver to reproduce an
issue.

## License and Review

The root [`LICENSE`](LICENSE) states MIT terms for original project material;
identified third-party patches and helpers retain their recorded terms.
This repository currently specifies no CLA or DCO workflow. Ask maintainers to
review provenance and licensing when a change includes copied, generated from,
or adapted third-party material. Do not assume a dependency's license from its
name or from this contribution guide.
