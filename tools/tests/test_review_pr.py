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
    partition_existing_files,
    run_review,
)


class ClassifyFilesTests(unittest.TestCase):
    def test_splits_by_type(self) -> None:
        files = [
            "readme.md",
            "src/foo.py",
            "src/ansible/roles/x/tasks/main.yml",
            ".github/workflows/ci.yml",
            "vars/lib.groovy",
            "jenkinsfile/Jenkinsfile",
            "maintainer_docs/a.adoc",
        ]
        targets = classify_changed_files(files)
        self.assertEqual(targets.python, ["src/foo.py"])
        self.assertEqual(targets.ansible, ["src/ansible/roles/x/tasks/main.yml"])
        self.assertEqual(
            targets.groovy,
            ["vars/lib.groovy", "jenkinsfile/Jenkinsfile"],
        )
        self.assertEqual(targets.adoc, ["maintainer_docs/a.adoc"])
        self.assertEqual(targets.skipped, ["readme.md", ".github/workflows/ci.yml"])

    def test_ansible_path_heuristic(self) -> None:
        self.assertTrue(is_ansible_yaml_path("roles/ldap/tasks/main.yml"))
        self.assertFalse(is_ansible_yaml_path(".gitlab-ci.yml"))

    def test_partition_skips_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.py").write_text("x = 1\n", encoding="utf-8")
            present, missing = partition_existing_files(
                root,
                ["keep.py", "gone.py", "also/gone.yml"],
            )
            self.assertEqual(present, ["keep.py"])
            self.assertEqual(missing, ["gone.py", "also/gone.yml"])


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

    def test_skips_deleted_files_when_linting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            clone = root / "demo-pr2"
            clone.mkdir()
            (clone / ".git").mkdir()
            (clone / "kept.py").write_text("x = 1\n", encoding="utf-8")
            (clone / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")

            checkout = ReviewCheckout(
                platform="github",
                host="github.com",
                repo="org/demo",
                number=2,
                kind="pr",
                clone_path=str(clone),
                created=True,
                target_branch="master",
                base_ref="origin/master",
                base_sha="abc",
                head_sha="def",
                head_ref="topic",
                changed_files=["kept.py", "deleted.py"],
                diff_stat="2 files changed",
            )

            with patch("ai_tools.review_pr.prepare_review", return_value=checkout):
                with patch("ai_tools.check_python.which", return_value="/usr/bin/ruff"):
                    with patch("subprocess.run") as mock_subprocess:
                        mock_subprocess.return_value.returncode = 0
                        mock_subprocess.return_value.stdout = "All checks passed!\n"
                        mock_subprocess.return_value.stderr = ""
                        report = run_review("org/demo#2", reviews_root=root)

            self.assertIsNotNone(report.python)
            self.assertEqual(report.python.paths, ["kept.py"])
            self.assertIn("deleted.py", report.skipped_lint)
            self.assertTrue(report.ok)


class RunReviewGroovyAdocTests(unittest.TestCase):
    def _checkout(self, clone: Path, files: list[str]) -> ReviewCheckout:
        return ReviewCheckout(
            platform="gitlab",
            host="gitlab.example.com",
            repo="grp/demo",
            number=3,
            kind="mr",
            clone_path=str(clone),
            created=True,
            target_branch="main",
            base_ref="origin/main",
            base_sha="abc",
            head_sha="def",
            head_ref="topic",
            changed_files=files,
            diff_stat="x",
        )

    def test_groovy_and_adoc_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            clone = root / "demo-mr3"
            (clone / "vars").mkdir(parents=True)
            (clone / "maintainer_docs").mkdir()
            (clone / "macros").mkdir()
            (clone / "vars" / "x.groovy").write_text("def a = 1\n", encoding="utf-8")
            (clone / "maintainer_docs" / "p.adoc").write_text("= T\n", encoding="utf-8")
            (clone / "macros" / "source-url.rb").write_text("", encoding="utf-8")
            (clone / "Makefile").write_text(
                "all:\nuser_docs:\nmaintainer_docs:\n",
                encoding="utf-8",
            )
            checkout = self._checkout(
                clone,
                ["vars/x.groovy", "maintainer_docs/p.adoc", "gone.groovy"],
            )

            def fake_which(name: str) -> str | None:
                return f"/usr/bin/{name}"

            with patch("ai_tools.review_pr.prepare_review", return_value=checkout):
                with patch("ai_tools.check_groovy.which", side_effect=fake_which):
                    with patch("ai_tools.check_adoc.which", side_effect=fake_which):
                        with patch("subprocess.run") as run:
                            run.return_value.returncode = 0
                            run.return_value.stdout = "ok\n"
                            run.return_value.stderr = ""
                            report = run_review("grp/demo!3", reviews_root=root)

            self.assertIsNotNone(report.groovy)
            self.assertEqual(report.groovy.paths, ["vars/x.groovy"])
            self.assertIsNotNone(report.adoc)
            self.assertEqual(report.adoc.target, "maintainer_docs")
            self.assertIn("gone.groovy", report.skipped_lint)
            self.assertTrue(report.ok)
            text = format_report(report)
            self.assertIn("=== groovy ===", text)
            self.assertIn("=== adoc ===", text)

    def test_adoc_without_docs_root_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            clone = root / "demo-mr3"
            clone.mkdir(parents=True)
            (clone / "a.adoc").write_text("= T\n", encoding="utf-8")
            checkout = self._checkout(clone, ["a.adoc"])
            with patch("ai_tools.review_pr.prepare_review", return_value=checkout):
                report = run_review("grp/demo!3", reviews_root=root)
            self.assertIsNone(report.adoc)
            self.assertIn("a.adoc", report.skipped_lint)


if __name__ == "__main__":
    unittest.main()
