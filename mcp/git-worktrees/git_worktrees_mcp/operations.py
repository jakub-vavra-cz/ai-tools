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


def _worktree_list_porcelain(main_clone: Path) -> GitResult:
    return _run(main_clone, ["git", "worktree", "list", "--porcelain"])


def find_worktree_for_branch(main_clone: Path, branch: str) -> Path | None:
    """Return the worktree path that has ``branch`` checked out, if any."""
    listed = _worktree_list_porcelain(main_clone)
    if not listed.ok:
        return None
    current: Path | None = None
    want = f"refs/heads/{branch}"
    for line in listed.stdout.splitlines():
        if line.startswith("worktree "):
            current = Path(line[len("worktree ") :])
        elif line.startswith("branch ") and current is not None:
            if line[len("branch ") :] == want:
                return current
            current = None
        elif line == "":
            current = None
    return None


def _ref_exists(cwd: Path, ref: str) -> bool:
    return _run(cwd, ["git", "rev-parse", "--verify", "--quiet", ref]).ok


def _resolve_upstream_ref(main_clone: Path, default_branch: str) -> str | None:
    candidate = f"upstream/{default_branch}"
    if _ref_exists(main_clone, candidate):
        return candidate
    sym = _run(main_clone, ["git", "symbolic-ref", "refs/remotes/upstream/HEAD"])
    if sym.ok and sym.stdout.strip():
        return sym.stdout.strip().replace("refs/remotes/", "")
    for name in ("upstream/master", "upstream/main", "upstream/devel"):
        if _ref_exists(main_clone, name):
            return name
    return None


def _commit_merged_upstream(main_clone: Path, commit: str, upstream_ref: str) -> tuple[bool, str, dict]:
    """
    True if ``commit`` is an ancestor of upstream_ref or all patches are
    cherry-equivalent already in upstream (``git cherry`` has no ``+`` lines).
    """
    details: dict = {"upstream_ref": upstream_ref, "commit": commit}
    ancestor = _run(
        main_clone,
        ["git", "merge-base", "--is-ancestor", commit, upstream_ref],
    )
    details["ancestor"] = ancestor.ok
    if ancestor.ok:
        details["merge_status"] = "exact"
        return True, "exact", details

    cherry = _run(main_clone, ["git", "cherry", upstream_ref, commit])
    details["cherry_ok"] = cherry.ok
    details["cherry_stdout"] = cherry.stdout.strip()
    if not cherry.ok:
        return False, "cherry_failed", details
    pending = [ln for ln in cherry.stdout.splitlines() if ln.startswith("+")]
    details["cherry_pending"] = len(pending)
    if not pending:
        details["merge_status"] = "cherry"
        return True, "cherry", details
    details["merge_status"] = "not_merged"
    return False, "not_merged", details


def _status_porcelain(cwd: Path) -> GitResult:
    return _run(cwd, ["git", "status", "--porcelain"])


