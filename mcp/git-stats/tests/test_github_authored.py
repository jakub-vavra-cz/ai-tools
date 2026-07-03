from __future__ import annotations

from unittest.mock import patch

from git_stats.github import fetch_authored_no_reviewer


@patch("git_stats.github._resolve_username", return_value="jakub-vavra-cz")
@patch("git_stats.github._graphql_search_pull_requests")
def test_authored_no_reviewer_excludes_prs_with_review_requests(mock_graphql, _mock_login):
    mock_graphql.return_value = (
        [
            {
                "number": 2,
                "title": "Add initial version of python-static-analysis and sssd-system-tests",
                "url": "https://github.com/SSSD/sssd-ai/pull/2",
                "updatedAt": "2026-07-01T07:28:15Z",
                "isDraft": False,
                "state": "OPEN",
                "repository": {"nameWithOwner": "SSSD/sssd-ai"},
                "reviewRequests": {"totalCount": 1},
            },
            {
                "number": 9,
                "title": "No reviewers yet",
                "url": "https://github.com/o/r/pull/9",
                "updatedAt": "2026-06-01T00:00:00Z",
                "isDraft": False,
                "state": "OPEN",
                "repository": {"nameWithOwner": "o/r"},
                "reviewRequests": {"totalCount": 0},
            },
        ],
        None,
    )

    result = fetch_authored_no_reviewer(limit=10, include_all=False)

    assert result.error is None
    assert len(result.items) == 1
    assert result.items[0].ref == "o/r#9"
    mock_graphql.assert_called_once_with(
        search_query="is:pr is:open author:jakub-vavra-cz",
        limit=30,
    )
