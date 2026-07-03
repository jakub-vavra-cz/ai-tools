from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.cleanup_review import (
    CleanupResult,
    cleanup_paths,
    format_report as cleanup_format_report,
    list_review_clones,
    resolve_cleanup_paths,
)
from ai_tools.clone_review import CloneReviewError, expected_clone_path, parse_ref
from ai_tools.review_diff import (
    changed_files_from_patch,
    format_report as diff_format_report,
    stat_from_patch,
)


SAMPLE_PATCH = """\
diff --git a/readme.md b/readme.md
index d6037af..1e6ecf4 100644
--- a/readme.md
+++ b/readme.md
@@ -1 +1,2 @@
 old
+new
diff --git a/src/foo.py b/src/foo.py
new file mode 100644
--- /dev/null
+++ b/src/foo.py
@@ -0,0 +1 @@
+x = 1
"""


class PatchParseTests(unittest.TestCase):
    def test_changed_files_from_patch(self) -> None:
        files = changed_files_from_patch(SAMPLE_PATCH)
        self.assertEqual(files, ["readme.md", "src/foo.py"])

    def test_stat_from_patch(self) -> None:
        stat = stat_from_patch(SAMPLE_PATCH, 2)
        self.assertIn("2 files changed", stat)
        self.assertIn("insertions(+)", stat)


class ExpectedClonePathTests(unittest.TestCase):
    def test_default_dirname(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            ref = parse_ref("https://github.com/SSSD/sssd/pull/1842")
            path = expected_clone_path(ref, reviews_root=root)
            self.assertEqual(path.name, "sssd-pr1842")


class DiffFormatTests(unittest.TestCase):
    def test_name_only_output(self) -> None:
        from ai_tools.review_diff import ReviewDiff

        result = ReviewDiff(
            platform="github",
            host="github.com",
            repo="SSSD/sssd",
            number=1,
            kind="pr",
            source="api",
            clone_path=None,
            base_ref="origin/master",
            base_sha="abc",
            head_sha="def",
            changed_files=["a.py", "b.py"],
            diff_stat="2 files changed",
            diff="ignored",
        )
        self.assertEqual(diff_format_report(result, names_only=True), "a.py\nb.py\n")


class CleanupResolveTests(unittest.TestCase):
    def test_resolve_by_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            paths = resolve_cleanup_paths(
                reference="SSSD/sssd#42",
                clone_path=None,
                dirname=None,
                reviews_root=root,
                all_clones=False,
                platform=None,
                host=None,
            )
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].name, "sssd-pr42")

    def test_requires_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            with self.assertRaises(CloneReviewError):
                resolve_cleanup_paths(
                    reference=None,
                    clone_path=None,
                    dirname=None,
                    reviews_root=root,
                    all_clones=False,
                    platform=None,
                    host=None,
                )


class CleanupPathsTests(unittest.TestCase):
    def test_dry_run_skips_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            clone = root / "demo-pr1"
            clone.mkdir()
            (clone / ".git").mkdir()
            result = cleanup_paths([clone], reviews_root=root, dry_run=True)
            self.assertTrue(clone.exists())
            self.assertEqual(result.removed, [str(clone.resolve())])

    def test_remove_clone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            clone = root / "demo-pr1"
            clone.mkdir()
            (clone / ".git").mkdir()
            result = cleanup_paths([clone], reviews_root=root)
            self.assertFalse(clone.exists())
            self.assertEqual(len(result.removed), 1)

    def test_skips_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            missing = root / "gone-pr9"
            result = cleanup_paths([missing], reviews_root=root)
            self.assertEqual(result.removed, [])
            self.assertEqual(result.skipped, [str(missing.resolve())])


class ListReviewClonesTests(unittest.TestCase):
    def test_lists_git_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "@REVIEWS"
            root.mkdir()
            good = root / "repo-pr1"
            good.mkdir()
            (good / ".git").mkdir()
            (root / "notes.txt").write_text("x", encoding="utf-8")
            clones = list_review_clones(root)
            self.assertEqual(clones, [good])


class CleanupFormatTests(unittest.TestCase):
    def test_report_lists_removed(self) -> None:
        result = CleanupResult(
            reviews_root="/tmp/@REVIEWS",
            removed=["/tmp/@REVIEWS/demo-pr1"],
            skipped=[],
            dry_run=False,
        )
        text = cleanup_format_report(result)
        self.assertIn("removed: 1", text)
        self.assertIn("demo-pr1", text)


if __name__ == "__main__":
    unittest.main()
