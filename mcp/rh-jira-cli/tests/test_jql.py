"""Unit tests for JQL helpers."""

from __future__ import annotations

import unittest

from jira_cli.jql import (
    combine_list_filters,
    ensure_jql_order_by,
    normalize_extra_jql_fragment,
    split_jql_order_by,
)


class TestJqlOrderBy(unittest.TestCase):
    def test_split_without_order_by(self) -> None:
        main, order_by = split_jql_order_by("assignee = currentUser()")
        self.assertEqual(main, "assignee = currentUser()")
        self.assertIsNone(order_by)

    def test_split_with_order_by(self) -> None:
        main, order_by = split_jql_order_by(
            "assignee = currentUser() ORDER BY updated DESC"
        )
        self.assertEqual(main, "assignee = currentUser()")
        self.assertEqual(order_by, "updated DESC")

    def test_ensure_appends_when_missing(self) -> None:
        self.assertEqual(
            ensure_jql_order_by("assignee = currentUser()"),
            "assignee = currentUser() ORDER BY updated DESC",
        )

    def test_ensure_preserves_existing_order_by(self) -> None:
        jql = "assignee = currentUser() ORDER BY updated DESC"
        self.assertEqual(ensure_jql_order_by(jql), jql)

    def test_ensure_custom_default(self) -> None:
        self.assertEqual(
            ensure_jql_order_by("project = IDM", order_by="key ASC"),
            "project = IDM ORDER BY key ASC",
        )


class TestExtraJqlFragment(unittest.TestCase):
    def test_strip_leading_and(self) -> None:
        self.assertEqual(
            normalize_extra_jql_fragment('AND updated >= "2026-07-09"'),
            'updated >= "2026-07-09"',
        )

    def test_strip_leading_or(self) -> None:
        self.assertEqual(
            normalize_extra_jql_fragment("OR status = Open"),
            "status = Open",
        )

    def test_combine_list_filters_strips_and(self) -> None:
        merged = combine_list_filters(
            issue_type_name=None,
            extra_jql='AND updated >= "2026-07-09"',
            sprint_id=None,
        )
        self.assertEqual(merged, '(updated >= "2026-07-09")')


if __name__ == "__main__":
    unittest.main()
