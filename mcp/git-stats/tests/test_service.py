from __future__ import annotations

from unittest.mock import patch

from git_stats.service import queue_fetch


def test_queue_fetch_invalid_category():
    result = queue_fetch(categories=["bad"])
    assert result["ok"] is False
    assert "invalid categories" in result["error"]


@patch("git_stats.github.fetch_github")
@patch("git_stats.gitlab.fetch_gitlab")
def test_queue_fetch_parallel(mock_gitlab, mock_github):
    mock_github.return_value = {
        "ok": True,
        "source": "gh",
        "username": "me",
        "error": None,
        "review_requested": {"count": 0, "items": []},
    }
    mock_gitlab.return_value = {
        "ok": True,
        "source": "api",
        "username": "me",
        "error": None,
        "review_requested": {"count": 0, "items": []},
    }
    result = queue_fetch(
        categories=["review_requested"], hosts=["github", "gitlab"], include_all=True
    )
    assert result["ok"] is True
    assert result["include_all"] is True
    assert "github" in result
    assert "gitlab" in result
    mock_github.assert_called_once()
    mock_gitlab.assert_called_once()
