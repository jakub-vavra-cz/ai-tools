"""Workspace activity orchestration."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from worklog import config
from worklog.dates import format_dt, last_workday, parse_date, window_bounds
from worklog.scan import (
    RepoEntry,
    discover_active_repos,
    is_git_repo,
    list_recent_repos,
    scan_commits,
    scan_files,
)


def resolve_workspaces(workspaces: list[str] | None) -> tuple[list[Path], list[dict[str, str]]]:
    raw_paths = workspaces if workspaces else [config.default_git_path()]
    resolved: list[Path] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()

    for raw in raw_paths:
        path = Path(raw).expanduser().resolve()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_dir():
            errors.append({"workspace": key, "message": "not a directory"})
            continue
        resolved.append(path)

    return resolved, errors


def workspace_activity(
    *,
    workspaces: list[str] | None = None,
    workday: date | str | None = None,
    max_repos: int | None = None,
    max_files_per_repo: int | None = None,
    max_commits_per_repo: int | None = None,
    recent_repos_count: int | None = None,
    include_scratch_dirs: bool | None = None,
) -> dict[str, Any]:
    max_repos = config.default_max_repos() if max_repos is None else max_repos
    max_files_per_repo = (
        config.default_max_files() if max_files_per_repo is None else max_files_per_repo
    )
    max_commits_per_repo = (
        config.default_max_commits() if max_commits_per_repo is None else max_commits_per_repo
    )
    recent_repos_count = (
        config.default_recent_repos() if recent_repos_count is None else recent_repos_count
    )
    if include_scratch_dirs is None:
        include_scratch_dirs = config.default_include_scratch()

    try:
        day = parse_date(workday) if workday is not None else last_workday()
    except ValueError as exc:
        return {"ok": False, "error": f"invalid workday: {exc}"}

    since, until = window_bounds(day)
    resolved, errors = resolve_workspaces(workspaces)
    if not resolved:
        return {
            "ok": False,
            "error": "no valid workspace directories",
            "errors": errors,
        }

    all_active: list[RepoEntry] = []
    all_recent: list[dict[str, Any]] = []

    for workspace in resolved:
        all_active.extend(
            discover_active_repos(
                workspace,
                workspace_root=workspace,
                since=since,
                until=until,
                include_scratch_dirs=include_scratch_dirs,
            )
        )
        all_recent.extend(
            list_recent_repos(
                workspace,
                workspace_root=workspace,
                since=since,
                limit=recent_repos_count,
                include_scratch_dirs=include_scratch_dirs,
            )
        )

    all_active.sort(key=lambda entry: entry.dir_mtime)
    selected = all_active[-max_repos:] if max_repos else []

    active_repos: list[dict[str, Any]] = []
    for entry in selected:
        files, file_count = scan_files(
            entry.path,
            since=since,
            until=until,
            max_files=max_files_per_repo,
        )
        commits, commit_count = scan_commits(
            entry.path,
            since=since,
            until=until,
            max_commits=max_commits_per_repo,
        )
        active_repos.append(
            {
                "workspace_root": str(entry.workspace_root),
                "name": entry.name,
                "path": str(entry.path),
                "dir_mtime": format_dt(entry.dir_mtime),
                "is_git": is_git_repo(entry.path),
                "files": files,
                "file_count": file_count,
                "commits": commits,
                "commit_count": commit_count,
            }
        )

    return {
        "workday": day.isoformat(),
        "workspaces": [str(path) for path in resolved],
        "window": {"since": format_dt(since), "until": format_dt(until)},
        "active_repos": active_repos,
        "recent_repos": all_recent,
        "no_activity_on_workday": len(all_active) == 0,
        "errors": errors,
    }


def last_workday_result(*, reference_date: date | str | None = None) -> dict[str, str]:
    if reference_date is None:
        ref = date.today()
    else:
        ref = parse_date(reference_date)
    return {"workday": last_workday(ref).isoformat(), "reference_date": ref.isoformat()}
