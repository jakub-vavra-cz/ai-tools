from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.dump_polarion_testcase import (
    attributes_to_pairs,
    build_jira_description,
    escape_property_value,
    fetch_testcase,
    format_key_value,
    format_hyperlinks,
    map_polarion_status_to_jira,
    ordered_items,
    polarion_pairs_to_jira,
    primary_script_url,
    teststeps_to_pairs,
    unwrap_text_value,
)


class UnwrapTextValueTests(unittest.TestCase):
    def test_rich_text(self) -> None:
        self.assertEqual(
            unwrap_text_value({"type": "text/html", "value": "<p>hi</p>"}),
            "<p>hi</p>",
        )

    def test_bool_and_none(self) -> None:
        self.assertEqual(unwrap_text_value(True), "true")
        self.assertEqual(unwrap_text_value(False), "false")
        self.assertEqual(unwrap_text_value(None), "")


class HyperlinkFormatTests(unittest.TestCase):
    def test_formats_role_and_uri(self) -> None:
        self.assertEqual(
            format_hyperlinks(
                [{"role": "testscript", "uri": "https://example.com/a"}]
            ),
            "testscript|https://example.com/a",
        )

    def test_includes_title_when_present(self) -> None:
        self.assertEqual(
            format_hyperlinks(
                [
                    {
                        "role": "ref",
                        "title": "docs",
                        "uri": "https://example.com",
                    }
                ]
            ),
            "ref|docs|https://example.com",
        )

    def test_primary_script_url_prefers_testscript(self) -> None:
        self.assertEqual(
            primary_script_url(
                "other|https://example.com/o,testscript|https://example.com/t"
            ),
            "https://example.com/t",
        )


class KeyValueFormatTests(unittest.TestCase):
    def test_escapes_newlines(self) -> None:
        self.assertEqual(escape_property_value("a\nb"), "a\\nb")

    def test_format_key_value_orders_standard_first(self) -> None:
        text = format_key_value(
            {
                "casecomponent": "ipa",
                "title": "t",
                "id": "RHEL-1",
                "project_id": "RHEL_IDM",
                "type": "testcase",
                "teststep.1.step": "do",
            }
        )
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "id=RHEL-1")
        self.assertEqual(lines[1], "project_id=RHEL_IDM")
        self.assertEqual(lines[2], "title=t")
        self.assertEqual(lines[3], "type=testcase")
        self.assertIn("casecomponent=ipa", lines)
        self.assertEqual(lines[-1], "teststep.1.step=do")

    def test_attributes_to_pairs_flattens_customs(self) -> None:
        pairs = attributes_to_pairs(
            {
                "id": "RHEL-1",
                "title": "Hello",
                "type": "testcase",
                "setup": {"type": "text/html", "value": "<p/>"},
                "casecomponent": "sssd",
                "hyperlinks": [
                    {"role": "testscript", "uri": "https://example.com/x"}
                ],
            },
            project_id="RHEL_IDM",
            author="jvavra",
            assignee="alice,bob",
        )
        self.assertEqual(pairs["project_id"], "RHEL_IDM")
        self.assertEqual(pairs["author"], "jvavra")
        self.assertEqual(pairs["assignee"], "alice,bob")
        self.assertEqual(pairs["setup"], "<p/>")
        self.assertEqual(pairs["casecomponent"], "sssd")
        self.assertEqual(pairs["hyperlinks"], "testscript|https://example.com/x")

    def test_teststeps_to_pairs(self) -> None:
        pairs = teststeps_to_pairs(
            [
                {
                    "type": "teststeps",
                    "id": "RHEL_IDM/RHEL-1/1",
                    "attributes": {
                        "index": "1",
                        "keys": ["step", "expectedResult"],
                        "values": [
                            {"type": "text/html", "value": "run"},
                            {"type": "text/html", "value": "pass"},
                        ],
                    },
                }
            ]
        )
        self.assertEqual(pairs["teststep.1.step"], "run")
        self.assertEqual(pairs["teststep.1.expectedResult"], "pass")

    def test_ordered_items_puts_teststeps_last(self) -> None:
        keys = [k for k, _ in ordered_items({"z": "1", "id": "x", "teststep.2.a": "y"})]
        self.assertEqual(keys[0], "id")
        self.assertEqual(keys[-1], "teststep.2.a")


