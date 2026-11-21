# Operational publication API

`AtomicOperationalPublisher` writes schema-2 envelopes through the guarded atomic writer shared with v1. The v1 extraction preserves its serializer and envelope behavior. The output file is capped at 16,384 bytes.

`OperationalFramer.accept(bytes)` incrementally parses v2 NDJSON. Each input chunk is at most 65,536 bytes; a pending unterminated record is at most 8,191 bytes, and a complete line including newline is at most 8,192 bytes. Its boolean result is true only when a sample record's callback returns the exact boolean `True`. End records and the empty EOF chunk never report progress. EOF rejects a partial record; repeated EOF returns false.

The caller must validate stream sequence, timing and freshness before publication and progress renewal. Stop coordination, terminal-publication ordering, and lifecycle/ownership handling are not solved by these primitives.

The focused validation set contains 7 publisher/framer tests in `test_operational_publication.py` and `test_operational_framing.py`, plus 14 v1 capture and 8 v1 protocol regressions. All 29 passed on macOS. The project check script includes the new component tests; this is not a full CI or integrated session result.
