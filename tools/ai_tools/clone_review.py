#!/usr/bin/env python3
"""Clone a GitHub PR or GitLab MR under ~/git/@REVIEWS and list changed files.

Implements the mechanical checkout steps of the review-changes skill so agents
can use an approved CLI instead of ad-hoc ``gh`` / ``glab`` / ``git`` sequences.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import click

REVIEWS_SUBSTRING = "reviews"
DEFAULT_BRANCH_CANDIDATES = ("main", "master", "devel")

# github.com/OWNER/REPO/pull/123  (optional trailing slash / query)
GITHUB_PR_RE = re.compile(
    r"(?i)^https?://(?P<host>[^/]+)/(?P<repo>[^/]+/[^/]+)/pull/(?P<num>\d+)"
    r"(?:/.*)?$"
)
# gitlab…/GROUP/PROJ/-/merge_requests/123
GITLAB_MR_RE = re.compile(
    r"(?i)^https?://(?P<host>[^/]+)/(?P<repo>.+)/-/merge_requests/(?P<num>\d+)"
    r"(?:/.*)?$"
)
# OWNER/REPO#123 or group/sub/proj!123
SHORTHAND_RE = re.compile(
    r"^(?P<repo>[\w.-]+(?:/[\w.-]+)+)(?P<sep>[#!])(?P<num>\d+)$"
)


class CloneReviewError(RuntimeError):
    """Fatal error preparing a review checkout."""


@dataclass
class ParsedRef:
    """Identifies a PR/MR to clone."""

    platform: str  # github | gitlab
    host: str
    repo: str  # OWNER/REPO or nested GitLab path
    number: int
    kind: str  # pr | mr
    web_url: str | None = None

    @property
    def repo_basename(self) -> str:
        return self.repo.rstrip("/").split("/")[-1]

    def default_dirname(self) -> str:
        return f"{self.repo_basename}-{self.kind}{self.number}"


@dataclass
class ReviewCheckout:
    """Result of cloning/checking out a PR/MR and listing changes."""

    platform: str
    host: str
    repo: str
    number: int
    kind: str
    clone_path: str
    created: bool
    target_branch: str
    base_ref: str
    base_sha: str
    head_sha: str
    head_ref: str
    changed_files: list[str] = field(default_factory=list)
    diff_stat: str = ""
    title: str | None = None
    source_branch: str | None = None
    web_url: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def run_cmd(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise CloneReviewError(f"{' '.join(argv)} failed: {detail}")
    return proc


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def default_reviews_root() -> Path:
    """Return ``$CLONE_REVIEW_ROOT`` or ``~/git/@REVIEWS``."""
    override = os.environ.get("CLONE_REVIEW_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / "git" / "@REVIEWS").resolve()


def assert_reviews_path(path: Path) -> Path:
    """Require *path* (resolved) to contain the literal substring ``reviews``."""
    resolved = path.expanduser().resolve()
    if REVIEWS_SUBSTRING not in resolved.as_posix().lower():
        raise CloneReviewError(
            f"review checkout path must contain '{REVIEWS_SUBSTRING}': {resolved}"
        )
    return resolved


def parse_ref(
    value: str,
    *,
    platform: str | None = None,
    host: str | None = None,
) -> ParsedRef:
    """Parse a PR/MR URL or ``owner/repo#N`` / ``group/proj!N`` shorthand."""
    value = value.strip()
    m = GITHUB_PR_RE.match(value)
    if m:
        return ParsedRef(
            platform="github",
            host=m.group("host").lower(),
            repo=m.group("repo"),
            number=int(m.group("num")),
            kind="pr",
            web_url=value.split("?", 1)[0].rstrip("/"),
        )
    m = GITLAB_MR_RE.match(value)
    if m:
        return ParsedRef(
            platform="gitlab",
            host=m.group("host").lower(),
            repo=m.group("repo").strip("/"),
            number=int(m.group("num")),
            kind="mr",
            web_url=value.split("?", 1)[0].rstrip("/"),
        )
    m = SHORTHAND_RE.match(value)
    if m:
        sep = m.group("sep")
        inferred = "github" if sep == "#" else "gitlab"
        plat = (platform or inferred).lower()
        if plat not in {"github", "gitlab"}:
            raise CloneReviewError(f"unsupported platform: {plat}")
        default_host = (
            host
            or ("github.com" if plat == "github" else "gitlab.com")
        )
        return ParsedRef(
            platform=plat,
            host=default_host.lower(),
            repo=m.group("repo"),
            number=int(m.group("num")),
            kind="pr" if plat == "github" else "mr",
        )
    raise CloneReviewError(
        "unrecognized PR/MR reference "
        f"(expected GitHub/GitLab URL or owner/repo#N / group/proj!N): {value!r}"
    )


