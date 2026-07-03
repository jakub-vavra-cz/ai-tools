from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.check_python import (
    CheckReport,
    CommandResult,
    discover_project_tools,
    find_python_root,
    format_report,
    relative_to_root,
    resolve_paths,
)


class FindPythonRootTests(unittest.TestCase):
    def test_finds_pyproject_in_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            nested = root / "src" / "mod"
            nested.mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            target = nested / "foo.py"
            target.write_text("x = 1\n", encoding="utf-8")
            self.assertEqual(find_python_root(target), root.resolve())


class DiscoverToolsTests(unittest.TestCase):
    def test_ruff_only_from_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[tool.ruff]\nline-length = 88\n",
                encoding="utf-8",
            )
            tools = discover_project_tools(root)
            self.assertEqual(tools.primary, "ruff")
            self.assertEqual(tools.selected_tools(), ["ruff-check", "ruff-format-check"])

    def test_flake8_stack_from_precommit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (root / ".pre-commit-config.yaml").write_text(
                "repos:\n"
                "  - repo: https://github.com/psf/black\n"
                "    hooks:\n"
                "      - id: black\n"
                "  - repo: https://github.com/pycqa/flake8\n"
                "    hooks:\n"
                "      - id: flake8\n",
                encoding="utf-8",
            )
            tools = discover_project_tools(root)
            self.assertEqual(tools.primary, "flake8-stack")
            self.assertIn("flake8", tools.selected_tools())
            self.assertIn("black-check", tools.selected_tools())

    def test_ruff_fallback_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "setup.py").write_text("from setuptools import setup\n", encoding="utf-8")
            tools = discover_project_tools(root)
            self.assertEqual(tools.primary, "ruff-fallback")
            self.assertIn("no project lint config found", tools.notes[0])


class ResolvePathsTests(unittest.TestCase):
    def test_rejects_non_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "readme.md"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_paths([path])


class RelativeToRootTests(unittest.TestCase):
    def test_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "pkg" / "mod.py"
            nested.parent.mkdir()
            nested.write_text("pass\n", encoding="utf-8")
            self.assertEqual(relative_to_root(nested, root), "pkg/mod.py")


class FormatReportTests(unittest.TestCase):
    def test_shows_failures(self) -> None:
        from ai_tools.check_python import ProjectPythonTools

        tools = ProjectPythonTools(
            python_root=Path("/tmp"),
            uses_ruff=True,
            uses_flake8=False,
            uses_black=False,
            uses_isort=False,
            primary="ruff",
        )
        report = CheckReport(
            python_root="/tmp",
            paths=["a.py"],
            tools=tools,
            results=[
                CommandResult(
                    name="ruff-check",
                    argv=["ruff", "check", "a.py"],
                    cwd="/tmp",
                    exit_code=1,
                    output="E501 line too long\n",
                )
            ],
        )
        text = format_report(report)
        self.assertIn("[FAIL] ruff-check", text)
        self.assertIn("overall: FAIL", text)


class CheckPythonIntegrationTests(unittest.TestCase):
    def test_runs_ruff_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.py"
            target.write_text("x=1\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")

            def fake_run(argv, cwd, env, capture_output, text, check):
                class Proc:
                    returncode = 0
                    stdout = "All checks passed!\n"
                    stderr = ""

                return Proc()

            with patch("ai_tools.check_python.which", return_value="/usr/bin/ruff"):
                with patch("subprocess.run", side_effect=fake_run):
                    from ai_tools.check_python import check_python

                    report = check_python([target], python_root=root)
            self.assertTrue(report.ok)
            names = [r.name for r in report.results]
            self.assertIn("ruff-check", names)
            self.assertIn("ruff-format-check", names)


if __name__ == "__main__":
    unittest.main()
