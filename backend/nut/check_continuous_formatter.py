"""Parse formatter-only lines emitted by the C inclusion harness.

The caller supplies the existing hash-pinned strict parser module and a file
captured by the approved bounded runner. This script never launches a process.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("captured_stdout", type=Path)
    parser.add_argument("strict_parser", type=Path)
    parser.add_argument("--strict-parser-sha256", required=True)
    args = parser.parse_args()

    actual_parser_sha256 = hashlib.sha256(args.strict_parser.read_bytes()).hexdigest()
    assert actual_parser_sha256 == args.strict_parser_sha256, "strict parser SHA-256 mismatch"
    spec = importlib.util.spec_from_file_location("pinned_diagnostics", args.strict_parser)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    captured = args.captured_stdout.read_bytes()
    lines = captured.splitlines(keepends=True)
    summary_lines = [line for line in lines if line.startswith(module.PREFIX.encode("ascii"))]
    assert len(summary_lines) == 2, "expected null-metadata and maximum-width formatter cases"
    summaries = []
    for line in summary_lines:
        assert len(line) <= 4096
        summary, remainder = module.parse_summary(line, True)
        assert summary is not None and remainder == b""
        summaries.append(summary)

    nulls, maximum = summaries
    for key in (
        "cache.first_ms", "cache.last_ms", "blob.rows_copied_min",
        "blob.rows_copied_max", "publication.observed_min_ms_last",
        "publication.observed_max_ms_last", "terminal.elapsed_ms",
        "last_success.age_s_at_idle_check",
    ):
        assert nulls[key] is None, f"undefined metadata was not null: {key}"
    assert maximum["saturated"] is True and maximum["time_saturated"] is True
    assert maximum["cache.last_ms"] == 0xFFFFFFFF
    assert maximum["terminal.elapsed_ms"] == 0xFFFFFFFF
    assert maximum["terminal.first_site"] == "update_post_session"
    assert maximum["last_success.source"] == "handshake"
    assert maximum["terminal.consecutive_timeouts"] == 0xFFFFFFFF
    assert maximum["cleanup.stop_state"] == "not_required"
    assert maximum["last_success.age_s_at_idle_check"] < 0
    assert maximum["last_success.age_s_at_idle_check"] not in (float("inf"), float("-inf"))
    assert b"SYNTHETIC_PRIVATE_MARKER" not in captured
    assert b"/Users/" not in captured and b"/private/" not in captured
    assert b"formatter_only=true" in captured
    print("formatter_only=true strict_parser=PASS summary_lines=2")


if __name__ == "__main__":
    main()
