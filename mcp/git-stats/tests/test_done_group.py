from __future__ import annotations

from git_stats.done_group import group_done_items
from git_stats.models import DoneItem


def _item(
    *,
    action: str,
    ref: str,
    kind: str,
    created_at: str,
    title: str = "Title",
    url: str = "https://example.com",
    detail: str | None = None,
) -> DoneItem:
    return DoneItem(
        action=action,
        ref=ref,
        title=title,
        url=url,
        created_at=created_at,
        kind=kind,
        detail=detail,
    )


def test_group_github_pr_review_and_label():
    items = [
        _item(
            action="labeled",
            ref="SSSD/sssd#8925",
            kind="pull_request",
            created_at="2026-07-10T07:53:13Z",
            title="Pull request SSSD/sssd#8925",
            url="https://github.com/SSSD/sssd/pull/8925",
        ),
        _item(
            action="approved",
            ref="SSSD/sssd#8925",
            kind="review",
            created_at="2026-07-10T07:53:25Z",
            title="Review on SSSD/sssd#8925",
            url="https://github.com/SSSD/sssd/pull/8925#pullrequestreview-1",
            detail="approved",
        ),
    ]

    grouped = group_done_items(items)

    assert len(grouped) == 1
    assert grouped[0].ref == "SSSD/sssd#8925"
    assert grouped[0].action == "labeled, approved"
    assert grouped[0].url == "https://github.com/SSSD/sssd/pull/8925"
    assert grouped[0].events is not None
    assert len(grouped[0].events) == 2


def test_group_gitlab_mr_actions():
    items = [
        _item(
            action="approved",
            ref="identity-management/samba-tests!795",
            kind="merge_request",
            created_at="2026-07-10T07:23:47Z",
            title="Decommision win2012",
            url="https://gitlab.example/identity-management/samba-tests/-/merge_requests/795",
        ),
        _item(
            action="accepted",
            ref="identity-management/samba-tests!795",
            kind="merge_request",
            created_at="2026-07-10T07:23:54Z",
            title="Decommision win2012",
            url="https://gitlab.example/identity-management/samba-tests/-/merge_requests/795",
        ),
    ]

    grouped = group_done_items(items)

    assert len(grouped) == 1
    assert grouped[0].action == "approved, accepted"
    assert grouped[0].created_at == "2026-07-10T07:23:54Z"


def test_leaves_push_events_ungrouped():
    items = [
        _item(
            action="pushed",
            ref="SSSD/sssd",
            kind="push",
            created_at="2026-07-10T07:59:41Z",
            title="Pushed to sssd-2-12",
        ),
        _item(
            action="approved",
            ref="SSSD/sssd#8925",
            kind="review",
            created_at="2026-07-10T07:53:25Z",
        ),
        _item(
            action="labeled",
            ref="SSSD/sssd#8925",
            kind="pull_request",
            created_at="2026-07-10T07:53:13Z",
        ),
    ]

    grouped = group_done_items(items)

    assert len(grouped) == 2
    assert grouped[0].ref == "SSSD/sssd"
    assert grouped[1].ref == "SSSD/sssd#8925"


def test_grouped_item_to_dict_includes_events():
    items = [
        _item(
            action="labeled",
            ref="SSSD/sssd#8925",
            kind="pull_request",
            created_at="2026-07-10T07:53:13Z",
        ),
        _item(
            action="approved",
            ref="SSSD/sssd#8925",
            kind="review",
            created_at="2026-07-10T07:53:25Z",
            detail="approved",
        ),
    ]

    data = group_done_items(items)[0].to_dict()

    assert data["action"] == "labeled, approved"
    assert data["actions"] == ["labeled", "approved"]
    assert len(data["events"]) == 2
    assert "events" not in data["events"][0]
