"""Git subprocess helpers mirroring branch_w.sh."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from git_worktrees_mcp.config import RepoConfig, git_base_path, resolve_fork_url


@dataclass
class GitResult:
    ok: bool
    command: list[str]
    cwd: str
    stdout: str
    stderr: str
    returncode: int


def _run(cwd: Path, args: Sequence[str]) -> GitResult:
    cmd = list(args)
    p = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return GitResult(
        ok=p.returncode == 0,
        command=cmd,
        cwd=str(cwd),
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        returncode=p.returncode,
    )


def ensure_main_clone(git_path: Path, cfg: RepoConfig) -> tuple[bool, list[GitResult]]:
    """Clone fork + upstream if missing; always safe to call."""
    results: list[GitResult] = []
    main = git_path / cfg.default_loc
    fork = resolve_fork_url(cfg)
    if main.is_dir() and (main / ".git").exists():
        return True, results

    git_path.mkdir(parents=True, exist_ok=True)
    r = _run(git_path, ["git", "clone", fork, cfg.default_loc])
    results.append(r)
    if not r.ok:
        return False, results

    r = _run(main, ["git", "remote", "add", "upstream", cfg.upstream])
    results.append(r)
    if not r.ok:
        err = r.stderr.lower()
        if "already exists" in err:
            pass
        else:
            return False, results

    r = _run(main, ["git", "fetch", "--all"])
    results.append(r)
    return r.ok, results


def fetch_all(main_clone: Path) -> GitResult:
    return _run(main_clone, ["git", "fetch", "--all"])


def checkout_branch(main_clone: Path, branch: str) -> GitResult:
    return _run(main_clone, ["git", "checkout", branch])


def pull_rebase_upstream(main_clone: Path, branch: str) -> GitResult:
    return _run(main_clone, ["git", "pull", "-r", "upstream", branch])


def worktree_add(
    main_clone: Path,
    new_branch: str,
    worktree_path: Path,
    upstream_ref: str,
) -> GitResult:
    # Match: git worktree add -b NEW ../PREFIX+NEW upstream/SOURCE
    return _run(
        main_clone,
        [
            "git",
            "worktree",
            "add",
            "-b",
            new_branch,
            str(worktree_path),
            upstream_ref,
        ],
    )


def push_set_upstream(worktree: Path, branch: str) -> GitResult:
    return _run(
        worktree,
        ["git", "push", "--set-upstream", "origin", branch],
    )


def push_origin(main_clone: Path, branch: str, *, force: bool = False) -> GitResult:
    cmd = ["git", "push"]
    if force:
        cmd.append("--force")
    cmd.extend(["origin", branch])
    return _run(main_clone, cmd)


def default_paths(cfg: RepoConfig) -> tuple[Path, Path]:
    base = Path(git_base_path())
    main_clone = base / cfg.default_loc
    return base, main_clone


def worktree_directory(cfg: RepoConfig, new_branch: str) -> Path:
    return Path(git_base_path()) / f"{cfg.prefix}{new_branch}"


def create_branch_worktree(
    repo_key: str,
    cfg: RepoConfig,
    new_branch: str,
    source_branch: str | None,
) -> dict:
    """
    End-to-end: ensure clone, fetch, worktree from upstream source, push origin.

    If source_branch is None, use cfg.default_branch (two-arg script mode).
    """
    base, main_clone = default_paths(cfg)
    source = source_branch if source_branch is not None else cfg.default_branch
    upstream_ref = f"upstream/{source}"
    wt = worktree_directory(cfg, new_branch)

    steps: list[dict] = []

    ok, clone_results = ensure_main_clone(base, cfg)
    for cr in clone_results:
        steps.append(
            {
                "step": "clone_or_remote",
                "command": cr.command,
                "cwd": cr.cwd,
                "ok": cr.ok,
                "stdout": cr.stdout.strip(),
                "stderr": cr.stderr.strip(),
            }
        )
    if not ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "ensure_main_clone failed",
            "steps": steps,
        }

    fr = fetch_all(main_clone)
    steps.append(
        {
            "step": "fetch_all",
            "command": fr.command,
            "cwd": fr.cwd,
            "ok": fr.ok,
            "stdout": fr.stdout.strip(),
            "stderr": fr.stderr.strip(),
        }
    )
    if not fr.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "git fetch --all failed",
            "steps": steps,
        }

    wr = worktree_add(main_clone, new_branch, wt, upstream_ref)
    steps.append(
        {
            "step": "worktree_add",
            "command": wr.command,
            "cwd": wr.cwd,
            "ok": wr.ok,
            "stdout": wr.stdout.strip(),
            "stderr": wr.stderr.strip(),
        }
    )
    if not wr.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "git worktree add failed",
            "steps": steps,
        }

    pr = push_set_upstream(wt, new_branch)
    steps.append(
        {
            "step": "push",
            "command": pr.command,
            "cwd": pr.cwd,
            "ok": pr.ok,
            "stdout": pr.stdout.strip(),
            "stderr": pr.stderr.strip(),
        }
    )
    if not pr.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "git push failed (worktree was created)",
            "main_clone": str(main_clone),
            "worktree": str(wt),
            "steps": steps,
        }

    return {
        "ok": True,
        "repo": repo_key,
        "message": f"Created {cfg.prefix}{new_branch}",
        "main_clone": str(main_clone),
        "worktree": str(wt),
        "new_branch": new_branch,
        "source_branch": source,
        "steps": steps,
    }


def _git_step(step: str, result: GitResult) -> dict:
    return {
        "step": step,
        "command": result.command,
        "cwd": result.cwd,
        "ok": result.ok,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def worktree_refresh(repo_key: str, cfg: RepoConfig) -> dict:
    """
    Sync the main fork clone (default_loc) with upstream default_branch:
    ensure clone exists, checkout default_branch, ``git pull -r upstream``,
    then ``git push --force origin`` that branch (matches branch_*.sh refresh flow).
    """
    base, main_clone = default_paths(cfg)
    branch = cfg.default_branch
    steps: list[dict] = []

    ok, clone_results = ensure_main_clone(base, cfg)
    for cr in clone_results:
        steps.append(_git_step("clone_or_remote", cr))
    if not ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "ensure_main_clone failed",
            "steps": steps,
        }

    co = checkout_branch(main_clone, branch)
    steps.append(_git_step("checkout", co))
    if not co.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": f"git checkout {branch} failed",
            "main_clone": str(main_clone),
            "steps": steps,
        }

    pr = pull_rebase_upstream(main_clone, branch)
    steps.append(_git_step("pull_rebase_upstream", pr))
    if not pr.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "git pull -r upstream failed",
            "main_clone": str(main_clone),
            "default_branch": branch,
            "steps": steps,
        }

    pu = push_origin(main_clone, branch, force=True)
    steps.append(_git_step("push_origin", pu))
    if not pu.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "git push --force origin failed",
            "main_clone": str(main_clone),
            "default_branch": branch,
            "steps": steps,
        }

    return {
        "ok": True,
        "repo": repo_key,
        "message": f"Synced {cfg.default_loc} with upstream/{branch} and pushed to origin",
        "main_clone": str(main_clone),
        "default_branch": branch,
        "steps": steps,
    }
