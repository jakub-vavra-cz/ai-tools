from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.check_adoc import (
    check_adoc,
    container_argv,
    find_docs_root,
    format_report,
    pick_target,
)


def make_docs_root(root: Path) -> None:
    (root / "macros").mkdir(parents=True)
    (root / "macros" / "source-url.rb").write_text("", encoding="utf-8")
    (root / "Makefile").write_text(
        "all:\nuser_docs:\nmaintainer_docs:\n",
        encoding="utf-8",
    )


class TargetTests(unittest.TestCase):
    def test_pick_target(self) -> None:
        self.assertEqual(pick_target(["maintainer_docs/a.adoc"]), "maintainer_docs")
        self.assertEqual(pick_target(["user_docs/a/b.adoc"]), "user_docs")
        self.assertEqual(
            pick_target(["user_docs/a.adoc", "maintainer_docs/b.adoc"]),
            "all",
        )
        self.assertEqual(pick_target(["index/a.adoc"]), "all")

    def test_container_argv(self) -> None:
        argv = container_argv(Path("/d"), "user_docs")
        self.assertEqual(argv[-2:], ["make", "user_docs"])
        self.assertIn("/d:/docs:Z", argv)


class FindRootTests(unittest.TestCase):
    def test_find_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_docs_root(root)
            page = root / "user_docs" / "p.adoc"
            page.parent.mkdir()
            page.write_text("= T\n", encoding="utf-8")
            self.assertEqual(find_docs_root(page), root.resolve())
            # stop below the root: not found
            self.assertIsNone(find_docs_root(page, stop=root / "user_docs"))


class CheckAdocTests(unittest.TestCase):
    def _setup(self, tmp: str) -> Path:
        root = Path(tmp)
        make_docs_root(root)
        page = root / "maintainer_docs" / "p.adoc"
        page.parent.mkdir()
        page.write_text("= T\n", encoding="utf-8")
        return page

    def test_warning_fails_even_with_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._setup(tmp)
            with patch("ai_tools.check_adoc.which", return_value="/usr/bin/x"):
                with patch("subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = "asciidoctor: WARNING: skipping reference\n"
                    run.return_value.stderr = ""
                    report = check_adoc([page])
            self.assertFalse(report.ok)
            self.assertEqual(report.target, "maintainer_docs")
            self.assertIn("[FAIL]", format_report(report))

    def test_clean_build_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._setup(tmp)
            with patch("ai_tools.check_adoc.which", return_value="/usr/bin/x"):
                with patch("subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = "built\n"
                    run.return_value.stderr = ""
                    report = check_adoc([page])
            self.assertTrue(report.ok)
            # make clean + make target
            self.assertEqual(run.call_count, 2)

    def test_podman_fallback_and_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._setup(tmp)

            def only_podman(name: str) -> str | None:
                return "/usr/bin/podman" if name == "podman" else None

            with patch("ai_tools.check_adoc.which", side_effect=only_podman):
                with patch("subprocess.run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = ""
                    run.return_value.stderr = ""
                    report = check_adoc([page])
            self.assertEqual(report.results[0].runner, "podman")

            with patch("ai_tools.check_adoc.which", return_value=None):
                skipped = check_adoc([page])
            self.assertTrue(skipped.results[0].skipped)

    def test_no_docs_root_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.adoc"
            f.write_text("= T\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                check_adoc([f])


if __name__ == "__main__":
    unittest.main()
