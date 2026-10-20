#!/usr/bin/env python3
"""Fetch and format GitLab merge-request comments via ``glab``.

Approved agent CLI for MR review threads (DiffNotes + plain notes) so agents
do not invent ad-hoc ``glab api`` / Python one-liners.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote

import click

from ai_tools.clone_review import (
    CloneReviewError,
    ParsedRef,
    gitlab_env,
    parse_ref,
    run_cmd,
    which,
)
from ai_tools.envfile import env_or_none


class GitlabMrCommentsError(RuntimeError):
    """Fatal error fetching or formatting MR comments."""


@dataclass
class MrComment:
    """One non-system (or included) MR note."""

    id: int
    author: str
    body: str
    created_at: str
    system: bool
    note_type: str | None = None
    resolvable: bool = False
    resolved: bool = False
    path: str | None = None
    new_line: int | None = None
    old_line: int | None = None
    web_url: str | None = None

    def location(self) -> str | None:
        if not self.path:
            return None
        line = self.new_line if self.new_line is not None else self.old_line
        if line is not None:
            return f"{self.path}:{line}"
        return self.path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["location"] = self.location()
        return data


@dataclass
class MrCommentsReport:
    """MR overview plus formatted comments."""

    host: str
    repo: str
    number: int
    title: str | None
    state: str | None
    author: str | None
    web_url: str | None
    description: str | None
    assignees: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)
    comments: list[MrComment] = field(default_factory=list)
    system_note_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "repo": self.repo,
            "number": self.number,
            "title": self.title,
            "state": self.state,
            "author": self.author,
            "web_url": self.web_url,
            "description": self.description,
            "assignees": self.assignees,
            "reviewers": self.reviewers,
            "system_note_count": self.system_note_count,
            "comments": [c.to_dict() for c in self.comments],
        }


def encode_project(repo: str) -> str:
    return quote(repo.strip().strip("/"), safe="")


def _usernames(people: Any) -> list[str]:
    if not isinstance(people, list):
        return []
    out: list[str] = []
    for person in people:
        if not isinstance(person, dict):
            continue
        name = person.get("username") or person.get("name")
        if name:
            out.append(str(name))
    return out


def _author_name(payload: dict[str, Any]) -> str | None:
    author = payload.get("author")
    if isinstance(author, dict):
        return str(author.get("username") or author.get("name") or "") or None
    return None


def parse_note(raw: dict[str, Any]) -> MrComment:
    """Map a GitLab note JSON object to ``MrComment``."""
    position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    path = position.get("new_path") or position.get("old_path")
    new_line = position.get("new_line")
    old_line = position.get("old_line")
    return MrComment(
        id=int(raw.get("id") or 0),
        author=_author_name(raw) or "unknown",
        body=str(raw.get("body") or "").rstrip(),
        created_at=str(raw.get("created_at") or ""),
        system=bool(raw.get("system")),
        note_type=raw.get("type"),
        resolvable=bool(raw.get("resolvable")),
        resolved=bool(raw.get("resolved")),
        path=str(path) if path else None,
        new_line=int(new_line) if new_line is not None else None,
        old_line=int(old_line) if old_line is not None else None,
    )


def fetch_mr_view(ref: ParsedRef) -> dict[str, Any]:
    """Return ``glab mr view -F json`` payload."""
    if not which("glab"):
        raise GitlabMrCommentsError("glab not found on PATH")
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
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise GitlabMrCommentsError(f"glab mr view failed: {detail}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitlabMrCommentsError(
            f"glab mr view returned non-JSON: {(proc.stdout or '')[:200]}"
        ) from exc
    if not isinstance(data, dict):
        raise GitlabMrCommentsError("glab mr view returned unexpected payload")
    return data


def fetch_mr_notes(ref: ParsedRef) -> list[dict[str, Any]]:
    """Return all MR notes via ``glab api --paginate``."""
    if not which("glab"):
        raise GitlabMrCommentsError("glab not found on PATH")
    path = f"projects/{encode_project(ref.repo)}/merge_requests/{ref.number}/notes"
    proc = run_cmd(
        [
            "glab",
            "api",
            "--hostname",
            ref.host,
            "--paginate",
            path,
        ],
        env=gitlab_env(ref.host),
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise GitlabMrCommentsError(f"glab api notes failed: {detail}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitlabMrCommentsError(
            f"glab api notes returned non-JSON: {(proc.stdout or '')[:200]}"
        ) from exc
    if not isinstance(data, list):
        raise GitlabMrCommentsError("glab api notes returned unexpected payload")
    return [item for item in data if isinstance(item, dict)]


def build_report(
    ref: ParsedRef,
    *,
    mr: dict[str, Any],
    notes: list[dict[str, Any]],
    include_system: bool = False,
) -> MrCommentsReport:
    """Filter and sort notes into an ``MrCommentsReport``."""
    comments: list[MrComment] = []
    system_count = 0
    for raw in notes:
        note = parse_note(raw)
        if note.system:
            system_count += 1
            if not include_system:
                continue
        if not note.body.strip():
            continue
        comments.append(note)
    comments.sort(key=lambda c: (c.created_at, c.id))

    return MrCommentsReport(
        host=ref.host,
        repo=ref.repo,
        number=ref.number,
        title=str(mr.get("title")) if mr.get("title") else None,
        state=str(mr.get("state")) if mr.get("state") else None,
        author=_author_name(mr),
        web_url=str(mr.get("web_url")) if mr.get("web_url") else ref.web_url,
        description=str(mr.get("description") or "").rstrip() or None,
        assignees=_usernames(mr.get("assignees")),
        reviewers=_usernames(mr.get("reviewers")),
        comments=comments,
        system_note_count=system_count,
    )


def fetch_mr_comments(
    reference: str,
    *,
    host: str | None = None,
    include_system: bool = False,
) -> MrCommentsReport:
    """Parse *reference*, fetch MR + notes, return a report."""
    try:
        ref = parse_ref(reference, platform="gitlab", host=host)
    except CloneReviewError as exc:
        raise GitlabMrCommentsError(str(exc)) from exc
    if ref.platform != "gitlab":
        raise GitlabMrCommentsError(
            f"expected a GitLab MR reference, got {ref.platform}: {reference!r}"
        )
    mr = fetch_mr_view(ref)
    notes = fetch_mr_notes(ref)
    return build_report(ref, mr=mr, notes=notes, include_system=include_system)


def format_report(
    report: MrCommentsReport,
    *,
    include_description: bool = True,
) -> str:
    """Human-readable MR comments for agents and terminals."""
    lines: list[str] = []
    title = report.title or "(no title)"
    lines.append(f"# MR !{report.number} — {title}")
    meta_bits = []
    if report.state:
        meta_bits.append(f"state: {report.state}")
    if report.author:
        meta_bits.append(f"author: {report.author}")
    if report.reviewers:
        meta_bits.append(f"reviewers: {', '.join(report.reviewers)}")
    if report.assignees:
        meta_bits.append(f"assignees: {', '.join(report.assignees)}")
    if meta_bits:
        lines.append(" | ".join(meta_bits))
    if report.web_url:
        lines.append(f"url: {report.web_url}")
    lines.append(f"repo: {report.repo} @ {report.host}")
    lines.append("")

    if include_description and report.description:
        lines.append("## Description")
        lines.append(report.description)
        lines.append("")

    n = len(report.comments)
    included_system = sum(1 for c in report.comments if c.system)
    if report.system_note_count and included_system == 0:
        sys_note = f" ({report.system_note_count} system notes omitted)"
    elif included_system:
        sys_note = f" (includes {included_system} system notes)"
    else:
        sys_note = ""
    lines.append(f"## Comments ({n}){sys_note}")
    if not report.comments:
        lines.append("(none)")
        lines.append("")
        return "\n".join(lines)

    lines.append("")
    for idx, comment in enumerate(report.comments, start=1):
        loc = comment.location()
        header = f"{idx}. [{comment.author}]"
        if loc:
            header += f" @{loc}"
        flags: list[str] = []
        if comment.system:
            flags.append("system")
        if comment.resolvable:
            flags.append("resolved" if comment.resolved else "unresolved")
        if flags:
            header += f" ({', '.join(flags)})"
        lines.append(header)
        for body_line in comment.body.splitlines() or [""]:
            lines.append(f"   {body_line}")
        lines.append("")
    return "\n".join(lines)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("reference")
@click.option(
    "--host",
    default=None,
    envvar="GITLAB_HOST",
    show_envvar=True,
    help="GitLab host for shorthand group/proj!N (default: $GITLAB_HOST / URL host)",
)
@click.option(
    "--include-system",
    is_flag=True,
    help="Include GitLab system notes (review requested, mentioned in, …)",
)
@click.option(
    "--no-description",
    is_flag=True,
    help="Omit MR description from text output",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON",
)
def cli(
    reference: str,
    host: str | None,
    include_system: bool,
    no_description: bool,
    as_json: bool,
) -> None:
    """Pull GitLab MR comments via glab and print a numbered review summary.

    REFERENCE is an MR URL or shorthand group/proj!N.
    For shorthand, host comes from ``--host`` / ``$GITLAB_HOST`` (ai-tools.env).
    """
    resolved_host = (host or "").strip() or env_or_none("GITLAB_HOST")
    try:
        report = fetch_mr_comments(
            reference,
            host=resolved_host,
            include_system=include_system,
        )
    except GitlabMrCommentsError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return
    click.echo(format_report(report, include_description=not no_description).rstrip("\n"))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="gitlab-mr-comments", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
