# NUT Client Completion Qualification

Date: 2026-10-08. Scope: actual `upsc` binary and synthetic ephemeral loopback
server. No UPS driver, existing NUT server, daemon or USB device was accessed.

## Reproduced Upstream Issue

At upstream revision `1a8369f8688443a500527059167d2f66ca27535f`,
[`list_vars()`](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/clients/upsc.c)
discards the final error result from `upscli_list_next()`. It then closes the
JSON object and the client exits successfully. The library also accepts an
`END LIST` marker without validating the rest of that marker against the query.

The unmodified, locally compiled binary accepted all five invalid cases below
as successful JSON. This is a reproduced behavior of this revision, not an
unverified claim about all stable NUT releases.

| Synthetic server response | Unmodified client | Patched client |
|---|---|---|
| Complete list with matching end marker | Exit 0, accepted | Exit 0, accepted |
| EOF after two variables, no end marker | Exit 0, accepted incorrectly | Exit 1, rejected |
| `ERR DATA-STALE` after two variables | Exit 0, accepted incorrectly | Exit 1, rejected |
| End marker naming a different UPS | Exit 0, accepted incorrectly | Exit 1, rejected |
| Incomplete `END LIST` marker | Exit 0, accepted incorrectly | Exit 1, rejected |
| End marker with an extra argument | Exit 0, accepted incorrectly | Exit 1, rejected |

All six scenarios observed only `LIST VAR fixture` from the client. No
authentication or modifying protocol command was observed in these tests.
This does not prove credential opt-out under every build/configuration.

## Narrow Patch

`backend/nut/nut-upsc-completion.patch` changes only `clients/upsc.c` and
`clients/upsclient.c`: a failed variable-list read terminates with failure,
and the end marker must match the requested list exactly. It preserves
upstream GPL-2.0-or-later licensing, as specified in both source headers;
the application's MIT license does not relicense this patch.

The patch passed `git apply --check` against the pristine pinned source, and
the patched `upsc` plus client library compiled. It is separate from the
experimental USB-driver guards and can be reviewed independently. It has not
been submitted or accepted upstream. Other listing modes and the full NUT
client-library suite are not qualified by these six tests.

The [upstream list container specification](https://github.com/networkupstools/nut/blob/1a8369f8688443a500527059167d2f66ca27535f/docs/net-protocol.txt#L284-L287)
requires the original query on both BEGIN and END markers; the marker check
enforces that existing protocol contract.

## Reproduction

Run from the application checkout with an explicitly built binary/library:

```sh
python3 backend/nut/check_upsc_completion.py \
  --binary /path/to/nut-build/clients/.libs/upsc \
  --libraries /path/to/nut-build/clients/.libs
```

The test owns a fresh loopback port, temporary HOME and short-lived client
process per scenario. It never discovers or connects to an existing service.
It is a bounded synthetic conformance check, not the app's process runner or
a production NUT server. The diagnostic build has TLS disabled; passing this
check does not qualify remote transport or production distribution.

Verified SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| Client patch | `8a92a55bc571f333e1d021ac8144dbe01d3cbac51f8ffd5a91e828748323346d` |
| Patched diagnostic upsc | `0a579d4a15f7a0a4da027cf32c77cf1e48dd7888e9898dd475b36b66a11b5e62` |
| Patched diagnostic libupsclient.7.dylib | `ee0657d4096405102022f61ec246d59de543b191d28eec299047da6f4d9a9e76` |

Binary hashes identify local evidence, not portable or signed release artifacts.

## Swift Adapter Interoperability

The opt-in `UPSCInteropTests.testPatchedUPSCCompletesOnlyWholeSyntheticLists`
also passed all six scenarios through the actual `NUTClient` adapter. It
accepted the complete snapshot and returned typed process failures for each
incomplete or mismatched list. The fixture recorded only the expected read
request. No inherited HOME or DYLD environment was added to production code.

For this test only, a copy of `upsc` was relocated to use an adjacent copy of
`libupsclient.7.dylib` through `@executable_path`, then ad-hoc re-signed and
checked with `codesign --verify --strict`. No system installation, Developer ID
certificate, notarization or change to macOS security policy was involved.
The relocated executable SHA-256 is
`9498d891e68f0f21d349629d10b256385fe98e5defa43d825f6b9fb50e38dad6`.

Run the opt-in suite using explicit paths to this kind of qualified fixture
bundle and a Python interpreter:

```sh
UPS_TEST_UPSC=/path/to/client-fixture-bundle/upsc \
UPS_TEST_UPSC_SHA256="$(shasum -a 256 /path/to/client-fixture-bundle/upsc | cut -d ' ' -f 1)" \
UPS_TEST_PYTHON=/path/to/python3 \
swift test --filter UPSCInteropTests
```

The digest identifies the exact already-qualified executable; computing a hash
does not establish trust in an arbitrary binary. The runtime-reader interop
test requires all three variables; the direct-client test uses the two paths.
Without the required explicit variables the respective integration test is skipped;
ordinary unit tests must not discover or connect to an installed NUT service.
An initial test failure was caused by the fixture waiting for 32 startup bytes
when only a port line was sent. The corrected bounded newline handshake plus
fixture watchdog removed that harness error; no production security relaxation
was needed. TLS, real-server authentication, production packaging and actual
UPS compatibility remain outside this synthetic qualification.
