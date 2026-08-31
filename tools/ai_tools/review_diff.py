#!/usr/bin/env python3
"""Fetch a GitHub PR or GitLab MR diff for review.

Uses ``gh pr diff`` / ``glab mr diff`` when no local checkout exists, or
``git diff`` from an existing ``clone-review`` tree under ``~/git/@REVIEWS``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import click

from ai_tools.clone_review import (
    CloneReviewError,
    assert_reviews_path,
    compute_changes,
    default_reviews_root,
    expected_clone_path,
    fetch_metadata,
    gitlab_env,
    parse_ref,
    run_cmd,
    which,
)

DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/")


@dataclass
class ReviewDiff:
    """PR/MR diff metadata and patch text."""

    platform: str
    host: str
    repo: str
    number: int
    kind: str
    source: str  # api | clone
    clone_path: str | None
    base_ref: str
    base_sha: str
    head_sha: str
    changed_files: list[str]
    diff_stat: str
    diff: str
    title: str | None = None
    web_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _is_git_clone(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def changed_files_from_patch(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        match = DIFF_GIT_RE.match(line)
        if match:
            files.append(match.group(1))
    return sorted(set(files))


def stat_from_patch(patch: str, file_count: int) -> str:
    adds = dels = 0
    for line in patch.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            adds += 1
        elif line.startswith("-"):
            dels += 1
    return f"{file_count} files changed, {adds} insertions(+), {dels} deletions(-)"


def diff_from_api(ref) -> str:
    if ref.platform == "github":
        if not which("gh"):
            raise CloneReviewError("gh not found on PATH (required for GitHub PR diff)")
        proc = run_cmd(
            ["gh", "pr", "diff", str(ref.number), "--repo", ref.repo],
            check=True,
        )
        return proc.stdout

    if not which("glab"):
        raise CloneReviewError("glab not found on PATH (required for GitLab MR diff)")
    proc = run_cmd(
        ["glab", "mr", "diff", str(ref.number), "-R", ref.repo],
        env=gitlab_env(ref.host),
        check=True,
    )
    return proc.stdout


def diff_from_clone(
    clone_path: Path,
    *,
    target_branch: str | None = None,
    include_patch: bool = True,
) -> tuple[str, str, str, list[str], str, str]:
    base_ref, base_sha, head_sha, changed, stat = compute_changes(
        clone_path,
        target_branch=target_branch,
    )
    patch = ""
    if include_patch:
        proc = run_cmd(
            ["git", "diff", f"{base_sha}..{head_sha}"],
            cwd=clone_path,
        )
        patch = proc.stdout
    return base_ref, base_sha, head_sha, changed, stat, patch


def prepare_review_diff(
    reference: str,
    *,
    reviews_root: Path | None = None,
    dirname: str | None = None,
    platform: str | None = None,
    host: str | None = None,
    clone_path: Path | None = None,
    prefer_clone: bool = True,
    include_patch: bool = True,
) -> ReviewDiff:
    ref = parse_ref(reference, platform=platform, host=host)
    meta = fetch_metadata(ref)
    target_branch = meta.get("target_branch")

    resolved_clone: Path | None = None
    if clone_path is not None:
        resolved_clone = assert_reviews_path(clone_path)
        if not _is_git_clone(resolved_clone):
            raise CloneReviewError(f"not a git clone: {resolved_clone}")
    elif prefer_clone:
        candidate = expected_clone_path(ref, reviews_root=reviews_root, dirname=dirname)
        if _is_git_clone(candidate):
            resolved_clone = candidate

    if resolved_clone is not None:
        base_ref, base_sha, head_sha, changed, stat, patch = diff_from_clone(
            resolved_clone,
            target_branch=target_branch,
            include_patch=include_patch,
        )
        return ReviewDiff(
            platform=ref.platform,
            host=ref.host,
            repo=ref.repo,
            number=ref.number,
            kind=ref.kind,
            source="clone",
            clone_path=str(resolved_clone),
            base_ref=base_ref,
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=changed,
            diff_stat=stat,
            diff=patch,
            title=meta.get("title"),
            web_url=meta.get("web_url") or ref.web_url,
        )

    patch = diff_from_api(ref)
    changed = changed_files_from_patch(patch)
    stat = stat_from_patch(patch, len(changed))
    if not include_patch:
        patch = ""
    return ReviewDiff(
        platform=ref.platform,
        host=ref.host,
        repo=ref.repo,
        number=ref.number,
        kind=ref.kind,
        source="api",
        clone_path=None,
        base_ref=f"origin/{target_branch}" if target_branch else "",
        base_sha="",
        head_sha="",
        changed_files=changed,
        diff_stat=stat,
        diff=patch,
        title=meta.get("title"),
        web_url=meta.get("web_url") or ref.web_url,
    )


def format_report(
    result: ReviewDiff,
    *,
    names_only: bool = False,
    stat_only: bool = False,
) -> str:
    if names_only:
        return "\n".join(result.changed_files) + ("\n" if result.changed_files else "")
    if stat_only:
        return result.diff_stat + ("\n" if result.diff_stat else "")
    return result.diff


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("reference")
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Reviews parent directory (default: $CLONE_REVIEW_ROOT or ~/git/@REVIEWS)",
)
@click.option(
    "--name",
    default=None,
    help="Clone directory name under --root (default: <repo>-prN / -mrN)",
)
@click.option(
    "--clone-path",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=None,
    help="Use this existing clone-review checkout (must contain 'reviews')",
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
    "--api-only",
    is_flag=True,
    help="Fetch diff via gh/glab even when a local clone exists",
)
@click.option(
    "--name-only",
    is_flag=True,
    help="Print changed file paths only",
)
@click.option(
    "--stat",
    "stat_only",
    is_flag=True,
    help="Print diffstat summary only",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Write patch output to FILE (default: stdout)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON (includes full diff unless --name-only/--stat)",
)
def cli(
    reference: str,
    root: Path | None,
    name: str | None,
    clone_path: Path | None,
    platform: str | None,
    host: str | None,
    api_only: bool,
    name_only: bool,
    stat_only: bool,
    output: Path | None,
    as_json: bool,
) -> None:
    """Print the diff for a GitHub PR or GitLab MR.

    REFERENCE is a PR/MR URL, or shorthand owner/repo#N / group/proj!N.
    Uses an existing ``clone-review`` checkout when present unless ``--api-only``.
    """
    include_patch = not name_only and not stat_only
    try:
        result = prepare_review_diff(
            reference,
            reviews_root=root,
            dirname=name,
            platform=platform.lower() if platform else None,
            host=host,
            clone_path=clone_path,
            prefer_clone=not api_only,
            include_patch=include_patch,
        )
    except CloneReviewError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        payload = result.to_dict()
        if name_only or stat_only:
            payload["diff"] = ""
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    text = format_report(result, names_only=name_only, stat_only=stat_only)
    if output is not None:
        output.write_text(text, encoding="utf-8")
    else:
        click.echo(text, nl=bool(text) and text.endswith("\n"))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="review-diff", standalone_mode=False)
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
