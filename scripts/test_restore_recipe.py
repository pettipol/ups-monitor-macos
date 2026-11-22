#!/usr/bin/env python3
"""Data-only tests for the native recipe restore contract."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile
from tempfile import TemporaryDirectory
import unittest


TOOLS = runpy.run_path(str(Path(__file__).with_name("restore_recipe.py")))
ROOT = TOOLS["ROOT"]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class RestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory(prefix="e104-test-", dir="/private/tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "out"

    def parcel(self, defect: str = "") -> tuple[Path, dict]:
        originals, delivered, rows = {}, {}, {}
        for number in range(60):
            name = f"directory/file{number:02d}.c"
            contents = f"/* original {number} */\n".encode()
            insertion = {"offset_bytes": len(contents), "text_utf8": "/* delivery notice */\n"} if number < 30 else None
            annotated = contents + (insertion["text_utf8"].encode() if insertion else b"")
            mode = 0o755 if number == 31 else 0o644
            originals[name] = (contents, mode)
            delivered[name] = (annotated, mode)
            rows[name] = {"original_sha256": sha(contents), "original_size": len(contents),
                          "delivered_sha256": sha(annotated), "delivered_size": len(annotated),
                          "mode": mode, "insertion": insertion}
        manifest = {"schema": 1, "files": rows,
                    "restored_project_tar_sha256": sha(TOOLS["project_bytes"](originals))}
        path = self.root / (defect + "bundle.tar")
        with tarfile.open(path, "x:") as archive:
            def add(name: str, raw: bytes = b"", mode: int = 0o644,
                    kind: bytes = tarfile.REGTYPE, link: str = "") -> None:
                member = tarfile.TarInfo(ROOT + ("/" + name if name else ""))
                member.mode, member.type, member.linkname, member.size = mode, kind, link, len(raw)
                archive.addfile(member, io.BytesIO(raw) if raw else None)

            add("", kind=tarfile.DIRTYPE)
            add("RECIPE_MANIFEST.json", json.dumps(manifest).encode())
            for name, (contents, mode) in delivered.items():
                if name.endswith("file00.c") and defect == "mutation":
                    contents = b"!" + contents[1:]
                add("recipe/" + name, contents, mode)
            links = TOOLS["LOCALE_LINKS"]
            for name, link in links.items():
                target = (Path(name).parent / link).as_posix()
                directory = not link.endswith(".po")
                add(target, kind=tarfile.DIRTYPE if directory else tarfile.REGTYPE)
                add(name, kind=tarfile.SYMTYPE, link=link)
            if defect == "traversal":
                add("recipe/../outside", b"x")
            if defect == "duplicate":
                add("recipe/directory/file00.c", b"x")
            if defect == "symlink":
                add("recipe/extra", kind=tarfile.SYMTYPE, link="/etc/passwd")
        return path, originals

    def test_round_trip_and_ustar_metadata(self) -> None:
        source, originals = self.parcel()
        result = TOOLS["restore"](source, sha(source.read_bytes()), self.output)
        expected = {"ups-monitor-source/" + name: item for name, item in originals.items()}
        with tarfile.open(self.output / "project.tar", "r:") as project:
            members = project.getmembers()
            self.assertEqual([row.name for row in members], sorted(expected))
            for row in members:
                data, mode = expected[row.name]
                self.assertEqual(project.extractfile(row).read(), data)
                self.assertEqual(row.mode, mode)
                self.assertFalse(any((row.uid, row.gid, row.mtime, row.uname, row.gname)))
        self.assertEqual(result["project_tar_sha256"], sha((self.output / "project.tar").read_bytes()))
        for name, (raw, mode) in originals.items():
            path = self.output / "recipe" / name
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mode & 0o777, mode)

    def test_mutation_traversal_duplicate_and_symlink_refused(self) -> None:
        for defect, reason in (
            ("mutation", "delivered recipe"), ("traversal", "unsafe archive path"),
            ("duplicate", "duplicate member"), ("symlink", "unsupported tar"),
        ):
            with self.subTest(defect=defect):
                source, _ = self.parcel(defect)
                with self.assertRaisesRegex(ValueError, reason):
                    TOOLS["restore"](source, sha(source.read_bytes()), self.output)
                self.assertFalse(self.output.exists())

    def test_existing_workspace_preserved(self) -> None:
        source, _ = self.parcel()
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "new output directory"):
            TOOLS["restore"](source, sha(source.read_bytes()), self.output)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
