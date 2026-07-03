"""Done: issues I touched today (updatedBy, with role-based fallback)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, TextIO

from jira_cli.api import JiraApiError, JiraClient
from jira_cli.commands import list_issues as list_issues_cmd
from jira_cli.config import Settings
from jira_cli.jql import (
    jql_quote,
    list_mine_base_or_clause,
)

STRATEGY_UPDATED_BY = "updated_by"
STRATEGY_ROLE_FALLBACK = "role_fallback"

_UPDATED_BY_EMPTY_NOTE = (
    "updatedBy returned no issues; used list-mine roles + updated date "
    "(updatedBy is often empty on redhat.atlassian.net)."
)


def parse_activity_date(activity_date: str | None) -> date | None:
    """Parse YYYY-MM-DD, or None for 'today' (``startOfDay()``)."""
    if activity_date is None or not str(activity_date).strip():
        return None
    raw = str(activity_date).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as e:
        raise ValueError(f"activity_date must be YYYY-MM-DD, got {raw!r}") from e


def build_done_updated_clause(activity_date: date | None) -> str:
    """``updated >= startOfDay()`` for today, else a half-open calendar-day range."""
    if activity_date is None:
        return "updated >= startOfDay()"
    day = activity_date.isoformat()
    nxt = (activity_date + timedelta(days=1)).isoformat()
    return f'updated >= "{day}" AND updated < "{nxt}"'


def build_done_updated_by_jql(
    *,
    updated_clause: str,
    project: str | None = None,
) -> str:
    """Prefer true updater history when the site indexes ``updatedBy``."""
    parts = ["updatedBy = currentUser()", updated_clause]
    if project is not None and str(project).strip():
        parts.insert(0, f"project = {jql_quote(str(project).strip().upper())}")
    return f"{' AND '.join(parts)} ORDER BY updated DESC"


def build_done_role_fallback_jql(
    *,
    updated_clause: str,
    contributors_field_id: str | None = None,
    project: str | None = None,
) -> str:
    """
    Fallback when ``updatedBy`` yields nothing: my list-mine roles and tickets
    updated in the window (may include updates by others on my tickets).
    """
    ownership = list_mine_base_or_clause(contributors_field_id)
    parts = [ownership, f"({updated_clause})"]
    if project is not None and str(project).strip():
        parts.insert(0, f"project = {jql_quote(str(project).strip().upper())}")
    return f"{' AND '.join(parts)} ORDER BY updated DESC"


def _search_fields() -> list[str]:
    return ["summary", "status", "issuetype", "updated", "assignee"]


def _print_done_lines(issues: list[dict[str, Any]], out: TextIO) -> None:
    for issue in issues:
        key = issue.get("key", "")
        flds = issue.get("fields") or {}
        summary = (flds.get("summary") or "").replace("\n", " ")
        st = (flds.get("status") or {}).get("name") or ""
        print(f"{key}\t{st}\t{summary}", file=out)


def fetch_done_data(
    client: JiraClient,
    settings: Settings,
    *,
    activity_date: str | None = None,
    project: str | None = None,
    max_results: int = 30,
    err: TextIO,
) -> dict[str, Any] | None:
    """
    Issues touched today (or on ``activity_date``).

    Tries ``updatedBy = currentUser()`` first; if empty, falls back to list-mine
    role OR + ``updated`` date window.
    """
    try:
        day = parse_activity_date(activity_date)
    except ValueError as e:
        print(f"jira-cli done: {e}", file=err)
        return None

    updated_clause = build_done_updated_clause(day)
    contrib = settings.contributors_field_id
    updated_by_jql = build_done_updated_by_jql(
        updated_clause=updated_clause,
        project=project,
    )

    try:
        updated_by_result = list_issues_cmd.search_issues_by_jql(
            client,
            updated_by_jql,
            max_results=max_results,
            all_fields=False,
        )
    except JiraApiError as e:
        print(f"jira-cli done: {e}", file=err)
        return None

    issues = list(updated_by_result.get("issues") or [])
    strategy = STRATEGY_UPDATED_BY
    jql = updated_by_jql
    note: str | None = None

    if not issues:
        role_jql = build_done_role_fallback_jql(
            updated_clause=updated_clause,
            contributors_field_id=contrib,
            project=project,
        )
        try:
            role_result = list_issues_cmd.search_issues_by_jql(
                client,
                role_jql,
                max_results=max_results,
                all_fields=False,
            )
        except JiraApiError as e:
            print(f"jira-cli done: {e}", file=err)
            return None
        issues = list(role_result.get("issues") or [])
        strategy = STRATEGY_ROLE_FALLBACK
        jql = role_jql
        note = _UPDATED_BY_EMPTY_NOTE

    return {
        "ok": True,
        "activity_date": day.isoformat() if day is not None else None,
        "strategy": strategy,
        "updated_by_empty": strategy == STRATEGY_ROLE_FALLBACK,
        "jql": jql,
        "issues": issues,
        "count": len(issues),
        "note": note,
        "fields": _search_fields(),
    }


def run_done(
    client: JiraClient,
    settings: Settings,
    *,
    activity_date: str | None = None,
    project: str | None = None,
    max_results: int = 30,
    as_json: bool = False,
    out: TextIO,
    err: TextIO,
    debug: bool = False,
) -> int:
    """CLI entry for ``jira-cli done``."""
    payload = fetch_done_data(
        client,
        settings,
        activity_date=activity_date,
        project=project,
        max_results=max_results,
        err=err,
    )
    if payload is None:
        return 1
    if debug:
        print(f"JQL:\n{payload['jql']}\n", file=err)
        if payload.get("note"):
            print(payload["note"], file=err)
    if as_json:
        print(json.dumps(payload, indent=2, default=str), file=out)
        return 0
    issues = payload.get("issues") or []
    if not issues:
        print("No issues found.", file=out)
        return 0
    _print_done_lines(issues, out)
    return 0
