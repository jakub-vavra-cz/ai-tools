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
        self.assertEqual(ref.default_dirname(), "sssd-pr1842")

    def test_gitlab_url_nested(self) -> None:
        url = (
            "https://gitlab.cee.redhat.com/identity-management/idm-ci/"
            "-/merge_requests/2726"
        )
        ref = parse_ref(url)
        self.assertEqual(ref.platform, "gitlab")
        self.assertEqual(ref.host, "gitlab.cee.redhat.com")
        self.assertEqual(ref.repo, "identity-management/idm-ci")
        self.assertEqual(ref.number, 2726)
        self.assertEqual(ref.kind, "mr")
        self.assertEqual(ref.default_dirname(), "idm-ci-mr2726")

    def test_github_shorthand(self) -> None:
        ref = parse_ref("SSSD/sssd#42")
        self.assertEqual(ref.platform, "github")
        self.assertEqual(ref.number, 42)
        self.assertEqual(ref.kind, "pr")

    def test_gitlab_shorthand_with_host(self) -> None:
        ref = parse_ref(
            "identity-management/idm-ci!2726",
            host="gitlab.cee.redhat.com",
        )
        self.assertEqual(ref.platform, "gitlab")
        self.assertEqual(ref.host, "gitlab.cee.redhat.com")
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
            host="gitlab.cee.redhat.com",
            repo="identity-management/idm-ci",
            number=2726,
            kind="mr",
            clone_path="/tmp/@REVIEWS/idm-ci-mr2726",
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
