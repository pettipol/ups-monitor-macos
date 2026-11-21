#!/usr/bin/env python3
"""Run the six offline reader contract suites by their exact module names."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


MODULES = (
    "test_extract_hidapi_nut",
    "test_replay_continuous_portable",
    "test_replay_hidapi_full_driver",
    "test_replay_hidapi_nut_config",
    "test_source_cancel",
    "test_stage_hidapi_candidate",
)


def main() -> int:
    test_root = Path(__file__).resolve().parent.parent / "backend" / "nut"
    if not test_root.is_dir():
        print(f"reader contracts failed: test directory missing: {test_root}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(test_root))
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    all_ok = True

    for module_name in MODULES:
        test_path = test_root / f"{module_name}.py"
        if not test_path.is_file():
            print(f"FAIL {module_name}: missing test file: {test_path}", file=sys.stderr)
            all_ok = False
            continue

        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName(module_name)
        if loader.errors:
            print(f"FAIL {module_name}: test loading failed", file=sys.stderr)
            for error in loader.errors:
                print(error, file=sys.stderr)
            all_ok = False
            continue

        discovered = suite.countTestCases()
        if discovered == 0:
            print(f"FAIL {module_name}: module contains no tests", file=sys.stderr)
            all_ok = False
            continue

        result = runner.run(suite)
        executed = result.testsRun - len(result.skipped)
        successful = result.wasSuccessful() and executed > 0
        print(
            f"GROUP {module_name}: {'PASS' if successful else 'FAIL'}; "
            f"discovered={discovered}; run={result.testsRun}; executed={executed}; "
            f"skipped={len(result.skipped)}; failures={len(result.failures)}; "
            f"errors={len(result.errors)}"
        )
        if not successful:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
