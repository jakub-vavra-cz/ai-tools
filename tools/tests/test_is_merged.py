from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_tools.is_merged import (
    check_is_merged,
    classify_tip_cherry,
    subject_search_terms,
)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")


def _commit(path: Path, name: str, message: str) -> str:
    file_path = path / name
    file_path.write_text(f"{name}\n")
    _git(path, "add", name)
    _git(path, "commit", "-m", message)
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def _upstream_ref(work: Path) -> str:
    return "upstream/main"


class SubjectSearchTermsTests(unittest.TestCase):
    def test_extracts_ticket_and_subject(self) -> None:
        terms = subject_search_terms(
            "Tests: Add test for SSSD-8151 Mismatch with default_domain_suffix",
        )
        self.assertIn("SSSD-8151", terms)
        self.assertTrue(any("Mismatch" in t for t in terms))


class IsMergedTests(unittest.TestCase):
    def test_exact_ancestor_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "upstream"
            work = root / "work"
            _init_repo(upstream)
            tip = _commit(upstream, "a.txt", "initial")
            _git(root, "clone", str(upstream), str(work))
            _git(work, "remote", "rename", "origin", "upstream")

            result = check_is_merged(
                work,
                upstream=_upstream_ref(work),
                check_origin=False,
            )
            self.assertTrue(result.merged)
            self.assertEqual(result.merge_status, "exact")
            self.assertTrue(result.ancestor)
            self.assertEqual(result.tip, tip)

    def test_tip_cherry_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "upstream"
            work = root / "work"
            _init_repo(upstream)
            _commit(upstream, "base.txt", "base")
            _git(root, "clone", str(upstream), str(work))
            _git(work, "remote", "rename", "origin", "upstream")

            _git(work, "checkout", "-b", "topic")
            _commit(work, "feature.txt", "Tests: Add feature SSSD-9999")

            patch = _git(work, "format-patch", "-1", "--stdout", "HEAD").stdout
            subprocess.run(
                ["git", "am"],
                cwd=upstream,
                input=patch,
                check=True,
                capture_output=True,
                text=True,
            )
            _git(work, "fetch", "upstream")

            result = check_is_merged(
                work,
                ref="topic",
                upstream=_upstream_ref(work),
                check_origin=False,
            )
            self.assertTrue(result.merged)
            self.assertIn(result.merge_status, ("cherry", "exact"))
            self.assertEqual(result.tip_cherry, "equivalent")

    def test_not_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "upstream"
            work = root / "work"
            _init_repo(upstream)
            _commit(upstream, "base.txt", "base")
            _git(root, "clone", str(upstream), str(work))
            _git(work, "remote", "rename", "origin", "upstream")
            _git(work, "checkout", "-b", "topic")
            _commit(work, "only-local.txt", "Tests: unique SSSD-8151 local only")

            upstream_ref = _upstream_ref(work)
            result = check_is_merged(
                work,
                ref="topic",
                upstream=upstream_ref,
                check_origin=False,
            )
            self.assertFalse(result.merged)
            self.assertEqual(result.merge_status, "not_merged")
            self.assertEqual(result.tip_cherry, "pending")
            self.assertEqual(
                classify_tip_cherry(work, upstream_ref, result.tip),
                "pending",
            )


if __name__ == "__main__":
    unittest.main()
