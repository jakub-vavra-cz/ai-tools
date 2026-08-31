#!/usr/bin/env python3
"""Remove clone-review checkouts under ~/git/@REVIEWS after a PR/MR review."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import click

from ai_tools.clone_review import (
    CloneReviewError,
    assert_reviews_path,
    default_reviews_root,
    expected_clone_path,
    parse_ref,
)


@dataclass
class CleanupResult:
    """Summary of removed review clones."""

    reviews_root: str
    removed: list[str]
    skipped: list[str]
    dry_run: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _is_git_clone(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def _assert_under_root(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve()
    root_resolved = root.expanduser().resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise CloneReviewError(
            f"path must be under reviews root {root_resolved}: {resolved}"
        ) from exc
    return resolved


def list_review_clones(reviews_root: Path) -> list[Path]:
    root = assert_reviews_path(reviews_root)
    if not root.is_dir():
        return []
    clones: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and _is_git_clone(child):
            clones.append(child)
    return clones


def remove_clone(path: Path, *, dry_run: bool = False) -> None:
    resolved = assert_reviews_path(path)
    if not resolved.exists():
        raise CloneReviewError(f"clone path does not exist: {resolved}")
    if not resolved.is_dir():
        raise CloneReviewError(f"not a directory: {resolved}")
    if not dry_run:
        shutil.rmtree(resolved)


def cleanup_paths(
    paths: Sequence[Path],
    *,
    reviews_root: Path,
    dry_run: bool = False,
) -> CleanupResult:
    root = assert_reviews_path(reviews_root)
    removed: list[str] = []
    skipped: list[str] = []

    for path in paths:
        resolved = _assert_under_root(path, root)
        if not resolved.exists():
            skipped.append(str(resolved))
            continue
        remove_clone(resolved, dry_run=dry_run)
        removed.append(str(resolved))

    return CleanupResult(
        reviews_root=str(root),
        removed=removed,
        skipped=skipped,
        dry_run=dry_run,
    )


def resolve_cleanup_paths(
    *,
    reference: str | None,
    clone_path: Path | None,
    dirname: str | None,
    reviews_root: Path,
    all_clones: bool,
    platform: str | None,
    host: str | None,
) -> list[Path]:
    root = assert_reviews_path(reviews_root)

    if all_clones:
        return list_review_clones(root)

    if clone_path is not None:
        return [_assert_under_root(assert_reviews_path(clone_path), root)]

    if reference is not None:
        ref = parse_ref(reference, platform=platform, host=host)
        return [expected_clone_path(ref, reviews_root=root, dirname=dirname)]

    if dirname is not None:
        return [_assert_under_root(root / dirname, root)]

    raise CloneReviewError(
        "specify REFERENCE, --clone-path, --name, or --all"
    )


def format_report(result: CleanupResult) -> str:
    lines = [
        f"reviews_root: {result.reviews_root}",
        f"dry_run: {result.dry_run}",
        f"removed: {len(result.removed)}",
    ]
    for path in result.removed:
        lines.append(f"  {path}")
    if result.skipped:
        lines.append(f"skipped: {len(result.skipped)}")
        for path in result.skipped:
            lines.append(f"  {path}")
    return "\n".join(lines) + "\n"


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("reference", required=False)
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
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Remove this specific clone-review checkout",
)
@click.option(
    "--all",
    "all_clones",
    is_flag=True,
    help="Remove every git clone under the reviews root",
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
    "-n",
    "--dry-run",
    is_flag=True,
    help="Show what would be removed without deleting",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON",
)
def cli(
    reference: str | None,
    root: Path | None,
    name: str | None,
    clone_path: Path | None,
    all_clones: bool,
    platform: str | None,
    host: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Remove clone-review checkouts after a PR/MR review.

    Pass a PR/MR REFERENCE, ``--clone-path``, ``--name``, or ``--all``.
    Only paths under a directory containing ``reviews`` are removed.
    """
    reviews_root = root or default_reviews_root()
    try:
        paths = resolve_cleanup_paths(
            reference=reference,
            clone_path=clone_path,
            dirname=name,
            reviews_root=reviews_root,
            all_clones=all_clones,
            platform=platform.lower() if platform else None,
            host=host,
        )
        result = cleanup_paths(
            paths,
            reviews_root=reviews_root,
            dry_run=dry_run,
        )
    except CloneReviewError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        click.echo(format_report(result), nl=False)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="cleanup-review", standalone_mode=False)
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
