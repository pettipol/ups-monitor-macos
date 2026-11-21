# Production cleanup diagnostic source delta

This source delta preserves a bounded cleanup diagnostic without changing the
operational measurement schema. The NUT-derived patch is GPL-2.0-or-later;
it is not relicensed by the application's MIT license. The original NUT source
notices and the repository's `COPYING.NUT` and `LICENSE-GPL2` remain applicable.

The base is NUT revision
`73c4502191d025e35122463986a80c676e734b04`, not an assertion that this is the
latest upstream revision. Reconstruction first uses the frozen continuous
baseline, including its seven copied backend modules and twelve patches, then
the five production patches in this order:

1. `nut-hidapi-continuous-pacing-v2-73c4502.patch`
2. `nut-operational-formatter-v2.patch`
3. `nut-operational-health-v2.patch`
4. `nut-operational-cleanup-v2.patch`
5. `nut-operational-driver-v2.patch`

The two `apcmicrolink-operational-freshness` source/header files must also be
present before comparing the complete tree to `production_source_pre_e28.json`.
Only then apply `nut-operational-cleanup-diagnostics-v1.patch` and compare the
complete result to `production_source_post_e28.json`. Both manifests contain
190 relative source paths and SHA-256 digests. Exactly three files change:
`drivers/apcmicrolink.c`, `drivers/apcmicrolink-hidapi-shared.c`, and
`drivers/apcmicrolink-hidapi-session.h`.

The canonical backend C files are inputs to the earlier patch stages. Replacing
them with these final postimages would break that chain. Operational replay
hooks and the simulated host belong to a subsequent test-only stage, not this
production delta. Historical v1 test seams remain in the selected source tree;
a production build must exclude their definitions and translation units.

The E31 operational replay checks the preceding E27 tree. It does not apply
this diagnostic delta and does not cover the later E29 diagnostic scenarios.
A separately admitted reconstruction, test-hook delta and fake matrix are
required to connect those paths. Neither these source manifests nor a
successful fake replay establish real USB behavior, clean hardware Stop,
widget rendering, or daily monitoring reliability.
