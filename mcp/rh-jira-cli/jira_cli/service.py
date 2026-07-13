"""Programmatic API shared by the MCP server and other callers (structured data, no argparse)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any, Mapping, Optional

from jira_cli.api import JiraApiError, JiraClient
from jira_cli.commands import edit_issue as edit_issue_cmd
from jira_cli.commands import agenda as agenda_cmd
from jira_cli.commands import backlog as backlog_cmd
from jira_cli.commands import issue_link as issue_link_cmd
from jira_cli.commands import list_issues as list_issues_cmd
from jira_cli.commands import move_issue as move_issue_cmd
from jira_cli.commands import new_issue as new_issue_cmd
from jira_cli.commands import search_issues as search_issues_cmd
from jira_cli.commands import show_issue as show_issue_cmd
from jira_cli.config import ConfigError, Settings, load_settings
from jira_cli.sprint_listing import fetch_project_sprint_rows


class JiraService:
    """Thin façade over ``JiraClient`` and command modules; returns JSON-serializable structures."""

    def __init__(self, env: Optional[Mapping[str, str]] = None) -> None:
        self.settings: Settings = load_settings(dict(env) if env is not None else None)
        self.client = JiraClient(self.settings)

    def list_mine(
        self,
        *,
        max_results: int = 50,
        all_fields: bool = False,
        unfinished_only: bool = False,
        issue_type: str | None = None,
        extra_jql: str | None = None,
        sprint: str | None = None,
        sprint_project: str | None = None,
        refresh_sprint_cache: bool = False,
    ) -> dict[str, Any]:
        return list_issues_cmd.fetch_list_mine_data(
            self.client,
            max_results=max_results,
            all_fields=all_fields,
            unfinished_only=unfinished_only,
            issue_type=issue_type,
            extra_jql=extra_jql,
            sprint=sprint,
            sprint_project=sprint_project,
            refresh_sprint_cache=refresh_sprint_cache,
            contributors_field_id=self.settings.contributors_field_id,
        )

    def list_for_email(
        self,
        user_email: str,
        *,
        max_results: int = 50,
        all_fields: bool = False,
        unfinished_only: bool = False,
        issue_type: str | None = None,
        extra_jql: str | None = None,
        sprint: str | None = None,
        sprint_project: str | None = None,
        refresh_sprint_cache: bool = False,
    ) -> dict[str, Any]:
        try:
            return list_issues_cmd.fetch_list_by_email_data(
                self.client,
                user_email=user_email,
                max_results=max_results,
                all_fields=all_fields,
                unfinished_only=unfinished_only,
                issue_type=issue_type,
                extra_jql=extra_jql,
                sprint=sprint,
                sprint_project=sprint_project,
                refresh_sprint_cache=refresh_sprint_cache,
                contributors_field_id=self.settings.contributors_field_id,
            )
        except list_issues_cmd.ListIssuesUserError as e:
            raise ValueError(str(e)) from e

    def search(
        self,
        *,
        term: str | None = None,
        summary_substring: str | None = None,
        project: str | None = None,
        jql: str | None = None,
        status: str | None = None,
        issue_type: str | None = None,
        priority: str | None = None,
        severity: str | None = None,
        testing: str | None = None,
        coverage: str | None = None,
        build: str | None = None,
        test_link: str | None = None,
        team: str | None = None,
        due: str | None = None,
        assignee_email: str | None = None,
        reporter_email: str | None = None,
        qa_contact_email: str | None = None,
        developer_email: str | None = None,
        doc_contact_email: str | None = None,
        unfinished_only: bool = False,
        max_results: int = 50,
    ) -> dict[str, Any]:
        err = StringIO()
        try:
            return search_issues_cmd.fetch_search_issues_data(
                self.client,
                self.settings,
                term=term,
                summary_substring=summary_substring,
                project=project,
                direct_jql=jql,
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
                max_results=max_results,
                err=err,
            )
        except ValueError as e:
            detail = err.getvalue().strip()
            if detail:
                raise ValueError(f"{e}\n{detail}") from e
            raise

    def get_issue(
        self,
        issue_key: str,
        *,
        expand: str | None = None,
        compact: bool = False,
        brief: bool = False,
        short: bool = False,
        custom_id: bool = False,
    ) -> dict[str, Any]:
        out = StringIO()
        err = StringIO()
        rc = show_issue_cmd.run_show(
            self.client,
            issue_key,
            expand=expand,
            compact=compact,
            brief=brief,
            short=short,
            custom_id=custom_id,
            preliminary_testing_field_id=self.settings.preliminary_testing_field_id,
            fixed_in_build_field_id=self.settings.fixed_in_build_field_id,
            test_coverage_field_id=self.settings.test_coverage_field_id,
            test_link_field_id=self.settings.test_link_field_id,
            git_pull_request_field_id=self.settings.git_pull_request_field_id,
            story_points_field_id=self.settings.story_points_field_id,
            assigned_team_field_id=self.settings.assigned_team_field_id,
            out=out,
            err=err,
        )
        body = out.getvalue()
        err_text = err.getvalue().strip()
        if rc != 0:
            raise JiraApiError(err_text or f"show failed with exit code {rc}", status_code=None)
        if short:
            return {
                "issue_key": issue_key.strip().upper(),
                "format": "text",
                "body": body,
            }
        try:
            parsed: Any = json.loads(body)
        except json.JSONDecodeError as e:
            raise JiraApiError(f"Invalid JSON from show: {e}") from e
        if not isinstance(parsed, dict):
            raise JiraApiError("show output was not a JSON object")
        return {"issue_key": issue_key.strip().upper(), "format": "json", "issue": parsed}

    def create_issue(
        self,
        *,
        project: str,
        summary: str,
        issue_type: str = "Task",
        issuetype_name: str | None = None,
        description: str | None = None,
        story_points: float | None = None,
        sprint: str | None = None,
        comment: str | None = None,
        transition: str | None = None,
        refresh_sprint_cache: bool = False,
        assignee_email: str | None = None,
        reporter_email: str | None = None,
        priority_name: str | None = None,
        duedate: str | None = None,
        severity: str | None = None,
        preliminary_testing: str | None = None,
        test_coverage: str | None = None,
        fixed_in_build: str | None = None,
        test_link: str | None = None,
        developer_email: str | None = None,
        qa_contact_email: str | None = None,
        doc_contact_email: str | None = None,
        parent_key: str | None = None,
    ) -> dict[str, Any]:
        err = StringIO()
        payload, rc = new_issue_cmd.execute_new_issue(
            self.client,
            self.settings,
            project=project,
            summary=summary,
            issue_type=issue_type,
            issuetype_name=issuetype_name,
            description=description,
            story_points=story_points,
            sprint=sprint,
            comment=comment,
            transition=transition,
            refresh_sprint_cache=refresh_sprint_cache,
            assignee_email=assignee_email,
            reporter_email=reporter_email,
            priority_name=priority_name,
            duedate=duedate,
            severity=severity,
            preliminary_testing=preliminary_testing,
            test_coverage=test_coverage,
            fixed_in_build=fixed_in_build,
            test_link=test_link,
            developer_email=developer_email,
            qa_contact_email=qa_contact_email,
            doc_contact_email=doc_contact_email,
            parent_key=parent_key,
            err=err,
        )
        if rc != 0:
            msg = err.getvalue().strip() or f"create_issue failed with code {rc}"
            raise ValueError(msg) if rc == 2 else JiraApiError(msg, status_code=None)
        assert payload is not None
        return payload

    def list_fields(
        self,
        *,
        custom_only: bool = True,
        search: str | None = None,
        search_regex: bool = False,
        id_name_only: bool = False,
    ) -> list[dict[str, Any]]:
        err = StringIO()
        try:
            rows = field_map_cmd.fetch_fields_filtered(
                self.client,
                custom_only=custom_only,
                search=search,
                search_regex=search_regex,
                err=err,
            )
        except JiraApiError:
            raise
        if id_name_only:
            return [{"id": f.get("id"), "name": f.get("name")} for f in rows]
        return rows

    def get_transitions(self, issue_key: str) -> dict[str, Any]:
        return self.client.get_transitions(issue_key)

    def list_sprints(
        self,
        project: str,
        *,
        state: str = "future,active",
        refresh_sprint_cache: bool = False,
    ) -> list[dict[str, Any]]:
        rows, err_msg = fetch_project_sprint_rows(
            self.client,
            project=project,
            state=state,
            refresh_sprint_cache=refresh_sprint_cache,
        )
        if err_msg:
            raise JiraApiError(err_msg, status_code=None)
        return rows

    def update_issue(
        self,
        issue_key: str,
        *,
        field_pairs: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        story_points: Any | None = None,
        sprint: str | None = None,
        comment: str | None = None,
        comment_idx: int | None = None,
        delete_comment_idx: int | None = None,
        transition: str | None = None,
        refresh_sprint_cache: bool = False,
        assignee_email: str | None = None,
        assignee_clear: bool = False,
        reporter_email: str | None = None,
        reporter_clear: bool = False,
        priority_name: str | None = None,
        issuetype_name: str | None = None,
        duedate: str | None = None,
        clear_due: bool = False,
        severity: str | None = None,
        team: str | None = None,
        preliminary_testing: str | None = None,
        test_coverage: str | None = None,
        fixed_in_build: str | None = None,
        test_link: str | None = None,
        git_pull_request: str | None = None,
        developer_email: str | None = None,
        developer_clear: bool = False,
        qa_contact_email: str | None = None,
        qa_contact_clear: bool = False,
        doc_contact_email: str | None = None,
        doc_contact_clear: bool = False,
        contributors_emails: str | None = None,
        contributors_clear: bool = False,
    ) -> dict[str, Any]:
        """Apply the same updates as ``jira-cli edit`` (non-interactive)."""
        key = issue_key.strip().upper()
        err = StringIO()
        additional_fields = None
        if field_pairs:
            additional_fields, rc = edit_issue_cmd.run_edit_field_specs(
                self.client,
                self.settings,
                key,
                field_pairs,
                skip_confirm=True,
                force_no_input=True,
                err=err,
            )
            if rc != 0:
                msg = err.getvalue().strip() or f"field specs failed with code {rc}"
                raise ValueError(msg)

        sprint_lookup = sprint if sprint and not str(sprint).isdigit() else None
        sprint_id = int(sprint) if sprint and str(sprint).strip().isdigit() else None

        rc = edit_issue_cmd.apply_edit(
            self.client,
            self.settings,
            key,
            summary=summary,
            description=description,
            story_points=story_points,
            sprint_id=sprint_id,
            sprint_lookup=sprint_lookup,
            comment=comment,
            comment_idx=comment_idx,
            delete_comment_idx=delete_comment_idx,
            transition=transition,
            refresh_sprint_cache=refresh_sprint_cache,
            assignee_email=assignee_email,
            assignee_clear=assignee_clear,
            reporter_email=reporter_email,
            reporter_clear=reporter_clear,
            priority_name=priority_name,
            issuetype_name=issuetype_name,
            duedate=duedate,
            clear_due=clear_due,
            severity=severity,
            team=team,
            preliminary_testing=preliminary_testing,
            test_coverage=test_coverage,
            fixed_in_build=fixed_in_build,
            test_link=test_link,
            git_pull_request=git_pull_request,
            developer_email=developer_email,
            developer_clear=developer_clear,
            qa_contact_email=qa_contact_email,
            qa_contact_clear=qa_contact_clear,
            doc_contact_email=doc_contact_email,
            doc_contact_clear=doc_contact_clear,
            contributors_emails=contributors_emails,
            contributors_clear=contributors_clear,
            additional_fields=additional_fields,
            err=err,
        )
        err_text = err.getvalue().strip()
        if rc != 0:
            raise ValueError(err_text) if rc == 2 else JiraApiError(err_text or "edit failed", None)
        return {"issue_key": key, "ok": True, "messages": err_text or None}

    def agenda(
        self,
        *,
        sprint: str | None = None,
        sprint_pattern: str | None = None,
        sprint_project: str = agenda_cmd.DEFAULT_SPRINT_PROJECT,
        preferred_board: str | None = agenda_cmd.DEFAULT_PREFERRED_BOARD,
        refresh_sprint_cache: bool = True,
        max_results: int = 50,
        show_story_points: bool = False,
    ) -> dict[str, Any]:
        """Same structured payload as ``jira-cli agenda --json``."""
        err = StringIO()
        sp_id = self.settings.story_points_field_id
        if show_story_points and not sp_id:
            sp_id = edit_issue_cmd.resolve_story_points_field_id(self.client)
        if show_story_points and not sp_id:
            raise ValueError(
                "show_story_points requires a Story Points field "
                "(set JIRA_STORY_POINTS_FIELD_ID or ensure the site has one named Story Points)."
            )
        payload = agenda_cmd.fetch_agenda_data(
            self.client,
            self.settings,
            sprint=sprint,
            sprint_pattern=sprint_pattern,
            sprint_project=sprint_project,
            preferred_board=preferred_board,
            refresh_sprint_cache=refresh_sprint_cache,
            max_results=max_results,
            story_points_field_id=sp_id,
            err=err,
        )
        if payload is None:
            msg = err.getvalue().strip() or "agenda failed"
            raise JiraApiError(msg, status_code=None)
        return payload

    def backlog(
        self,
        *,
        sprint: str | None = None,
        sprint_pattern: str | None = None,
        sprint_project: str = backlog_cmd.DEFAULT_SPRINT_PROJECT,
        preferred_board: str | None = backlog_cmd.DEFAULT_PREFERRED_BOARD,
        refresh_sprint_cache: bool = True,
        max_results: int = 100,
        show_story_points: bool = True,
        include_future_sprints: bool = True,
    ) -> dict[str, Any]:
        """Same structured payload as ``jira-cli backlog --json``."""
        err = StringIO()
        sp_id = self.settings.story_points_field_id
        if show_story_points and not sp_id:
            sp_id = edit_issue_cmd.resolve_story_points_field_id(self.client)
        if show_story_points and not sp_id:
            raise ValueError(
                "show_story_points requires a Story Points field "
                "(set JIRA_STORY_POINTS_FIELD_ID or ensure the site has one named Story Points)."
            )
        payload = backlog_cmd.fetch_backlog_data(
            self.client,
            self.settings,
            sprint=sprint,
            sprint_pattern=sprint_pattern,
            sprint_project=sprint_project,
            preferred_board=preferred_board,
            refresh_sprint_cache=refresh_sprint_cache,
            max_results=max_results,
            story_points_field_id=sp_id,
            include_future_sprints=include_future_sprints,
            err=err,
        )
        if payload is None:
            msg = err.getvalue().strip() or "backlog failed"
            raise JiraApiError(msg, status_code=None)
        return payload

    def list_link_types(self, *, search: str | None = None) -> list[dict[str, Any]]:
        """GET /rest/api/3/issueLinkType (optional name/inward/outward filter)."""
        types = self.client.get_issue_link_types()
        if search is not None and search.strip():
            needle = search.strip().lower()
            types = [
                lt
                for lt in types
                if needle in str(lt.get("name") or "").lower()
                or needle in str(lt.get("inward") or "").lower()
                or needle in str(lt.get("outward") or "").lower()
            ]
        return types

    def create_issue_link(
        self,
        *,
        source_key: str,
        target_key: str,
        link_type: str,
        as_relationship: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """
        Link two issues from the source issue's perspective.

        ``as_relationship`` must match the link type inward/outward label on the source
        (e.g. ``blocks`` or ``is blocked by`` for type Blocks).
        """
        err = StringIO()
        result = issue_link_cmd.create_issue_link_between(
            self.client,
            source_key=source_key,
            target_key=target_key,
            link_type_name=link_type,
            as_relationship=as_relationship,
            comment=comment,
            err=err,
        )
        if result is None:
            msg = err.getvalue().strip() or "create_issue_link failed"
            raise JiraApiError(msg, status_code=None)
        return result

    def create_issue_link_explicit(
        self,
        *,
        link_type: str,
        inward_issue_key: str,
        outward_issue_key: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """POST /rest/api/3/issueLink with explicit inward/outward issue keys."""
        err = StringIO()
        result = issue_link_cmd.create_issue_link(
            self.client,
            link_type_name=link_type,
            inward_issue_key=inward_issue_key,
            outward_issue_key=outward_issue_key,
            comment=comment,
            err=err,
        )
        if result is None:
            msg = err.getvalue().strip() or "create_issue_link failed"
            raise JiraApiError(msg, status_code=None)
        return result

    def delete_issue_link(self, link_id: str) -> dict[str, Any]:
        """DELETE /rest/api/3/issueLink/{linkId}."""
        err = StringIO()
        ok = issue_link_cmd.delete_issue_link(self.client, link_id, err=err)
        if not ok:
            msg = err.getvalue().strip() or "delete_issue_link failed"
            raise JiraApiError(msg, status_code=None)
        return {"ok": True, "link_id": link_id.strip()}

    def list_issue_links(self, issue_key: str) -> dict[str, Any]:
        """Issue links on one ticket (compact rows)."""
        links = issue_link_cmd.fetch_issue_links(self.client, issue_key)
        rows = [
            issue_link_cmd.summarize_issue_link(link, perspective_key=issue_key)
            for link in links
        ]
        return {"issue_key": issue_key, "links": rows}

    def move_issue(
        self,
        issue_key: str,
        *,
        project: str,
        issue_type: str | None = None,
    ) -> dict[str, Any]:
        """Move an issue to another project (POST /rest/api/3/bulk/issues/move)."""
        err = StringIO()
        payload, rc = move_issue_cmd.execute_move_issue(
            self.client,
            issue_key=issue_key,
            project=project,
            issue_type=issue_type,
            err=err,
        )
        if rc != 0:
            msg = err.getvalue().strip() or f"move_issue failed with code {rc}"
            raise ValueError(msg) if rc == 2 else JiraApiError(msg, status_code=None)
        assert payload is not None
        return payload


def service_from_env(env: Optional[Mapping[str, str]] = None) -> JiraService:
    """Convenience: load settings and return a service (raises ``ConfigError`` if misconfigured)."""
    return JiraService(env=env)


__all__ = ["JiraService", "service_from_env", "ConfigError"]
