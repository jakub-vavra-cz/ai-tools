"""Unit tests for issue link helpers."""

from __future__ import annotations

import unittest

from jira_cli.commands.issue_link import (
    post_keys_for_source_role,
    resolve_source_role,
    summarize_issue_link,
)


class TestPostKeysForSourceRole(unittest.TestCase):
    def test_source_blocks_target(self) -> None:
        inward, outward = post_keys_for_source_role(
            "IDM-7305",
            "IDM-6829",
            source_role="outward",
        )
        self.assertEqual(inward, "IDM-7305")
        self.assertEqual(outward, "IDM-6829")

    def test_source_blocked_by_target(self) -> None:
        inward, outward = post_keys_for_source_role(
            "IDM-7305",
            "IDM-6829",
            source_role="inward",
        )
        self.assertEqual(inward, "IDM-6829")
        self.assertEqual(outward, "IDM-7305")


class TestResolveSourceRole(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks_type = {
            "name": "Blocks",
            "inward": "is blocked by",
            "outward": "blocks",
        }

    def test_resolve_outward_label(self) -> None:
        import io

        role = resolve_source_role(
            self.blocks_type,
            as_relationship="blocks",
            err=io.StringIO(),
        )
        self.assertEqual(role, "outward")

    def test_resolve_inward_label(self) -> None:
        import io

        role = resolve_source_role(
            self.blocks_type,
            as_relationship="is blocked by",
            err=io.StringIO(),
        )
        self.assertEqual(role, "inward")


class TestSummarizeIssueLink(unittest.TestCase):
    def test_outward_perspective(self) -> None:
        row = summarize_issue_link(
            {
                "id": "123",
                "type": {
                    "name": "Blocks",
                    "inward": "is blocked by",
                    "outward": "blocks",
                },
                "outwardIssue": {"key": "IDM-6829"},
            },
            perspective_key="IDM-7305",
        )
        self.assertEqual(row["other_issue"], "IDM-6829")
        self.assertEqual(row["relationship"], "blocks")


if __name__ == "__main__":
    unittest.main()
