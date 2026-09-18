#!/usr/bin/env python3
"""Orchestrate PR/MR review: clone, diff, lint changed files, optional cleanup."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import click

from ai_tools.check_ansible import CheckReport as AnsibleCheckReport
from ai_tools.check_ansible import check_ansible, format_report as format_ansible_report
from ai_tools.check_python import CheckReport as PythonCheckReport
from ai_tools.check_python import check_python, format_report as format_python_report
from ai_tools.cleanup_review import CleanupResult, cleanup_paths
from ai_tools.clone_review import (
    CloneReviewError,
    ReviewCheckout,
    prepare_review,
    run_cmd,
)

ANSIBLE_PATH_RE = re.compile(
    r"(?:^|/)"
    r"(?:ansible|playbooks?|roles?|handlers|inventory|(?:group|host)_vars)"
    r"(?:/|$)|"
    r"/tasks/[^/]+\.ya?ml$",
    re.IGNORECASE,
)


@dataclass
class ReviewPrReport:
    """Aggregate result of a review-pr run."""

    checkout: ReviewCheckout
    diff_patch: str
    python: PythonCheckReport | None = None
    ansible: AnsibleCheckReport | None = None
    skipped_lint: list[str] = field(default_factory=list)
    cleanup: CleanupResult | None = None

    @property
    def lint_ok(self) -> bool:
        reports = [r for r in (self.python, self.ansible) if r is not None]
        if not reports:
            return True
        return all(r.ok for r in reports)

    @property
    def ok(self) -> bool:
        return self.lint_ok

    def to_dict(self, *, include_diff: bool = False) -> dict:
        data = {
            "checkout": self.checkout.to_dict(),
            "changed_files": self.checkout.changed_files,
            "diff_stat": self.checkout.diff_stat,
            "skipped_lint": self.skipped_lint,
            "lint_ok": self.lint_ok,
            "ok": self.ok,
        }
        if include_diff:
            data["diff"] = self.diff_patch
        if self.python is not None:
            data["python"] = self.python.to_dict()
        if self.ansible is not None:
            data["ansible"] = self.ansible.to_dict()
        if self.cleanup is not None:
            data["cleanup"] = self.cleanup.to_dict()
        return data


def is_ansible_yaml_path(path: str) -> bool:
    return bool(ANSIBLE_PATH_RE.search(path.replace("\\", "/")))


def classify_changed_files(files: list[str]) -> tuple[list[str], list[str], list[str]]:
    python_files: list[str] = []
    ansible_files: list[str] = []
    skipped: list[str] = []

    for rel in files:
        if rel.endswith(".py"):
            python_files.append(rel)
        elif rel.endswith((".yml", ".yaml")):
            if is_ansible_yaml_path(rel):
                ansible_files.append(rel)
            else:
                skipped.append(rel)
        else:
            skipped.append(rel)

    return python_files, ansible_files, skipped


def partition_existing_files(
    clone_path: Path,
    files: list[str],
) -> tuple[list[str], list[str]]:
    """Split changed paths into present-at-HEAD vs deleted/missing."""
    present: list[str] = []
    missing: list[str] = []
    for rel in files:
        if (clone_path / rel).is_file():
            present.append(rel)
        else:
            missing.append(rel)
    return present, missing


def fetch_diff_patch(clone_path: Path, base_sha: str, head_sha: str) -> str:
    proc = run_cmd(
        ["git", "diff", f"{base_sha}..{head_sha}"],
        cwd=clone_path,
    )
    return proc.stdout


def run_review(
    reference: str,
    *,
    reviews_root: Path | None = None,
    dirname: str | None = None,
    platform: str | None = None,
    host: str | None = None,
    refresh: bool = True,
    skip_lint: bool = False,
    include_diff: bool = False,
    cleanup: bool = False,
    cleanup_dry_run: bool = False,
) -> ReviewPrReport:
    """Clone a PR/MR, lint changed Python/Ansible files, optionally clean up."""
    checkout = prepare_review(
        reference,
        reviews_root=reviews_root,
        dirname=dirname,
        platform=platform,
        host=host,
        refresh=refresh,
    )

    clone_path = Path(checkout.clone_path)
    diff_patch = ""
    if include_diff:
        diff_patch = fetch_diff_patch(
            clone_path,
            checkout.base_sha,
            checkout.head_sha,
        )

    python_report: PythonCheckReport | None = None
    ansible_report: AnsibleCheckReport | None = None
    skipped_lint: list[str] = []

    if not skip_lint:
        # Deleted paths still appear in the diff list but are gone at HEAD.
        present, deleted = partition_existing_files(
            clone_path,
            checkout.changed_files,
        )
        python_files, ansible_files, skipped_lint = classify_changed_files(present)
        skipped_lint = deleted + skipped_lint

        if python_files:
            py_paths = [clone_path / rel for rel in python_files]
            python_report = check_python(py_paths, python_root=clone_path)

        if ansible_files:
            yaml_paths = [clone_path / rel for rel in ansible_files]
            ansible_report = check_ansible(yaml_paths)

    cleanup_result: CleanupResult | None = None
    if cleanup:
        cleanup_result = cleanup_paths(
            [clone_path],
            reviews_root=reviews_root or clone_path.parent,
            dry_run=cleanup_dry_run,
        )

    return ReviewPrReport(
        checkout=checkout,
        diff_patch=diff_patch,
        python=python_report,
        ansible=ansible_report,
        skipped_lint=skipped_lint,
        cleanup=cleanup_result,
    )


def format_report(
    report: ReviewPrReport,
    *,
    quiet: bool = False,
    include_diff: bool = False,
) -> str:
    checkout = report.checkout
    lines: list[str] = [
        f"platform: {checkout.platform}",
        f"repo: {checkout.repo}",
        f"{checkout.kind}: {checkout.number}",
        f"clone_path: {checkout.clone_path}",
        f"created: {checkout.created}",
        f"base_ref: {checkout.base_ref}",
        f"base_sha: {checkout.base_sha}",
        f"head_sha: {checkout.head_sha}",
        f"head_ref: {checkout.head_ref}",
        f"changed_files: {len(checkout.changed_files)}",
    ]
    if checkout.title:
        lines.append(f"title: {checkout.title}")
    if checkout.web_url:
        lines.append(f"web_url: {checkout.web_url}")
    for note in checkout.notes:
        lines.append(f"note: {note}")

    lines.append("files:")
    for path in checkout.changed_files:
        lines.append(f"  {path}")
    if checkout.diff_stat:
        lines.append("diff_stat:")
        for line in checkout.diff_stat.splitlines():
            lines.append(f"  {line}")

    if report.skipped_lint:
        lines.append(f"skipped_lint: {len(report.skipped_lint)}")
        for path in report.skipped_lint:
            lines.append(f"  {path}")

    if report.python is not None:
        lines.append("")
        lines.append("=== python ===")
        lines.append(format_python_report(report.python, quiet=quiet).rstrip())

    if report.ansible is not None:
        lines.append("")
        lines.append("=== ansible ===")
        lines.append(format_ansible_report(report.ansible, quiet=quiet).rstrip())

    if include_diff and report.diff_patch:
        lines.append("")
        lines.append("=== diff ===")
        lines.append(report.diff_patch.rstrip())

    if report.cleanup is not None:
        lines.append("")
        lines.append("=== cleanup ===")
        lines.append(f"removed: {len(report.cleanup.removed)}")
        for path in report.cleanup.removed:
            lines.append(f"  {path}")
        if report.cleanup.skipped:
            lines.append(f"skipped: {len(report.cleanup.skipped)}")

    lines.append("")
    lines.append(f"lint: {'PASS' if report.lint_ok else 'FAIL'}")
    lines.append(f"overall: {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(lines) + "\n"


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
    help="Reuse existing clone; only recompute diff and lint",
)
@click.option(
    "--skip-lint",
    is_flag=True,
    help="Clone and list changes only; skip linters",
)
@click.option(
    "--include-diff",
    is_flag=True,
    help="Include full patch in text/JSON output",
)
@click.option(
    "--cleanup",
    is_flag=True,
    help="Remove the review clone after the run",
)
@click.option(
    "--cleanup-dry-run",
    is_flag=True,
    help="With --cleanup, show removal without deleting",
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
    help="Omit linter command output from text report",
)
def cli(
    reference: str,
    root: Path | None,
    name: str | None,
    platform: str | None,
    host: str | None,
    no_refresh: bool,
    skip_lint: bool,
    include_diff: bool,
    cleanup: bool,
    cleanup_dry_run: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Run the review-changes workflow for a GitHub PR or GitLab MR.

    REFERENCE is a PR/MR URL, or shorthand owner/repo#N / group/proj!N.

    Steps: clone-review → lint changed Python/Ansible files present at HEAD
    (deleted paths are skipped) → optional cleanup.
    Code-quality evaluation remains for the agent after linter output.
    """
    try:
        report = run_review(
            reference,
            reviews_root=root,
            dirname=name,
            platform=platform.lower() if platform else None,
            host=host,
            refresh=not no_refresh,
            skip_lint=skip_lint,
            include_diff=include_diff,
            cleanup=cleanup,
            cleanup_dry_run=cleanup_dry_run,
        )
    except CloneReviewError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc
    except (FileNotFoundError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(
            json.dumps(
                report.to_dict(include_diff=include_diff),
                indent=2,
                sort_keys=True,
            ),
        )
    else:
        click.echo(
            format_report(
                report,
                quiet=quiet,
                include_diff=include_diff,
            ),
            nl=False,
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="review-pr", standalone_mode=False)
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
