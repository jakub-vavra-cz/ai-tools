from __future__ import annotations

import unittest

from ai_tools.beetlejuice import (
    build_testresult_fields,
    normalize_architecture,
)


class NormalizeArchitectureTests(unittest.TestCase):
    def test_x8664(self) -> None:
        self.assertEqual(normalize_architecture("x8664"), "x86_64")

    def test_passthrough(self) -> None:
        self.assertEqual(normalize_architecture("aarch64"), "aarch64")


class BuildFieldsTests(unittest.TestCase):
    def test_required_parent_and_summary(self) -> None:
        fields = build_testresult_fields(
            {
                "summary": "IDM-TR: example",
                "TestCaseID": "tc-1",
                "components": "sssd",
                "AssignedTeam": "rhel-idm-sssd",
                "Architecture": "x86_64",
                "Compose Version": "RHEL-10.2-1",
                "Build": "sssd-2.12.0-1.el10.x86_64",
                "description": "<p>run metadata</p>",
            },
            project_key="RHELTEST",
            issue_type_id="10300",
            parent_key="RHELTEST-100",
            assignee_account_id=None,
        )
        self.assertEqual(fields["summary"], "IDM-TR: example")
        self.assertEqual(fields["parent"], {"key": "RHELTEST-100"})
        self.assertEqual(fields["components"], [{"name": "sssd"}])
        self.assertEqual(fields["customfield_10606"], {"value": "rhel-idm-sssd"})
        self.assertEqual(fields["customfield_11501"], "RHEL-10.2-1")


if __name__ == "__main__":
    unittest.main()
