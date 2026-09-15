"""Unit tests for archive issue key normalization."""

from __future__ import annotations

import unittest

from jira_cli.commands.archive import normalize_issue_keys


class TestNormalizeIssueKeys(unittest.TestCase):
    def test_strips_and_uppercases(self) -> None:
        self.assertEqual(normalize_issue_keys([" proj-1 ", "idm-2"]), ["PROJ-1", "IDM-2"])

    def test_splits_commas(self) -> None:
        self.assertEqual(
            normalize_issue_keys(["PROJ-1,PROJ-2", "PROJ-3"]), ["PROJ-1", "PROJ-2", "PROJ-3"]
        )

    def test_dedupes(self) -> None:
        self.assertEqual(normalize_issue_keys(["PROJ-1", "proj-1", "PROJ-2"]), ["PROJ-1", "PROJ-2"])

    def test_empty_input(self) -> None:
        self.assertEqual(normalize_issue_keys([]), [])
        self.assertEqual(normalize_issue_keys(["", "  ", ","]), [])


if __name__ == "__main__":
    unittest.main()