class JiraImportFormatTests(unittest.TestCase):
    def test_maps_clear_fields(self) -> None:
        pairs = {
            "id": "RHEL-1",
            "project_id": "RHEL_IDM",
            "title": "My case",
            "type": "testcase",
            "assignee": "jvavra,other",
            "assignee_email": "jvavra@redhat.com,other@redhat.com",
            "author": "author1",
            "author_email": "author1@redhat.com",
            "casecomponent": "sssd",
            "subsystemteam": "rhel-idm-sssd",
            "tags": "tier1,nightly",
            "hyperlinks": "testscript|https://example.com/script",
            "description": "<p>Body</p>",
            "caseautomation": "automated",
            "status": "approved",
            "created": "2018-03-28T13:28:03.558Z",
            "updated": "2025-08-06T18:57:43.320Z",
            "setup": "<p>prep</p>",
            "teststep.1.step": "<p>do it</p>",
            "teststep.1.expectedResult": "<p>ok</p>",
            "automation_script": "<p>/home/sumenon/test_idrange.py#12</p>",
            "testCaseID": "com.example.TestClass.test_0001",
        }
        jira = polarion_pairs_to_jira(
            pairs,
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["summary"], "My case")
        self.assertEqual(jira["assignee"], "jvavra@redhat.com")
        self.assertEqual(jira["components"], "sssd")
        self.assertEqual(jira["AssignedTeam"], "rhel-idm-sssd")
        self.assertEqual(jira["labels"], "tier1,nightly")
        self.assertEqual(jira["ID"], "com.example.TestClass.test_0001")
        # Path-like automation_script is invalid → fall back to testscript hyperlink.
        self.assertEqual(jira["URL"], "https://example.com/script")
        self.assertEqual(jira["status"], "Active")
        self.assertEqual(
            jira["External issue URL"],
            "https://polarion.example.com/polarion/#/project/RHEL_IDM/workitem?id=RHEL-1",
        )
        desc = jira["description"]
        self.assertIn("<p>Body</p>", desc)
        self.assertIn("<h2>Setup</h2>", desc)
        self.assertIn("<p>prep</p>", desc)
        self.assertIn("<h2>Test steps</h2>", desc)
        self.assertIn("<th>Step</th>", desc)
        self.assertIn("<th>Action</th>", desc)
        self.assertIn("<th>Result</th>", desc)
        self.assertIn("<td>1</td>", desc)
        self.assertIn("<p>do it</p>", desc)
        self.assertIn("<p>ok</p>", desc)
        self.assertNotIn("<ol>", desc)
        self.assertNotIn("<h2>Automation script</h2>", desc)
        self.assertIn("<h2>Polarion fields</h2>", desc)
        self.assertIn("<th>caseautomation</th>", desc)
        self.assertIn("<td>automated</td>", desc)
        # Mapped status / dates / automation must not be duplicated as metadata.
        self.assertNotIn("<th>status</th>", desc)
        self.assertNotIn("<th>created</th>", desc)
        self.assertNotIn("<th>updated</th>", desc)
        self.assertNotIn("<th>testCaseID</th>", desc)
        self.assertNotIn("<th>automation_script</th>", desc)
        # Mapped fields must not be duplicated as metadata rows.
        self.assertNotIn("<th>title</th>", desc)
        self.assertNotIn("<th>casecomponent</th>", desc)
        self.assertNotIn("<th>subsystemteam</th>", desc)
        self.assertNotIn("<th>assignee_email</th>", desc)

    def test_summary_strips_newlines(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "title": "SSSD fails to start\nwhen ldap user extra attrs contains mail",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(
            jira["summary"],
            "SSSD fails to start when ldap user extra attrs contains mail",
        )
        self.assertNotIn("\n", jira["summary"])

    def test_summary_truncated_to_255(self) -> None:
        jira = polarion_pairs_to_jira(
            {"title": "x" * 300},
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(len(jira["summary"]), 255)
        self.assertEqual(jira["summary"], "x" * 255)

    def test_status_mapping_table(self) -> None:
        cases = {
            "draft": "Draft",
            "needs update": "Draft",
            "needsupdate": "Draft",
            "proposed": "Draft",
            "inactive": "Retired",
            "approved": "Active",
            "unknown": None,
        }
        for polarion, expected in cases.items():
            self.assertEqual(
                map_polarion_status_to_jira(polarion),
                expected,
                msg=polarion,
            )

    def test_url_prefers_valid_automation_script(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "id": "RHEL-1",
                "project_id": "RHEL_IDM",
                "title": "t",
                "automation_script": "https://gitlab.example.com/a/b",
                "hyperlinks": "testscript|https://example.com/script",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["URL"], "https://gitlab.example.com/a/b")

    def test_url_falls_back_to_testscript_hyperlink(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "id": "RHEL-1",
                "project_id": "RHEL_IDM",
                "title": "t",
                "automation_script": "/home/user/script.py#1",
                "hyperlinks": "testscript|https://example.com/script",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["URL"], "https://example.com/script")

    def test_url_omitted_when_neither_valid(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "id": "RHEL-1",
                "project_id": "RHEL_IDM",
                "title": "t",
                "automation_script": "/home/user/script.py",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertNotIn("URL", jira)

    def test_assignee_falls_back_to_author_email(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "id": "RHEL-1",
                "project_id": "RHEL_IDM",
                "title": "t",
                "author": "sumenon",
                "author_email": "sumenon@redhat.com",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["assignee"], "sumenon@redhat.com")

    def test_skips_empty_html_sections(self) -> None:
        desc = build_jira_description(
            {
                "title": "t",
                "description": "",
                "setup": "<p/>",
                "caseautomation": "manual",
                "teststep.1.step": "<p/>",
                "teststep.1.expectedResult": "<p></p>",
            }
        )
        self.assertNotIn("<h2>Setup</h2>", desc)
        self.assertNotIn("<h2>Test steps</h2>", desc)
        self.assertIn("<th>caseautomation</th>", desc)

    def test_omits_placeholder_subtype_from_description(self) -> None:
        desc = build_jira_description(
            {
                "title": "t",
                "subtype1": "-",
                "subtype2": "--",
                "caseautomation": "automated",
            }
        )
        self.assertNotIn("<th>subtype1</th>", desc)
        self.assertNotIn("<th>subtype2</th>", desc)
        self.assertIn("<th>caseautomation</th>", desc)

    def test_strips_duplicate_docstring_sections(self) -> None:
        desc = build_jira_description(
            {
                "title": "t",
                "description": (
                    "<pre>Topology: ldap\n\n"
                    ":title: Call the infopipe ping method\n"
                    ":setup:\n"
                    "    1. Start SSSD\n"
                    ":steps:\n"
                    "    1. Call ping method\n"
                    ":expectedresults:\n"
                    "    1. Ping success\n"
                    ":customerscenario: False</pre>"
                ),
                "setup": "<pre>1. Start SSSD</pre>",
                "teststep.1.step": "Call ping method",
                "teststep.1.expectedResult": "Ping success",
            }
        )
        self.assertIn("Topology: ldap", desc)
        self.assertNotIn(":title:", desc)
        self.assertIn(":customerscenario: False", desc)
        self.assertNotIn(":setup:", desc)
        self.assertNotIn(":steps:", desc)
        self.assertNotIn(":expectedresults:", desc)
        self.assertIn("<h2>Setup</h2>", desc)
        self.assertIn("<h2>Test steps</h2>", desc)
        self.assertIn("<th>Step</th>", desc)

    def test_customerscenario_true_adds_label_and_strips(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "title": "t",
                "tags": "tier1",
                "description": (
                    "<pre>Topology: ldap\n\n"
                    ":customerscenario: True</pre>"
                ),
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["labels"], "tier1,customerscenario")
        self.assertNotIn(":customerscenario:", jira["description"])
        self.assertIn("Topology: ldap", jira["description"])

    def test_customerscenario_false_keeps_description_no_label(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "title": "t",
                "tags": "tier1",
                "description": "<pre>:customerscenario: False</pre>",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["labels"], "tier1")
        self.assertIn(":customerscenario: False", jira["description"])

    def test_customerscenario_true_label_without_other_tags(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "title": "t",
                "description": "<pre>:customerscenario: True</pre>",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["labels"], "customerscenario")
        self.assertNotIn(":customerscenario:", jira["description"])

    def test_upstream_yes_adds_label_and_omits_from_description(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "title": "t",
                "tags": "tier1",
                "upstream": "yes",
                "caseautomation": "automated",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["labels"], "tier1,upstream")
        self.assertNotIn("<th>upstream</th>", jira["description"])
        self.assertIn("<th>caseautomation</th>", jira["description"])

    def test_upstream_no_omits_from_description_without_label(self) -> None:
        jira = polarion_pairs_to_jira(
            {
                "title": "t",
                "tags": "tier1",
                "upstream": "no",
            },
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["labels"], "tier1")
        self.assertNotIn("<th>upstream</th>", jira.get("description", ""))

    def test_keeps_docstring_sections_without_polarion_fields(self) -> None:
        desc = build_jira_description(
            {
                "description": (
                    "<pre>:title: Only in description\n"
                    ":setup:\n"
                    "    1. Start SSSD\n"
                    ":steps:\n"
                    "    1. Call ping\n"
                    ":expectedresults:\n"
                    "    1. Ok</pre>"
                ),
            }
        )
        self.assertIn(":title:", desc)
        self.assertIn(":setup:", desc)
        self.assertIn(":steps:", desc)
        self.assertIn(":expectedresults:", desc)
        self.assertNotIn("<h2>Setup</h2>", desc)
        self.assertNotIn("<h2>Test steps</h2>", desc)

    def test_format_jira_key_order(self) -> None:
        text = format_key_value(
            {
                "ID": "RHEL-1",
                "summary": "s",
                "AssignedTeam": "rhel-idm-ipa",
                "description": "d",
            },
            key_order=(
                "summary",
                "description",
                "AssignedTeam",
                "ID",
            ),
        )
        lines = text.strip().splitlines()
        self.assertEqual(
            lines,
            [
                "summary=s",
                "description=d",
                "AssignedTeam=rhel-idm-ipa",
                "ID=RHEL-1",
            ],
        )


class FetchTestcaseTests(unittest.TestCase):
    def test_fetch_merges_workitem_and_steps(self) -> None:
        workitem = {
            "data": {
                "type": "workitems",
                "id": "RHEL_IDM/RHEL-1",
                "attributes": {
                    "id": "RHEL-1",
                    "title": "t",
                    "type": "testcase",
                    "status": "approved",
                },
                "relationships": {
                    "author": {"data": {"type": "users", "id": "jvavra"}},
                    "assignee": {"data": []},
                },
            },
            "included": [
                {
                    "type": "users",
                    "id": "jvavra",
                    "attributes": {
                        "name": "Jakub",
                        "email": "jvavra@redhat.com",
                    },
                }
            ],
        }
        steps = {
            "data": [
                {
                    "type": "teststeps",
                    "id": "RHEL_IDM/RHEL-1/1",
                    "attributes": {
                        "index": "1",
                        "keys": ["step"],
                        "values": [{"type": "text/html", "value": "s"}],
                    },
                }
            ]
        }

        def fake_get(base, path, **kwargs):
            if path.endswith("/teststeps"):
                return steps
            return workitem

        with patch(
            "ai_tools.dump_polarion_testcase.polarion_get",
            side_effect=fake_get,
        ):
            pairs = fetch_testcase(
                "RHEL_IDM",
                "RHEL-1",
                base_api_url="https://example.com/polarion/rest/v1",
                token="tok",
            )

        self.assertEqual(pairs["id"], "RHEL-1")
        self.assertEqual(pairs["author"], "jvavra")
        self.assertEqual(pairs["author_email"], "jvavra@redhat.com")
        self.assertEqual(pairs["teststep.1.step"], "s")
        self.assertEqual(pairs["type"], "testcase")
        jira = polarion_pairs_to_jira(
            pairs,
            polarion_url="https://polarion.example.com",
        )
        self.assertEqual(jira["assignee"], "jvavra@redhat.com")

    def test_dump_file_roundtrip(self) -> None:
        from ai_tools.dump_polarion_testcase import dump_testcase_to_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.properties"
            dump_testcase_to_file({"id": "RHEL-1", "title": "a\nb"}, path)
            content = path.read_text(encoding="utf-8")
            self.assertIn("id=RHEL-1\n", content)
            self.assertIn("title=a\\nb\n", content)


if __name__ == "__main__":
    unittest.main()
