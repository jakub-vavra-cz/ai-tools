"""Unit tests for bulk move payload."""

from __future__ import annotations

import unittest

from jira_cli.commands.move_issue import build_bulk_move_payload


class TestBuildBulkMovePayload(unittest.TestCase):
    def test_sends_bulk_notifications(self) -> None:
        payload = build_bulk_move_payload(
            target_project="IDM",
            issuetype_id="10014",
            issue_key="RHEL-1",
        )
        self.assertTrue(payload["sendBulkNotification"])
        self.assertEqual(payload["targetToSourcesMapping"]["IDM,10014"]["issueIdsOrKeys"], ["RHEL-1"])


if __name__ == "__main__":
    unittest.main()
