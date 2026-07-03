"""stdio MCP server for git-stats."""

from __future__ import annotations

import sys
from typing import Any

from git_stats import config
from git_stats.done_service import done_fetch
from git_stats.service import queue_fetch, review_queue


def _require_fastmcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        print("Install the MCP extra: pip install 'git-stats[mcp]'", file=sys.stderr)
        raise SystemExit(1) from exc
    return FastMCP


def main() -> None:
    FastMCP = _require_fastmcp()
    mcp = FastMCP(
        "git-stats",
        instructions=(
            "PR/MR queues on GitHub and Red Hat GitLab. "
            "Categories: review_requested, authored_changes_requested, authored_no_reviewer. "
            "git_stats_done: GitHub/GitLab activity for a calendar day. "
            "Env: GIT_PATH, GIT_STATS_GITLAB_HOST; per-repo fallbacks scan git clones under GIT_PATH."
        ),
    )

    @mcp.tool()
    def git_stats(
        categories: list[str] | None = None,
        hosts: list[str] | None = None,
        github_limit: int = config.default_github_limit(),
        gitlab_limit: int = config.default_gitlab_limit(),
        include_drafts: bool = config.default_include_drafts(),
        gitlab_host: str = config.default_gitlab_host(),
        dirs: list[str] | None = None,
        include_all: bool = config.default_include_all(),
    ) -> dict[str, Any]:
        """Fetch PR/MR queues on GitHub and GitLab."""
        return queue_fetch(
            categories=categories,
            hosts=hosts,
            github_limit=github_limit,
            gitlab_limit=gitlab_limit,
            include_drafts=include_drafts,
            gitlab_host=gitlab_host,
            dirs=dirs,
            include_all=include_all,
        )

    @mcp.tool()
    def git_stats_reviews(
        hosts: list[str] | None = None,
        github_limit: int = config.default_github_limit(),
        gitlab_limit: int = config.default_gitlab_limit(),
        include_drafts: bool = config.default_include_drafts(),
        gitlab_host: str = config.default_gitlab_host(),
        dirs: list[str] | None = None,
        include_all: bool = config.default_include_all(),
    ) -> dict[str, Any]:
        """Fetch review-requested PR/MR queues only (agenda section 2)."""
        return review_queue(
            hosts=hosts,
            github_limit=github_limit,
            gitlab_limit=gitlab_limit,
            include_drafts=include_drafts,
            gitlab_host=gitlab_host,
            dirs=dirs,
            include_all=include_all,
        )

    @mcp.tool()
    def git_stats_done(
        activity_date: str | None = None,
        hosts: list[str] | None = None,
        gitlab_host: str = config.default_gitlab_host(),
        max_pages: int = config.default_done_max_pages(),
    ) -> dict[str, Any]:
        """Fetch GitHub/GitLab updates for a calendar day (default: today)."""
        return done_fetch(
            activity_date=activity_date,
            hosts=hosts,
            gitlab_host=gitlab_host,
            max_pages=max_pages,
        )

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
