from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_stats import config
from git_stats.categories import (
    CATEGORY_LABELS,
    normalize_categories,
    normalize_dirs,
    normalize_hosts,
)
from git_stats.github import _has_pending_review_requests, _item_from_search, _open_qualifier
from git_stats.gitlab import _item_from_mr, _query
from git_stats.models import CategoryResult, QueueItem


def test_normalize_categories_default():
    assert normalize_categories(None) == list(normalize_categories([]))


def test_normalize_categories_invalid():
    with pytest.raises(ValueError, match="invalid categories"):
        normalize_categories(["nope"])


def test_normalize_hosts():
    assert normalize_hosts(["GitHub"]) == ["github"]
    with pytest.raises(ValueError, match="invalid hosts"):
        normalize_hosts(["forge"])


def test_normalize_dirs():
    assert normalize_dirs(["sssd-fork-master", "sssd-fork-master"]) == ["sssd-fork-master"]
    assert normalize_dirs([]) is None


def test_remote_host_for_clone(tmp_path: Path):
    clone = tmp_path / "myrepo"
    clone.mkdir()
    subprocess.run(["git", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:user/repo.git"],
        cwd=clone,
        check=True,
        capture_output=True,
    )
    assert config.remote_host_for_clone(clone) == "github"

    gl = tmp_path / "gitlab-repo"
    gl.mkdir()
    subprocess.run(["git", "init"], cwd=gl, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@gitlab.cee.redhat.com:user/repo.git"],
        cwd=gl,
        check=True,
        capture_output=True,
    )
    assert config.remote_host_for_clone(gl) == "gitlab"


def test_iter_workspace_clones(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GIT_PATH", str(tmp_path))
    gh = tmp_path / "gh-repo"
    gh.mkdir()
    subprocess.run(["git", "init"], cwd=gh, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/o/r.git"],
        cwd=gh,
        check=True,
        capture_output=True,
    )
    not_git = tmp_path / "plain"
    not_git.mkdir()

    clones = config.iter_workspace_clones()
    assert len(clones) == 1
    assert clones[0][0] == "gh-repo"
    assert clones[0][1] == "github"

    filtered = config.iter_workspace_clones(dirs=["missing"])
    assert filtered == []


def test_open_qualifier():
    assert _open_qualifier(False) == "is:open "
    assert _open_qualifier(True) == ""


def test_gitlab_query_state():
    opened = _query("user", include_all=False, reviewer_username="user", per_page="10")
    assert "state=opened" in opened
    all_states = _query("user", include_all=True, reviewer_username="user", per_page="10")
    assert "state=all" in all_states


def test_item_from_search():
    item = _item_from_search(
        {
            "number": 42,
            "title": "Fix bug",
            "url": "https://github.com/SSSD/sssd/pull/42",
            "updatedAt": "2026-06-30T12:00:00Z",
            "isDraft": False,
            "repository": {"nameWithOwner": "SSSD/sssd"},
        }
    )
    assert item.ref == "SSSD/sssd#42"
    assert item.repository == "SSSD/sssd"


def test_item_from_mr():
    item = _item_from_mr(
        {
            "references": {"full": "idm/sssd!17"},
            "title": "CI update",
            "web_url": "https://gitlab.cee.redhat.com/idm/sssd/-/merge_requests/17",
            "updated_at": "2026-06-29T09:00:00Z",
            "project": {"path_with_namespace": "idm/sssd"},
            "iid": 17,
            "draft": False,
            "work_in_progress": False,
        }
    )
    assert item.ref == "idm/sssd!17"
    assert item.project == "idm/sssd"


def test_has_pending_review_requests():
    assert not _has_pending_review_requests({"reviewRequests": []})
    assert _has_pending_review_requests({"reviewRequests": [{"__typename": "User"}]})
    assert not _has_pending_review_requests({"reviewRequests": {"totalCount": 0}})
    assert _has_pending_review_requests({"reviewRequests": {"totalCount": 1}})


def test_repo_name_from_rest_urls():
    from git_stats.github import _repo_name

    assert (
        _repo_name(
            {
                "repository_url": "https://api.github.com/repos/SSSD/sssd-ai",
                "number": 2,
            }
        )
        == "SSSD/sssd-ai"
    )
    assert (
        _repo_name(
            {
                "html_url": "https://github.com/SSSD/sssd-ai/pull/2",
                "number": 2,
            }
        )
        == "SSSD/sssd-ai"
    )


def test_category_result_to_dict():
    result = CategoryResult(
        items=[
            QueueItem(
                ref="a/b#1",
                title="t",
                url="https://example.com",
                updated_at="2026-01-01T00:00:00Z",
            )
        ]
    )
    data = result.to_dict()
    assert data["count"] == 1
    assert data["items"][0]["ref"] == "a/b#1"


def test_category_labels_cover_all():
    from git_stats.categories import ALL_CATEGORIES

    for category in ALL_CATEGORIES:
        assert category in CATEGORY_LABELS
