#!/usr/bin/env python3
"""Check whether a local git tip is already present on an upstream remote ref.

Mirrors the practical checks used for topic worktrees: exact ancestor,
``git cherry`` for the tip and for the whole branch, optional tip subject
search on upstream, and optional tip patch-id scan.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

UPSTREAM_FALLBACKS = (
    "upstream/master",
    "upstream/main",
    "upstream/devel",
    "origin/master",
    "origin/main",
)


@dataclass
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    command: list[str]


@dataclass
class MergeCheckResult:
    """Outcome of an upstream-merge check for one tip."""

    merged: bool
    merge_status: str
    repo: str
    ref: str
    tip: str
    tip_subject: str
    upstream_ref: str
    fetched: bool = False
    ancestor: bool = False
    tip_cherry: str = "unknown"
    branch_cherry_pending: int | None = None
    branch_cherry_equivalent: int | None = None
    subject_hits: list[str] = field(default_factory=list)
    tip_patch_id: str | None = None
    tip_patch_id_match: str | None = None
    origin_branch: str | None = None
    origin_branch_present: bool | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class IsMergedError(RuntimeError):
    """Fatal error resolving the repository or refs."""


def run_git(cwd: Path, args: Sequence[str]) -> GitResult:
    cmd = ["git", *args]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return GitResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
        command=cmd,
    )


def require_git(cwd: Path, args: Sequence[str]) -> GitResult:
    result = run_git(cwd, args)
    if not result.ok:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise IsMergedError(f"git {' '.join(args)} failed: {detail}")
    return result


def resolve_git_dir(path: Path) -> Path:
    """Return the top-level work tree for *path* (file or directory)."""
    path = path.expanduser().resolve()
    probe = path if path.is_dir() else path.parent
    result = run_git(probe, ["rev-parse", "--show-toplevel"])
    if not result.ok:
        raise IsMergedError(f"not a git repository: {path}")
    return Path(result.stdout.strip())


def ref_exists(cwd: Path, ref: str) -> bool:
    return run_git(cwd, ["rev-parse", "--verify", "--quiet", ref]).ok


def resolve_upstream_ref(cwd: Path, upstream: str | None) -> str:
    if upstream:
        if not ref_exists(cwd, upstream):
            raise IsMergedError(f"upstream ref not found: {upstream}")
        return upstream

    for remote in ("upstream", "origin"):
        sym = run_git(cwd, ["symbolic-ref", f"refs/remotes/{remote}/HEAD"])
        if sym.ok and sym.stdout.strip():
            ref = sym.stdout.strip().replace("refs/remotes/", "")
            if ref_exists(cwd, ref):
                return ref

    for candidate in UPSTREAM_FALLBACKS:
        if ref_exists(cwd, candidate):
            return candidate

    raise IsMergedError(
        "could not resolve upstream ref (tried upstream/*, origin/*, pass --upstream)",
    )


def resolve_tip(cwd: Path, ref: str | None) -> tuple[str, str, str]:
    """Return ``(ref_name, tip_sha, subject)``."""
    name = ref or "HEAD"
    tip = require_git(cwd, ["rev-parse", name]).stdout.strip()
    subject = require_git(
        cwd,
        ["log", "-1", "--format=%s", tip],
    ).stdout.strip()
    if ref is None:
        branch = run_git(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
        if branch.ok and branch.stdout.strip() not in ("", "HEAD"):
            name = branch.stdout.strip()
    return name, tip, subject


def tip_parent(cwd: Path, tip: str) -> str | None:
    parent = run_git(cwd, ["rev-parse", f"{tip}^"])
    if parent.ok:
        return parent.stdout.strip()
    return None


def cherry_lines(cwd: Path, upstream_ref: str, *rev_range: str) -> GitResult:
    return run_git(cwd, ["cherry", upstream_ref, *rev_range])


def classify_tip_cherry(cwd: Path, upstream_ref: str, tip: str) -> str:
    """Return equivalent | pending | failed for the single tip commit.

    ``git cherry <upstream> <head> [<limit>]`` lists commits on *head* not in
    upstream, optionally only those after *limit*. Pass head=tip and
    limit=parent so only the tip commit is considered.
    """
    parent = tip_parent(cwd, tip)
    if parent:
        result = cherry_lines(cwd, upstream_ref, tip, parent)
    else:
        result = cherry_lines(cwd, upstream_ref, tip)
    if not result.ok:
        return "failed"
    pending = [ln for ln in result.stdout.splitlines() if ln.startswith("+")]
    equivalent = [ln for ln in result.stdout.splitlines() if ln.startswith("-")]
    if pending:
        return "pending"
    if equivalent:
        return "equivalent"
    if run_git(cwd, ["merge-base", "--is-ancestor", tip, upstream_ref]).ok:
        return "equivalent"
    return "pending"


def branch_cherry_counts(
    cwd: Path,
    upstream_ref: str,
    tip: str,
) -> tuple[int | None, int | None, str | None]:
    result = cherry_lines(cwd, upstream_ref, tip)
    if not result.ok:
        return None, None, (result.stderr or result.stdout).strip() or "cherry failed"
    pending = sum(1 for ln in result.stdout.splitlines() if ln.startswith("+"))
    equivalent = sum(1 for ln in result.stdout.splitlines() if ln.startswith("-"))
    return pending, equivalent, None


def subject_search_terms(subject: str) -> list[str]:
    """Build grep terms from a commit subject (tickets + meaningful phrase)."""
    terms: list[str] = []
    for match in re.finditer(
        r"\b(?:SSSD|RHEL|RHELTEST|BZ|CVE)-\d+\b",
        subject,
        flags=re.IGNORECASE,
    ):
        terms.append(match.group(0))
    # Drop conventional-commit prefix for a looser subject search
    stripped = re.sub(
        r"^(?:feat|fix|chore|docs|refactor|test|tests)\s*:\s*",
        "",
        subject,
        flags=re.IGNORECASE,
    ).strip()
    if stripped and stripped not in terms:
        terms.append(stripped)
    if subject and subject not in terms:
        terms.append(subject)
    # preserve order, unique
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def search_subject_on_upstream(
    cwd: Path,
    upstream_ref: str,
    subject: str,
    *,
    limit: int = 20,
) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for term in subject_search_terms(subject):
        result = run_git(
            cwd,
            [
                "log",
                upstream_ref,
                f"--grep={term}",
                "-i",
                "--oneline",
                f"-n{limit}",
            ],
        )
        if not result.ok:
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            hits.append(line)
    return hits[:limit]


def patch_id_for(cwd: Path, commit: str) -> str | None:
    show = run_git(cwd, ["show", commit])
    if not show.ok or not show.stdout:
        return None
    proc = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=show.stdout,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.split()[0]


def find_patch_id_match(
    cwd: Path,
    upstream_ref: str,
    tip_patch_id: str,
    *,
    limit: int = 800,
) -> str | None:
    listed = run_git(cwd, ["rev-list", upstream_ref, f"-n{limit}"])
    if not listed.ok:
        return None
    for sha in listed.stdout.splitlines():
        sha = sha.strip()
        if not sha:
            continue
        pid = patch_id_for(cwd, sha)
        if pid == tip_patch_id:
            return sha
    return None


def check_origin_branch(cwd: Path, branch: str) -> tuple[str | None, bool | None]:
    if not branch or branch == "HEAD":
        return None, None
    if not run_git(cwd, ["remote", "get-url", "origin"]).ok:
        return None, None
    result = run_git(cwd, ["ls-remote", "--heads", "origin", branch])
    if not result.ok:
        return f"origin/{branch}", None
    # ls-remote prints "<sha>\trefs/heads/<branch>"
    present = bool(result.stdout.strip())
    return f"origin/{branch}", present


def check_is_merged(
    repo: Path,
    *,
    ref: str | None = None,
    upstream: str | None = None,
    fetch: bool = False,
    deep: bool = False,
    deep_limit: int = 800,
    check_origin: bool = True,
) -> MergeCheckResult:
    """Return merge status for *ref* (default HEAD) against upstream."""
    cwd = resolve_git_dir(repo)
    notes: list[str] = []
    fetched = False

    if fetch:
        for remote in ("upstream", "origin"):
            if run_git(cwd, ["remote", "get-url", remote]).ok:
                fr = run_git(cwd, ["fetch", remote])
                if not fr.ok:
                    notes.append(
                        f"fetch {remote} failed: "
                        f"{(fr.stderr or fr.stdout).strip() or fr.returncode}",
                    )
                else:
                    fetched = True

    upstream_ref = resolve_upstream_ref(cwd, upstream)
    ref_name, tip, subject = resolve_tip(cwd, ref)

    ancestor = run_git(
        cwd,
        ["merge-base", "--is-ancestor", tip, upstream_ref],
    ).ok
    tip_cherry = classify_tip_cherry(cwd, upstream_ref, tip)
    pending, equivalent, cherry_err = branch_cherry_counts(cwd, upstream_ref, tip)
    if cherry_err:
        notes.append(f"branch cherry: {cherry_err}")

    subject_hits = search_subject_on_upstream(cwd, upstream_ref, subject)

    tip_pid = None
    tip_match = None
    if deep:
        tip_pid = patch_id_for(cwd, tip)
        if tip_pid:
            tip_match = find_patch_id_match(
                cwd,
                upstream_ref,
                tip_pid,
                limit=deep_limit,
            )
        else:
            notes.append("could not compute tip patch-id")

    origin_name, origin_present = (None, None)
    if check_origin:
        origin_name, origin_present = check_origin_branch(cwd, ref_name)

    if ancestor:
        status = "exact"
        merged = True
    elif tip_cherry == "equivalent" or tip_match:
        status = "cherry"
        merged = True
        if tip_match and tip_cherry != "equivalent":
            notes.append(f"tip patch-id matched {tip_match[:12]}")
    elif pending == 0 and equivalent is not None and equivalent > 0:
        status = "cherry"
        merged = True
    else:
        status = "not_merged"
        merged = False
        if subject_hits:
            notes.append(
                "upstream log subject hits found but tip patch not confirmed; "
                "review hits before treating as merged",
            )

    return MergeCheckResult(
        merged=merged,
        merge_status=status,
        repo=str(cwd),
        ref=ref_name,
        tip=tip,
        tip_subject=subject,
        upstream_ref=upstream_ref,
        fetched=fetched,
        ancestor=ancestor,
        tip_cherry=tip_cherry,
        branch_cherry_pending=pending,
        branch_cherry_equivalent=equivalent,
        subject_hits=subject_hits,
        tip_patch_id=tip_pid,
        tip_patch_id_match=tip_match,
        origin_branch=origin_name,
        origin_branch_present=origin_present,
        notes=notes,
    )


def format_human(result: MergeCheckResult) -> str:
    if result.error:
        return f"error: {result.error}"

    lines = [
        f"repo: {result.repo}",
        f"ref: {result.ref}",
        f"tip: {result.tip[:12]} {result.tip_subject}",
        f"upstream: {result.upstream_ref}",
        f"merged: {'yes' if result.merged else 'no'} ({result.merge_status})",
        f"ancestor: {'yes' if result.ancestor else 'no'}",
        f"tip_cherry: {result.tip_cherry}",
    ]
    if result.branch_cherry_pending is not None:
        lines.append(
            "branch_cherry: "
            f"{result.branch_cherry_pending} pending, "
            f"{result.branch_cherry_equivalent or 0} equivalent",
        )
    if result.subject_hits:
        lines.append("subject_hits:")
        for hit in result.subject_hits:
            lines.append(f"  - {hit}")
    else:
        lines.append("subject_hits: (none)")
    if result.tip_patch_id_match:
        lines.append(f"tip_patch_id_match: {result.tip_patch_id_match}")
    elif result.tip_patch_id:
        lines.append("tip_patch_id_match: (none)")
    if result.origin_branch:
        if result.origin_branch_present is None:
            state = "unknown"
        else:
            state = "present" if result.origin_branch_present else "gone"
        lines.append(f"origin_branch: {result.origin_branch} ({state})")
    if result.fetched:
        lines.append("fetched: yes")
    for note in result.notes:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether a local git tip is already on upstream "
            "(exact ancestor, tip/branch cherry, subject hits, optional patch-id)."
        ),
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        type=Path,
        help="Git repository or worktree path (default: current directory)",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Local ref to check (default: current branch / HEAD)",
    )
    parser.add_argument(
        "--upstream",
        default=None,
        help="Upstream ref (default: upstream/HEAD, else upstream/master|main, …)",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="git fetch upstream/origin before checking",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Scan recent upstream commits for a tip patch-id match",
    )
    parser.add_argument(
        "--deep-limit",
        type=int,
        default=800,
        help="Max upstream commits to scan with --deep (default: 800)",
    )
    parser.add_argument(
        "--no-origin",
        action="store_true",
        help="Skip checking whether origin still has the branch",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = check_is_merged(
            args.repo,
            ref=args.ref,
            upstream=args.upstream,
            fetch=args.fetch,
            deep=args.deep,
            deep_limit=args.deep_limit,
            check_origin=not args.no_origin,
        )
    except IsMergedError as exc:
        err = MergeCheckResult(
            merged=False,
            merge_status="error",
            repo=str(args.repo),
            ref=args.ref or "HEAD",
            tip="",
            tip_subject="",
            upstream_ref=args.upstream or "",
            error=str(exc),
        )
        if args.json:
            print(json.dumps(err.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_human(result))

    return 0 if result.merged else 1


if __name__ == "__main__":
    raise SystemExit(main())
