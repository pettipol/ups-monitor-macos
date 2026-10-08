# Changelog

## Unreleased

- Connected the in-memory session energy tracker to the app's selected source,
  with separate input and UPS active-watt channels, covered Wh, breaks and
  provenance.
- Added an explicit confirmed reset and a separate schema-version-1 JSON export
  that does not depend on history recording.
- Exposed the coordinator's monotonic successful-receipt time before sink work
  so energy intervals use acquisition receipt timing rather than UI refreshes.
- Updated public compatibility, build, contribution and third-party licensing
  guidance. The local synthetic suite passed; rendered UI and live watt
  qualification remain open.
- Added a pinned hosted-CI configuration and local synthetic validation entry
  point. Hosted execution remains unverified until the repository is published.
