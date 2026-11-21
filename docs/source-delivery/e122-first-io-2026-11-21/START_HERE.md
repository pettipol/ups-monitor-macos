# First-IO macOS preview: recipient source pairing

This technical addendum pairs the E122 private app-package identity with the current public app source and the separate E124 reader/runtime source archive. It is a source/build handoff, not permission to redistribute or a distribution-clearance decision. The app payload, driver, and hardware were not executed for this addendum.

## Source set

Use the public source checkout at commit [`01e8e67e29db2fbf1ba7bcfb11f9aa32251323c3`](https://github.com/pettipol/ups-monitor-macos/tree/01e8e67e29db2fbf1ba7bcfb11f9aa32251323c3), tree `d135251255d67943aae365231ffbd88633db6f8c`. The immutable E106 source archive remains useful historical evidence for the exact frontend layout, tests, and notice inputs: 73/73 frontend files, 80/80 tests, and 26/26 notice inputs match the current source. E106 is not the current build recipe: its two runtime preparation scripts differ from the current public source, and it predates the first-IO validator/profile. Use current public files for those paths and the current public real-preview guide.

The E124 companion is `UPS-Monitor-E121-First-IO-Source.tar`, SHA-256 `b76213d3cc42bc9c7726500108d03e2f11f399f0cdd53c265bbade0a984e366d`. It contains the recipe and materials to restore the reader/runtime stage: 77 recipe files, 190 native reader files, 8 HIDAPI vendor files, and 9 runtime modules. Preserve its upstream notices and first-IO notice. It does not contain the Swift/Xcode frontend.

Obtain E124 through a trusted delivery channel and verify its whole-archive SHA-256 against this pairing record before reading or restoring members. Then follow the archive-local `UPS-Monitor-E121-First-IO-Source/README.md`; its `UPS-Monitor-E121-First-IO-Source/restore_first_io_source.py` is the data-only restorer, and `UPS-Monitor-E121-First-IO-Source/notices/` contains the eight native notice inputs. Use the restored stage root as `FIRST_IO_SOURCE_STAGE=<restored E124 output>/stage`, and set `CHECKOUT_ROOT` to the pinned public source checkout above. Then build from those source inputs and record the new build's receipt digest: `FRESH_NATIVE_ROOT=<recipient fresh-build OUTPUT_DIR>` and `NATIVE_RECEIPT_SHA256=<SHA-256 of its BUILD_RECEIPT.json>`. The E124 source archive is not a compiled native output and does not supply that fresh build receipt. Its restored stage already includes the qualification and first-IO source changes; do not apply the historical qualification patch a second time.

## Recipient build sequence

Follow the seven numbered steps in the versioned [real preview packaging guide](https://github.com/pettipol/ups-monitor-macos/blob/01e8e67e29db2fbf1ba7bcfb11f9aa32251323c3/docs/REAL_PREVIEW_PACKAGE.md):

1. Set `NATIVE_PROFILE=first-io-v1`, validate the installed Apple toolchain, and build the selected first-IO native producer and frozen helper from the current source inputs. The explicit profile prevents the guide's historical 0.15 default from being selected.
2. Verify the recorded native product and copy/sign only the package copy.
3. Stage the first-IO runtime, run the source/build/stage pairing checks, and retain the stage receipt and manifest pins.
4. Prepare a private app-source copy with the recipient’s chosen real bundle identifier ending in `.real` and generated runtime pin.
5. Build the real app and widget from that copy with the real configuration.
6. Assemble the runtime and retain the native, runtime, and first-IO profile notices. For this fresh build, use `upstream-notices/nut` and `upstream-notices/hidapi` from its `FRESH_NATIVE_ROOT`, plus `NOTICE.md` from the current public first-IO profile. E124's flat notice inputs support source review; they are not the fresh-build notice source paths expected by the guide.
7. Verify the eight native notice files, first-IO notice, runtime closure and nine external module hashes; sign the outer app last and verify the archive against the assembled tree.

The steps describe a recipient procedure; this addendum records no new build, signature, installation, app launch, widget observation, or hardware result. The recipient supplies fresh build outputs, generated release pins, and local signing parameters. Keep local signing identities and resolved entitlement values private; source entitlement templates remain part of the source.

## Pairing and runtime notes

See [PAIRING.json](PAIRING.json) for the immutable E122/E124 identities, stage maps, current generated-file hash pairs, E106 historical source comparison, and recipient-generated values. See [RUNTIME_CHANGES.md](RUNTIME_CHANGES.md) for the E122-specific helper, library, standard-library ZIP and notice pins. Verify these files with [SHA256SUMS](SHA256SUMS).

Distribution review remains open. In particular, the runtime manifest records `redistribution_review: NOT_PERFORMED`; component applicability and corresponding-source scope must be reviewed for the selected payload. Do not treat this addendum as legal advice, a license compatibility finding, release authorization, or a claim that a package reproduced the E122 binary.
