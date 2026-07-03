from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ai_tools.te_test_summary import (
    TeSummaryError,
    format_draft,
    last_summary_block,
    parse_outcomes,
    summarize_twd,
)
from ai_tools.te_test_summary import main as summary_main


PASS_LOG = """\
2026-08-25T08:42:23+0000 PHASE START: test
2026-08-25T08:42:23+0000 TESTS STEP START: pytests
2026-08-25T08:42:23+0000 Running: "/usr/bin/python3 -m pytest ../sudo-tests/pytest/ -k=regex"
2026-08-25T08:42:35+0000 =========================== short test summary info ============================
2026-08-25T08:42:35+0000 PASSED ../sudo-tests/pytest/tests/test_misc_issues.py::test__regex_non_canonical_path (bare_client)
2026-08-25T08:42:35+0000 ================ 1 passed, 116 deselected, 2 warnings in 11.76s ================
2026-08-25T08:42:36+0000 RETURN CODE: 0
2026-08-25T08:42:36+0000 TESTS STEP END: pytests
2026-08-25T08:42:36+0000 PHASE END: test
"""

FAIL_THEN_PASS = """\
2026-08-24T16:40:05+0000 =========================== short test summary info ============================
2026-08-24T16:40:05+0000 FAILED ../sudo-tests/pytest/tests/test_misc_issues.py::test__regex_non_canonical_path (bare_client)
2026-08-24T16:40:05+0000 ================ 1 failed, 116 deselected, 2 warnings in 9.96s =================
2026-08-24T16:40:05+0000 RETURN CODE: 1
2026-08-24T16:40:05+0000 TESTS STEP END: pytests
2026-08-24T16:46:26+0000 =========================== short test summary info ============================
2026-08-24T16:46:26+0000 PASSED ../sudo-tests/pytest/tests/test_misc_issues.py::test__regex_non_canonical_path (bare_client)
2026-08-24T16:46:26+0000 FAILED ../sudo-tests/pytest/tests/test_misc_issues.py::test__other (bare_client)
2026-08-24T16:46:26+0000 =========== 1 failed, 1 passed, 114 deselected, 3 warnings in 48.27s ===========
2026-08-24T16:46:26+0000 RETURN CODE: 1
"""

JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="0" failures="1" skipped="0" tests="2">
    <testcase classname="tests.test_misc_issues" name="test_ok (bare_client)" time="1"/>
    <testcase classname="tests.test_misc_issues" name="test_bad (bare_client)" time="1">
      <failure message="assert 0">fail</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def _twd(tmp: Path) -> Path:
    twd = tmp / "twd"
    twd.mkdir()
    (twd / "metadata.yaml").write_text("domains: []\n")
    return twd


class ParseLogTests(unittest.TestCase):
    def test_strips_timestamps_and_outcomes(self) -> None:
        block, rc = last_summary_block(PASS_LOG)
        self.assertEqual(rc, 0)
        self.assertTrue(block[0].startswith("="))
        self.assertNotIn("2026-08-25", "\n".join(block))
        parsed = parse_outcomes(block)
        self.assertEqual(
            parsed["passed"],
            [
                "../sudo-tests/pytest/tests/test_misc_issues.py::"
                "test__regex_non_canonical_path (bare_client)"
            ],
        )
        self.assertEqual(parsed["totals"], "1 passed, 116 deselected, 2 warnings in 11.76s")

    def test_uses_last_summary(self) -> None:
        block, rc = last_summary_block(FAIL_THEN_PASS)
        self.assertEqual(rc, 1)
        parsed = parse_outcomes(block)
        self.assertEqual(len(parsed["passed"]), 1)
        self.assertEqual(len(parsed["failed"]), 1)

    def test_draft_shape(self) -> None:
        block, _rc = last_summary_block(PASS_LOG)
        draft = format_draft(
            block,
            upgraded=[
                "sudo-1.9.17-5.p2.el10_2.x86_64",
                "sudo-python-plugin-1.9.17-5.p2.el10_2.x86_64",
            ],
        )
        self.assertTrue(draft.startswith("Upgraded:\n  sudo-1.9.17-5.p2.el10_2.x86_64\n"))
        self.assertIn("Complete!\n", draft)
        self.assertIn("PASSED ../sudo-tests/pytest/", draft)
        self.assertIn("1 passed, 116 deselected", draft)


class SummarizeTwdTests(unittest.TestCase):
    def test_from_runner_and_rc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd(Path(tmp))
            (twd / "runner.log").write_text(PASS_LOG)
            (twd / "pytest-run.rc").write_text("0\n")
            result = summarize_twd(
                twd,
                upgraded=["sudo-1.9.17-5.p2.el10_2.x86_64"],
            )
            self.assertEqual(result.rc, 0)
            self.assertEqual(result.outcome, "passed")
            self.assertEqual(result.command, "te --phase test metadata.yaml")
            self.assertIn("pytest ../sudo-tests/pytest/", result.running or "")
            self.assertTrue(result.draft.startswith("Upgraded:"))
            self.assertIn("Complete!", result.draft)
            payload = result.to_dict()
            self.assertEqual(
                payload["passed"][0].split("::")[1].split()[0], "test__regex_non_canonical_path"
            )

    def test_campaign_root_and_failed_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd(Path(tmp))
            (twd / "runner.log").write_text(FAIL_THEN_PASS)
            result = summarize_twd(twd.parent)
            self.assertEqual(result.outcome, "failed")
            self.assertEqual(result.rc, 1)
            self.assertEqual(len(result.failed), 1)

    def test_junit_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd(Path(tmp))
            (twd / "pytests_junit.xml").write_text(JUNIT)
            result = summarize_twd(twd)
            self.assertEqual(result.outcome, "failed")
            self.assertTrue(any("test_bad" in name for name in result.failed))
            self.assertTrue(any("test_ok" in name for name in result.passed))
            self.assertTrue(result.source.endswith("junit.xml"))

    def test_rejects_empty_twd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd(Path(tmp))
            with self.assertRaises(TeSummaryError):
                summarize_twd(twd)


class CliMainTests(unittest.TestCase):
    def test_json_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd(Path(tmp))
            (twd / "runner.log").write_text(PASS_LOG)
            with patch("sys.stdout", new_callable=StringIO):
                self.assertEqual(summary_main(["--twd", str(twd), "--json"]), 0)
                self.assertEqual(
                    summary_main(
                        [
                            "--twd",
                            str(twd),
                            "--upgraded",
                            "sudo-1.9.17-5.p2.el10_2.x86_64",
                        ]
                    ),
                    0,
                )

    def test_bad_twd_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sys.stderr", new_callable=StringIO):
                self.assertEqual(summary_main(["--twd", tmp]), 2)


if __name__ == "__main__":
    unittest.main()
