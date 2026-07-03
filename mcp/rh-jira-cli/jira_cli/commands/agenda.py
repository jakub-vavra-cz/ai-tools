"""Agenda: current sprint + my unfinished issues (list-mine + sprint filter)."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from typing import Any, TextIO

from jira_cli.api import JiraClient
from jira_cli.commands import list_issues as list_issues_cmd
from jira_cli.commands.edit_issue import (
    custom_field_key_from_settings,
    resolve_custom_field_key_by_display_name,
)
from jira_cli.commands.show_issue import (
    _short_git_pull_request_display_value,
    _short_git_pull_request_field_raw,
)
from jira_cli.config import Settings
from jira_cli.jql import jql_quote
from jira_cli.sprint_listing import fetch_project_sprint_rows

DEFAULT_SPRINT_PROJECT = "IDM"
DEFAULT_SPRINT_PATTERN = "*IDM-SSSD*"
DEFAULT_PREFERRED_BOARD = "rhel-idm-sssd"
_IN_PROGRESS_STATUS = "In Progress"

_ROLE_ASSIGNEE = "Assignee"
_ROLE_DEVELOPER = "Developer"
_ROLE_CONTRIBUTOR = "Contributor"
_ROLE_QA_CONTACT = "QA Contact"
_ROLE_DOC_CONTACT = "Doc Contact"


@dataclass(frozen=True)
class _RoleFieldIds:
    developer: str | None
    qa_contact: str | None
    doc_contact: str | None
    contributors: str | None


def _story_points_api_field_id(field_id: str | None) -> str | None:
    return list_issues_cmd._story_points_api_field_id(field_id)


def _resolve_role_field_ids(client: JiraClient, settings: Settings) -> _RoleFieldIds:
    return _RoleFieldIds(
        developer=resolve_custom_field_key_by_display_name(client, "Developer"),
        qa_contact=resolve_custom_field_key_by_display_name(client, "QA Contact"),
        doc_contact=resolve_custom_field_key_by_display_name(client, "Doc Contact"),
        contributors=custom_field_key_from_settings(
            settings.contributors_field_id,
            "Contributors",
            client,
        ),
    )


def _resolve_current_user_account_id(client: JiraClient, settings: Settings) -> str | None:
    email = (settings.email or "").strip()
    if not email:
        return None
    user = client.find_user_by_email(email)
    if not user:
        return None
    aid = user.get("accountId")
    if isinstance(aid, str) and aid.strip():
        return aid.strip()
    return None


def _account_ids_in_user_value(value: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        aid = value.get("accountId")
        if isinstance(aid, str) and aid.strip():
            ids.add(aid.strip())
    elif isinstance(value, list):
        for item in value:
            ids.update(_account_ids_in_user_value(item))
    return ids


def _user_matches_field(fields: dict[str, Any], field_id: str | None, account_id: str) -> bool:
    if not field_id:
        return False
    return account_id in _account_ids_in_user_value(fields.get(field_id))


def my_roles_on_issue(
    issue: dict[str, Any],
    account_id: str,
    role_field_ids: _RoleFieldIds,
) -> list[str]:
    """Roles the current user holds on ``issue`` (stable display order)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return []
    roles: list[str] = []
    assignee = fields.get("assignee")
    if isinstance(assignee, dict) and account_id in _account_ids_in_user_value(assignee):
        roles.append(_ROLE_ASSIGNEE)
    if _user_matches_field(fields, role_field_ids.developer, account_id):
        roles.append(_ROLE_DEVELOPER)
    if _user_matches_field(fields, role_field_ids.contributors, account_id):
        roles.append(_ROLE_CONTRIBUTOR)
    if _user_matches_field(fields, role_field_ids.qa_contact, account_id):
        roles.append(_ROLE_QA_CONTACT)
    if _user_matches_field(fields, role_field_ids.doc_contact, account_id):
        roles.append(_ROLE_DOC_CONTACT)
    return roles


def _resolve_git_pull_request_field_id(
    client: JiraClient,
    settings: Settings,
) -> str | None:
    return custom_field_key_from_settings(
        settings.git_pull_request_field_id,
        "Git Pull Request",
        client,
    )


