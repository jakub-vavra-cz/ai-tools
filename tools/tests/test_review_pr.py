from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.check_python import CheckReport as PythonCheckReport
from ai_tools.check_python import ProjectPythonTools
from ai_tools.clone_review import ReviewCheckout
from ai_tools.review_pr import (
    classify_changed_files,
    format_report,
    is_ansible_yaml_path,
    run_review,
)


class ClassifyFilesTests(unittest.TestCase):
    def test_splits_by_type(self) -> None:
        files = [
            "readme.md",
            "src/foo.py",
            "src/ansible/roles/x/tasks/main.yml",
            ".github/workflows/ci.yml",
        ]
        py, ans, skip = classify_changed_files(files)
        self.assertEqual(py, ["src/foo.py"])
        self.assertEqual(ans, ["src/ansible/roles/x/tasks/main.yml"])
        self.assertEqual(skip, ["readme.md", ".github/workflows/ci.yml"])

    def test_ansible_path_heuristic(self) -> None:
        self.assertTrue(is_ansible_yaml_path("roles/ldap/tasks/main.yml"))
        self.assertFalse(is_ansible_yaml_path(".gitlab-ci.yml"))


class FormatReportTests(unittest.TestCase):
    def test_includes_sections(self) -> None:
        from ai_tools.review_pr import ReviewPrReport

        checkout = ReviewCheckout(
            platform="github",
            host="github.com",
            repo="SSSD/sssd",
            number=1,
            kind="pr",
            clone_path="/tmp/@REVIEWS/sssd-pr1",
            created=True,
            target_branch="master",
            base_ref="origin/master",
            base_sha="abc",
            head_sha="def",
            head_ref="topic",
            changed_files=["a.py"],
            diff_stat="1 file changed",
            title="demo",
        )
        tools = ProjectPythonTools(
            python_root=Path("/tmp"),
            uses_ruff=True,
            uses_flake8=False,
            uses_black=False,
            uses_isort=False,
            primary="ruff",
        )
        report = ReviewPrReport(
            checkout=checkout,
            diff_patch="",
            python=PythonCheckReport(
                python_root="/tmp",
                paths=["a.py"],
                tools=tools,
            ),
        )
        text = format_report(report)
        self.assertIn("=== python ===", text)
        self.assertIn("overall: PASS", text)


class RunReviewTests(unittest.TestCase):
    def test_orchestrates_clone_and_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            clone = root / "demo-pr1"
            clone.mkdir()
            (clone / ".git").mkdir()
            py_file = clone / "mod.py"
            py_file.write_text("x=1\n", encoding="utf-8")
            (clone / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")

            checkout = ReviewCheckout(
                platform="github",
                host="github.com",
                repo="org/demo",
                number=1,
                kind="pr",
                clone_path=str(clone),
                created=True,
                target_branch="master",
                base_ref="origin/master",
                base_sha="abc",
                head_sha="def",
                head_ref="topic",
                changed_files=["mod.py"],
                diff_stat="1 file changed",
            )

            def fake_prepare_review(*args, **kwargs):
                return checkout

            def fake_run(argv, cwd=None, env=None, check=True):
                class Proc:
                    returncode = 0
                    stdout = "diff --git a/mod.py\n"
                    stderr = ""

                return Proc()

            with patch("ai_tools.review_pr.prepare_review", side_effect=fake_prepare_review):
                with patch("ai_tools.review_pr.run_cmd", side_effect=fake_run):
                    with patch("ai_tools.check_python.which", return_value="/usr/bin/ruff"):
                        with patch("subprocess.run") as mock_subprocess:
                            mock_subprocess.return_value.returncode = 0
                            mock_subprocess.return_value.stdout = "All checks passed!\n"
                            mock_subprocess.return_value.stderr = ""
                            report = run_review(
                                "org/demo#1",
                                reviews_root=root,
                                include_diff=True,
                            )

            self.assertIsNotNone(report.python)
            self.assertTrue(report.ok)


if __name__ == "__main__":
    unittest.main()
