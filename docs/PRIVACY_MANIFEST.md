# macOS Privacy Declarations

Reviewed on 2026-10-08. The app and widget each include a
`PrivacyInfo.xcprivacy` resource with `NSPrivacyTracking` set to Boolean false
and an empty `NSPrivacyCollectedDataTypes` array. This describes the original
project's local-only data design; it is not a runtime network audit, an Apple
approval, or a statement about arbitrary user-selected executables.

## Platform and Scope

Apple's [privacy manifest overview](https://developer.apple.com/documentation/bundleresources/privacy-manifest-files)
separates data-collection declarations for all platforms from required-reason
API declarations for iOS, iPadOS, tvOS, visionOS and watchOS. macOS is not in
that latter list. This project targets native macOS only. It intentionally
omits `NSPrivacyAccessedAPITypes`; it does not invent approved reasons or assert
that it never uses file metadata or system-uptime APIs. A future platform port
requires a new review, not reuse of this decision unchanged.

Apple defines collection in terms of off-device transmission accessible to the
developer or partners beyond real-time request servicing, and distinguishes
on-device processing. The project has no developer-operated telemetry service
or analytics SDK. History, energy estimates and widget sharing stay local;
exports are user-directed files. See [Apple's privacy definitions](https://developer.apple.com/app-store/app-privacy-details/)
and [the project's local-data policy](../PRIVACY.md). Local persistence is still
real data storage; an empty collection declaration does not mean no data is
read, saved, shared between local processes or retained by macOS.

The selected external NUT client, local server, user export destinations,
system services and future dependencies require their own assessment. These
declarations do not constrain arbitrary code in an external executable. Do not
treat the manifests as proof of no egress, secure erasure or hardware privacy.

## Source Inventory

The review found these uses in first-party source:

| API / source | Purpose |
|---|---|
| `ProcessInfo.systemUptime`, `MonitorCoordinator` and `MonitorAppModel` | Monotonic receipt timing and local alert/widget scheduling |
| `FileManager.attributesOfItem`, `UPSCClientConfiguration` | Check the selected client is a regular file |
| `fstat`, `NUTSnapshotReader` | Validate ownership/type/mode/size and compare metadata, including modification/change times, while hashing |
| `lstat` / `fstat`, `UPSHistoryStore` | Check local history directory/database safety |
| `fstat`, `WidgetSnapshotStore` | Check shared-directory/file safety, bound reads and verify file identity |

No `UserDefaults`/`@AppStorage`, disk-space query or active-keyboard inventory
was found in the scoped app/widget/library sources. UI keyboard shortcuts are
not keyboard inventory. The render probe also uses `lstat` for its private
output directory; it is a separate offline executable, not shipped in the app.
NUT source and replay tools are external qualification artifacts, not embedded
libraries. This inventory is a dated source check, not complete binary analysis.

## Packaging and Checks

Both manifests belong to their respective Xcode target's Copy Bundle Resources
phase. On macOS the expected path is `Contents/Resources/PrivacyInfo.xcprivacy`
inside the app and inside its embedded widget extension. This follows
[Apple's bundle placement guidance](https://developer.apple.com/documentation/bundleresources/adding-a-privacy-manifest-to-your-app-or-third-party-sdk).
The SwiftPM `UPSAppHost` test target excludes the app manifest; the native
application and extension are packaged by Xcode. The local package is not
qualified here as an independently distributed third-party SDK.

`scripts/check_privacy_manifest.py` parses plists with the standard library and
checks this project's exact two-key declaration in both source manifests. With
`--app-bundle`, it also checks both expected bundle locations. It rejects missing,
malformed or changed declarations, rather than accepting plist syntax alone.
The synthetic regression tests mutate inputs and bundle placement. They do not
prove that the declarations are true, validate Apple policy, inspect all SDKs,
or replace source review. Normal validation runs these checks before and after
the Xcode build without launching either executable.

The review observed one reused DerivedData build that updated the standalone
extension but left the embedded copy without its new manifest. The checker
rejected it despite Xcode reporting build success; repeating the build copied
the extension and passed. A fresh-directory build also passed. The cause of
the first omission is not established. Normal validation now allocates a fresh
Xcode output directory and retains the post-build check; it does not manually
repair or re-sign missing resources to obtain a pass.

Review the source policy and dependencies again before any distribution. A
notarized archive, App Store submission and Apple's privacy-report/acceptance
checks have not been performed. No manifest was uploaded to an Apple account.
