from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.check_groovy import (
    check_groovy,
    container_argv,
    find_groovy_root,
    format_report,
    is_groovy_path,
    lint_args,
)


class PathTests(unittest.TestCase):
    def test_is_groovy_path(self) -> None:
        for name in ("a.groovy", "x/b.gvy", "build.gradle", "Jenkinsfile", "d/Jenkinsfile.ci"):
            self.assertTrue(is_groovy_path(name), name)
        for name in ("a.py", "jenkinsfile/readme.md", "x.yml"):
            self.assertFalse(is_groovy_path(name), name)

    def test_find_root_by_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".groovylintrc.json").write_text("{}", encoding="utf-8")
            f = repo / "vars" / "a.groovy"
            f.parent.mkdir()
            f.write_text("", encoding="utf-8")
            self.assertEqual(find_groovy_root(f), repo.resolve())


class ArgvTests(unittest.TestCase):
    def test_lint_args_read_only(self) -> None:
        args = lint_args(["a.groovy", "b.groovy"])
        self.assertNotIn("--fix", args)
        self.assertEqual(args[-1], "a.groovy,b.groovy")

    def test_container_argv(self) -> None:
        argv = container_argv(Path("/r"), ["a.groovy"])
        self.assertEqual(argv[:3], ["podman", "run", "--rm"])
        self.assertIn("/r:/src:Z", argv)
        self.assertIn("npm-groovy-lint", argv[-1])
        self.assertIn("docker.io/library/node:22-bookworm", argv)


class CheckGroovyTests(unittest.TestCase):
    def _repo(self, tmp: str) -> tuple[Path, Path]:
        repo = Path(tmp)
        (repo / ".groovylintrc.json").write_text("{}", encoding="utf-8")
        f = repo / "a.groovy"
        f.write_text("def a = 1\n", encoding="utf-8")
        return repo, f

    def test_host_runner_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, f = self._repo(tmp)
            with patch("ai_tools.check_groovy.which", return_value="/usr/bin/npm-groovy-lint"):
                with patch("subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = "clean"
                    run.return_value.stderr = ""
                    ok = check_groovy([f])
                    run.return_value.returncode = 1
                    bad = check_groovy([f])
            self.assertTrue(ok.ok)
            self.assertEqual(ok.results[0].runner, "host")
            self.assertEqual(ok.config, ".groovylintrc.json")
            self.assertFalse(bad.ok)
            self.assertIn("overall: FAIL", format_report(bad))

    def test_podman_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, f = self._repo(tmp)

            def which(name: str) -> str | None:
                return "/usr/bin/podman" if name == "podman" else None

            with patch("ai_tools.check_groovy.which", side_effect=which):
                with patch("subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = ""
                    run.return_value.stderr = ""
                    report = check_groovy([f])
            self.assertEqual(report.results[0].runner, "podman")

    def test_skipped_when_no_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, f = self._repo(tmp)
            with patch("ai_tools.check_groovy.which", return_value=None):
                report = check_groovy([f])
            self.assertTrue(report.results[0].skipped)
            self.assertTrue(report.ok)
            self.assertIn("[SKIP]", format_report(report))

    def test_rejects_non_groovy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.py"
            f.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                check_groovy([f])


if __name__ == "__main__":
    unittest.main()
