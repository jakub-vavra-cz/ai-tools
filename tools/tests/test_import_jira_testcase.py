from __future__ import annotations

import unittest
from unittest.mock import patch

from ai_tools.dump_polarion_testcase import (
    escape_property_value,
    parse_key_value_text,
    unescape_property_value,
)
from ai_tools.import_jira_testcase import (
    FIELD_ASSIGNED_TEAM,
    FIELD_EXTERNAL_URL,
    FIELD_ID,
    FIELD_URL,
    JiraConfig,
    build_issue_fields,
    escape_jql_string,
    escape_lucene_chars,
    find_by_summary,
    find_by_work_item_id,
    html_to_adf,
    import_testcase,
    plain_text_to_adf,
)


class PropertiesRoundTripTests(unittest.TestCase):
    def test_unescape_roundtrip(self) -> None:
        raw = "a\nb\tc\\d"
        self.assertEqual(unescape_property_value(escape_property_value(raw)), raw)

    def test_parse_key_value_text(self) -> None:
        pairs = parse_key_value_text(
            "# comment\nsummary=Hello\\nWorld\nID=RHEL-1\n"
        )
        self.assertEqual(pairs["summary"], "Hello\nWorld")
        self.assertEqual(pairs["ID"], "RHEL-1")


class AdfConversionTests(unittest.TestCase):
    def test_plain_text(self) -> None:
        doc = plain_text_to_adf("line1\nline2")
        self.assertEqual(doc["type"], "doc")
        para = doc["content"][0]
        self.assertEqual(para["type"], "paragraph")
        texts = [n.get("text") for n in para["content"] if n.get("type") == "text"]
        self.assertEqual(texts, ["line1", "line2"])

    def test_html_heading_and_table(self) -> None:
        doc = html_to_adf(
            "<h2>Polarion fields</h2>"
            "<table><tr><th>status</th><td>approved</td></tr></table>"
        )
        types = [b["type"] for b in doc["content"]]
        self.assertIn("heading", types)
        self.assertIn("table", types)


class BuildFieldsTests(unittest.TestCase):
    def test_maps_dump_keys(self) -> None:
        fields = build_issue_fields(
            {
                "summary": "My case",
                "description": "<p>Body</p>",
                "components": "sssd,ipa",
                "labels": "a,b",
                "AssignedTeam": "rhel-idm-sssd",
                "ID": "RHEL-1",
                "URL": "https://example.com/script",
                "External issue URL": "https://polarion.example/wi",
                "Tier": "1",
                "Architecture": "x86_64,aarch64",
            },
            project_key="RHELTEST",
            issue_type="Test Case",
            issue_type_id="10239",
            assignee_account_id="abc-123",
        )
        self.assertEqual(fields["summary"], "My case")
        self.assertEqual(fields["project"], {"key": "RHELTEST"})
        self.assertEqual(fields["issuetype"], {"id": "10239"})
        self.assertEqual(fields["assignee"], {"accountId": "abc-123"})
        self.assertEqual(
            fields["components"],
            [{"name": "sssd"}, {"name": "ipa"}],
        )
        self.assertEqual(fields["labels"], ["a", "b"])
        self.assertEqual(fields[FIELD_ASSIGNED_TEAM], {"value": "rhel-idm-sssd"})
        self.assertEqual(fields[FIELD_ID], "RHEL-1")
        self.assertEqual(fields[FIELD_URL], "https://example.com/script")
        self.assertEqual(fields[FIELD_EXTERNAL_URL], "https://polarion.example/wi")
        self.assertEqual(fields["customfield_11177"], {"value": "1"})
        self.assertEqual(
            fields["customfield_10772"],
            [{"value": "x86_64"}, {"value": "aarch64"}],
        )
        self.assertEqual(fields["description"]["type"], "doc")

    def test_skips_dash_component(self) -> None:
        fields = build_issue_fields(
            {"summary": "s", "components": "-"},
            project_key="RHELTEST",
            issue_type="Test Case",
        )
        self.assertNotIn("components", fields)

        fields = build_issue_fields(
            {"summary": "s", "components": "-,sssd,-"},
            project_key="RHELTEST",
            issue_type="Test Case",
        )
        self.assertEqual(fields["components"], [{"name": "sssd"}])

    def test_update_omits_project_type(self) -> None:
        fields = build_issue_fields(
            {"summary": "s"},
            project_key="RHELTEST",
            issue_type="Test Case",
            include_project_type=False,
        )
        self.assertNotIn("project", fields)
        self.assertNotIn("issuetype", fields)


class MatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = JiraConfig(
            base_url="https://jira.example.com",
            email="u@example.com",
            api_token="tok",
        )

    def test_escape_jql(self) -> None:
        self.assertEqual(escape_jql_string('a"b\\c'), 'a\\"b\\\\c')

    def test_escape_lucene_chars(self) -> None:
        self.assertEqual(
            escape_lucene_chars("a::b[c](d)"),
            r"a\:\:b\[c\]\(d\)",
        )

    def test_find_by_work_item_id_filters_exact(self) -> None:
        issues = [
            {
                "key": "RHELTEST-1",
                "fields": {FIELD_ID: "RHEL-1", "summary": "a"},
            },
            {
                "key": "RHELTEST-2",
                "fields": {FIELD_ID: "RHEL-10", "summary": "b"},
            },
        ]
        with patch(
            "ai_tools.import_jira_testcase.search_issues",
            return_value=issues,
        ) as search:
            found = find_by_work_item_id(
                self.config,
                project_key="RHELTEST",
                issue_type="Test Case",
                work_item_id="RHEL-1",
            )
        self.assertEqual([i["key"] for i in found], ["RHELTEST-1"])
        jql = search.call_args.kwargs.get("jql") or search.call_args.args[1]
        self.assertIn('cf[10591] ~ "\\"', jql)

    def test_find_by_summary_exact(self) -> None:
        issues = [
            {"key": "RHELTEST-1", "fields": {"summary": "Exact Title"}},
            {"key": "RHELTEST-2", "fields": {"summary": "Exact Title extra"}},
        ]
        with patch(
            "ai_tools.import_jira_testcase.search_issues",
            return_value=issues,
        ):
            found = find_by_summary(
                self.config,
                project_key="RHELTEST",
                issue_type="Test Case",
                summary="Exact Title",
            )
        self.assertEqual([i["key"] for i in found], ["RHELTEST-1"])


class ImportFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = JiraConfig(
            base_url="https://stage-redhat.atlassian.net",
            email="u@example.com",
            api_token="tok",
        )
        self.dump = {
            "summary": "Import me",
            "ID": "RHEL-99",
            "description": "<p>hi</p>",
            "AssignedTeam": "rhel-idm-sssd",
        }

    def test_updates_when_id_matches(self) -> None:
        with (
            patch(
                "ai_tools.import_jira_testcase.find_by_work_item_id",
                return_value=[{"key": "RHELTEST-7", "fields": {}}],
            ),
            patch(
                "ai_tools.import_jira_testcase.find_by_summary",
            ) as summary_search,
            patch("ai_tools.import_jira_testcase.update_issue") as update,
            patch(
                "ai_tools.import_jira_testcase.find_user_account_id",
                return_value=None,
            ),
            patch(
                "ai_tools.import_jira_testcase.resolve_issue_type",
            ) as resolve_type,
            patch(
                "ai_tools.import_jira_testcase.transition_issue_to_status",
                return_value=(True, None),
            ) as transition,
        ):
            result = import_testcase(self.dump, config=self.config)
        summary_search.assert_not_called()
        resolve_type.assert_not_called()
        update.assert_called_once()
        transition.assert_not_called()  # dump has no status
        self.assertEqual(result.action, "updated")
        self.assertEqual(result.issue_key, "RHELTEST-7")
        self.assertEqual(result.match, "id")
        self.assertEqual(
            result.browse_url,
            "https://stage-redhat.atlassian.net/browse/RHELTEST-7",
        )

    def test_falls_back_to_summary_then_creates(self) -> None:
        dump = {**self.dump, "status": "Active"}
        with (
            patch(
                "ai_tools.import_jira_testcase.find_by_work_item_id",
                return_value=[],
            ),
            patch(
                "ai_tools.import_jira_testcase.find_by_summary",
            ) as summary_search,
            patch(
                "ai_tools.import_jira_testcase.resolve_issue_type",
                return_value={"id": "10239", "name": "Test Case"},
            ),
            patch(
                "ai_tools.import_jira_testcase.create_issue",
                return_value={"key": "RHELTEST-8"},
            ) as create,
            patch(
                "ai_tools.import_jira_testcase.find_user_account_id",
                return_value=None,
            ),
            patch(
                "ai_tools.import_jira_testcase.transition_issue_to_status",
                return_value=(True, None),
            ) as transition,
        ):
            result = import_testcase(dump, config=self.config)
        # ID is present → no summary fallback even when ID search misses.
        summary_search.assert_not_called()
        create.assert_called_once()
        fields = create.call_args.args[1]
        self.assertEqual(fields["summary"], "Import me")
        self.assertEqual(fields[FIELD_ID], "RHEL-99")
        self.assertEqual(fields["issuetype"], {"id": "10239"})
        self.assertNotIn("status", fields)
        transition.assert_called_once_with(self.config, "RHELTEST-8", "Active")
        self.assertEqual(result.action, "created")
        self.assertEqual(result.issue_key, "RHELTEST-8")
        self.assertEqual(result.match, "none")
        self.assertEqual(result.status, "Active")
        self.assertTrue(result.status_applied)

    def test_dry_run_update_skips_write(self) -> None:
        with (
            patch(
                "ai_tools.import_jira_testcase.find_by_work_item_id",
                return_value=[{"key": "RHELTEST-7", "fields": {}}],
            ),
            patch("ai_tools.import_jira_testcase.update_issue") as update,
            patch(
                "ai_tools.import_jira_testcase.find_user_account_id",
                return_value=None,
            ),
        ):
            result = import_testcase(self.dump, config=self.config, dry_run=True)
        update.assert_not_called()
        self.assertEqual(result.action, "dry-run-update")

    def test_summary_match_updates_only_without_id(self) -> None:
        dump = {"summary": "Import me", "description": "<p>hi</p>"}
        with (
            patch(
                "ai_tools.import_jira_testcase.find_by_work_item_id",
            ) as id_search,
            patch(
                "ai_tools.import_jira_testcase.find_by_summary",
                return_value=[{"key": "RHELTEST-9", "fields": {}}],
            ),
            patch("ai_tools.import_jira_testcase.update_issue") as update,
            patch(
                "ai_tools.import_jira_testcase.find_user_account_id",
                return_value=None,
            ),
        ):
            result = import_testcase(dump, config=self.config)
        id_search.assert_not_called()
        update.assert_called_once()
        self.assertEqual(result.action, "updated")
        self.assertEqual(result.match, "summary")

    def test_create_fails_clearly_when_type_missing(self) -> None:
        from ai_tools.import_jira_testcase import JiraError

        with (
            patch(
                "ai_tools.import_jira_testcase.find_by_work_item_id",
                return_value=[],
            ),
            patch(
                "ai_tools.import_jira_testcase.find_by_summary",
                return_value=[],
            ),
            patch(
                "ai_tools.import_jira_testcase.resolve_issue_type",
                side_effect=JiraError(
                    "issue type 'Test Case' is not available for creating "
                    "issues in project RHELTEST. Available: Bug, Task"
                ),
            ),
        ):
            with self.assertRaises(JiraError) as ctx:
                import_testcase(self.dump, config=self.config, dry_run=True)
        self.assertIn("not available", str(ctx.exception))
        self.assertIn("Task", str(ctx.exception))


class ResolveIssueTypeTests(unittest.TestCase):
    def test_resolve_by_name_uses_id(self) -> None:
        from ai_tools.import_jira_testcase import resolve_issue_type

        config = JiraConfig(
            base_url="https://jira.example.com",
            email="u@example.com",
            api_token="tok",
        )
        with patch(
            "ai_tools.import_jira_testcase.list_createable_issue_types",
            return_value=[
                {"id": "10014", "name": "Task"},
                {"id": "10239", "name": "Test Case"},
            ],
        ):
            resolved = resolve_issue_type(
                config,
                project_key="RHELTEST",
                issue_type="test case",
            )
        self.assertEqual(resolved, {"id": "10239", "name": "Test Case"})


if __name__ == "__main__":
    unittest.main()