def cleanup_worktree(
    repo_key: str,
    cfg: RepoConfig,
    branch: str,
    *,
    force: bool = False,
) -> dict:
    """
    Remove a topic worktree and delete its branch on the fork when the work is
    already present upstream.

    Stops if commits are not merged into ``upstream/<default_branch>`` (exact
    ancestor or cherry-equivalent). Warns and stops on uncommitted changes
    unless ``force`` is True (force does not skip the merge check).
    """
    base, main_clone = default_paths(cfg)
    branch = branch.strip()
    steps: list[dict] = []
    warnings: list[str] = []

    if not branch:
        return {"ok": False, "repo": repo_key, "error": "branch is empty"}

    if branch == cfg.default_branch:
        return {
            "ok": False,
            "repo": repo_key,
            "error": (
                f"Refusing to clean up default branch {branch!r} "
                f"(main clone {cfg.default_loc})"
            ),
        }

    expected_wt = worktree_directory(cfg, branch)
    if expected_wt.resolve() == main_clone.resolve():
        return {
            "ok": False,
            "repo": repo_key,
            "error": "Refusing to remove the main clone directory",
        }

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

    if not main_clone.is_dir():
        return {
            "ok": False,
            "repo": repo_key,
            "error": f"Main clone missing: {main_clone}",
            "steps": steps,
        }

    fr = fetch_all(main_clone)
    steps.append(_git_step("fetch_all", fr))
    if not fr.ok:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "git fetch --all failed",
            "main_clone": str(main_clone),
            "steps": steps,
        }

    wt = find_worktree_for_branch(main_clone, branch)
    if wt is None and expected_wt.is_dir():
        wt = expected_wt

    commit: str | None = None
    if wt is not None and wt.is_dir():
        rev = _run(wt, ["git", "rev-parse", "HEAD"])
        steps.append(_git_step("rev_parse_worktree", rev))
        if rev.ok:
            commit = rev.stdout.strip()
    if commit is None and _ref_exists(main_clone, f"refs/heads/{branch}"):
        rev = _run(main_clone, ["git", "rev-parse", f"refs/heads/{branch}"])
        steps.append(_git_step("rev_parse_local_branch", rev))
        if rev.ok:
            commit = rev.stdout.strip()
    if commit is None and _ref_exists(main_clone, f"refs/remotes/origin/{branch}"):
        rev = _run(main_clone, ["git", "rev-parse", f"refs/remotes/origin/{branch}"])
        steps.append(_git_step("rev_parse_origin_branch", rev))
        if rev.ok:
            commit = rev.stdout.strip()

    if commit is None:
        return {
            "ok": False,
            "repo": repo_key,
            "error": (
                f"No worktree, local branch, or origin/{branch} found for {branch!r}"
            ),
            "main_clone": str(main_clone),
            "worktree": str(wt) if wt else str(expected_wt),
            "branch": branch,
            "steps": steps,
        }

    upstream_ref = _resolve_upstream_ref(main_clone, cfg.default_branch)
    if upstream_ref is None:
        return {
            "ok": False,
            "repo": repo_key,
            "error": "No upstream/* ref found after fetch",
            "main_clone": str(main_clone),
            "branch": branch,
            "steps": steps,
        }

    merged, how, merge_details = _commit_merged_upstream(
        main_clone, commit, upstream_ref
    )
    if not merged:
        tip = _run(main_clone, ["git", "log", "-1", "--format=%h %s", commit])
        return {
            "ok": False,
            "repo": repo_key,
            "error": (
                f"Branch {branch!r} is not merged into {upstream_ref} "
                f"(status={how}); refusing cleanup"
            ),
            "main_clone": str(main_clone),
            "worktree": str(wt) if wt else None,
            "branch": branch,
            "merge": merge_details,
            "tip": tip.stdout.strip() if tip.ok else commit,
            "steps": steps,
        }

    dirty = False
    dirty_porcelain = ""
    if wt is not None and wt.is_dir():
        st = _status_porcelain(wt)
        steps.append(_git_step("status_porcelain", st))
        dirty_porcelain = st.stdout.strip()
        dirty = bool(dirty_porcelain)
        if dirty:
            msg = (
                f"Uncommitted changes in {wt}:\n{dirty_porcelain}"
            )
            if force:
                warnings.append(msg + " (--force: proceeding anyway)")
            else:
                return {
                    "ok": False,
                    "repo": repo_key,
                    "error": (
                        "Uncommitted changes present; "
                        "re-run with force=True / --force to ignore"
                    ),
                    "warning": msg,
                    "main_clone": str(main_clone),
                    "worktree": str(wt),
                    "branch": branch,
                    "merge": merge_details,
                    "merge_how": how,
                    "dirty": True,
                    "steps": steps,
                }

    # Delete fork branch on origin (ok if already absent).
    ls = _run(main_clone, ["git", "ls-remote", "--heads", "origin", branch])
    steps.append(_git_step("ls_remote_origin", ls))
    remote_present = False
    if ls.ok:
        suffix = f"refs/heads/{branch}"
        for line in ls.stdout.splitlines():
            # ls-remote: "<sha><TAB>refs/heads/<branch>"
            parts = line.split()
            if len(parts) >= 2 and parts[-1] == suffix:
                remote_present = True
                break
    if remote_present:
        # Prefer deleting from main clone so we do not need the worktree.
        dr = _run(main_clone, ["git", "push", "origin", "--delete", branch])
        steps.append(_git_step("push_delete_origin", dr))
        if not dr.ok:
            err_l = (dr.stderr + dr.stdout).lower()
            if "remote ref does not exist" in err_l or "does not exist" in err_l:
                warnings.append(
                    f"origin/{branch} already absent while deleting"
                )
            else:
                return {
                    "ok": False,
                    "repo": repo_key,
                    "error": f"git push origin --delete {branch} failed",
                    "main_clone": str(main_clone),
                    "worktree": str(wt) if wt else None,
                    "branch": branch,
                    "merge_how": how,
                    "warnings": warnings,
                    "steps": steps,
                }
    else:
        warnings.append(f"origin/{branch} not present (nothing to delete on fork)")

    if wt is not None and wt.is_dir():
        rm_cmd = ["git", "worktree", "remove"]
        if force or dirty:
            rm_cmd.append("--force")
        rm_cmd.append(str(wt))
        wr = _run(main_clone, rm_cmd)
        steps.append(_git_step("worktree_remove", wr))
        if not wr.ok:
            return {
                "ok": False,
                "repo": repo_key,
                "error": "git worktree remove failed",
                "main_clone": str(main_clone),
                "worktree": str(wt),
                "branch": branch,
                "merge_how": how,
                "warnings": warnings,
                "steps": steps,
            }

    if _ref_exists(main_clone, f"refs/heads/{branch}"):
        # -D: topic branch may look unmerged vs local default even when upstream has it.
        br = _run(main_clone, ["git", "branch", "-D", branch])
        steps.append(_git_step("branch_delete", br))
        if not br.ok:
            return {
                "ok": False,
                "repo": repo_key,
                "error": f"git branch -D {branch} failed",
                "main_clone": str(main_clone),
                "branch": branch,
                "merge_how": how,
                "warnings": warnings,
                "steps": steps,
            }

    prune = _run(main_clone, ["git", "worktree", "prune"])
    steps.append(_git_step("worktree_prune", prune))

    return {
        "ok": True,
        "repo": repo_key,
        "message": (
            f"Cleaned up branch {branch!r} "
            f"(merged into {upstream_ref} as {how})"
        ),
        "main_clone": str(main_clone),
        "worktree": str(wt) if wt else str(expected_wt),
        "branch": branch,
        "merge_how": how,
        "merge": merge_details,
        "dirty_ignored": dirty and force,
        "warnings": warnings,
        "steps": steps,
    }
