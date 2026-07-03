"""git-worktrees CLI (cleanup and related helpers)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from git_worktrees_mcp.config import repo_registry
from git_worktrees_mcp.operations import cleanup_worktree
from git_worktrees_mcp.operations import create_branch_worktree
from git_worktrees_mcp.operations import worktree_refresh


def _print_result(result: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if result.get("ok"):
            print(result.get("message", "ok"))
            for warn in result.get("warnings") or []:
                print(f"warning: {warn}", file=sys.stderr)
        else:
            err = result.get("error") or result.get("warning") or "failed"
            print(err, file=sys.stderr)
            if result.get("warning") and result.get("error"):
                print(result["warning"], file=sys.stderr)
            for warn in result.get("warnings") or []:
                print(f"warning: {warn}", file=sys.stderr)
    return 0 if result.get("ok") else 1


def _resolve_repo(name: str) -> tuple[str, Any] | tuple[None, None]:
    reg = repo_registry()
    key = name.strip().upper()
    cfg = reg.get(key)
    if cfg is None:
        print(
            f"Unknown repo {name!r}. Use one of: {', '.join(sorted(reg))}",
            file=sys.stderr,
        )
        return None, None
    return key, cfg


def _cmd_cleanup(args: argparse.Namespace) -> int:
    key, cfg = _resolve_repo(args.repo)
    if cfg is None:
        return 2
    result = cleanup_worktree(key, cfg, args.branch, force=args.force)
    return _print_result(result, as_json=args.json)


def _cmd_refresh(args: argparse.Namespace) -> int:
    key, cfg = _resolve_repo(args.repo)
    if cfg is None:
        return 2
    result = worktree_refresh(key, cfg)
    return _print_result(result, as_json=args.json)


def _cmd_create(args: argparse.Namespace) -> int:
    key, cfg = _resolve_repo(args.repo)
    if cfg is None:
        return 2
    source = args.source_branch.strip() if args.source_branch else None
    if source == "":
        source = None
    result = create_branch_worktree(key, cfg, args.new_branch, source)
    return _print_result(result, as_json=args.json)


def _cmd_list_repos(args: argparse.Namespace) -> int:
    from pathlib import Path

    from git_worktrees_mcp.config import default_repos_ini_path, git_base_path

    reg = repo_registry()
    base = git_base_path()
    out = {
        "git_path": base,
        "repos_ini": str(default_repos_ini_path()),
        "repos": {
            k: {
                "default_branch": c.default_branch,
                "default_clone_dir": c.default_loc,
                "worktree_prefix": c.prefix,
                "main_clone_path": str(Path(base) / c.default_loc),
            }
            for k, c in sorted(reg.items())
        },
    }
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"GIT_PATH={base}")
        for k, meta in out["repos"].items():
            print(
                f"{k}: default={meta['default_branch']} "
                f"clone={meta['default_clone_dir']} prefix={meta['worktree_prefix']}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="git-worktrees",
        description=(
            "Manage fork worktrees under GIT_PATH: create topic branches, "
            "refresh the main clone, or clean up merged worktrees."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list-repos", help="List configured repository codes")
    list_p.add_argument("--json", action="store_true", help="Emit JSON")
    list_p.set_defaults(func=_cmd_list_repos)

    create_p = sub.add_parser(
        "create",
        help="Create a topic branch worktree from upstream and push to origin",
    )
    create_p.add_argument("repo", help="Repo code (e.g. IDMCI, SSSD, FW)")
    create_p.add_argument("new_branch", help="New branch / worktree name suffix")
    create_p.add_argument(
        "source_branch",
        nargs="?",
        default=None,
        help="Upstream source branch (default: repo default_branch)",
    )
    create_p.add_argument("--json", action="store_true", help="Emit JSON")
    create_p.set_defaults(func=_cmd_create)

    refresh_p = sub.add_parser(
        "refresh",
        help="Sync main clone with upstream default branch and force-push origin",
    )
    refresh_p.add_argument("repo", help="Repo code (e.g. IDMCI, SSSD, FW)")
    refresh_p.add_argument("--json", action="store_true", help="Emit JSON")
    refresh_p.set_defaults(func=_cmd_refresh)

    cleanup_p = sub.add_parser(
        "cleanup",
        help=(
            "Delete a merged topic worktree and its fork branch "
            "(refuses if not merged upstream)"
        ),
    )
    cleanup_p.add_argument("repo", help="Repo code (e.g. IDMCI, SSSD, FW)")
    cleanup_p.add_argument("branch", help="Topic branch name (worktree suffix)")
    cleanup_p.add_argument(
        "--force",
        action="store_true",
        help="Ignore uncommitted changes in the worktree (still requires upstream merge)",
    )
    cleanup_p.add_argument("--json", action="store_true", help="Emit JSON")
    cleanup_p.set_defaults(func=_cmd_cleanup)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
