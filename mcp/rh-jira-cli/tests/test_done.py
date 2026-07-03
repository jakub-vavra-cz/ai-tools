"""Unit tests for jira-cli done JQL and fallback."""

from __future__ import annotations

import unittest
from datetime import date
from io import StringIO
from unittest.mock import MagicMock, patch

from jira_cli.commands.done import (
    STRATEGY_ROLE_FALLBACK,
    STRATEGY_UPDATED_BY,
    build_done_role_fallback_jql,
    build_done_updated_by_jql,
    build_done_updated_clause,
    fetch_done_data,
    parse_activity_date,
)


class TestDoneJql(unittest.TestCase):
    def test_parse_none_is_today(self) -> None:
        self.assertIsNone(parse_activity_date(None))
        self.assertIsNone(parse_activity_date("  "))

    def test_parse_iso_date(self) -> None:
        self.assertEqual(parse_activity_date("2026-09-30"), date(2026, 9, 30))

    def test_parse_bad_date(self) -> None:
        with self.assertRaises(ValueError):
            parse_activity_date("30-09-2026")

    def test_updated_clause_today(self) -> None:
        self.assertEqual(build_done_updated_clause(None), "updated >= startOfDay()")

    def test_updated_clause_past_day(self) -> None:
        self.assertEqual(
            build_done_updated_clause(date(2026, 9, 30)),
            'updated >= "2026-09-30" AND updated < "2026-10-01"',
        )

    def test_updated_by_jql(self) -> None:
        jql = build_done_updated_by_jql(
            updated_clause="updated >= startOfDay()",
            project="IDM",
        )
        self.assertIn('project = "IDM"', jql)
        self.assertIn("updatedBy = currentUser()", jql)
        self.assertTrue(jql.endswith("ORDER BY updated DESC"))

    def test_role_fallback_jql(self) -> None:
        jql = build_done_role_fallback_jql(
            updated_clause="updated >= startOfDay()",
        )
        self.assertIn("assignee = currentUser()", jql)
        self.assertIn("updated >= startOfDay()", jql)
        self.assertNotIn("updatedBy", jql)


class TestFetchDoneFallback(unittest.TestCase):
    @patch("jira_cli.commands.done.list_issues_cmd.search_issues_by_jql")
    def test_uses_updated_by_when_nonempty(self, mock_search: MagicMock) -> None:
        mock_search.return_value = {
            "issues": [{"key": "IDM-1", "fields": {"summary": "x"}}],
        }
        client = MagicMock()
        settings = MagicMock()
        settings.contributors_field_id = None
        err = StringIO()
        payload = fetch_done_data(client, settings, err=err)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["strategy"], STRATEGY_UPDATED_BY)
        self.assertEqual(payload["count"], 1)
        self.assertFalse(payload["updated_by_empty"])
        self.assertEqual(mock_search.call_count, 1)

    @patch("jira_cli.commands.done.list_issues_cmd.search_issues_by_jql")
    def test_falls_back_when_updated_by_empty(self, mock_search: MagicMock) -> None:
        mock_search.side_effect = [
            {"issues": []},
            {
                "issues": [
                    {
                        "key": "IDM-8429",
                        "fields": {"summary": "sudoers", "status": {"name": "Closed"}},
                    },
                ],
            },
        ]
        client = MagicMock()
        settings = MagicMock()
        settings.contributors_field_id = None
        err = StringIO()
        payload = fetch_done_data(client, settings, err=err)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["strategy"], STRATEGY_ROLE_FALLBACK)
        self.assertTrue(payload["updated_by_empty"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["issues"][0]["key"], "IDM-8429")
        self.assertIn("updatedBy returned no issues", payload["note"] or "")
        self.assertEqual(mock_search.call_count, 2)


if __name__ == "__main__":
    unittest.main()
