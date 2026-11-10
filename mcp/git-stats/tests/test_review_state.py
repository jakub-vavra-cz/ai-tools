from __future__ import annotations

from unittest.mock import patch

from git_stats.github import _item_from_search, fetch_review_requested
from git_stats.gitlab import _partition_review_items


def _gh_node(url: str, *, requested: list[str], reviews: list[tuple[str, str]], labels: list[str]):
    return {
        "number": int(url.rsplit("/", 1)[1]),
        "title": "t",
        "url": url,
        "updatedAt": "2026-06-01T00:00:00Z",
        "isDraft": False,
        "state": "OPEN",
        "repository": {"nameWithOwner": "o/r"},
        "labels": {"nodes": [{"name": name} for name in labels]},
        "reviewRequests": {
            "totalCount": len(requested),
            "nodes": [{"requestedReviewer": {"login": login}} for login in requested],
        },
        "latestReviews": {
            "nodes": [{"state": state, "author": {"login": login}} for login, state in reviews]
        },
    }


def test_github_item_labels_and_pending_request():
    node = _gh_node(
        "https://github.com/o/r/pull/1",
        requested=["Me"],
        reviews=[("me", "APPROVED")],
        labels=["Tests"],
    )
    item = _item_from_search(node, login="me")
    assert item.labels == ["Tests"]
    # re-requested: old verdict is stale
    assert item.my_review == "pending"
    assert item.my_review_done is False


def test_github_item_review_done_states():
    node = _gh_node(
        "https://github.com/o/r/pull/2",
        requested=[],
        reviews=[("me", "CHANGES_REQUESTED")],
        labels=[],
    )
    item = _item_from_search(node, login="me")
    assert item.my_review == "changes_requested"
    assert item.my_review_done is True
    assert item.to_dict()["my_review_done"] is True


def test_github_item_without_graphql_data_has_unknown_review():
    raw = {
        "number": 3,
        "title": "t",
        "url": "https://github.com/o/r/pull/3",
        "labels": [{"name": "bug"}],
    }
    item = _item_from_search(raw, login="me")
    assert item.labels == ["bug"]
    assert item.my_review is None
    assert "my_review" not in item.to_dict()


@patch("git_stats.github._graphql_search_pull_requests")
@patch("git_stats.github._resolve_username", return_value="me")
def test_github_review_requested_include_reviewed_orders_pending_first(_login, mock_gql):
    pending = _gh_node("https://github.com/o/r/pull/10", requested=["me"], reviews=[], labels=[])
    pending["updatedAt"] = "2026-01-01T00:00:00Z"
    done = _gh_node(
        "https://github.com/o/r/pull/11", requested=[], reviews=[("me", "APPROVED")], labels=[]
    )
    done["updatedAt"] = "2026-06-01T00:00:00Z"
    mock_gql.side_effect = [([pending], None), ([done, pending], None)]

    result = fetch_review_requested(limit=10, include_all=False, include_reviewed=True)

    assert [item.number for item in result.items] == [10, 11]
    assert [item.my_review_done for item in result.items] == [False, True]
    queries = [call.kwargs["search_query"] for call in mock_gql.call_args_list]
    assert queries == [
        "is:pr is:open review-requested:me",
        "is:pr is:open reviewed-by:me -author:me",
    ]


@patch("git_stats.github._graphql_search_pull_requests")
@patch("git_stats.github._resolve_username", return_value="me")
def test_github_review_requested_default_single_query(_login, mock_gql):
    mock_gql.return_value = ([], None)
    fetch_review_requested(limit=5, include_all=False)
    assert mock_gql.call_count == 1


def _gl_row(iid: int, state: str, labels: list[str]):
    return {
        "title": f"MR {iid}",
        "iid": str(iid),
        "webUrl": f"https://gitlab.example/o/r/-/merge_requests/{iid}",
        "updatedAt": f"2026-06-0{iid}T00:00:00Z",
        "draft": False,
        "state": "opened",
        "project": {"fullPath": "o/r"},
        "labels": {"nodes": [{"title": name} for name in labels]},
        "reviewers": {
            "nodes": [
                {"username": "other", "mergeRequestInteraction": {"reviewState": "APPROVED"}},
                {"username": "Alice", "mergeRequestInteraction": {"reviewState": state}},
            ]
        },
    }


def test_gitlab_labels_and_my_review_and_ordering():
    rows = [
        _gl_row(1, "APPROVED", ["workflow::done"]),
        _gl_row(2, "UNREVIEWED", ["bug", "tests"]),
        _gl_row(3, "REQUESTED_CHANGES", []),
        _gl_row(4, "REVIEW_STARTED", []),
    ]
    result = _partition_review_items(rows, limit=10, include_drafts=False, username="alice")

    by_iid = {item.iid: item for item in result.items}
    assert by_iid[1].my_review == "approved" and by_iid[1].my_review_done is True
    assert by_iid[2].my_review == "pending" and by_iid[2].labels == ["bug", "tests"]
    assert by_iid[3].my_review == "changes_requested" and by_iid[3].my_review_done is True
    assert by_iid[4].my_review == "pending" and by_iid[4].my_review_done is False
    # pending first (newest first), then done
    assert [item.iid for item in result.items] == [4, 2, 3, 1]


def test_gitlab_rest_labels_are_strings():
    row = {
        "title": "t",
        "iid": 7,
        "web_url": "https://gitlab.example/o/r/-/merge_requests/7",
        "updated_at": "2026-06-01T00:00:00Z",
        "references": {"full": "o/r!7"},
        "labels": ["a", "b"],
    }
    result = _partition_review_items([row], limit=5, include_drafts=False, username="alice")
    assert result.items[0].labels == ["a", "b"]
    assert result.items[0].my_review is None
