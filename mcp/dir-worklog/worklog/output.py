"""Human-readable and JSON output."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any, TextIO


def print_activity(
    result: dict[str, Any], *, out: TextIO = sys.stdout, quiet: bool = False
) -> None:
    if result.get("ok") is False:
        if not quiet:
            print(result.get("error", "unknown error"), file=sys.stderr)
        return

    if quiet:
        return

    print(f"workday: {result['workday']}", file=out)
    print(f"workspaces: {', '.join(result['workspaces'])}", file=out)
    print(file=out)

    by_workspace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repo in result.get("active_repos", []):
        by_workspace[repo["workspace_root"]].append(repo)

    multiple_workspaces = len(result.get("workspaces", [])) > 1
    for workspace_root in result.get("workspaces", []):
        repos = by_workspace.get(workspace_root, [])
        if multiple_workspaces and repos:
            print(f"## {workspace_root}", file=out)
        for repo in repos:
            _print_repo(repo, out=out)

    if result.get("no_activity_on_workday"):
        print("No repos touched on workday. Recent repos:", file=out)
        recent_by_ws: dict[str, list[str]] = defaultdict(list)
        for item in result.get("recent_repos", []):
            recent_by_ws[item["workspace_root"]].append(item["name"])
        for workspace_root in result.get("workspaces", []):
            names = recent_by_ws.get(workspace_root, [])
            if not names:
                continue
            tail = names[-5:]
            if multiple_workspaces:
                print(f"  {workspace_root}: {', '.join(tail)}", file=out)
            else:
                print(f"  {', '.join(tail)}", file=out)


def _print_repo(repo: dict[str, Any], *, out: TextIO) -> None:
    commit_count = repo.get("commit_count", 0)
    file_count = repo.get("file_count", 0)
    if commit_count:
        summary = (
            f"{commit_count} commit{'s' if commit_count != 1 else ''}, {file_count} files touched"
        )
    elif file_count:
        summary = f"dir touched, {file_count} files"
    else:
        summary = "dir touched"
    print(f"[{repo['name']}] {summary}", file=out)
    for commit in repo.get("commits", []):
        print(f"  {commit['hash']} {commit['subject']}", file=out)
    for file_info in repo.get("files", []):
        print(f"  {file_info['path']}", file=out)
    print(file=out)


def print_json(data: dict[str, Any], *, out: TextIO = sys.stdout) -> None:
    json.dump(data, out, indent=2)
    print(file=out)