def gitlab_env(host: str) -> dict[str, str]:
    """Env overrides so ``glab`` talks to *host*."""
    env: dict[str, str] = {}
    if host and host not in {"gitlab.com"}:
        env["GITLAB_HOST"] = host
    return env


def fetch_metadata(ref: ParsedRef) -> dict[str, str | None]:
    """Best-effort title / branches / default target from gh or glab."""
    meta: dict[str, str | None] = {
        "title": None,
        "source_branch": None,
        "target_branch": None,
        "web_url": ref.web_url,
    }
    if ref.platform == "github":
        if not which("gh"):
            return meta
        proc = run_cmd(
            [
                "gh",
                "pr",
                "view",
                str(ref.number),
                "--repo",
                ref.repo,
                "--json",
                "title,headRefName,baseRefName,url",
            ],
            check=False,
        )
        if proc.returncode != 0:
            return meta
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return meta
        meta["title"] = data.get("title")
        meta["source_branch"] = data.get("headRefName")
        meta["target_branch"] = data.get("baseRefName")
        meta["web_url"] = data.get("url") or meta["web_url"]
        return meta

    if not which("glab"):
        return meta
    proc = run_cmd(
        [
            "glab",
            "mr",
            "view",
            str(ref.number),
            "-R",
            ref.repo,
            "-F",
            "json",
        ],
        env=gitlab_env(ref.host),
        check=False,
    )
    if proc.returncode != 0:
        return meta
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return meta
    meta["title"] = data.get("title")
    meta["source_branch"] = data.get("source_branch")
    meta["target_branch"] = data.get("target_branch")
    meta["web_url"] = data.get("web_url") or meta["web_url"]
    return meta


def resolve_default_branch(cwd: Path, preferred: str | None = None) -> str:
    """Return remote default branch name (without ``origin/``)."""
    if preferred:
        if run_cmd(
            ["git", "rev-parse", "--verify", "--quiet", f"origin/{preferred}"],
            cwd=cwd,
            check=False,
        ).returncode == 0:
            return preferred

    sym = run_cmd(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=cwd,
        check=False,
    )
    if sym.returncode == 0 and sym.stdout.strip():
        ref = sym.stdout.strip()
        # refs/remotes/origin/main → main
        parts = ref.split("/")
        if len(parts) >= 4:
            return parts[-1]

    for name in DEFAULT_BRANCH_CANDIDATES:
        if run_cmd(
            ["git", "rev-parse", "--verify", "--quiet", f"origin/{name}"],
            cwd=cwd,
            check=False,
        ).returncode == 0:
            return name

    raise CloneReviewError(
        "could not determine default branch "
        f"(tried preferred={preferred!r} and {DEFAULT_BRANCH_CANDIDATES})"
    )


def ensure_remote_branch(cwd: Path, branch: str) -> None:
    run_cmd(
        ["git", "fetch", "origin", branch],
        cwd=cwd,
        check=False,
    )


