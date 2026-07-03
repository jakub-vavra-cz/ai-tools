"""MCP (stdio) server for Jira. Requires ``pip install 'jira-cli[mcp]'``."""

from __future__ import annotations

import os
import sys
from typing import Any

from jira_cli.commands import agenda as agenda_cmd
from jira_cli.service import JiraService


def _require_mcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        print(
            "Install the MCP extra: pip install 'jira-cli[mcp]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    return FastMCP


def main() -> None:
    FastMCP = _require_mcp()
    os.environ.setdefault("JIRA_CLI_NO_INPUT", "1")

    _svc: dict[str, JiraService] = {}

    def get_svc() -> JiraService:
        if "x" not in _svc:
            _svc["x"] = JiraService()
        return _svc["x"]

    mcp = FastMCP(
        "jira-cli",
        instructions=(
            "Jira Cloud REST helpers. Set JIRA_URL, JIRA_EMAIL (or JIRA_USER), and JIRA_API_TOKEN. "
            "Use jira_search with jql= for full JQL; other search parameters combine like the CLI."
        ),
    )

    @mcp.tool()
    def jira_list_mine(
        max_results: int = 50,
        all_fields: bool = False,
        unfinished_only: bool = False,
        issue_type: str | None = None,
        extra_jql: str | None = None,
        sprint: str | None = None,
        sprint_project: str | None = None,
        refresh_sprint_cache: bool = False,
    ) -> dict[str, Any]:
        """Issues for the authenticated user (assignee, Developer, QA Contact, Doc Contact, Contributors)."""
        return get_svc().list_mine(
            max_results=max_results,
            all_fields=all_fields,
            unfinished_only=unfinished_only,
            issue_type=issue_type,
            extra_jql=extra_jql,
            sprint=sprint,
            sprint_project=sprint_project,
            refresh_sprint_cache=refresh_sprint_cache,
        )

    @mcp.tool()
    def jira_list_for_email(
        user_email: str,
        max_results: int = 50,
        all_fields: bool = False,
        unfinished_only: bool = False,
        issue_type: str | None = None,
        extra_jql: str | None = None,
        sprint: str | None = None,
        sprint_project: str | None = None,
        refresh_sprint_cache: bool = False,
    ) -> dict[str, Any]:
        """Same as list-mine but for a user resolved by email."""
        return get_svc().list_for_email(
            user_email,
            max_results=max_results,
            all_fields=all_fields,
            unfinished_only=unfinished_only,
            issue_type=issue_type,
            extra_jql=extra_jql,
            sprint=sprint,
            sprint_project=sprint_project,
            refresh_sprint_cache=refresh_sprint_cache,
        )

    @mcp.tool()
    def jira_search(
        jql: str | None = None,
        term: str | None = None,
        project: str | None = None,
        status: str | None = None,
        issue_type: str | None = None,
        max_results: int = 50,
        unfinished_only: bool = False,
        assignee_email: str | None = None,
        developer_email: str | None = None,
        qa_contact_email: str | None = None,
    ) -> dict[str, Any]:
        """Search issues (summary/status/issuetype fields). Pass jql= for a raw JQL query."""
        return get_svc().search(
            term=term,
            project=project,
            jql=jql,
            status=status,
            issue_type=issue_type,
            max_results=max_results,
            unfinished_only=unfinished_only,
            assignee_email=assignee_email,
            developer_email=developer_email,
            qa_contact_email=qa_contact_email,
        )

    @mcp.tool()
    def jira_get_issue(
        issue_key: str,
        brief: bool = False,
        compact: bool = False,
        short: bool = False,
        custom_id: bool = False,
        expand: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one issue. Default: full JSON with custom field display names. short= human-readable lines."""
        return get_svc().get_issue(
            issue_key,
            expand=expand,
            compact=compact,
            brief=brief,
            short=short,
            custom_id=custom_id,
        )

    @mcp.tool()
    def jira_create_issue(
        project: str,
        summary: str,
        issue_type: str = "Task",
        description: str | None = None,
        issuetype_name: str | None = None,
        parent_key: str | None = None,
        assignee_email: str | None = None,
        sprint: str | None = None,
        comment: str | None = None,
        transition: str | None = None,
    ) -> dict[str, Any]:
        """POST /rest/api/3/issue. Returns issue_key and create payload."""
        return get_svc().create_issue(
            project=project,
            summary=summary,
            issue_type=issue_type,
            issuetype_name=issuetype_name,
            description=description,
            parent_key=parent_key,
            assignee_email=assignee_email,
            sprint=sprint,
            comment=comment,
            transition=transition,
        )

    @mcp.tool()
    def jira_update_issue(
        issue_key: str,
        summary: str | None = None,
        description: str | None = None,
        comment: str | None = None,
        transition: str | None = None,
        sprint: str | None = None,
        story_points: float | None = None,
        assignee_email: str | None = None,
        assignee_clear: bool = False,
        reporter_email: str | None = None,
        reporter_clear: bool = False,
        developer_email: str | None = None,
        developer_clear: bool = False,
        qa_contact_email: str | None = None,
        qa_contact_clear: bool = False,
        doc_contact_email: str | None = None,
        doc_contact_clear: bool = False,
        contributors_emails: str | None = None,
        contributors_clear: bool = False,
        field_pairs: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Update fields / comments / sprint / transition like ``jira-cli edit``.
        field_pairs: entries ``KEY=VALUE`` resolved like ``--field`` (applied without extra prompt).
        Empty VALUE clears user-picker fields (e.g. ``QA Contact=``).
        """
        return get_svc().update_issue(
            issue_key,
            field_pairs=field_pairs,
            summary=summary,
            description=description,
            comment=comment,
            transition=transition,
            sprint=sprint,
            story_points=story_points,
            assignee_email=assignee_email,
            assignee_clear=assignee_clear,
            reporter_email=reporter_email,
            reporter_clear=reporter_clear,
            developer_email=developer_email,
            developer_clear=developer_clear,
            qa_contact_email=qa_contact_email,
            qa_contact_clear=qa_contact_clear,
            doc_contact_email=doc_contact_email,
            doc_contact_clear=doc_contact_clear,
            contributors_emails=contributors_emails,
            contributors_clear=contributors_clear,
        )

    @mcp.tool()
    def jira_agenda(
        sprint: str | None = None,
        sprint_pattern: str | None = None,
        sprint_project: str = agenda_cmd.DEFAULT_SPRINT_PROJECT,
        preferred_board: str | None = agenda_cmd.DEFAULT_PREFERRED_BOARD,
        refresh_sprint_cache: bool = True,
        max_results: int = 50,
        show_story_points: bool = False,
    ) -> dict[str, Any]:
        """
        My unfinished sprint tickets (same as ``jira-cli agenda --json``).

        Resolves the active sprint by default (pattern *IDM-SSSD* in project IDM).
        Returns sprint metadata, JQL, sections (in_progress, other_open, contributor),
        and issues with my_roles and optional git_pull_request.
        """
        return get_svc().agenda(
            sprint=sprint,
            sprint_pattern=sprint_pattern,
            sprint_project=sprint_project,
            preferred_board=preferred_board,
            refresh_sprint_cache=refresh_sprint_cache,
            max_results=max_results,
            show_story_points=show_story_points,
        )

    @mcp.tool()
    def jira_move_issue(
        issue_key: str,
        project: str,
        issue_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Move an issue to another project (POST /rest/api/3/bulk/issues/move).

        ``project`` is the target project key. ``issue_type`` is optional; defaults to
        keeping the current issue type name in the target project.
        """
        return get_svc().move_issue(
            issue_key,
            project=project,
            issue_type=issue_type,
        )

    @mcp.tool()
    def jira_list_fields(
        include_builtin: bool = False,
        search: str | None = None,
        search_regex: bool = False,
        id_name_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Field metadata from GET /rest/api/3/field (custom fields only unless include_builtin)."""
        return get_svc().list_fields(
            custom_only=not include_builtin,
            search=search,
            search_regex=search_regex,
            id_name_only=id_name_only,
        )

    @mcp.tool()
    def jira_get_transitions(issue_key: str) -> dict[str, Any]:
        """Workflow transitions available for the issue."""
        return get_svc().get_transitions(issue_key)

    @mcp.tool()
    def jira_list_sprints(
        project: str,
        state: str = "future,active",
        refresh_sprint_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """Sprint rows for Scrum boards in the project (id, state, board_name, name)."""
        return get_svc().list_sprints(
            project,
            state=state,
            refresh_sprint_cache=refresh_sprint_cache,
        )

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
