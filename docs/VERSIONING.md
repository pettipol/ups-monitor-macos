# Versioning

`VERSION` is the canonical SemVer identifier for the source tree. The current
`0.1.0-preview.1` is explicitly a prerelease source preview, not a release or a
claim that hardware, interactive UI or widget installation is qualified. No
Git tag or release is implied by this file.

Apple requires `CFBundleShortVersionString` to contain three numeric
components ([bundle version documentation](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleshortversionstring)),
so the app and widget keep `0.1.0` there. Their numeric build version remains
`1`. Both bundles also carry `UPSMonitorSemVer`, which preserves the complete
source version for tooling and future presentation. Run
`bash scripts/check-version.sh` to verify the SemVer, changelog heading, and
both bundles' version metadata agree. The main validation sequence runs this
check after its preflight and plist checks.

For a source-preview iteration, update `VERSION`, the matching changelog
heading and both `UPSMonitorSemVer` values together. Keep Apple bundle fields
numeric. A future distributable build needs its own acceptance decision,
release notes and incremented bundle build; this version file does not authorize
signing, notarization, tagging or publication of a binary.
