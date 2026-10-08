# SPDX-License-Identifier: MIT
"""Source-fence regressions; no compiler, driver, network or hardware use."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import replay_hid_fallback as replay


class SourceFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources: dict[Path, Path] = {}
        for relative_path in replay.SOURCE_RELATIVE_PATHS:
            source = self.root / relative_path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f"/* synthetic source: {relative_path} */\n")
            self.sources[relative_path] = source
        self.expected_hashes = {
            revision: dict(paths)
            for revision, paths in replay.SOURCE_SHA256.items()
        }
        self.expected_hashes[replay.BASE_REVISION] = {
            relative_path: hashlib.sha256(source.read_bytes()).hexdigest()
            for relative_path, source in self.sources.items()
        }

    def test_unknown_revision_is_refused_before_git(self) -> None:
        with patch.object(replay, "git_output") as git:
            with self.assertRaises(replay.ReplayError):
                replay.verify_source(self.root, "0" * 40)
            git.assert_not_called()

    def test_wrong_head_is_refused(self) -> None:
        with patch.object(replay, "git_output", return_value="0" * 40):
            with self.assertRaises(replay.ReplayError):
                replay.verify_source(self.root, replay.BASE_REVISION)

    def test_dirty_checkout_is_refused(self) -> None:
        with patch.object(
            replay, "git_output", side_effect=[replay.BASE_REVISION, " M drivers/apcmicrolink.c"]
        ):
            with self.assertRaises(replay.ReplayError):
                replay.verify_source(self.root, replay.BASE_REVISION)

    def test_clean_checkout_returns_both_authorized_source_buffers(self) -> None:
        with (
            patch.object(replay, "SOURCE_SHA256", self.expected_hashes),
            patch.object(replay, "git_output", side_effect=[replay.BASE_REVISION, ""]),
        ):
            label, source_bytes = replay.verify_source(self.root, replay.BASE_REVISION)
        self.assertEqual(label, "base")
        self.assertEqual(
            source_bytes,
            {relative_path: source.read_bytes() for relative_path, source in self.sources.items()},
        )

    def test_clean_fake_git_metadata_cannot_admit_changed_source_bytes(self) -> None:
        for target in replay.SOURCE_RELATIVE_PATHS:
            with self.subTest(source=target):
                expected = {
                    revision: dict(paths)
                    for revision, paths in replay.SOURCE_SHA256.items()
                }
                for other in replay.SOURCE_RELATIVE_PATHS:
                    if other != target:
                        expected[replay.BASE_REVISION][other] = self.expected_hashes[
                            replay.BASE_REVISION
                        ][other]
                with (
                    patch.object(replay, "SOURCE_SHA256", expected),
                    patch.object(replay, "git_output", side_effect=[replay.BASE_REVISION, ""]),
                ):
                    with self.assertRaises(replay.ReplayError):
                        replay.verify_source(self.root, replay.BASE_REVISION)

    def test_symlink_source_is_refused_for_each_fenced_file(self) -> None:
        for target in replay.SOURCE_RELATIVE_PATHS:
            with self.subTest(source=target):
                source = self.sources[target]
                source.unlink()
                replacement = self.root / f"synthetic-{target.name}"
                replacement.write_text("/* synthetic */\n")
                source.symlink_to(replacement)
                with (
                    patch.object(replay, "SOURCE_SHA256", self.expected_hashes),
                    patch.object(replay, "git_output", side_effect=[replay.BASE_REVISION, ""]),
                ):
                    with self.assertRaises(replay.ReplayError) as caught:
                        replay.verify_source(self.root, replay.BASE_REVISION)
                self.assertIn(target.as_posix(), str(caught.exception))
                source.unlink()
                source.write_text(f"/* synthetic source: {target} */\n")

    def test_missing_source_is_refused_for_each_fenced_file(self) -> None:
        for target in replay.SOURCE_RELATIVE_PATHS:
            with self.subTest(source=target):
                source = self.sources[target]
                source.unlink()
                with (
                    patch.object(replay, "SOURCE_SHA256", self.expected_hashes),
                    patch.object(replay, "git_output", side_effect=[replay.BASE_REVISION, ""]),
                ):
                    with self.assertRaises(replay.ReplayError) as caught:
                        replay.verify_source(self.root, replay.BASE_REVISION)
                self.assertIn(target.as_posix(), str(caught.exception))
                source.write_text(f"/* synthetic source: {target} */\n")


if __name__ == "__main__":
    unittest.main()
