"""List issues: mine (assignee) or by assignee email."""

from __future__ import annotations

import json
import sys
from io import StringIO
from typing import Any, TextIO

from jira_cli.api import JiraApiError, JiraClient
from jira_cli.commands.edit_issue import (
    resolve_sprint_id_for_project,
    resolve_sprint_id_without_project,
)
from jira_cli.commands.show_issue import (
    _is_omitted_value,
    _short_custom_field_display_value,
    _short_story_points_field_raw,
)
from jira_cli.jql import (
    build_list_by_assignee_jql,
    build_list_jql,
    combine_list_filters,
    jql_user_identity_for_clause,
    unfinished_condition_from_statuses,
)


def _story_points_api_field_id(field_id: str | None) -> str | None:
    """REST ``fields`` entry for Story Points (``customfield_*`` or id as returned by settings)."""
    if not field_id or not isinstance(field_id, str):
        return None
    s = field_id.strip()
    if not s:
        return None
    if s.startswith("customfield_"):
        return s
    if s.isdigit():
        return f"customfield_{s}"
    return s


def _issue_fields_for_list(all_fields: bool, story_points_field_id: str | None = None) -> list[str]:
    if all_fields:
        return ["*all"]
    base = [
        "summary",
        "status",
        "assignee",
        "issuetype",
        "priority",
        "updated",
    ]
    sp = _story_points_api_field_id(story_points_field_id)
    if sp and sp not in base:
        base = [*base, sp]
    return base


def _story_points_list_cell(fields: dict[str, Any], story_points_field_id: str | None) -> str:
    """Tab column text; unset or empty values show as ``-``."""
    raw = _short_story_points_field_raw(fields, story_points_field_id)
    if _is_omitted_value(raw):
        return "-"
    text = _short_custom_field_display_value(raw)
    return text if text else "-"


def _print_issue_lines(
    issues: list[dict],
    out: TextIO,
    *,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
) -> None:
    for issue in issues:
        key = issue.get("key", "")
        flds = issue.get("fields") or {}
        summary = (flds.get("summary") or "").replace("\n", " ")
        st = (flds.get("status") or {}).get("name") or ""
        it = (flds.get("issuetype") or {}).get("name") or ""
        if show_story_points:
            sp = _story_points_list_cell(flds, story_points_field_id)
            line = f"{key}\t{it}\t{st}\t{sp}\t{summary}"
        else:
            line = f"{key}\t{it}\t{st}\t{summary}"
        print(line, file=out)


def search_issues_by_jql(
    client: JiraClient,
    jql: str,
    *,
    max_results: int,
    all_fields: bool,
    story_points_field_id: str | None = None,
) -> dict[str, Any]:
    """Run search for list-mine / list-by-email (structured result, no printing)."""
    return client.search(
        jql,
        fields=_issue_fields_for_list(all_fields, story_points_field_id),
        max_results=max_results,
    )


class ListIssuesUserError(Exception):
    """Email did not resolve to a unique Jira user (or user lacks JQL identity)."""


def resolve_list_sprint_id(
    client: JiraClient,
    sprint: str | None,
    sprint_project: str | None,
    *,
    refresh_sprint_cache: bool,
    err: TextIO,
) -> int | None:
    """
    Agile sprint id for ``list-mine`` / ``list`` JQL ``sprint = …``.

    Numeric ``sprint`` is returned as-is. A sprint **name** requires ``sprint_project``.
    On failure prints to ``err`` and returns ``None``.
    """
    if sprint is None or not str(sprint).strip():
        return None
    raw = str(sprint).strip()
    if raw.isdigit():
        return int(raw)
    try:
        if sprint_project is not None and str(sprint_project).strip():
            return resolve_sprint_id_for_project(
                client,
                str(sprint_project).strip().upper(),
                raw,
                refresh_sprint_cache=refresh_sprint_cache,
            )
        return resolve_sprint_id_without_project(
            client,
            raw,
            refresh_sprint_cache=refresh_sprint_cache,
        )
    except SystemExit as e:
        msg = str(e.args[0]) if e.args else str(e)
        print(msg, file=err)
        return None


