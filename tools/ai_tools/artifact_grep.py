#!/usr/bin/env python3
"""Search IdM-CI / Jenkins artifact dumps and twd logs for patterns."""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from ai_tools.clean_twd import require_twd
from ai_tools.compression import maybe_decompress

SKIP_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", ".pytest_cache"})
DEFAULT_MAX_BYTES = 50 * 1024 * 1024


class ArtifactGrepError(RuntimeError):
    """Invalid path or pattern."""


@dataclass
class GrepMatch:
    """One matching line in an artifact file."""

    path: str
    line_number: int
    line: str
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GrepSummary:
    """Batch grep outcome."""

    root: str
    pattern: str
    matches: list[GrepMatch] = field(default_factory=list)
    files_searched: int = 0
    files_skipped: int = 0

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "pattern": self.pattern,
            "match_count": len(self.matches),
            "files_searched": self.files_searched,
            "files_skipped": self.files_skipped,
            "matches": [item.to_dict() for item in self.matches],
        }


def read_artifact_text(path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str | None:
    """Read a log artifact as UTF-8 text, transparently gunzipping when needed."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > max_bytes:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        data = maybe_decompress(data)
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def compile_patterns(
    pattern: str,
    *,
    fixed_strings: bool,
    ignore_case: bool,
) -> list[re.Pattern[str]]:
    flags = re.IGNORECASE if ignore_case else 0
    if fixed_strings:
        parts = [part for part in pattern.split("|") if part]
        if not parts:
            raise ArtifactGrepError("empty pattern")
        return [re.compile(re.escape(part), flags) for part in parts]
    try:
        return [re.compile(pattern, flags)]
    except re.error as exc:
        raise ArtifactGrepError(f"invalid pattern: {exc}") from exc


def line_matches(line: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(item.search(line) is not None for item in patterns)


def collect_files(
    paths: list[Path],
    *,
    recursive: bool,
    include_globs: tuple[str, ...],
) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def accept(path: Path) -> bool:
        if not include_globs:
            return True
        name = path.name
        rel = path.as_posix()
        return any(fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(rel, glob) for glob in include_globs)

    for raw in paths:
        path = raw.expanduser().resolve()
        if not path.exists():
            raise ArtifactGrepError(f"Path not found: {path}")
        if path.is_file():
            if path not in seen and accept(path):
                found.append(path)
                seen.add(path)
            continue
        iterator = path.rglob("*") if recursive else path.iterdir()
        for item in sorted(iterator):
            if not item.is_file() or item in seen:
                continue
            if any(part in SKIP_DIR_NAMES for part in item.parts):
                continue
            if accept(item):
                found.append(item)
                seen.add(item)
    return found


def grep_file(
    path: Path,
    patterns: list[re.Pattern[str]],
    *,
    before: int,
    after: int,
    max_matches: int | None,
    matches: list[GrepMatch],
) -> str | None:
    """Search one file. Returns None when unreadable, else 'searched'."""
    text = read_artifact_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        if not line_matches(line, patterns):
            continue
        item = GrepMatch(
            path=str(path),
            line_number=index,
            line=line,
            before=lines[max(0, index - before - 1) : index - 1],
            after=lines[index : index + after],
        )
        matches.append(item)
        if max_matches is not None and len(matches) >= max_matches:
            return "searched"
    return "searched"


def artifact_grep(
    pattern: str,
    paths: list[Path],
    *,
    fixed_strings: bool = False,
    ignore_case: bool = False,
    recursive: bool = True,
    before_context: int = 0,
    after_context: int = 0,
    max_matches: int | None = None,
    include_globs: tuple[str, ...] = (),
) -> GrepSummary:
    if not paths:
        raise ArtifactGrepError("At least one path is required")

    patterns = compile_patterns(
        pattern,
        fixed_strings=fixed_strings,
        ignore_case=ignore_case,
    )
    root = str(paths[0].expanduser().resolve())
    summary = GrepSummary(root=root, pattern=pattern)
    files = collect_files(paths, recursive=recursive, include_globs=include_globs)

    for path in files:
        status = grep_file(
            path,
            patterns,
            before=before_context,
            after=after_context,
            max_matches=max_matches,
            matches=summary.matches,
        )
        if status is None:
            summary.files_skipped += 1
        else:
            summary.files_searched += 1
        if max_matches is not None and len(summary.matches) >= max_matches:
            break

    return summary


def format_match(item: GrepMatch, *, root: Path | None = None) -> str:
    path = Path(item.path)
    label = path.name
    if root is not None:
        try:
            label = path.relative_to(root).as_posix()
        except ValueError:
            label = str(path)
    chunks = []
    base = item.line_number - len(item.before)
    for offset, ctx in enumerate(item.before):
        chunks.append(f"{label}:{base + offset}:{ctx}")
    chunks.append(f"{label}:{item.line_number}:{item.line}")
    for offset, ctx in enumerate(item.after, start=1):
        chunks.append(f"{label}:{item.line_number + offset}:{ctx}")
    return "\n".join(chunks)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("pattern")
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option(
    "--twd",
    "use_twd",
    is_flag=True,
    help="Treat PATH as a twd or campaign root (validated via require_twd).",
)
@click.option("-F", "--fixed-strings", is_flag=True, help="Treat PATTERN as literal text.")
@click.option("-i", "--ignore-case", is_flag=True, help="Case-insensitive search.")
@click.option(
    "-r",
    "--recursive/--no-recursive",
    default=True,
    show_default=True,
    help="Walk directories recursively.",
)
@click.option("-B", "--before-context", type=int, default=0, show_default=True)
@click.option("-A", "--after-context", type=int, default=0, show_default=True)
@click.option("-C", "--context", "context_lines", type=int, default=None, help="Lines before/after.")
@click.option("-m", "--max-count", type=int, default=None, help="Stop after N matches.")
@click.option(
    "--include",
    "includes",
    multiple=True,
    metavar="GLOB",
    help="Search only paths matching GLOB (repeatable).",
)
@click.option("--json", "as_json", is_flag=True, help="Print matches as JSON.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress output; exit 1 when no matches.")
@click.option("-l", "--files-with-matches", is_flag=True, help="Print only file paths.")
def main(
    pattern: str,
    paths: tuple[Path, ...],
    use_twd: bool,
    fixed_strings: bool,
    ignore_case: bool,
    recursive: bool,
    before_context: int,
    after_context: int,
    context_lines: int | None,
    max_count: int | None,
    includes: tuple[str, ...],
    as_json: bool,
    quiet: bool,
    files_with_matches: bool,
) -> None:
    """Search Jenkins / IdM-CI artifact dumps and twd logs for PATTERN."""
    if not paths:
        raise click.UsageError("At least one PATH is required.")

    if context_lines is not None:
        before_context = after_context = context_lines

    search_paths = list(paths)
    if use_twd:
        search_paths = [require_twd(paths[0])]

    try:
        summary = artifact_grep(
            pattern,
            search_paths,
            fixed_strings=fixed_strings,
            ignore_case=ignore_case,
            recursive=recursive,
            before_context=before_context,
            after_context=after_context,
            max_matches=max_count,
            include_globs=includes,
        )
    except ArtifactGrepError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(summary.to_dict(), indent=2))
    elif not quiet:
        root = Path(summary.root)
        seen_files: set[str] = set()
        for item in summary.matches:
            if files_with_matches:
                if item.path not in seen_files:
                    click.echo(item.path)
                    seen_files.add(item.path)
                continue
            click.echo(format_match(item, root=root))

    if not summary.matches:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main(standalone_mode=True)
    except click.ClickException as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
