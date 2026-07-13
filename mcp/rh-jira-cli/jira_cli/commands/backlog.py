"""Backlog: my pre-sprint issues (assignee or reporter) in New/Refinement/Backlog."""

from __future__ import annotations

import json
from typing import Any, TextIO

from jira_cli.api import JiraClient
from jira_cli.commands import agenda as agenda_cmd
from jira_cli.commands import list_issues as list_issues_cmd
from jira_cli.commands.edit_issue import resolve_custom_field_key_by_display_name
from jira_cli.commands.show_issue import _short_story_points_field_raw
from jira_cli.config import Settings
from jira_cli.jql import jql_quote
from jira_cli.sprint_listing import fetch_project_sprint_rows

DEFAULT_SPRINT_PROJECT = agenda_cmd.DEFAULT_SPRINT_PROJECT
DEFAULT_SPRINT_PATTERN = agenda_cmd.DEFAULT_SPRINT_PATTERN
DEFAULT_PREFERRED_BOARD = agenda_cmd.DEFAULT_PREFERRED_BOARD
DEFAULT_BACKLOG_STATUSES = ("New", "Refinement", "Backlog")

_RELATION_ASSIGNEE = "Assignee"
_RELATION_REPORTER = "Reporter"


def build_backlog_jql(
    *,
    status_names: tuple[str, ...] = DEFAULT_BACKLOG_STATUSES,
    sprint_id: int,
    project: str | None = None,
) -> str:
    """JQL for backlog: mine (assignee or reporter), backlog statuses, not in current sprint."""
    ownership = "(assignee = currentUser() OR reporter = currentUser())"
    statuses = ", ".join(jql_quote(name) for name in status_names)
    status_clause = f"status IN ({statuses})"
    sprint_clause = f"sprint not in ({int(sprint_id)})"
    parts = [ownership, status_clause, sprint_clause]
    if project is not None and str(project).strip():
        parts.insert(0, f"project = {jql_quote(str(project).strip().upper())}")
    main = " AND ".join(f"({part})" for part in parts)
    return f"{main} ORDER BY status ASC, updated DESC"


def _resolve_sprint_field_id(client: JiraClient) -> str | None:
    return resolve_custom_field_key_by_display_name(client, "Sprint")


def _sprint_raw_from_fields(
    fields: dict[str, Any],
    sprint_field_id: str | None,
) -> Any:
    if sprint_field_id and sprint_field_id in fields:
        return fields[sprint_field_id]
    if "Sprint" in fields:
        return fields["Sprint"]
    return None


def _sprint_names_from_fields(
    fields: dict[str, Any],
    sprint_field_id: str | None,
) -> list[str]:
    sprint = _sprint_raw_from_fields(fields, sprint_field_id)
    if sprint is None:
        return []
    names: list[str] = []
    if isinstance(sprint, list):
        for item in sprint:
            if isinstance(item, dict):
                nm = item.get("name")
                if isinstance(nm, str) and nm.strip():
                    names.append(nm.strip())
    elif isinstance(sprint, dict):
        nm = sprint.get("name")
        if isinstance(nm, str) and nm.strip():
            names.append(nm.strip())
    return names


def _backlog_sprint_cell(issue: dict[str, Any], sprint_field_id: str | None) -> str:
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return "-"
    names = _sprint_names_from_fields(fields, sprint_field_id)
    return ", ".join(names) if names else "-"


def _account_id_matches_user_field(fields: dict[str, Any], field: str, account_id: str) -> bool:
    value = fields.get(field)
    if not isinstance(value, dict):
        return False
    aid = value.get("accountId")
    return isinstance(aid, str) and aid.strip() == account_id


def my_relation_on_issue(issue: dict[str, Any], account_id: str | None) -> list[str]:
    """How the current user relates to the issue (Assignee and/or Reporter)."""
    if not account_id:
        return []
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return []
    relations: list[str] = []
    if _account_id_matches_user_field(fields, "assignee", account_id):
        relations.append(_RELATION_ASSIGNEE)
    if _account_id_matches_user_field(fields, "reporter", account_id):
        relations.append(_RELATION_REPORTER)
    return relations


