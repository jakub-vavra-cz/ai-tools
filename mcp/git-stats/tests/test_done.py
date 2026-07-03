from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

from git_stats.dates import activity_window, event_on_date, parse_activity_date
from git_stats.done_github import _item_from_event
from git_stats.done_service import done_fetch


def test_parse_activity_date_defaults_today():
    assert parse_activity_date(None) == date.today()
    assert parse_activity_date("2026-07-01") == date(2026, 7, 1)


def test_event_on_date_uses_local_calendar_day():
    day = date(2026, 7, 1)
    start, _ = activity_window(day)
    utc_midnight = datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc).astimezone(start.tzinfo)
    assert event_on_date(utc_midnight.isoformat(), day) is True
    assert event_on_date("2026-06-30T23:59:59Z", day) is False


def test_github_review_event_item():
    item = _item_from_event(
        {
            "type": "PullRequestReviewEvent",
            "created_at": "2026-07-01T08:34:29Z",
            "repo": {"name": "SSSD/sssd-test-framework"},
            "payload": {
                "pull_request": {
                    "number": 248,
                    "url": "https://api.github.com/repos/SSSD/sssd-test-framework/pulls/248",
                },
                "review": {
                    "state": "approved",
                    "body": "LGTM",
                    "html_url": "https://github.com/SSSD/sssd-test-framework/pull/248#pullrequestreview-1",
                },
            },
        }
    )
    assert item is not None
    assert item.action == "approved"
    assert item.ref == "SSSD/sssd-test-framework#248"
    assert item.kind == "review"


@patch("git_stats.done_service.done_gitlab.fetch_gitlab_done")
@patch("git_stats.done_service.done_github.fetch_github_done")
def test_done_fetch_parallel(mock_github, mock_gitlab):
    from git_stats.models import DoneItem, DoneResult

    mock_github.return_value = DoneResult(
        username="me",
        items=[
            DoneItem(
                action="approved",
                ref="o/r#1",
                title="Review",
                url="https://github.com/o/r/pull/1",
                created_at="2026-07-01T10:00:00Z",
                kind="review",
            )
        ],
    )
    mock_gitlab.return_value = DoneResult(username="me", items=[])

    result = done_fetch(activity_date="2026-07-01", hosts=["github", "gitlab"])

    assert result["ok"] is True
    assert result["date"] == "2026-07-01"
    assert result["github"]["count"] == 1
    assert result["gitlab"]["count"] == 0
    mock_github.assert_called_once()
    mock_gitlab.assert_called_once()
