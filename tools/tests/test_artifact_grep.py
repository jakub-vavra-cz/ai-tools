from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from ai_tools.artifact_grep import (
    artifact_grep,
    compile_patterns,
    read_artifact_text,
)


class ReadArtifactTextTests(unittest.TestCase):
    def test_reads_plain_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner.log"
            path.write_text("Going offline\n", encoding="utf-8")
            self.assertEqual(read_artifact_text(path), "Going offline\n")

    def test_reads_gzip_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner.log"
            path.write_bytes(gzip.compress(b"Failed to resolve server\n"))
            self.assertEqual(
                read_artifact_text(path),
                "Failed to resolve server\n",
            )

    def test_skips_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            path.write_bytes(b"\x00\x01\x02")
            self.assertIsNone(read_artifact_text(path))


class CompilePatternTests(unittest.TestCase):
    def test_fixed_strings_split_on_pipe(self) -> None:
        patterns = compile_patterns("foo|bar", fixed_strings=True, ignore_case=False)
        self.assertEqual(len(patterns), 2)


class ArtifactGrepTests(unittest.TestCase):
    def test_grep_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runner.log").write_text(
                "line one\nFailed to resolve server 'x'\nGoing offline\n",
                encoding="utf-8",
            )
            gz = root / "logs" / "test.log.gz"
            gz.parent.mkdir()
            gz.write_bytes(gzip.compress(b"DNS server returned answer with no data\n"))

            summary = artifact_grep(
                r"Failed to resolve|Going offline|DNS server",
                [root],
            )

            self.assertEqual(len(summary.matches), 3)
            self.assertEqual(summary.files_searched, 2)

    def test_context_and_max_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runner.log").write_text(
                "before\nmatch one\nafter\nmatch two\n",
                encoding="utf-8",
            )
            summary = artifact_grep(
                "match",
                [root],
                after_context=1,
                max_matches=1,
            )
            self.assertEqual(len(summary.matches), 1)
            self.assertEqual(summary.matches[0].after, ["after"])

    def test_ignore_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner.log"
            path.write_text("Backend is offline\n", encoding="utf-8")
            summary = artifact_grep("OFFLINE", [path], ignore_case=True)
            self.assertEqual(len(summary.matches), 1)

    def test_include_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runner.log").write_text("hit\n", encoding="utf-8")
            (root / "skip.xml").write_text("hit\n", encoding="utf-8")
            summary = artifact_grep(
                "hit",
                [root],
                include_globs=("*.log",),
            )
            self.assertEqual(len(summary.matches), 1)
            self.assertTrue(summary.matches[0].path.endswith("runner.log"))


if __name__ == "__main__":
    unittest.main()
