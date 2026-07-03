from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from worklog.cli import _cmd_activity, _cmd_today, build_parser
from worklog.dates import window_bounds
from worklog.service import resolve_workspaces, workspace_activity


def _touch_in_window(path: Path, workday: date) -> None:
    since, _ = window_bounds(workday)
    ts = (since + timedelta(hours=12)).timestamp()
    os.utime(path, (ts, ts))


def test_resolve_workspaces_dedupes(tmp_path: Path):
    a = tmp_path / "git"
    a.mkdir()
    resolved, errors = resolve_workspaces([str(a), str(a)])
    assert len(resolved) == 1
    assert not errors


def test_resolve_workspaces_skips_missing(tmp_path: Path):
    resolved, errors = resolve_workspaces([str(tmp_path / "nope")])
    assert resolved == []
    assert len(errors) == 1


def test_workspace_activity_finds_repo(tmp_path: Path, monkeypatch):
    workday = date(2026, 6, 30)
    ws = tmp_path / "git"
    repo = ws / "myapp"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("hi", encoding="utf-8")
    _touch_in_window(repo, workday)
    _touch_in_window(repo / "README.md", workday)

    result = workspace_activity(
        workspaces=[str(ws)],
        workday=workday.isoformat(),
        max_repos=8,
        max_files_per_repo=10,
        max_commits_per_repo=0,
        recent_repos_count=5,
        include_scratch_dirs=False,
    )

    assert result["workday"] == workday.isoformat()
    assert result["active_repos"]
    assert result["active_repos"][0]["name"] == "myapp"
    assert result["active_repos"][0]["file_count"] == 1
    assert result["no_activity_on_workday"] is False


def test_workspace_activity_no_match_shows_recent(tmp_path: Path):
    workday = date(2020, 1, 3)
    ws = tmp_path / "git"
    repo = ws / "old"
    repo.mkdir(parents=True)
    old_ts = datetime(2019, 1, 1).timestamp()
    os.utime(repo, (old_ts, old_ts))

    result = workspace_activity(
        workspaces=[str(ws)],
        workday=workday.isoformat(),
        max_commits_per_repo=0,
    )

    assert result["no_activity_on_workday"] is True
    assert result["recent_repos"]
    assert result["recent_repos"][0]["name"] == "old"


def test_cli_activity_accepts_date_flag(tmp_path: Path):
    ws = tmp_path / "git"
    ws.mkdir()
    parser = build_parser()
    args = parser.parse_args(["activity", str(ws), "--date", "2026-06-30", "--max-commits", "0"])
    assert args.activity_date == "2026-06-30"

    workday = date(2026, 6, 30)
    repo = ws / "myapp"
    repo.mkdir()
    (repo / "file.txt").write_text("x", encoding="utf-8")
    _touch_in_window(repo, workday)
    _touch_in_window(repo / "file.txt", workday)

    assert _cmd_activity(args) == 0


def test_cli_today_uses_today_date(tmp_path: Path):
    ws = tmp_path / "git"
    ws.mkdir()
    parser = build_parser()
    args = parser.parse_args(["today", str(ws), "--max-commits", "0"])
    assert args.command == "today"
    assert getattr(args, "activity_date", None) is None

    workday = date.today()
    repo = ws / "myapp"
    repo.mkdir()
    (repo / "file.txt").write_text("x", encoding="utf-8")
    _touch_in_window(repo, workday)
    _touch_in_window(repo / "file.txt", workday)

    assert _cmd_today(args) == 0

    result = workspace_activity(
        workspaces=[str(ws)],
        workday=workday.isoformat(),
        max_commits_per_repo=0,
    )
    assert result["workday"] == workday.isoformat()
    assert result["active_repos"][0]["name"] == "myapp"
