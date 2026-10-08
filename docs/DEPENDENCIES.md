# Dependency Baseline

Checked on 2026-10-08. Stable tools are preferred; exact revisions are frozen for
each qualification run. This list does not claim hardware compatibility.

| Component | Version | Role and source |
|---|---|---|
| Xcode | 27.0 (27A266a) | Build toolchain; [Apple releases](https://developer.apple.com/news/releases/) |
| Swift | 6.4 | Application language; [release announcement](https://www.swift.org/blog/swift-6.4-released/) |
| macOS SDK | 27.0 | Compilation SDK; deployment target is a separate choice |
| SQLite (Apple SDK/system) | 3.54.0 observed locally | `import SQLite3; sqlite3_libversion()` through Xcode Swift; no separately bundled engine; [SQLite documentation](https://www.sqlite.org/docs.html) |
| Python (offline tests only) | 3.14.8 | Installed runtime matches the latest macOS release shown on [Python downloads](https://www.python.org/downloads/), checked through BrowserOS; stdlib only, not an app runtime dependency |
| NUT stable | 2.8.5 | Does not contain apcmicrolink; [release](https://github.com/networkupstools/nut/releases/tag/v2.8.5) |
| NUT experimental | 1a8369f8688443a500527059167d2f66ca27535f | Candidate source build, not a release; [commit](https://github.com/networkupstools/nut/commit/1a8369f8688443a500527059167d2f66ca27535f) |
| libusb | 1.0.30 | Optional NUT USB dependency; [release](https://github.com/libusb/libusb/releases/tag/v1.0.30) |

NUT is an independent upstream project with its own licensing requirements.
The two patches in `backend/nut/` retain GPL-2.0-or-later licensing and apply
to the exact experimental revision above; see that directory's README.
No NUT source is relicensed under the application's MIT license.
Other package dependencies must be reviewed and recorded before adoption.

Hosted automation uses `actions/checkout` v7.0.1 and `actions/setup-python`
v7.0.0 pinned to reviewed release commits; exact SHAs, source links and the
preview hosted-image limitation are recorded in [CI.md](CI.md). These are
CI-only inputs, not application runtime dependencies or included app code.
