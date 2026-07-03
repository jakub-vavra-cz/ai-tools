"""Unit tests for backlog JQL helpers."""

from __future__ import annotations

import unittest

from jira_cli.commands.backlog import (
    _backlog_sprint_cell,
    build_backlog_jql,
    partition_backlog_issues,
)


class TestBuildBacklogJql(unittest.TestCase):
    def test_default_statuses_and_sprint_exclusion(self) -> None:
        jql = build_backlog_jql(sprint_id=42, project="IDM")
        self.assertIn("assignee = currentUser() OR reporter = currentUser()", jql)
        self.assertIn('status IN ("New", "Refinement", "Backlog")', jql)
        self.assertIn("sprint not in (42)", jql)
        self.assertIn('project = "IDM"', jql)
        self.assertTrue(jql.endswith("ORDER BY status ASC, updated DESC"))

    def test_custom_statuses(self) -> None:
        jql = build_backlog_jql(
            status_names=("New", "Backlog"),
            sprint_id=7,
        )
        self.assertIn('status IN ("New", "Backlog")', jql)
        self.assertNotIn("Refinement", jql)


class TestPartitionBacklogIssues(unittest.TestCase):
    def test_groups_by_status(self) -> None:
        issues = [
            {"key": "A", "fields": {"status": {"name": "Backlog"}}},
            {"key": "B", "fields": {"status": {"name": "New"}}},
            {"key": "C", "fields": {"status": {"name": "New"}}},
        ]
        parts = partition_backlog_issues(issues)
        self.assertEqual([i["key"] for i in parts["New"]], ["B", "C"])
        self.assertEqual([i["key"] for i in parts["Backlog"]], ["A"])
        self.assertNotIn("Refinement", parts)


class TestBacklogSprintCell(unittest.TestCase):
    def test_sprint_names_from_sprint_field(self) -> None:
        issue = {
            "fields": {
                "Sprint": [
                    {"name": "IDM-SSSD Sprint 42"},
                    {"name": "Other Sprint"},
                ]
            }
        }
        self.assertEqual(_backlog_sprint_cell(issue, None), "IDM-SSSD Sprint 42, Other Sprint")

    def test_no_sprint_shows_dash(self) -> None:
        issue = {"fields": {"Sprint": None}}
        self.assertEqual(_backlog_sprint_cell(issue, None), "-")


if __name__ == "__main__":
    unittest.main()
