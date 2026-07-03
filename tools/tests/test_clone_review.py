from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.clone_review import (
    CloneReviewError,
    assert_reviews_path,
    default_reviews_root,
    format_report,
    migrate_legacy_review_clone,
    parse_ref,
    prepare_review,
)


class ParseRefTests(unittest.TestCase):
    def test_github_url(self) -> None:
        ref = parse_ref("https://github.com/SSSD/sssd/pull/1842")
        self.assertEqual(ref.platform, "github")
        self.assertEqual(ref.repo, "SSSD/sssd")
        self.assertEqual(ref.number, 1842)
        self.assertEqual(ref.kind, "pr")
        self.assertEqual(ref.default_dirname(), "sssd_pr1842")
        self.assertEqual(ref.legacy_dirname(), "sssd-pr1842")

    def test_gitlab_url_nested(self) -> None:
        url = (
            "https://gitlab.example.invalid/identity-management/idm-ci/"
            "-/merge_requests/2726"
        )
        ref = parse_ref(url)
        self.assertEqual(ref.platform, "gitlab")
        self.assertEqual(ref.host, "gitlab.example.invalid")
        self.assertEqual(ref.repo, "identity-management/idm-ci")
        self.assertEqual(ref.number, 2726)
        self.assertEqual(ref.kind, "mr")
        self.assertEqual(ref.default_dirname(), "idm_ci_mr2726")
        self.assertEqual(ref.legacy_dirname(), "idm-ci-mr2726")

    def test_hyphenated_repo_dirname_is_galaxy_safe(self) -> None:
        url = (
            "https://github.com/linux-system-roles/"
            "ad_integration/pull/234"
        )
        ref = parse_ref(url)
        self.assertEqual(ref.default_dirname(), "ad_integration_pr234")
        self.assertNotIn("-", ref.default_dirname())

    def test_migrate_legacy_review_clone_renames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            ref = parse_ref("https://github.com/SSSD/sssd/pull/1842")
            legacy = root / ref.legacy_dirname()
            legacy.mkdir()
            (legacy / "marker").write_text("ok", encoding="utf-8")
            dest, notes = migrate_legacy_review_clone(root, ref)
            self.assertEqual(dest.name, "sssd_pr1842")
            self.assertTrue(dest.is_dir())
            self.assertFalse(legacy.exists())
            self.assertEqual((dest / "marker").read_text(encoding="utf-8"), "ok")
            self.assertTrue(any("renamed legacy clone" in n for n in notes))

    def test_migrate_legacy_noop_when_safe_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            ref = parse_ref("https://github.com/SSSD/sssd/pull/1842")
            dest = root / ref.default_dirname()
            legacy = root / ref.legacy_dirname()
            dest.mkdir()
            legacy.mkdir()
            out, notes = migrate_legacy_review_clone(root, ref)
            self.assertEqual(out, dest)
            self.assertEqual(notes, [])
            self.assertTrue(legacy.exists())

    def test_github_shorthand(self) -> None:
        ref = parse_ref("SSSD/sssd#42")
        self.assertEqual(ref.platform, "github")
        self.assertEqual(ref.number, 42)
        self.assertEqual(ref.kind, "pr")

    def test_gitlab_shorthand_with_host(self) -> None:
        ref = parse_ref(
            "identity-management/idm-ci!2726",
            host="gitlab.example.invalid",
        )
        self.assertEqual(ref.platform, "gitlab")
        self.assertEqual(ref.host, "gitlab.example.invalid")
        self.assertEqual(ref.kind, "mr")

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(CloneReviewError):
            parse_ref("not-a-pr")


class ReviewsPathTests(unittest.TestCase):
    def test_requires_reviews_substring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "elsewhere"
            bad.mkdir()
            with self.assertRaises(CloneReviewError):
                assert_reviews_path(bad)

    def test_accepts_reviews_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "@REVIEWS" / "x"
            good.mkdir(parents=True)
            self.assertEqual(assert_reviews_path(good), good.resolve())

    def test_default_root_contains_reviews(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            # Unset override if present
            import os

            os.environ.pop("CLONE_REVIEW_ROOT", None)
            root = default_reviews_root()
            self.assertIn("reviews", root.as_posix().lower())


class FormatReportTests(unittest.TestCase):
    def test_lists_files(self) -> None:
        from ai_tools.clone_review import ReviewCheckout

        result = ReviewCheckout(
            platform="gitlab",
            host="gitlab.example.invalid",
            repo="identity-management/idm-ci",
            number=2726,
            kind="mr",
            clone_path="/tmp/@REVIEWS/idm_ci_mr2726",
            created=True,
            target_branch="master",
            base_ref="origin/master",
            base_sha="abc",
            head_sha="def",
            head_ref="topic",
            changed_files=["a.yml", "b.yml"],
            diff_stat=" 2 files changed",
            title="chore: demo",
        )
        text = format_report(result)
        self.assertIn("clone_path:", text)
        self.assertIn("  a.yml", text)
        self.assertIn("title: chore: demo", text)


class PrepareReviewSafetyTests(unittest.TestCase):
    def test_refuses_non_reviews_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CloneReviewError):
                prepare_review(
                    "https://github.com/SSSD/sssd/pull/1",
                    reviews_root=Path(tmp) / "not-allowed",
                )


if __name__ == "__main__":
    unittest.main()
