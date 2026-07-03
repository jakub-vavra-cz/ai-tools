#!/usr/bin/env python3
"""Overlay local test WIP onto an IdM-CI campaign sibling of twd."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from ai_tools.clean_twd import require_twd

TEST_STEP_RE = re.compile(
    r"^\s*-\s+(?:pytest-mh|pytests|restraint):\s+(\S+)",
    re.MULTILINE,
)
EXCLUDE_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", ".pytest_cache"})
METADATA_CANDIDATES = ("metadata.yaml", "config/metadata.yaml")


class SyncTwdError(RuntimeError):
    """Fatal overlay error (bad twd, dest, or metadata)."""


@dataclass
class SyncResult:
    """Paths and files copied by an overlay."""

    src: str
    dest: str
    twd: str
    copied: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def find_git_root(path: Path) -> Path | None:
    """Nearest ancestor (inclusive) that contains ``.git``."""
    cur = path if path.is_dir() else path.parent
    for parent in (cur, *cur.parents):
        if (parent / ".git").exists():
            return parent
    return None


def metadata_path(twd: Path) -> Path:
    for rel in METADATA_CANDIDATES:
        path = twd / rel
        if path.is_file():
            return path
    raise SyncTwdError(f"no metadata.yaml under {twd}")


def test_step_paths(metadata: Path) -> list[str]:
    """Relative pytest-mh / pytests / restraint paths from metadata."""
    return TEST_STEP_RE.findall(metadata.read_text(encoding="utf-8"))


def sibling_and_test_step(twd: Path) -> tuple[Path, Path, str]:
    """Campaign sibling root, resolved test-step dir, and raw relative path."""
    rels = test_step_paths(metadata_path(twd))
    if not rels:
        raise SyncTwdError(f"no pytest-mh/pytests/restraint path in {metadata_path(twd)}")
    rel = rels[0].rstrip("/")
    parts = Path(rel).parts
    if not parts or parts[0] != ".." or len(parts) < 2:
        raise SyncTwdError(f"test path must be relative to twd (..): {rel}")
    sibling = (twd.parent / parts[1]).resolve()
    test_step = (twd / rel).resolve()
    return sibling, test_step, rel


def assert_dest_allowed(dest: Path, twd: Path) -> Path:
    """Dest must sit under the campaign, never inside twd."""
    dest = dest.resolve()
    twd = twd.resolve()
    campaign = twd.parent
    try:
        dest.relative_to(campaign)
    except ValueError as exc:
        raise SyncTwdError(f"dest is not inside campaign {campaign}: {dest}") from exc
    if dest == campaign:
        raise SyncTwdError(f"dest must be a sibling of twd, not {campaign}")
    try:
        dest.relative_to(twd)
    except ValueError:
        return dest
    raise SyncTwdError(f"dest must be a sibling of twd, not inside it: {dest}")


def resolve_dest(twd: Path, src: Path, dest: Path | None = None) -> Path:
    """Map local src onto the campaign clone (sibling or test-step path)."""
    twd = require_twd(twd)
    src = src.expanduser().resolve()
    if dest is not None:
        return assert_dest_allowed(dest.expanduser().resolve(), twd)

    sibling, test_step, _rel = sibling_and_test_step(twd)
    git_root = find_git_root(src)

    if src.is_file():
        if git_root is not None:
            target = sibling / src.relative_to(git_root)
        elif src.parent.name == test_step.name:
            target = test_step / src.name
        else:
            target = sibling / src.name
        return assert_dest_allowed(target, twd)

    if git_root is not None and src != git_root:
        target = sibling / src.relative_to(git_root)
    elif git_root is not None:
        target = sibling
    elif src.name == test_step.name:
        target = test_step
    else:
        target = sibling
    return assert_dest_allowed(target, twd)


def overlay(src: Path, dest: Path, *, dry_run: bool = False) -> list[str]:
    """Copy src onto dest. No delete. Skip .git/.venv/__pycache__/.pytest_cache."""
    src = src.resolve()
    dest = dest.resolve()
    copied: list[str] = []
    if src.is_file():
        target = dest / src.name if dest.is_dir() else dest
        copied.append(src.name if dest.is_dir() else target.name)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        return copied

    if not src.is_dir():
        raise SyncTwdError(f"src is not a file or directory: {src}")

    for root, dirs, files in os.walk(src):
        dirs[:] = [name for name in dirs if name not in EXCLUDE_DIR_NAMES]
        rel_root = Path(root).relative_to(src)
        for name in files:
            if name in EXCLUDE_DIR_NAMES:
                continue
            rel = (rel_root / name).as_posix()
            copied.append(rel)
            if dry_run:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(root) / name, target)
    copied.sort()
    return copied


def sync_twd_tests(
    src: Path,
    *,
    twd: Path,
    dest: Path | None = None,
    dry_run: bool = False,
) -> SyncResult:
    """Overlay src onto the campaign sibling inferred from twd metadata."""
    twd = require_twd(twd)
    src = src.expanduser().resolve()
    if not src.exists():
        raise SyncTwdError(f"src does not exist: {src}")
    dest_path = resolve_dest(twd, src, dest)
    copied = overlay(src, dest_path, dry_run=dry_run)
    return SyncResult(
        src=str(src),
        dest=str(dest_path),
        twd=str(twd),
        copied=copied,
        dry_run=dry_run,
    )


def format_report(result: SyncResult) -> str:
    verb = "would copy" if result.dry_run else "copied"
    lines = [
        f"src: {result.src}",
        f"dest: {result.dest}",
        f"{verb}: {len(result.copied)} file(s)",
    ]
    return "\n".join(lines) + "\n"


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("src", type=click.Path(path_type=Path, exists=True))
@click.option(
    "--twd",
    type=click.Path(path_type=Path, file_okay=False),
    default=".",
    show_default=True,
    help="twd or campaign directory",
)
@click.option(
    "--dest",
    type=click.Path(path_type=Path),
    default=None,
    help="Override dest (must be a campaign sibling of twd)",
)
@click.option("-n", "--dry-run", is_flag=True, help="List files without copying")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
def cli(src: Path, twd: Path, dest: Path | None, dry_run: bool, as_json: bool) -> None:
    """Overlay local tests onto the campaign clone next to twd.

    Dest is inferred from pytest-mh / pytests / restraint in metadata.yaml.
    Excludes .git, .venv, __pycache__, .pytest_cache. Does not --delete.
    """
    try:
        result = sync_twd_tests(src, twd=twd, dest=dest, dry_run=dry_run)
    except (SyncTwdError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        payload = result.to_dict()
        payload["count"] = len(result.copied)
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(format_report(result), nl=False)


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="sync-twd-tests", standalone_mode=False)
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
