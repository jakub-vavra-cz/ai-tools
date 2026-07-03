from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_tools.clean_twd import clean_twd, is_twd_directory


class CleanTwdTests(unittest.TestCase):
    def test_is_twd_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = Path(tmp)
            self.assertFalse(is_twd_directory(twd))
            (twd / "metadata.yaml").write_text("domains: []\n")
            self.assertTrue(is_twd_directory(twd))

    def test_clean_removes_logs_and_root_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = Path(tmp)
            logs = twd / "logs"
            logs.mkdir()
            (logs / "pytests_pytest-run.log").write_text("old log\n")
            nested = logs / "tests"
            nested.mkdir()
            (nested / "case.log").write_text("nested\n")
            (twd / "runner.log").write_text("runner\n")
            (twd / "pytest-run.rc").write_text("1\n")
            (twd / "pytests_junit.xml").write_text("<testsuite/>\n")
            (twd / "junit.xml").write_text("<testsuite/>\n")
            (twd / "config").mkdir()

            removed = clean_twd(twd)

            self.assertIn("logs/pytests_pytest-run.log", removed)
            self.assertIn("logs/tests", removed)
            self.assertIn("runner.log", removed)
            self.assertIn("pytest-run.rc", removed)
            self.assertIn("pytests_junit.xml", removed)
            self.assertIn("junit.xml", removed)
            self.assertTrue(logs.is_dir())
            self.assertEqual(list(logs.iterdir()), [])
            self.assertFalse((twd / "runner.log").exists())
            self.assertFalse((twd / "pytest-run.rc").exists())
            self.assertFalse((twd / "pytests_junit.xml").exists())

    def test_dry_run_leaves_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = Path(tmp)
            (twd / "logs").mkdir()
            (twd / "logs" / "a.log").write_text("x\n")
            (twd / "runner.log").write_text("x\n")

            removed = clean_twd(twd, dry_run=True)

            self.assertEqual(removed, ["logs/a.log", "runner.log"])
            self.assertTrue((twd / "logs" / "a.log").exists())
            self.assertTrue((twd / "runner.log").exists())

    def test_rejects_non_twd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                clean_twd(Path(tmp))


if __name__ == "__main__":
    unittest.main()
