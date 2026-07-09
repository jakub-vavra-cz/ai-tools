"""Search issues by show-like fields or direct JQL."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from jira_cli.api import JiraApiError, JiraClient
from jira_cli.config import Settings
from jira_cli.jql import (
    add_jql_and_before_order,
    ensure_jql_order_by,
    jql_quote,
    jql_user_identity_for_clause,
    unfinished_condition_from_statuses,
)


def _issue_fields_for_output() -> list[str]:
    return ["summary", "status", "issuetype"]


def _print_issue_lines(issues: list[dict], out: TextIO) -> None:
    for issue in issues:
        key = issue.get("key", "")
        flds = issue.get("fields") or {}
        summary = (flds.get("summary") or "").replace("\n", " ")
        st = (flds.get("status") or {}).get("name") or ""
        it = (flds.get("issuetype") or {}).get("name") or ""
        print(f"{key}\t{summary}\t{it}\t{st}", file=out)


def _custom_field_ref(display_name: str, env_id: str | None) -> str:
    if env_id and isinstance(env_id, str) and env_id.strip():
        fid = env_id.strip()
        if fid.startswith("customfield_"):
            return fid
        if fid.isdigit():
            return f"customfield_{fid}"
    return jql_quote(display_name)


def _user_clause(client: JiraClient, field_ref: str, email: str, err: TextIO) -> str | None:
    user = client.find_user_by_email(email)
    if user is None:
        print(
            f"No unique Jira user found for email {email.strip()!r} "
            f"(try an exact address or check /rest/api/3/user/search).",
            file=err,
        )
        return None
    ident = jql_user_identity_for_clause(user)
    if ident is None:
        print(f"Resolved user {email.strip()!r} has no accountId/name/key for JQL.", file=err)
        return None
    return f"{field_ref} = {ident}"


def _project_jql(project: str) -> str | None:
    """JQL ``project = KEY`` or ``project in (KEY1, KEY2, ...)`` from comma-separated keys."""
    keys = [k.strip() for k in project.split(",") if k.strip()]
    if not keys:
        return None
    if len(keys) == 1:
        return f"project = {jql_quote(keys[0])}"
    return "project in (" + ", ".join(jql_quote(k) for k in keys) + ")"


def compose_ordered_search_jql(
    client: JiraClient,
    settings: Settings,
    *,
    term: str | None,
    summary_substring: str | None,
    project: str | None,
    direct_jql: str | None,
    status: str | None,
    issue_type: str | None,
    priority: str | None,
    severity: str | None,
    testing: str | None,
    coverage: str | None,
    build: str | None,
    test_link: str | None,
    team: str | None,
    due: str | None,
    assignee_email: str | None,
    reporter_email: str | None,
    qa_contact_email: str | None,
    developer_email: str | None,
    doc_contact_email: str | None,
    unfinished_only: bool = False,
    err: TextIO | None = None,
) -> str:
    """
    Build the final JQL string for ``search`` (including ``ORDER BY``).

    Raises ``ValueError`` for invalid input (same messages the CLI prints).
    ``err`` is only used for ``_user_clause`` error printing when provided.
    """
    err_io = err if err is not None else sys.stderr

    has_filter_args = any(
        [
            term,
            summary_substring,
            project,
            status,
            issue_type,
            priority,
            severity,
            testing,
            coverage,
            build,
            test_link,
            team,
            due,
            assignee_email,
            reporter_email,
            qa_contact_email,
            developer_email,
            doc_contact_email,
        ]
    )
    if direct_jql and has_filter_args:
        raise ValueError("Use either field filters/TERM or --jql, not both.")

    unfinished_clause: str | None = None
    if unfinished_only:
        try:
            statuses = client.get_statuses()
            unfinished_clause = unfinished_condition_from_statuses(statuses)
        except JiraApiError:
            unfinished_clause = 'statusCategory != "Done"'

    clauses: list[str] = []
    if direct_jql and direct_jql.strip():
        jql = direct_jql.strip()
    else:
        if summary_substring and summary_substring.strip():
            sq = jql_quote(summary_substring.strip())
            clauses.append(f"summary ~ {sq}")

        if term and term.strip():
            q = jql_quote(term.strip())
            clauses.extend(
                [
                    f"summary ~ {q}",
                    f"description ~ {q}",
                    f"status = {q}",
                    f"issuetype = {q}",
                    f"priority = {q}",
                    f"{jql_quote('Severity')} ~ {q}",
                    f"{jql_quote('Preliminary Testing')} ~ {q}",
                    f"{jql_quote('Test Coverage')} ~ {q}",
                    f"{jql_quote('Fixed in Build')} ~ {q}",
                    f"{jql_quote('Test Link')} ~ {q}",
                    f"{_custom_field_ref('AssignedTeam', settings.assigned_team_field_id)} ~ {q}",
                    f"{jql_quote('QA Contact')} ~ {q}",
                    f"{jql_quote('Developer')} ~ {q}",
                    f"{jql_quote('Doc Contact')} ~ {q}",
                ]
            )

        if status and status.strip():
            clauses.append(f"status = {jql_quote(status.strip())}")
        if issue_type and issue_type.strip():
            clauses.append(f"issuetype = {jql_quote(issue_type.strip())}")
        if priority and priority.strip():
            clauses.append(f"priority = {jql_quote(priority.strip())}")
        if due and due.strip():
            clauses.append(f"duedate = {jql_quote(due.strip())}")

        for value, display_name, env_id in (
            (severity, "Severity", None),
            (testing, "Preliminary Testing", settings.preliminary_testing_field_id),
            (coverage, "Test Coverage", settings.test_coverage_field_id),
            (build, "Fixed in Build", settings.fixed_in_build_field_id),
            (test_link, "Test Link", settings.test_link_field_id),
            (team, "AssignedTeam", settings.assigned_team_field_id),
        ):
            if value and value.strip():
                clauses.append(
                    f"{_custom_field_ref(display_name, env_id)} = {jql_quote(value.strip())}"
                )

        for email, display_name, env_id in (
            (developer_email, "Developer", None),
            (qa_contact_email, "QA Contact", None),
            (doc_contact_email, "Doc Contact", None),
        ):
            if not (email and email.strip()):
                continue
            uc = _user_clause(
                client, _custom_field_ref(display_name, env_id), email.strip(), err_io
            )
            if uc is None:
                raise ValueError("Could not resolve user for JQL (developer/qa/doc contact).")
            clauses.append(uc)

        if assignee_email and assignee_email.strip():
            uc = _user_clause(client, "assignee", assignee_email.strip(), err_io)
            if uc is None:
                raise ValueError("Could not resolve assignee email for JQL.")
            clauses.append(uc)
        if reporter_email and reporter_email.strip():
            uc = _user_clause(client, "reporter", reporter_email.strip(), err_io)
            if uc is None:
                raise ValueError("Could not resolve reporter email for JQL.")
            clauses.append(uc)

        proj_clause = _project_jql(project) if project and project.strip() else None
        if not clauses and not proj_clause:
            if unfinished_only and unfinished_clause:
                jql = unfinished_clause
            else:
                raise ValueError(
                    "Provide TERM, one or more search filters, --project, --unfinished, or --jql."
                )
        elif proj_clause and clauses:
            jql = f"({proj_clause}) AND ({' OR '.join(clauses)})"
        elif proj_clause:
            jql = proj_clause
        else:
            jql = "(" + " OR ".join(clauses) + ")"

    if unfinished_only and unfinished_clause:
        if jql.strip() != unfinished_clause.strip():
            return add_jql_and_before_order(ensure_jql_order_by(jql), unfinished_clause)
        return ensure_jql_order_by(jql)
    return ensure_jql_order_by(jql)


def fetch_search_issues_data(
    client: JiraClient,
    settings: Settings,
    *,
    term: str | None,
    summary_substring: str | None,
    project: str | None,
    direct_jql: str | None,
    status: str | None,
    issue_type: str | None,
    priority: str | None,
    severity: str | None,
    testing: str | None,
    coverage: str | None,
    build: str | None,
    test_link: str | None,
    team: str | None,
    due: str | None,
    assignee_email: str | None,
    reporter_email: str | None,
    qa_contact_email: str | None,
    developer_email: str | None,
    doc_contact_email: str | None,
    unfinished_only: bool = False,
    max_results: int,
    err: TextIO | None = None,
) -> dict[str, Any]:
    """Structured ``search`` response (same JQL and fields as the CLI)."""
    ordered = compose_ordered_search_jql(
        client,
        settings,
        term=term,
        summary_substring=summary_substring,
        project=project,
        direct_jql=direct_jql,
        status=status,
        issue_type=issue_type,
        priority=priority,
        severity=severity,
        testing=testing,
        coverage=coverage,
        build=build,
        test_link=test_link,
        team=team,
        due=due,
        assignee_email=assignee_email,
        reporter_email=reporter_email,
        qa_contact_email=qa_contact_email,
        developer_email=developer_email,
        doc_contact_email=doc_contact_email,
        unfinished_only=unfinished_only,
        err=err,
    )
    return client.search(ordered, fields=_issue_fields_for_output(), max_results=max_results)


def run_search(
    client: JiraClient,
    settings: Settings,
    *,
    term: str | None,
    summary_substring: str | None,
    project: str | None,
    direct_jql: str | None,
    status: str | None,
    issue_type: str | None,
    priority: str | None,
    severity: str | None,
    testing: str | None,
    coverage: str | None,
    build: str | None,
    test_link: str | None,
    team: str | None,
    due: str | None,
    assignee_email: str | None,
    reporter_email: str | None,
    qa_contact_email: str | None,
    developer_email: str | None,
    doc_contact_email: str | None,
    unfinished_only: bool = False,
    max_results: int,
    as_json: bool,
    out: TextIO,
    err: TextIO,
    debug: bool = False,
) -> int:
    try:
        ordered = compose_ordered_search_jql(
            client,
            settings,
            term=term,
            summary_substring=summary_substring,
            project=project,
            direct_jql=direct_jql,
            status=status,
            issue_type=issue_type,
            priority=priority,
            severity=severity,
            testing=testing,
            coverage=coverage,
            build=build,
            test_link=test_link,
            team=team,
            due=due,
            assignee_email=assignee_email,
            reporter_email=reporter_email,
            qa_contact_email=qa_contact_email,
            developer_email=developer_email,
            doc_contact_email=doc_contact_email,
            unfinished_only=unfinished_only,
            err=err,
        )
    except ValueError as e:
        print(str(e), file=err)
        return 2

    if debug:
        print(f"JQL:\n{ordered}\n", file=err)

    data = client.search(ordered, fields=_issue_fields_for_output(), max_results=max_results)
    issues = data.get("issues") or []
    if as_json:
        json.dump(data, out, indent=2)
        out.write("\n")
        return 0

    _print_issue_lines(issues, out)
    if not issues:
        print("No issues found.", file=out)
    return 0