def _agenda_git_pull_request_text(
    issue: dict[str, Any],
    git_pull_request_field_id: str | None,
) -> str | None:
    """PR URL or dev-status summary when Git Pull Request is set."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_git_pull_request_field_raw(fields, git_pull_request_field_id)
    if raw is None:
        return None
    text = _short_git_pull_request_display_value(raw)
    if not text:
        return None
    return text.replace("\n", " ").strip()


def _agenda_search_fields(
    *,
    story_points_field_id: str | None,
    role_field_ids: _RoleFieldIds,
    git_pull_request_field_id: str | None,
) -> list[str]:
    fields = [
        "summary",
        "status",
        "assignee",
        "priority",
        "updated",
    ]
    for fid in (
        role_field_ids.developer,
        role_field_ids.qa_contact,
        role_field_ids.doc_contact,
        role_field_ids.contributors,
    ):
        if fid and fid not in fields:
            fields.append(fid)
    sp = _story_points_api_field_id(story_points_field_id)
    if sp and sp not in fields:
        fields.append(sp)
    if git_pull_request_field_id and git_pull_request_field_id not in fields:
        fields.append(git_pull_request_field_id)
    return fields


def _annotate_issues_with_roles(
    issues: list[dict[str, Any]],
    account_id: str | None,
    role_field_ids: _RoleFieldIds,
    git_pull_request_field_id: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for issue in issues:
        enriched = dict(issue)
        if account_id:
            enriched["my_roles"] = my_roles_on_issue(issue, account_id, role_field_ids)
        pr = _agenda_git_pull_request_text(issue, git_pull_request_field_id)
        if pr:
            enriched["git_pull_request"] = pr
        out.append(enriched)
    return out


def _format_roles(roles: list[str]) -> str:
    return ", ".join(roles) if roles else "-"


def _print_agenda_line(
    issue: dict[str, Any],
    out: TextIO,
    *,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    git_pull_request_field_id: str | None = None,
) -> None:
    key = issue.get("key", "")
    flds = issue.get("fields") or {}
    summary = (flds.get("summary") or "").replace("\n", " ")
    st = (flds.get("status") or {}).get("name") or ""
    roles = _format_roles(issue.get("my_roles") or [])
    if show_story_points:
        sp = list_issues_cmd._story_points_list_cell(flds, story_points_field_id)
        line = f"{key}\t{roles}\t{st}\t{sp}\t{summary}"
    else:
        line = f"{key}\t{roles}\t{st}\t{summary}"
    pr = issue.get("git_pull_request") or _agenda_git_pull_request_text(
        issue, git_pull_request_field_id
    )
    if pr:
        line = f"{line}\t{pr}"
    print(line, file=out)


def _sprint_name_matches(name: str, pattern: str) -> bool:
    n = name.strip()
    p = pattern.strip()
    if not n or not p:
        return False
    if fnmatch.fnmatch(n.lower(), p.lower()):
        return True
    # Treat bare substring patterns like IDM-SSSD as *IDM-SSSD*.
    if "*" not in p and "?" not in p:
        return p.lower() in n.lower()
    return False


def pick_active_sprint_row(
    rows: list[dict[str, Any]],
    *,
    pattern: str,
    preferred_board: str | None = None,
) -> dict[str, Any] | None:
    """Choose one active sprint row whose name matches ``pattern``."""
    active = [
        r for r in rows if str(r.get("state") or "").lower() == "active" and r.get("id") is not None
    ]
    matches = [r for r in active if _sprint_name_matches(str(r.get("name") or ""), pattern)]
    if not matches:
        return None
    if preferred_board:
        pref = preferred_board.strip().lower()
        for row in matches:
            if str(row.get("board_name") or "").strip().lower() == pref:
                return row
    return matches[0]


def resolve_agenda_sprint(
    client: JiraClient,
    *,
    sprint: str | None,
    sprint_pattern: str | None,
    sprint_project: str,
    preferred_board: str | None,
    refresh_sprint_cache: bool,
    err: TextIO,
) -> tuple[int | None, dict[str, Any] | None]:
    """
    Return ``(sprint_id, sprint_row)`` for agenda.

    ``sprint_row`` is set when resolved from active sprint listing (name/board metadata).
    """
    if sprint is not None and str(sprint).strip():
        sprint_id = list_issues_cmd.resolve_list_sprint_id(
            client,
            sprint,
            sprint_project,
            refresh_sprint_cache=refresh_sprint_cache,
            err=err,
        )
        if sprint_id is None:
            return None, None
        return sprint_id, {"id": sprint_id, "name": str(sprint).strip(), "board_name": ""}

    pattern = (
        sprint_pattern.strip()
        if sprint_pattern is not None and str(sprint_pattern).strip()
        else DEFAULT_SPRINT_PATTERN
    )
    project = sprint_project.strip().upper()
    rows, fetch_err = fetch_project_sprint_rows(
        client,
        project=project,
        state="active",
        refresh_sprint_cache=refresh_sprint_cache,
    )
    if fetch_err:
        print(f"jira-cli agenda: {fetch_err}", file=err)
        return None, None
    row = pick_active_sprint_row(
        rows,
        pattern=pattern,
        preferred_board=preferred_board,
    )
    if row is None:
        print(
            f"jira-cli agenda: no active sprint matching {pattern!r} in project {project}. "
            f"Try: jira-cli sprints {project} --state active",
            file=err,
        )
        return None, None
    sid = row.get("id")
    if not isinstance(sid, int):
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            print("jira-cli agenda: matched sprint has no numeric id.", file=err)
            return None, None
    return sid, row


def _issue_updated(issue: dict[str, Any]) -> str:
    return str((issue.get("fields") or {}).get("updated") or "")


def _issue_status_name(issue: dict[str, Any]) -> str:
    return str(((issue.get("fields") or {}).get("status") or {}).get("name") or "")


def _is_contributor_issue(issue: dict[str, Any]) -> bool:
    return _ROLE_CONTRIBUTOR in (issue.get("my_roles") or [])


def _sort_by_updated_desc(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(issues, key=_issue_updated, reverse=True)


def partition_agenda_issues(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split issues into In Progress, Other open, and Contributor sections."""
    contributor = [i for i in issues if _is_contributor_issue(i)]
    primary = [i for i in issues if i not in contributor]
    in_progress = [i for i in primary if _issue_status_name(i) == _IN_PROGRESS_STATUS]
    other = [i for i in primary if i not in in_progress]
    return {
        "in_progress": _sort_by_updated_desc(in_progress),
        "other_open": _sort_by_updated_desc(other),
        "contributor": _sort_by_updated_desc(contributor),
    }


