"""stdio MCP server: same workflow as ~/git/branch_w.sh."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from git_worktrees_mcp.config import default_repos_ini_path, git_base_path, repo_registry
from git_worktrees_mcp.operations import create_branch_worktree
from git_worktrees_mcp.operations import worktree_refresh as run_worktree_refresh


def _require_fastmcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        print("Install dependencies: pip install -e .", file=sys.stderr)
        raise SystemExit(1) from e
    return FastMCP


def main() -> None:
    FastMCP = _require_fastmcp()
    reg = repo_registry()
    keys_sorted = sorted(reg.keys())

    mcp = FastMCP(
        "git-worktrees",
        instructions=(
            "Create a new branch in a new git worktree from upstream, then push to origin (fork). "
            f"Repos: {', '.join(keys_sorted)}. "
            "Env: GIT_PATH (default ~/git), GITLAB_CEE_USER, GITHUB_USER for fork URLs; "
            "GIT_WORKTREES_REPOS_INI to override repos.ini."
        ),
    )

    @mcp.tool()
    def list_repos() -> dict[str, Any]:
        """List supported repo codes and each default upstream branch and clone directory name."""
        out: dict[str, Any] = {}
        base = git_base_path()
        for k in keys_sorted:
            c = reg[k]
            out[k] = {
                "default_branch": c.default_branch,
                "default_clone_dir": c.default_loc,
                "worktree_prefix": c.prefix,
                "main_clone_path": str(Path(base) / c.default_loc),
            }
        return {
            "git_path": base,
            "repos_ini": str(default_repos_ini_path()),
            "repos": out,
        }

    @mcp.tool()
    def create_worktree_branch(
        repo: str,
        new_branch: str,
        source_branch: str | None = None,
    ) -> dict[str, Any]:
        """
        Mirror branch_w.sh: ensure fork clone with upstream remote exists under GIT_PATH,
        fetch all, ``git worktree add -b`` from upstream source branch, push -u origin.

        Two-arg mode: omit source_branch (uses repo default_branch, e.g. master/main).
        Three-arg mode: pass source_branch to branch off upstream that ref instead.
        """
        key = repo.strip().upper()
        cfg = reg.get(key)
        if cfg is None:
            return {
                "ok": False,
                "error": f"Unknown repo {repo!r}. Use one of: {', '.join(keys_sorted)}",
            }
        nb = new_branch.strip()
        if not nb:
            return {"ok": False, "error": "new_branch is empty"}
        sb = source_branch.strip() if source_branch else None
        if sb == "":
            sb = None
        return create_branch_worktree(key, cfg, nb, sb)

    @mcp.tool()
    def worktree_refresh(repo: str) -> dict[str, Any]:
        """
        Sync the main fork clone (default_loc) for a repo with upstream default_branch:
        ensure clone exists, checkout default_branch, ``git pull -r upstream``,
        then ``git push --force origin`` that branch.
        """
        key = repo.strip().upper()
        cfg = reg.get(key)
        if cfg is None:
            return {
                "ok": False,
                "error": f"Unknown repo {repo!r}. Use one of: {', '.join(keys_sorted)}",
            }
        return run_worktree_refresh(key, cfg)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