def _run_search(
    client: JiraClient,
    jql: str,
    *,
    max_results: int,
    as_json: bool,
    all_fields: bool,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    out: TextIO,
    err: TextIO = sys.stderr,
    debug: bool = False,
) -> int:
    if debug:
        print(f"JQL:\n{jql}\n", file=err)
    sp_for_search = None
    if show_story_points and not all_fields and story_points_field_id:
        sp_for_search = story_points_field_id
    data = search_issues_by_jql(
        client,
        jql,
        max_results=max_results,
        all_fields=all_fields,
        story_points_field_id=sp_for_search,
    )
    issues = data.get("issues") or []

    if as_json or all_fields:
        json.dump(data, out, indent=2)
        out.write("\n")
        return 0

    _print_issue_lines(
        issues,
        out,
        show_story_points=show_story_points,
        story_points_field_id=story_points_field_id,
    )
    if not issues:
        print("No issues found.", file=out)
    return 0


def build_list_mine_jql(
    client: JiraClient,
    *,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    sprint_id: int | None = None,
    contributors_field_id: str | None = None,
) -> str:
    """JQL for ``list-mine`` (current user roles). May call the API for status names."""
    unfinished_clause: str | None = None
    if unfinished_only:
        try:
            statuses = client.get_statuses()
        except JiraApiError:
            unfinished_clause = 'statusCategory != "Done"'
        else:
            unfinished_clause = unfinished_condition_from_statuses(statuses)

    merged_extra = combine_list_filters(
        issue_type_name=issue_type,
        extra_jql=extra_jql,
        sprint_id=sprint_id,
    )
    return build_list_jql(
        unfinished_clause=unfinished_clause,
        extra_jql=merged_extra,
        contributors_field_id=contributors_field_id,
    )


def fetch_list_mine_data(
    client: JiraClient,
    *,
    max_results: int,
    all_fields: bool,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    sprint: str | None = None,
    sprint_project: str | None = None,
    refresh_sprint_cache: bool = False,
    contributors_field_id: str | None = None,
) -> dict[str, Any]:
    """Structured search response for issues where the current user is in list-mine roles."""
    err = StringIO()
    sprint_id = resolve_list_sprint_id(
        client,
        sprint,
        sprint_project,
        refresh_sprint_cache=refresh_sprint_cache,
        err=err,
    )
    if sprint is not None and str(sprint).strip() and sprint_id is None:
        raise ValueError(err.getvalue().strip() or "Sprint filter could not be resolved.")
    jql = build_list_mine_jql(
        client,
        unfinished_only=unfinished_only,
        issue_type=issue_type,
        extra_jql=extra_jql,
        sprint_id=sprint_id,
        contributors_field_id=contributors_field_id,
    )
    return search_issues_by_jql(
        client,
        jql,
        max_results=max_results,
        all_fields=all_fields,
    )


def build_list_by_email_jql(
    client: JiraClient,
    user_email: str,
    *,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    sprint_id: int | None = None,
    contributors_field_id: str | None = None,
) -> str:
    """JQL for ``list EMAIL``; raises ``ListIssuesUserError`` if the user cannot be resolved."""
    user = client.find_user_by_email(user_email)
    if user is None:
        raise ListIssuesUserError(
            f"No unique Jira user found for email {user_email.strip()!r} "
            f"(try an exact address or check /rest/api/3/user/search)."
        )
    if jql_user_identity_for_clause(user) is None:
        raise ListIssuesUserError("Resolved user has no accountId/name/key for JQL.")

    unfinished_clause: str | None = None
    if unfinished_only:
        try:
            statuses = client.get_statuses()
        except JiraApiError:
            unfinished_clause = 'statusCategory != "Done"'
        else:
            unfinished_clause = unfinished_condition_from_statuses(statuses)

    merged_extra = combine_list_filters(
        issue_type_name=issue_type,
        extra_jql=extra_jql,
        sprint_id=sprint_id,
    )
    return build_list_by_assignee_jql(
        user,
        unfinished_clause=unfinished_clause,
        extra_jql=merged_extra,
        contributors_field_id=contributors_field_id,
    )