def sort_agenda_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flat list: primary sections first, then contributor (each sorted)."""
    parts = partition_agenda_issues(issues)
    return parts["in_progress"] + parts["other_open"] + parts["contributor"]


def _print_agenda_section(
    title: str,
    issues: list[dict[str, Any]],
    out: TextIO,
    *,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    git_pull_request_field_id: str | None = None,
) -> None:
    if not issues:
        return
    print(title, file=out)
    for issue in issues:
        _print_agenda_line(
            issue,
            out,
            show_story_points=show_story_points,
            story_points_field_id=story_points_field_id,
            git_pull_request_field_id=git_pull_request_field_id,
        )


def _print_agenda_sections(
    issues: list[dict[str, Any]],
    out: TextIO,
    *,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    git_pull_request_field_id: str | None = None,
) -> None:
    if not issues:
        print("No unfinished issues found.", file=out)
        return

    parts = partition_agenda_issues(issues)
    sections = [
        ("In Progress", parts["in_progress"]),
        ("Other open", parts["other_open"]),
        ("Contributor", parts["contributor"]),
    ]
    printed_any = False
    for title, section_issues in sections:
        if not section_issues:
            continue
        if printed_any:
            print(file=out)
        _print_agenda_section(
            title,
            section_issues,
            out,
            show_story_points=show_story_points,
            story_points_field_id=story_points_field_id,
            git_pull_request_field_id=git_pull_request_field_id,
        )
        printed_any = True


def fetch_agenda_data(
    client: JiraClient,
    settings: Settings,
    *,
    sprint: str | None = None,
    sprint_pattern: str | None = None,
    sprint_project: str = DEFAULT_SPRINT_PROJECT,
    preferred_board: str | None = DEFAULT_PREFERRED_BOARD,
    refresh_sprint_cache: bool = True,
    max_results: int = 50,
    story_points_field_id: str | None = None,
    err: TextIO,
) -> dict[str, Any] | None:
    """Structured agenda payload or ``None`` on failure (messages on ``err``)."""
    project = sprint_project.strip().upper()
    sprint_id, sprint_row = resolve_agenda_sprint(
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

    role_field_ids = _resolve_role_field_ids(client, settings)
    git_pull_request_field_id = _resolve_git_pull_request_field_id(client, settings)
    account_id = _resolve_current_user_account_id(client, settings)
    if account_id is None:
        print(
            "jira-cli agenda: could not resolve current user accountId; role column will be empty.",
            file=err,
        )
    search_fields = _agenda_search_fields(
        story_points_field_id=story_points_field_id,
        role_field_ids=role_field_ids,
        git_pull_request_field_id=git_pull_request_field_id,
    )

    jql = list_issues_cmd.build_list_mine_jql(
        client,
        unfinished_only=True,
        sprint_id=sprint_id,
        contributors_field_id=settings.contributors_field_id,
    )
    data = client.search(
        jql,
        fields=search_fields,
        max_results=max_results,
    )
    issues = data.get("issues") or []
    fallback_used = False

    if not issues and sprint is None:
        fallback_jql = list_issues_cmd.build_list_mine_jql(
            client,
            unfinished_only=True,
            extra_jql=f"project = {jql_quote(project)} AND Sprint in openSprints()",
            contributors_field_id=settings.contributors_field_id,
        )
        data = client.search(
            fallback_jql,
            fields=search_fields,
            max_results=max_results,
        )
        issues = data.get("issues") or []
        jql = fallback_jql
        fallback_used = True

    sorted_issues = sort_agenda_issues(
        _annotate_issues_with_roles(
            issues,
            account_id,
            role_field_ids,
            git_pull_request_field_id,
        )
    )
    sections = partition_agenda_issues(sorted_issues)
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
        "fallback_used": fallback_used,
        "git_pull_request_field_id": git_pull_request_field_id,
        "sections": sections,
        "issues": sorted_issues,
        "total": len(sorted_issues),
    }


def run_agenda(
    client: JiraClient,
    settings: Settings,
    *,
    sprint: str | None = None,
    sprint_pattern: str | None = None,
    sprint_project: str = DEFAULT_SPRINT_PROJECT,
    preferred_board: str | None = DEFAULT_PREFERRED_BOARD,
    refresh_sprint_cache: bool = True,
    max_results: int = 50,
    show_story_points: bool = False,
    story_points_field_id: str | None = None,
    as_json: bool = False,
    out: TextIO,
    err: TextIO,
    debug: bool = False,
) -> int:
    payload = fetch_agenda_data(
        client,
        settings,
        sprint=sprint,
        sprint_pattern=sprint_pattern,
        sprint_project=sprint_project,
        preferred_board=preferred_board,
        refresh_sprint_cache=refresh_sprint_cache,
        max_results=max_results,
        story_points_field_id=story_points_field_id,
        err=err,
    )
    if payload is None:
        return 1

    sprint_info = payload["sprint"]
    sid = sprint_info["id"]
    sname = sprint_info.get("name") or ""
    board = sprint_info.get("board_name") or ""
    header = f"Sprint: {sname} ({sid})" if sname else f"Sprint: {sid}"
    if board:
        header = f"{header} [{board}]"
    print(header, file=err)
    if payload.get("fallback_used"):
        print(
            "Note: sprint filter returned no issues; used openSprints() fallback.",
            file=err,
        )
    if debug:
        print(f"JQL:\n{payload['jql']}\n", file=err)

    issues = payload["issues"]
    if as_json:
        json.dump(payload, out, indent=2)
        out.write("\n")
        return 0

    _print_agenda_sections(
        issues,
        out,
        show_story_points=show_story_points,
        story_points_field_id=story_points_field_id,
        git_pull_request_field_id=payload.get("git_pull_request_field_id"),
    )
    return 0
