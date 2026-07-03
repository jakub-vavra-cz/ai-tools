from __future__ import annotations

from unittest.mock import patch

from git_stats.gitlab import _partition_review_items, fetch_review_requested


def test_partition_review_items_excludes_drafts_by_default():
    rows = [
        {
            "title": "Ready MR",
            "iid": 1,
            "webUrl": "https://gitlab.example/o/r/-/merge_requests/1",
            "updatedAt": "2026-06-01T00:00:00Z",
            "draft": False,
            "state": "opened",
            "project": {"fullPath": "o/r"},
        },
        {
            "title": "Draft MR",
            "iid": 2,
            "webUrl": "https://gitlab.example/o/r/-/merge_requests/2",
            "updatedAt": "2026-06-02T00:00:00Z",
            "draft": True,
            "state": "opened",
            "project": {"fullPath": "o/r"},
        },
    ]

    result = _partition_review_items(rows, limit=10, include_drafts=False)

    assert [item.ref for item in result.items] == ["o/r!1"]
    assert [item.ref for item in result.drafts] == ["o/r!2"]


@patch("git_stats.gitlab._graphql_review_requested")
def test_fetch_review_requested_uses_unreviewed_graphql_rows(mock_graphql):
    mock_graphql.return_value = (
        [
            {
                "title": "Draft: still waiting",
                "iid": "2678",
                "webUrl": "https://gitlab.cee.redhat.com/identity-management/idm-ci/-/merge_requests/2678",
                "updatedAt": "2026-06-10T12:03:25Z",
                "draft": True,
                "state": "opened",
                "project": {"fullPath": "identity-management/idm-ci"},
            },
        ],
        None,
    )

    result = fetch_review_requested(
        username="jvavra",
        hostname="gitlab.cee.redhat.com",
        limit=10,
        include_drafts=False,
        include_all=False,
    )

    assert result.error is None
    assert result.items == []
    assert [item.ref for item in result.drafts] == ["identity-management/idm-ci!2678"]
    mock_graphql.assert_called_once_with(
        hostname="gitlab.cee.redhat.com",
        limit=10,
        include_all=False,
    )
