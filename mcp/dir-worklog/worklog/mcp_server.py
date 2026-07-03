"""MCP (stdio) server for worklog."""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from worklog import config
from worklog.service import last_workday_result, workspace_activity


def _require_mcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        print("Install the MCP extra: pip install 'worklog[mcp]'", file=sys.stderr)
        raise SystemExit(1) from exc
    return FastMCP


def _run_workspace_activity(
    *,
    workspaces: list[str] | None,
    workday: str | None,
    max_repos: int,
    max_files_per_repo: int,
    max_commits_per_repo: int,
    recent_repos_count: int,
    include_scratch_dirs: bool,
) -> dict[str, Any]:
    ws = workspaces if workspaces else []
    return workspace_activity(
        workspaces=ws or None,
        workday=workday,
        max_repos=max_repos,
        max_files_per_repo=max_files_per_repo,
        max_commits_per_repo=max_commits_per_repo,
        recent_repos_count=recent_repos_count,
        include_scratch_dirs=include_scratch_dirs,
    )


def main() -> None:
    FastMCP = _require_mcp()

    mcp = FastMCP(
        "worklog",
        instructions=(
            "Git workspace activity under GIT_PATH (default ~/git). "
            "worklog_workspace_activity: last workday. "
            "worklog_workspace_today: today. Pass workspaces array for multiple roots."
        ),
    )

    @mcp.tool()
    def worklog_workspace_activity(
        workspaces: list[str] | None = None,
        workday: str | None = None,
        max_repos: int = config.default_max_repos(),
        max_files_per_repo: int = config.default_max_files(),
        max_commits_per_repo: int = config.default_max_commits(),
        recent_repos_count: int = config.default_recent_repos(),
        include_scratch_dirs: bool = config.default_include_scratch(),
    ) -> dict[str, Any]:
        """
        Last workday git workspace activity: repos touched that day, notable files,
        and your git commits. Same as `worklog activity`.
        """
        return _run_workspace_activity(
            workspaces=workspaces,
            workday=workday,
            max_repos=max_repos,
            max_files_per_repo=max_files_per_repo,
            max_commits_per_repo=max_commits_per_repo,
            recent_repos_count=recent_repos_count,
            include_scratch_dirs=include_scratch_dirs,
        )

    @mcp.tool()
    def worklog_workspace_today(
        workspaces: list[str] | None = None,
        max_repos: int = config.default_max_repos(),
        max_files_per_repo: int = config.default_max_files(),
        max_commits_per_repo: int = config.default_max_commits(),
        recent_repos_count: int = config.default_recent_repos(),
        include_scratch_dirs: bool = config.default_include_scratch(),
    ) -> dict[str, Any]:
        """
        Today's git workspace activity: repos touched today, notable files,
        and your git commits. Same as `worklog today`.
        """
        return _run_workspace_activity(
            workspaces=workspaces,
            workday=date.today().isoformat(),
            max_repos=max_repos,
            max_files_per_repo=max_files_per_repo,
            max_commits_per_repo=max_commits_per_repo,
            recent_repos_count=recent_repos_count,
            include_scratch_dirs=include_scratch_dirs,
        )

    @mcp.tool()
    def worklog_last_workday(reference_date: str | None = None) -> dict[str, str]:
        """Return the previous Mon–Fri workday as an ISO date."""
        return last_workday_result(reference_date=reference_date)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
