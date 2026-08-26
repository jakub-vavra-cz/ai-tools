#!/usr/bin/env python3
"""Decompress gzip IdM-CI / Jenkins log artifacts under a twd or artifact dump."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from ai_tools.compression import is_gzip_payload, maybe_decompress


class DecompressLogsError(RuntimeError):
    """Invalid path or decompress failure."""


@dataclass
class DecompressResult:
    """One input file and how it was handled."""

    src: str
    dest: str
    action: str
    skipped: bool = False
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecompressSummary:
    """Batch decompress outcome."""

    root: str
    results: list[DecompressResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "results": [item.to_dict() for item in self.results],
            "decompressed": sum(1 for item in self.results if item.action == "decompressed"),
            "renamed": sum(1 for item in self.results if item.action == "renamed"),
            "skipped": sum(1 for item in self.results if item.skipped),
        }


def output_path_for(path: Path) -> Path:
    """Plain-text destination for a gzip artifact path."""
    if path.suffix == ".gz":
        return path.with_suffix("")
    return path


def should_process(path: Path, *, only_gz: bool) -> bool:
    if not only_gz:
        return True
    if path.suffix == ".gz":
        return True
    return is_gzip_payload(path.read_bytes()[:2])


def decompress_file(
    path: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    remove_source: bool = False,
) -> DecompressResult:
    """Decompress or rename one log artifact."""
    path = path.resolve()
    if not path.is_file():
        raise DecompressLogsError(f"Not a file: {path}")

    data = path.read_bytes()
    dest = output_path_for(path)
    compressed = is_gzip_payload(data)

    if dest.exists() and not force:
        if dest.stat().st_mtime >= path.stat().st_mtime:
            return DecompressResult(
                src=str(path),
                dest=str(dest),
                action="skipped",
                skipped=True,
                reason="destination exists",
            )

    if compressed:
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(maybe_decompress(data))
            if remove_source and path != dest:
                path.unlink()
        return DecompressResult(str(path), str(dest), "decompressed")

    if path.suffix == ".gz":
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if remove_source:
                path.rename(dest)
            else:
                shutil.copy2(path, dest)
        return DecompressResult(str(path), str(dest), "renamed")

    return DecompressResult(
        str(path),
        str(path),
        "skipped",
        skipped=True,
        reason="not gzip",
    )


def collect_paths(paths: list[Path], *, recursive: bool) -> list[Path]:
    """Expand files and optional directory trees."""
    found: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        path = raw.expanduser().resolve()
        if not path.exists():
            raise DecompressLogsError(f"Path not found: {path}")
        if path.is_file():
            if path not in seen:
                found.append(path)
                seen.add(path)
            continue
        iterator = path.rglob("*") if recursive else path.iterdir()
        for item in sorted(iterator):
            if item.is_file() and item not in seen:
                found.append(item)
                seen.add(item)
    return found


def decompress_logs(
    paths: list[Path],
    *,
    recursive: bool = True,
    dry_run: bool = False,
    force: bool = False,
    remove_source: bool = False,
    only_gz: bool = True,
) -> DecompressSummary:
    """Decompress gzip logs in *paths* (files or directories)."""
    if not paths:
        raise DecompressLogsError("At least one path is required")

    root = str(paths[0].expanduser().resolve())
    summary = DecompressSummary(root=root)
    for path in collect_paths(paths, recursive=recursive):
        if not should_process(path, only_gz=only_gz):
            continue
        summary.results.append(
            decompress_file(
                path,
                dry_run=dry_run,
                force=force,
                remove_source=remove_source,
            )
        )
    return summary


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option(
    "-r",
    "--recursive/--no-recursive",
    default=True,
    show_default=True,
    help="Walk directories recursively.",
)
@click.option("-n", "--dry-run", is_flag=True, help="Show actions without writing files.")
@click.option("-f", "--force", is_flag=True, help="Overwrite existing outputs.")
@click.option(
    "--remove-source",
    is_flag=True,
    help="Delete or rename away the .gz source after success.",
)
@click.option(
    "--all-files",
    is_flag=True,
    help="Inspect every file, not only .gz names and gzip payloads.",
)
@click.option("--json", "as_json", is_flag=True, help="Print a JSON summary.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-error output.")
def main(
    paths: tuple[Path, ...],
    recursive: bool,
    dry_run: bool,
    force: bool,
    remove_source: bool,
    all_files: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Decompress gzip logs from IdM-CI / Jenkins artifact dumps."""
    if not paths:
        raise click.UsageError("At least one PATH is required.")

    try:
        summary = decompress_logs(
            list(paths),
            recursive=recursive,
            dry_run=dry_run,
            force=force,
            remove_source=remove_source,
            only_gz=not all_files,
        )
    except DecompressLogsError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(summary.to_dict(), indent=2))
    elif not quiet:
        for item in summary.results:
            if item.skipped:
                click.echo(f"skip {item.src}: {item.reason}")
            else:
                prefix = "would " if dry_run else ""
                click.echo(f"{prefix}{item.action} {item.src} -> {item.dest}")


if __name__ == "__main__":
    main(standalone_mode=True)
