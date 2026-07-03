#!/usr/bin/env python3
"""Clean twd artifacts and re-run only previously failed IdM-CI pytest tests."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from ai_tools.clean_twd import clean_twd, require_twd
from ai_tools.sync_twd_tests import sync_twd_tests
from ai_tools.te_test_summary import (
    TeSummaryError,
    build_pytest_k_filter,
    failed_nodeids_from_twd,
)

PHASE_NAME_RE = re.compile(r"^-\s+name:\s+(\S+)\s*$")
PYTESTS_STEP_RE = re.compile(r"^\s+-\s+(pytest-mh|pytests|restraint):\s+")
ARGS_RE = re.compile(r"^(\s+args:\s+)(.*)$")
DEFAULT_PHASE = "test"
RERUN_METADATA = "metadata.rerun.yaml"


class RerunFailedError(RuntimeError):
    """Invalid twd, metadata, or pytest results."""


@dataclass
class RerunResult:
    """Outcome of idmci-rerun-failed."""

    twd: str
    metadata: str
    rerun_metadata: str
    failed: list[str] = field(default_factory=list)
    pytest_args: str = ""
    cleaned: list[str] = field(default_factory=list)
    overlay: str | None = None
    te_command: list[str] = field(default_factory=list)
    te_rc: int | None = None
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def metadata_source(twd: Path) -> Path:
    for name in ("metadata.yaml", "config/metadata.yaml"):
        path = twd / name
        if path.is_file():
            return path
    raise RerunFailedError(f"no metadata.yaml under {twd}")


def append_pytest_args(metadata_text: str, extra_args: str, *, phase: str) -> str:
    """Append pytest args to every pytests/pytest-mh step in *phase*."""
    if not extra_args.strip():
        return metadata_text

    lines = metadata_text.splitlines()
    out: list[str] = []
    current_phase: str | None = None
    updated = False
    index = 0
    while index < len(lines):
        line = lines[index]
        phase_match = PHASE_NAME_RE.match(line)
        if phase_match:
            current_phase = phase_match.group(1)
            out.append(line)
            index += 1
            continue

        if current_phase == phase and PYTESTS_STEP_RE.match(line):
            step_lines = [line]
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if next_line.strip() == "":
                    step_lines.append(next_line)
                    index += 1
                    continue
                if next_line.startswith("  - "):
                    break
                if not next_line.startswith("    "):
                    break
                step_lines.append(next_line)
                index += 1

            args_index: int | None = None
            for step_index, step_line in enumerate(step_lines):
                if ARGS_RE.match(step_line):
                    args_index = step_index
                    break
            if args_index is not None:
                match = ARGS_RE.match(step_lines[args_index])
                assert match is not None
                prefix, value = match.groups()
                merged = f"{value.strip()} {extra_args}".strip()
                step_lines[args_index] = f"{prefix}{merged}"
            else:
                step_lines.insert(1, f"    args: {extra_args}")
            out.extend(step_lines)
            updated = True
            continue

        out.append(line)
        index += 1

    if not updated:
        raise RerunFailedError(f"no pytests/pytest-mh steps in phase {phase!r}")

    return "\n".join(out).rstrip() + "\n"


def write_rerun_metadata(
    twd: Path,
    pytest_extra: str,
    *,
    phase: str = DEFAULT_PHASE,
) -> Path:
    src = metadata_source(twd)
    patched = append_pytest_args(
        src.read_text(encoding="utf-8"),
        pytest_extra,
        phase=phase,
    )
    dest = twd / RERUN_METADATA
    dest.write_text(patched, encoding="utf-8")
    return dest


def find_te_executable() -> str:
    return "te"


def idmci_rerun_failed(
    twd: Path,
    *,
    overlay: Path | None = None,
    phase: str = DEFAULT_PHASE,
    pytest_filter: str | None = None,
    nodeids: list[str] | None = None,
    dry_run: bool = False,
    run_te: bool = True,
    te_executable: str | None = None,
) -> RerunResult:
    twd = require_twd(twd)
    if nodeids is None:
        try:
            nodeids = failed_nodeids_from_twd(twd)
        except (TeSummaryError, ValueError) as exc:
            raise RerunFailedError(str(exc)) from exc
    if not nodeids:
        raise RerunFailedError("no failed or errored tests found in the last run")

    extra = pytest_filter or build_pytest_k_filter(nodeids)
    cleaned = clean_twd(twd, dry_run=dry_run)

    overlay_path: str | None = None
    if overlay is not None:
        sync = sync_twd_tests(overlay, twd=twd, dry_run=dry_run)
        overlay_path = sync.dest

    if dry_run:
        rerun_metadata = twd / RERUN_METADATA
        te_cmd = [
            te_executable or find_te_executable(),
            f"--phase={phase}",
            rerun_metadata.name,
        ]
        return RerunResult(
            twd=str(twd),
            metadata=str(metadata_source(twd)),
            rerun_metadata=str(rerun_metadata),
            failed=list(nodeids),
            pytest_args=extra,
            cleaned=cleaned,
            overlay=overlay_path,
            te_command=te_cmd,
            te_rc=None,
            dry_run=True,
        )

    rerun_metadata = write_rerun_metadata(twd, extra, phase=phase)
    te_cmd = [
        te_executable or find_te_executable(),
        f"--phase={phase}",
        rerun_metadata.name,
    ]
    te_rc: int | None = None
    if run_te:
        completed = subprocess.run(
            te_cmd,
            cwd=twd,
            check=False,
        )
        te_rc = completed.returncode

    return RerunResult(
        twd=str(twd),
        metadata=str(metadata_source(twd)),
        rerun_metadata=str(rerun_metadata),
        failed=list(nodeids),
        pytest_args=extra,
        cleaned=cleaned,
        overlay=overlay_path,
        te_command=te_cmd,
        te_rc=te_rc,
        dry_run=False,
    )


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--twd",
    type=click.Path(path_type=Path, file_okay=False),
    default=".",
    show_default=True,
    help="twd or campaign directory",
)
@click.option(
    "--overlay",
    type=click.Path(path_type=Path, exists=True),
    default=None,
    help="Local test checkout to overlay via sync-twd-tests before re-run",
)
@click.option(
    "--phase",
    default=DEFAULT_PHASE,
    show_default=True,
    help="Metadata phase containing pytests steps to filter",
)
@click.option(
    "--pytest-args",
    default=None,
    help="Override generated pytest args (default: -k from failed nodeids)",
)
@click.option(
    "--prepare-only",
    is_flag=True,
    help="Clean/sync/write metadata.rerun.yaml but do not invoke te",
)
@click.option(
    "--te",
    "te_executable",
    default=None,
    help="te executable (default: te on PATH)",
)
@click.option("-n", "--dry-run", is_flag=True, help="Show actions without running te")
@click.option("--json", "as_json", is_flag=True, help="Print a JSON summary")
def main(
    twd: Path,
    overlay: Path | None,
    phase: str,
    pytest_args: str | None,
    prepare_only: bool,
    te_executable: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Clean twd, optionally overlay tests, and re-run only failed pytest cases."""
    try:
        result = idmci_rerun_failed(
            twd,
            overlay=overlay,
            phase=phase,
            pytest_filter=pytest_args,
            dry_run=dry_run,
            run_te=not prepare_only and not dry_run,
            te_executable=te_executable,
        )
    except RerunFailedError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(f"twd: {result.twd}")
        click.echo(f"failed: {len(result.failed)}")
        for nodeid in result.failed:
            click.echo(f"  {nodeid}")
        click.echo(f"pytest args: {result.pytest_args}")
        if result.cleaned:
            click.echo(f"cleaned: {len(result.cleaned)} path(s)")
        if result.overlay:
            click.echo(f"overlay: {result.overlay}")
        click.echo(f"rerun metadata: {result.rerun_metadata}")
        click.echo(f"command: {shlex.join(result.te_command)}")
        if result.te_rc is not None:
            click.echo(f"te rc: {result.te_rc}")

    if result.te_rc not in (None, 0):
        raise SystemExit(result.te_rc)


if __name__ == "__main__":
    try:
        main(standalone_mode=True)
    except click.ClickException as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
