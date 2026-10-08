# SPDX-License-Identifier: MIT
"""Source-fence regressions; no compiler, driver, network or hardware use."""

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
        self.source = self.root / replay.SOURCE_RELATIVE_PATH
        self.source.parent.mkdir()
        self.source.write_text("/* deliberately not upstream source */\n")

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
            replay, "git_output", side_effect=[replay.BASE_REVISION, " M source.c"]
        ):
            with self.assertRaises(replay.ReplayError):
                replay.verify_source(self.root, replay.BASE_REVISION)

    def test_clean_git_metadata_cannot_admit_different_source_bytes(self) -> None:
        # Git status can be clean for an assume-unchanged path: hash the bytes too.
        with patch.object(
            replay, "git_output", side_effect=[replay.BASE_REVISION, ""]
        ):
            with self.assertRaises(replay.ReplayError):
                replay.verify_source(self.root, replay.BASE_REVISION)

    def test_symlink_source_is_refused(self) -> None:
        self.source.unlink()
        target = self.root / "synthetic.c"
        target.write_text("/* synthetic */\n")
        self.source.symlink_to(target)
        with patch.object(
            replay, "git_output", side_effect=[replay.BASE_REVISION, ""]
        ):
            with self.assertRaises(replay.ReplayError):
                replay.verify_source(self.root, replay.BASE_REVISION)


if __name__ == "__main__":
    unittest.main()
