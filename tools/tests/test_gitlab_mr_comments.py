from __future__ import annotations

import unittest
from unittest.mock import patch

from ai_tools.clone_review import ParsedRef
from ai_tools.gitlab_mr_comments import (
    GitlabMrCommentsError,
    build_report,
    encode_project,
    format_report,
    main,
    parse_note,
)

SAMPLE_NOTES = [
    {
        "id": 1,
        "body": "left review comments",
        "system": True,
        "created_at": "2026-10-19T14:15:19.000Z",
        "author": {"username": "davherna"},
        "type": None,
        "resolvable": False,
        "resolved": False,
    },
    {
        "id": 2,
        "body": "Should this fail the run?",
        "system": False,
        "created_at": "2026-10-19T14:15:20.009Z",
        "author": {"username": "davherna"},
        "type": "DiffNote",
        "resolvable": True,
        "resolved": False,
        "position": {
            "new_path": "pipelines/jiraImportTool.groovy",
            "old_path": "pipelines/jiraImportTool.groovy",
            "new_line": 35,
            "old_line": None,
        },
    },
    {
        "id": 3,
        "body": "That url is stale.",
        "system": False,
        "created_at": "2026-10-19T14:15:20.248Z",
        "author": {"username": "davherna"},
        "type": "DiffNote",
        "resolvable": True,
        "resolved": False,
        "position": {
            "new_path": "jobdsl/jiraImportTool.groovy",
            "new_line": 28,
            "old_line": None,
        },
    },
]


class EncodeProjectTests(unittest.TestCase):
    def test_nested_path(self) -> None:
        self.assertEqual(
            encode_project("identity-management/idm-jenkins-libs"),
            "identity-management%2Fidm-jenkins-libs",
        )


class ParseNoteTests(unittest.TestCase):
    def test_diff_note_location(self) -> None:
        note = parse_note(SAMPLE_NOTES[1])
        self.assertEqual(note.author, "davherna")
        self.assertEqual(note.location(), "pipelines/jiraImportTool.groovy:35")
        self.assertTrue(note.resolvable)
        self.assertFalse(note.resolved)


class BuildReportTests(unittest.TestCase):
    def test_omits_system_by_default(self) -> None:
        ref = ParsedRef(
            platform="gitlab",
            host="gitlab.example.invalid",
            repo="identity-management/idm-jenkins-libs",
            number=183,
            kind="mr",
        )
        mr = {
            "title": "feat: jira import",
            "state": "opened",
            "author": {"username": "jvavra"},
            "web_url": "https://gitlab.example.invalid/x/-/merge_requests/183",
            "description": "Mirror polarion tool.",
            "reviewers": [{"username": "davherna"}],
            "assignees": [],
        }
        report = build_report(ref, mr=mr, notes=SAMPLE_NOTES)
        self.assertEqual(report.system_note_count, 1)
        self.assertEqual(len(report.comments), 2)
        self.assertEqual(report.comments[0].body, "Should this fail the run?")

    def test_include_system(self) -> None:
        ref = ParsedRef(
            platform="gitlab",
            host="gitlab.example.invalid",
            repo="g/p",
            number=1,
            kind="mr",
        )
        report = build_report(
            ref,
            mr={"title": "t", "state": "opened"},
            notes=SAMPLE_NOTES,
            include_system=True,
        )
        self.assertEqual(len(report.comments), 3)


class FormatReportTests(unittest.TestCase):
    def test_numbered_locations(self) -> None:
        ref = ParsedRef(
            platform="gitlab",
            host="gitlab.example.invalid",
            repo="identity-management/idm-jenkins-libs",
            number=183,
            kind="mr",
        )
        report = build_report(
            ref,
            mr={
                "title": "feat: jira import",
                "state": "opened",
                "author": {"username": "jvavra"},
                "web_url": "https://example/mr/183",
                "description": "Body text.",
                "reviewers": [{"username": "davherna"}],
            },
            notes=SAMPLE_NOTES,
        )
        text = format_report(report)
        self.assertIn("# MR !183 — feat: jira import", text)
        self.assertIn("1. [davherna] @pipelines/jiraImportTool.groovy:35", text)
        self.assertIn("2. [davherna] @jobdsl/jiraImportTool.groovy:28", text)
        self.assertIn("1 system notes omitted", text)
        self.assertIn("## Description", text)
        self.assertIn("Body text.", text)


class MainTests(unittest.TestCase):
    def test_rejects_github_url(self) -> None:
        with patch("ai_tools.gitlab_mr_comments.which", return_value="/usr/bin/glab"):
            code = main(["https://github.com/SSSD/sssd/pull/1"])
        self.assertEqual(code, 2)

    def test_happy_path_text(self) -> None:
        mr = {
            "title": "feat: jira import",
            "state": "opened",
            "author": {"username": "jvavra"},
            "web_url": "https://example/mr/183",
            "description": "",
            "reviewers": [],
            "assignees": [],
        }
        with (
            patch("ai_tools.gitlab_mr_comments.which", return_value="/usr/bin/glab"),
            patch("ai_tools.gitlab_mr_comments.fetch_mr_view", return_value=mr),
            patch(
                "ai_tools.gitlab_mr_comments.fetch_mr_notes",
                return_value=SAMPLE_NOTES,
            ),
        ):
            code = main(
                [
                    (
                        "https://gitlab.example.invalid/identity-management/"
                        "idm-jenkins-libs/-/merge_requests/183"
                    )
                ]
            )
        self.assertEqual(code, 0)

    def test_glab_missing(self) -> None:
        from ai_tools.gitlab_mr_comments import fetch_mr_view

        ref = ParsedRef(
            platform="gitlab",
            host="gitlab.example.invalid",
            repo="g/p",
            number=1,
            kind="mr",
        )
        with (
            patch("ai_tools.gitlab_mr_comments.which", return_value=None),
            self.assertRaises(GitlabMrCommentsError),
        ):
            fetch_mr_view(ref)


if __name__ == "__main__":
    unittest.main()