def compute_changes(
    cwd: Path,
    *,
    target_branch: str | None = None,
) -> tuple[str, str, str, list[str], str]:
    """Return ``(base_ref, base_sha, head_sha, changed_files, diff_stat)``."""
    branch = resolve_default_branch(cwd, preferred=target_branch)
    ensure_remote_branch(cwd, branch)
    base_ref = f"origin/{branch}"
    mb = run_cmd(["git", "merge-base", "HEAD", base_ref], cwd=cwd)
    base_sha = mb.stdout.strip()
    head = run_cmd(["git", "rev-parse", "HEAD"], cwd=cwd)
    head_sha = head.stdout.strip()
    names = run_cmd(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        cwd=cwd,
    )
    changed = [line for line in names.stdout.splitlines() if line.strip()]
    stat = run_cmd(
        ["git", "diff", "--stat", f"{base_sha}..{head_sha}"],
        cwd=cwd,
    )
    return base_ref, base_sha, head_sha, changed, stat.stdout.strip()


def _git_toplevel(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    proc = run_cmd(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


def _remote_matches(cwd: Path, ref: ParsedRef) -> bool:
    proc = run_cmd(
        ["git", "remote", "get-url", "origin"],
        cwd=cwd,
        check=False,
    )
    if proc.returncode != 0:
        return False
    url = proc.stdout.strip().lower().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    repo_tail = ref.repo.lower()
    basename = ref.repo_basename.lower()
    return repo_tail in url or url.endswith(f"/{basename}")


def clone_github(ref: ParsedRef, dest: Path, *, created: bool) -> None:
    if not which("gh"):
        raise CloneReviewError("gh not found on PATH (required for GitHub PRs)")
    if created:
        run_cmd(["gh", "repo", "clone", ref.repo, str(dest)])
    else:
        run_cmd(["git", "fetch", "origin"], cwd=dest, check=False)
    run_cmd(["gh", "pr", "checkout", str(ref.number)], cwd=dest)


def clone_gitlab(ref: ParsedRef, dest: Path, *, created: bool) -> None:
    if not which("glab"):
        raise CloneReviewError("glab not found on PATH (required for GitLab MRs)")
    env = gitlab_env(ref.host)
    if created:
        run_cmd(
            ["glab", "repo", "clone", ref.repo, str(dest)],
            env=env,
        )
    else:
        run_cmd(["git", "fetch", "origin"], cwd=dest, env=env, check=False)
    run_cmd(
        ["glab", "mr", "checkout", str(ref.number)],
        cwd=dest,
        env=env,
    )


def prepare_review(
    reference: str,
    *,
    reviews_root: Path | None = None,
    dirname: str | None = None,
    platform: str | None = None,
    host: str | None = None,
    refresh: bool = True,
) -> ReviewCheckout:
    """Clone (or refresh) a PR/MR under the reviews root and list changed files.

    Destinations must resolve under a path containing ``reviews``. Existing
    checkouts are reused when the origin remote matches; otherwise an error is
    raised (no silent overwrite of unrelated repos).
    """
    ref = parse_ref(reference, platform=platform, host=host)
    root = assert_reviews_path(reviews_root or default_reviews_root())
    root.mkdir(parents=True, exist_ok=True)

    dest = assert_reviews_path(root / (dirname or ref.default_dirname()))
    notes: list[str] = []
    created = False

    existing = _git_toplevel(dest)
    if existing is not None:
        if existing.resolve() != dest.resolve():
            raise CloneReviewError(
                f"path is inside another git worktree ({existing}), not {dest}"
            )
        if not _remote_matches(dest, ref):
            raise CloneReviewError(
                f"existing clone at {dest} does not look like {ref.repo}; "
                "refuse to overwrite — pick --name or remove the directory"
            )
        if not refresh:
            notes.append("reused existing clone without refresh")
        else:
            notes.append("refreshed existing clone")
    elif dest.exists():
        if any(dest.iterdir()):
            raise CloneReviewError(
                f"destination exists and is not an empty git clone: {dest}"
            )
        created = True
    else:
        created = True

    meta = fetch_metadata(ref)
    if ref.platform == "github":
        if created or refresh:
            clone_github(ref, dest, created=created)
    elif ref.platform == "gitlab":
        if created or refresh:
            clone_gitlab(ref, dest, created=created)
    else:
        raise CloneReviewError(f"unsupported platform: {ref.platform}")

    head_ref_proc = run_cmd(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=dest,
        check=False,
    )
    head_ref = head_ref_proc.stdout.strip() if head_ref_proc.returncode == 0 else "HEAD"

    base_ref, base_sha, head_sha, changed, stat = compute_changes(
        dest,
        target_branch=meta.get("target_branch"),
    )

    return ReviewCheckout(
        platform=ref.platform,
        host=ref.host,
        repo=ref.repo,
        number=ref.number,
        kind=ref.kind,
        clone_path=str(dest),
        created=created,
        target_branch=(meta.get("target_branch") or base_ref.split("/", 1)[-1] or ""),
        base_ref=base_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        head_ref=head_ref,
        changed_files=changed,
        diff_stat=stat,
        title=meta.get("title"),
        source_branch=meta.get("source_branch"),
        web_url=meta.get("web_url") or ref.web_url,
        notes=notes,
    )


def format_report(result: ReviewCheckout, *, quiet: bool = False) -> str:
    lines: list[str] = [
        f"platform: {result.platform}",
        f"repo: {result.repo}",
        f"{result.kind}: {result.number}",
        f"clone_path: {result.clone_path}",
        f"created: {result.created}",
        f"base_ref: {result.base_ref}",
        f"base_sha: {result.base_sha}",
        f"head_sha: {result.head_sha}",
        f"head_ref: {result.head_ref}",
        f"changed_files: {len(result.changed_files)}",
    ]
    if result.title:
        lines.append(f"title: {result.title}")
    if result.source_branch:
        lines.append(f"source_branch: {result.source_branch}")
    if result.target_branch:
        lines.append(f"target_branch: {result.target_branch}")
    if result.web_url:
        lines.append(f"web_url: {result.web_url}")
    for note in result.notes:
        lines.append(f"note: {note}")
    if not quiet:
        lines.append("files:")
        for path in result.changed_files:
            lines.append(f"  {path}")
        if result.diff_stat:
            lines.append("diff_stat:")
            for line in result.diff_stat.splitlines():
                lines.append(f"  {line}")
    return "\n".join(lines) + "\n"


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("reference")
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help=(
        "Reviews parent directory (default: $CLONE_REVIEW_ROOT or "
        "~/git/@REVIEWS); must contain 'reviews'"
    ),
)
@click.option(
    "--name",
    default=None,
    help="Clone directory name under --root (default: <repo>-prN / -mrN)",
)
@click.option(
    "--platform",
    type=click.Choice(["github", "gitlab"], case_sensitive=False),
    default=None,
    help="Force platform for shorthand references",
)
@click.option(
    "--host",
    default=None,
    help="API/git host for shorthand (e.g. gitlab.cee.redhat.com)",
)
@click.option(
    "--no-refresh",
    is_flag=True,
    help="If clone exists, only recompute the diff (skip fetch/checkout)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Omit file list and diffstat from text output",
)
def cli(
    reference: str,
    root: Path | None,
    name: str | None,
    platform: str | None,
    host: str | None,
    no_refresh: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Clone a GitHub PR or GitLab MR under ~/git/@REVIEWS.

    Lists files changed vs the target/default branch. REFERENCE is a PR/MR
    URL, or shorthand owner/repo#N (GitHub) / group/proj!N (GitLab).
    """
    try:
        result = prepare_review(
            reference,
            reviews_root=root,
            dirname=name,
            platform=platform.lower() if platform else None,
            host=host,
            refresh=not no_refresh,
        )
    except CloneReviewError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        click.echo(format_report(result, quiet=quiet), nl=False)


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="clone-review", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
