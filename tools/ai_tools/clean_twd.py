#!/usr/bin/env python3
"""Remove stale IdM-CI twd artifacts before re-running tests."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

TWD_MARKERS = ("config", "logs", "metadata.yaml", "runner.log", "pytest-run.rc")
ROOT_ARTIFACTS = ("runner.log", "pytest-run.rc")
JUNIT_GLOB = "*junit.xml"


def is_twd_directory(twd: Path) -> bool:
    return any((twd / marker).exists() for marker in TWD_MARKERS)


def clean_twd(twd: Path, *, dry_run: bool = False) -> list[str]:
    """Delete logs/ contents and twd-root junit/runner artifacts.

    Returns paths removed, relative to ``twd``.
    """
    twd = twd.resolve()
    if not twd.is_dir():
        raise ValueError(f"Not a directory: {twd}")
    if not is_twd_directory(twd):
        markers = ", ".join(TWD_MARKERS)
        raise ValueError(f"Not a twd directory (expected one of: {markers}): {twd}")

    removed: list[str] = []

    logs_dir = twd / "logs"
    if logs_dir.is_dir():
        for item in sorted(logs_dir.iterdir()):
            rel = item.relative_to(twd).as_posix()
            if not dry_run:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            removed.append(rel)

    for name in ROOT_ARTIFACTS:
        path = twd / name
        if path.is_file():
            if not dry_run:
                path.unlink()
            removed.append(name)

    seen: set[str] = set(ROOT_ARTIFACTS)
    for path in sorted(twd.glob(JUNIT_GLOB)):
        if not path.is_file() or path.name in seen:
            continue
        if not dry_run:
            path.unlink()
        removed.append(path.name)
        seen.add(path.name)

    return removed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clean IdM-CI twd artifacts before test re-execution: "
            "logs/ contents, runner.log, pytest-run.rc, and *junit.xml at twd root."
        ),
    )
    parser.add_argument(
        "twd",
        nargs="?",
        default=".",
        type=Path,
        help="Path to twd (default: current directory)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print what would be removed without deleting",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Do not print removed paths",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        removed = clean_twd(args.twd, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        prefix = "would remove" if args.dry_run else "removed"
        if removed:
            for path in removed:
                print(f"{prefix}: {path}")
        else:
            print(f"{prefix}: (nothing to clean)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