def _annotate_issues(
    issues: list[dict[str, Any]],
    account_id: str | None,
    role_field_ids: agenda_cmd._RoleFieldIds,
    git_pull_request_field_id: str | None,
    sprint_field_id: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for issue in issues:
        enriched = dict(issue)
        if account_id:
            enriched["my_relation"] = my_relation_on_issue(issue, account_id)
            enriched["my_roles"] = agenda_cmd.my_roles_on_issue(
                issue, account_id, role_field_ids
            )
        sprint_cell = _backlog_sprint_cell(issue, sprint_field_id)
        enriched["sprint"] = None if sprint_cell == "-" else sprint_cell
        pr = agenda_cmd._agenda_git_pull_request_text(issue, git_pull_request_field_id)
        if pr:
            enriched["git_pull_request"] = pr
        out.append(enriched)
    return out


def _issue_status_name(issue: dict[str, Any]) -> str:
    return str(((issue.get("fields") or {}).get("status") or {}).get("name") or "")


def _story_points_value(issue: dict[str, Any], story_points_field_id: str | None) -> float | None:
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_story_points_field_raw(fields, story_points_field_id)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def partition_backlog_issues(
    issues: list[dict[str, Any]],
    *,
    status_names: tuple[str, ...] = DEFAULT_BACKLOG_STATUSES,
) -> dict[str, list[dict[str, Any]]]:
    """Group issues by backlog status (stable workflow order)."""
    by_status: dict[str, list[dict[str, Any]]] = {name: [] for name in status_names}
    other: list[dict[str, Any]] = []
    for issue in issues:
        status = _issue_status_name(issue)
        if status in by_status:
            by_status[status].append(issue)
        else:
            other.append(issue)
    if other:
        by_status["Other"] = other
    return {name: items for name, items in by_status.items() if items}


def sort_backlog_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flat list ordered by status workflow, then updated desc within each status."""
    parts = partition_backlog_issues(issues)
    ordered: list[dict[str, Any]] = []
    for status_name in (*DEFAULT_BACKLOG_STATUSES, "Other"):
        section = parts.get(status_name)
        if not section:
            continue
        ordered.extend(
            sorted(
                section,
                key=lambda i: str((i.get("fields") or {}).get("updated") or ""),
                reverse=True,
            )
        )
    return ordered


def _filter_future_sprints(
    rows: list[dict[str, Any]],
    *,
    pattern: str,
    preferred_board: str | None,
) -> list[dict[str, Any]]:
    future = [
        r
        for r in rows
        if str(r.get("state") or "").lower() == "future" and r.get("id") is not None
    ]
    matches = [
        r
        for r in future
        if agenda_cmd._sprint_name_matches(str(r.get("name") or ""), pattern)
    ]
    if not matches:
        return future
    if preferred_board:
        pref = preferred_board.strip().lower()
        board_matches = [
            r for r in matches if str(r.get("board_name") or "").strip().lower() == pref
        ]
        if board_matches:
            return board_matches
    return matches


def _backlog_search_fields(
    *,
    story_points_field_id: str | None,
    role_field_ids: agenda_cmd._RoleFieldIds,
    git_pull_request_field_id: str | None,
    sprint_field_id: str | None,
) -> list[str]:
    fields = agenda_cmd._agenda_search_fields(
        story_points_field_id=story_points_field_id,
        role_field_ids=role_field_ids,
        git_pull_request_field_id=git_pull_request_field_id,
    )
    for extra in ("reporter", "issuetype", "created"):
        if extra not in fields:
            fields.append(extra)
    if sprint_field_id and sprint_field_id not in fields:
        fields.append(sprint_field_id)
    return fields


def _sum_story_points(
    issues: list[dict[str, Any]],
    story_points_field_id: str | None,
) -> tuple[float, int]:
    total = 0.0
    unset = 0
    for issue in issues:
        sp = _story_points_value(issue, story_points_field_id)
        if sp is None:
            unset += 1
        else:
            total += sp
    return total, unset


def fetch_backlog_data(
    client: JiraClient,
    settings: Settings,
    *,
    sprint: str | None = None,
    sprint_pattern: str | None = None,
    sprint_project: str = DEFAULT_SPRINT_PROJECT,
    preferred_board: str | None = DEFAULT_PREFERRED_BOARD,
    refresh_sprint_cache: bool = True,
    max_results: int = 100,
    story_points_field_id: str | None = None,
    status_names: tuple[str, ...] = DEFAULT_BACKLOG_STATUSES,
    include_future_sprints: bool = True,
    err: TextIO,
) -> dict[str, Any] | None:
    """Structured backlog payload or ``None`` on failure (messages on ``err``)."""
    project = sprint_project.strip().upper()
    sprint_id, sprint_row = agenda_cmd.resolve_agenda_sprint(
        client,
        sprint=sprint,
        sprint_pattern=sprint_pattern,
        sprint_project=project,
        preferred_board=preferred_board,
        refresh_sprint_cache=refresh_sprint_cache,
        err=err,
    )
    if sprint_id is None:
        return None

    role_field_ids = agenda_cmd._resolve_role_field_ids(client, settings)
    git_pull_request_field_id = agenda_cmd._resolve_git_pull_request_field_id(client, settings)
    sprint_field_id = _resolve_sprint_field_id(client)
    account_id = agenda_cmd._resolve_current_user_account_id(client, settings)
    if account_id is None:
        print(
            "jira-cli backlog: could not resolve current user accountId; relation column will be empty.",
            file=err,
        )

    jql = build_backlog_jql(
        status_names=status_names,
        sprint_id=sprint_id,
        project=project,
    )
    search_fields = _backlog_search_fields(
        story_points_field_id=story_points_field_id,
        role_field_ids=role_field_ids,
        git_pull_request_field_id=git_pull_request_field_id,
        sprint_field_id=sprint_field_id,
    )
    data = client.search(
        jql,
        fields=search_fields,
        max_results=max_results,
    )
    issues = data.get("issues") or []
    sorted_issues = sort_backlog_issues(
        _annotate_issues(
            issues,
            account_id,
            role_field_ids,
            git_pull_request_field_id,
            sprint_field_id,
        )
    )
    sections = partition_backlog_issues(sorted_issues, status_names=status_names)
    points_total, points_unset = _sum_story_points(sorted_issues, story_points_field_id)

    pattern = (
        sprint_pattern.strip()
        if sprint_pattern is not None and str(sprint_pattern).strip()
        else DEFAULT_SPRINT_PATTERN
    )
    future_sprints: list[dict[str, Any]] = []
    if include_future_sprints:
        future_rows, fetch_err = fetch_project_sprint_rows(
            client,
            project=project,
            state="future",
            refresh_sprint_cache=refresh_sprint_cache,
        )
        if fetch_err:
            print(f"jira-cli backlog: future sprints: {fetch_err}", file=err)
        else:
            future_sprints = _filter_future_sprints(
                future_rows,
                pattern=pattern,
                preferred_board=preferred_board,
            )

    sprint_name = ""
    board_name = ""
    if sprint_row:
        sprint_name = str(sprint_row.get("name") or "")
        board_name = str(sprint_row.get("board_name") or "")

    return {
        "sprint": {
            "id": sprint_id,
            "name": sprint_name,
            "board_name": board_name,
            "project": project,
        },
        "jql": jql,
        "statuses": list(status_names),
        "git_pull_request_field_id": git_pull_request_field_id,
        "sprint_field_id": sprint_field_id,
        "sections": sections,
        "issues": sorted_issues,
        "total": len(sorted_issues),
        "story_points": {
            "total": points_total,
            "unset_count": points_unset,
        },
        "future_sprints": future_sprints,
    }


def _format_relation(relations: list[str]) -> str:
    return ", ".join(relations) if relations else "-"


def _print_backlog_line(
    issue: dict[str, Any],
    out: TextIO,
    *,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    sprint_field_id: str | None = None,
    git_pull_request_field_id: str | None = None,
) -> None:
    key = issue.get("key", "")
    flds = issue.get("fields") or {}
    summary = (flds.get("summary") or "").replace("\n", " ")
    st = (flds.get("status") or {}).get("name") or ""
    relation = _format_relation(issue.get("my_relation") or [])
    sprint = issue.get("sprint") or _backlog_sprint_cell(issue, sprint_field_id)
    if show_story_points:
        sp = list_issues_cmd._story_points_list_cell(flds, story_points_field_id)
        line = f"{key}\t{relation}\t{st}\t{sprint}\t{sp}\t{summary}"
    else:
        line = f"{key}\t{relation}\t{st}\t{sprint}\t{summary}"
    pr = issue.get("git_pull_request") or agenda_cmd._agenda_git_pull_request_text(
        issue, git_pull_request_field_id
    )
    if pr:
        line = f"{line}\t{pr}"
    print(line, file=out)


def _print_backlog_sections(
    issues: list[dict[str, Any]],
    out: TextIO,
    *,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    sprint_field_id: str | None = None,
    git_pull_request_field_id: str | None = None,
    status_names: tuple[str, ...] = DEFAULT_BACKLOG_STATUSES,
) -> None:
    if not issues:
        print("No backlog issues found.", file=out)
        return

    parts = partition_backlog_issues(issues, status_names=status_names)
    printed_any = False
    for title in (*status_names, "Other"):
        section_issues = parts.get(title)
        if not section_issues:
            continue
        if printed_any:
            print(file=out)
        print(title, file=out)
        for issue in section_issues:
            _print_backlog_line(
                issue,
                out,
                show_story_points=show_story_points,
                story_points_field_id=story_points_field_id,
                sprint_field_id=sprint_field_id,
                git_pull_request_field_id=git_pull_request_field_id,
            )
        printed_any = True


def run_backlog(
    client: JiraClient,
    settings: Settings,
    *,
    sprint: str | None = None,
    sprint_pattern: str | None = None,
    sprint_project: str = DEFAULT_SPRINT_PROJECT,
    preferred_board: str | None = DEFAULT_PREFERRED_BOARD,
    refresh_sprint_cache: bool = True,
    max_results: int = 100,
    show_story_points: bool = True,
    story_points_field_id: str | None = None,
    status_names: tuple[str, ...] = DEFAULT_BACKLOG_STATUSES,
    include_future_sprints: bool = True,
    as_json: bool = False,
    out: TextIO,
    err: TextIO,
    debug: bool = False,
) -> int:
    payload = fetch_backlog_data(
        client,
        settings,
        sprint=sprint,
        sprint_pattern=sprint_pattern,
        sprint_project=sprint_project,
        preferred_board=preferred_board,
        refresh_sprint_cache=refresh_sprint_cache,
        max_results=max_results,
        story_points_field_id=story_points_field_id,
        status_names=status_names,
        include_future_sprints=include_future_sprints,
        err=err,
    )
    if payload is None:
        return 1

    sprint_info = payload["sprint"]
    sid = sprint_info["id"]
    sname = sprint_info.get("name") or ""
    board = sprint_info.get("board_name") or ""
    header = f"Excluding sprint: {sname} ({sid})" if sname else f"Excluding sprint: {sid}"
    if board:
        header = f"{header} [{board}]"
    print(header, file=err)
    sp_info = payload.get("story_points") or {}
    if show_story_points:
        total = sp_info.get("total", 0)
        unset = sp_info.get("unset_count", 0)
        print(
            f"Story points: {total:g} total ({unset} unset)",
            file=err,
        )
    if debug:
        print(f"JQL:\n{payload['jql']}\n", file=err)

    issues = payload["issues"]
    if as_json:
        json.dump(payload, out, indent=2)
        out.write("\n")
        return 0

    _print_backlog_sections(
        issues,
        out,
        show_story_points=show_story_points,
        story_points_field_id=story_points_field_id,
        sprint_field_id=payload.get("sprint_field_id"),
        git_pull_request_field_id=payload.get("git_pull_request_field_id"),
        status_names=status_names,
    )
    return 0