def fetch_list_by_email_data(
    client: JiraClient,
    *,
    user_email: str,
    max_results: int,
    all_fields: bool,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    sprint: str | None = None,
    sprint_project: str | None = None,
    refresh_sprint_cache: bool = False,
    contributors_field_id: str | None = None,
) -> dict[str, Any]:
    """Structured search response for ``list`` by email (same JQL OR as list-mine)."""
    err = StringIO()
    sprint_id = resolve_list_sprint_id(
        client,
        sprint,
        sprint_project,
        refresh_sprint_cache=refresh_sprint_cache,
        err=err,
    )
    if sprint is not None and str(sprint).strip() and sprint_id is None:
        raise ValueError(err.getvalue().strip() or "Sprint filter could not be resolved.")
    jql = build_list_by_email_jql(
        client,
        user_email,
        unfinished_only=unfinished_only,
        issue_type=issue_type,
        extra_jql=extra_jql,
        sprint_id=sprint_id,
        contributors_field_id=contributors_field_id,
    )
    return search_issues_by_jql(client, jql, max_results=max_results, all_fields=all_fields)


def run_list_mine(
    client: JiraClient,
    *,
    max_results: int,
    as_json: bool,
    all_fields: bool,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    sprint: str | None = None,
    sprint_project: str | None = None,
    refresh_sprint_cache: bool = False,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    contributors_field_id: str | None = None,
    out: TextIO,
    err: TextIO = sys.stderr,
    debug: bool = False,
) -> int:
    """Issues where the current user is assignee, Developer, QA Contact, or Doc Contact."""
    sprint_id = resolve_list_sprint_id(
        client,
        sprint,
        sprint_project,
        refresh_sprint_cache=refresh_sprint_cache,
        err=err,
    )
    if sprint is not None and str(sprint).strip() and sprint_id is None:
        return 2
    jql = build_list_mine_jql(
        client,
        unfinished_only=unfinished_only,
        issue_type=issue_type,
        extra_jql=extra_jql,
        sprint_id=sprint_id,
        contributors_field_id=contributors_field_id,
    )
    return _run_search(
        client,
        jql,
        max_results=max_results,
        as_json=as_json,
        all_fields=all_fields,
        show_story_points=show_story_points,
        story_points_field_id=story_points_field_id,
        out=out,
        err=err,
        debug=debug,
    )


def run_list_by_email(
    client: JiraClient,
    *,
    user_email: str,
    max_results: int,
    as_json: bool,
    all_fields: bool,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    sprint: str | None = None,
    sprint_project: str | None = None,
    refresh_sprint_cache: bool = False,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    contributors_field_id: str | None = None,
    out: TextIO,
    err: TextIO,
    debug: bool = False,
) -> int:
    """Issues where the resolved user is assignee, Developer, QA Contact, or Doc Contact (same as list-mine)."""
    sprint_id = resolve_list_sprint_id(
        client,
        sprint,
        sprint_project,
        refresh_sprint_cache=refresh_sprint_cache,
        err=err,
    )
    if sprint is not None and str(sprint).strip() and sprint_id is None:
        return 2
    try:
        jql = build_list_by_email_jql(
            client,
            user_email,
            unfinished_only=unfinished_only,
            issue_type=issue_type,
            extra_jql=extra_jql,
            sprint_id=sprint_id,
            contributors_field_id=contributors_field_id,
        )
    except ListIssuesUserError as e:
        print(str(e), file=err)
        return 2
    return _run_search(
        client,
        jql,
        max_results=max_results,
        as_json=as_json,
        all_fields=all_fields,
        show_story_points=show_story_points,
        story_points_field_id=story_points_field_id,
        out=out,
        err=err,
        debug=debug,
    )


# Backwards-compatible name for tests / imports
def run_list(
    client: JiraClient,
    *,
    max_results: int,
    as_json: bool,
    all_fields: bool,
    unfinished_only: bool = False,
    issue_type: str | None = None,
    extra_jql: str | None = None,
    contributors_field_id: str | None = None,
    out: TextIO,
    err: TextIO = sys.stderr,
    debug: bool = False,
) -> int:
    return run_list_mine(
        client,
        max_results=max_results,
        as_json=as_json,
        all_fields=all_fields,
        unfinished_only=unfinished_only,
        issue_type=issue_type,
        extra_jql=extra_jql,
        sprint=None,
        sprint_project=None,
        refresh_sprint_cache=False,
        contributors_field_id=contributors_field_id,
        out=out,
        err=err,
        debug=debug,
    )
