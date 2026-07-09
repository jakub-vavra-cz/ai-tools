"""Unit tests for search JQL composition."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from jira_cli.commands.search_issues import compose_ordered_search_jql
from jira_cli.config import Settings


class TestComposeOrderedSearchJql(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.settings = Settings(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="token",
            preliminary_testing_field_id=None,
            fixed_in_build_field_id=None,
            test_coverage_field_id=None,
            test_link_field_id=None,
            git_pull_request_field_id=None,
            story_points_field_id=None,
            contributors_field_id=None,
            assigned_team_field_id=None,
        )

    def test_direct_jql_with_existing_order_by(self) -> None:
        jql = compose_ordered_search_jql(
            self.client,
            self.settings,
            term=None,
            summary_substring=None,
            project=None,
            direct_jql="assignee = currentUser() AND updated >= startOfDay() ORDER BY updated DESC",
            status=None,
            issue_type=None,
            priority=None,
            severity=None,
            testing=None,
            coverage=None,
            build=None,
            test_link=None,
            team=None,
            due=None,
            assignee_email=None,
            reporter_email=None,
            qa_contact_email=None,
            developer_email=None,
            doc_contact_email=None,
        )
        self.assertEqual(
            jql,
            "assignee = currentUser() AND updated >= startOfDay() ORDER BY updated DESC",
        )

    def test_direct_jql_without_order_by(self) -> None:
        jql = compose_ordered_search_jql(
            self.client,
            self.settings,
            term=None,
            summary_substring=None,
            project=None,
            direct_jql="assignee = currentUser() AND updated >= startOfDay()",
            status=None,
            issue_type=None,
            priority=None,
            severity=None,
            testing=None,
            coverage=None,
            build=None,
            test_link=None,
            team=None,
            due=None,
            assignee_email=None,
            reporter_email=None,
            qa_contact_email=None,
            developer_email=None,
            doc_contact_email=None,
        )
        self.assertEqual(
            jql,
            "assignee = currentUser() AND updated >= startOfDay() ORDER BY updated DESC",
        )


if __name__ == "__main__":
    unittest.main()
