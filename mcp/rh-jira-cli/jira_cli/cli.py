"""CLI entrypoint for jira-cli."""

from __future__ import annotations

import argparse
import os
import sys

from jira_cli.api import JiraApiError, JiraClient
from jira_cli.config import ConfigError, load_settings
from jira_cli.commands import agenda as agenda_cmd
from jira_cli.commands import edit_issue as edit_issue_cmd
from jira_cli.commands import field_map as field_map_cmd
from jira_cli.commands import list_issues as list_issues_cmd
from jira_cli.commands import move_issue as move_issue_cmd
from jira_cli.commands import new_issue as new_issue_cmd
from jira_cli.commands import search_issues as search_issues_cmd
from jira_cli.commands import show_issue as show_issue_cmd
from jira_cli.interactive import collect_edit_actions


def _no_input(args: argparse.Namespace) -> bool:
    if getattr(args, "no_input", False):
        return True
    return os.environ.get("JIRA_CLI_NO_INPUT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _cmd_list_mine(client: JiraClient, settings, args: argparse.Namespace) -> int:
    show_sp = getattr(args, "show_story_points", False)
    sp_id = settings.story_points_field_id
    if show_sp and not sp_id:
        sp_id = edit_issue_cmd.resolve_story_points_field_id(client)
    if show_sp and not sp_id:
        print(
            "jira-cli list-mine: --show-story-points requires a Story Points field "
            "(set JIRA_STORY_POINTS_FIELD_ID or ensure the site has a custom field named Story Points).",
            file=sys.stderr,
        )
        return 2
    return list_issues_cmd.run_list_mine(
        client,
        max_results=args.max_results,
        as_json=args.json,
        all_fields=args.all_fields,
        unfinished_only=getattr(args, "unfinished", False),
        issue_type=getattr(args, "issue_type", None),
        extra_jql=args.jql,
        sprint=getattr(args, "sprint", None),
        sprint_project=getattr(args, "sprint_project", None),
        refresh_sprint_cache=getattr(args, "refresh_sprint_cache", False),
        show_story_points=show_sp,
        story_points_field_id=sp_id,
        contributors_field_id=settings.contributors_field_id,
        out=sys.stdout,
        err=sys.stderr,
        debug=getattr(args, "debug", False),
    )


def _cmd_list(client: JiraClient, settings, args: argparse.Namespace) -> int:
    raw = getattr(args, "email", None)
    user_email = (raw or "").strip() or (settings.email or "").strip()
    if not user_email:
        print(
            "jira-cli list: provide EMAIL or set JIRA_EMAIL (or JIRA_USER) for the assignee to look up.",
            file=sys.stderr,
        )
        return 2
    show_sp = getattr(args, "show_story_points", False)
    sp_id = settings.story_points_field_id
    if show_sp and not sp_id:
        sp_id = edit_issue_cmd.resolve_story_points_field_id(client)
    if show_sp and not sp_id:
        print(
            "jira-cli list: --show-story-points requires a Story Points field "
            "(set JIRA_STORY_POINTS_FIELD_ID or ensure the site has a custom field named Story Points).",
            file=sys.stderr,
        )
        return 2
    return list_issues_cmd.run_list_by_email(
        client,
        user_email=user_email,
        max_results=args.max_results,
        as_json=args.json,
        all_fields=args.all_fields,
        unfinished_only=getattr(args, "unfinished", False),
        issue_type=getattr(args, "issue_type", None),
        extra_jql=args.jql,
        sprint=getattr(args, "sprint", None),
        sprint_project=getattr(args, "sprint_project", None),
        refresh_sprint_cache=getattr(args, "refresh_sprint_cache", False),
        show_story_points=show_sp,
        story_points_field_id=sp_id,
        contributors_field_id=settings.contributors_field_id,
        out=sys.stdout,
        err=sys.stderr,
        debug=getattr(args, "debug", False),
    )


def _cmd_search(client: JiraClient, settings, args: argparse.Namespace) -> int:
    return search_issues_cmd.run_search(
        client,
        settings,
        term=getattr(args, "term", None),
        summary_substring=getattr(args, "summary_substring", None),
        project=getattr(args, "project", None),
        direct_jql=getattr(args, "jql", None),
        status=getattr(args, "status", None),
        issue_type=getattr(args, "issue_type", None),
        priority=getattr(args, "priority", None),
        severity=getattr(args, "severity", None),
        testing=getattr(args, "testing", None),
        coverage=getattr(args, "coverage", None),
        build=getattr(args, "build", None),
        test_link=getattr(args, "test_link", None),
        team=getattr(args, "team", None),
        due=getattr(args, "due", None),
        assignee_email=getattr(args, "assignee_email", None),
        reporter_email=getattr(args, "reporter_email", None),
        qa_contact_email=getattr(args, "qa_contact_email", None),
        developer_email=getattr(args, "developer_email", None),
        doc_contact_email=getattr(args, "doc_contact_email", None),
        unfinished_only=getattr(args, "unfinished", False),
        max_results=args.max_results,
        as_json=args.json,
        out=sys.stdout,
        err=sys.stderr,
        debug=getattr(args, "debug", False),
    )


def _cmd_new(client: JiraClient, settings, args: argparse.Namespace) -> int:
    return new_issue_cmd.run_new(
        client,
        settings,
        project=args.project,
        summary=args.summary,
        issue_type=args.issue_type,
        issuetype_name=getattr(args, "issuetype_name", None),
        description=getattr(args, "description", None),
        story_points=getattr(args, "story_points", None),
        sprint=getattr(args, "sprint", None),
        comment=getattr(args, "comment", None),
        transition=getattr(args, "transition", None),
        refresh_sprint_cache=getattr(args, "refresh_sprint_cache", False),
        assignee_email=getattr(args, "assignee_email", None),
        reporter_email=getattr(args, "reporter_email", None),
        priority_name=getattr(args, "priority_name", None),
        duedate=getattr(args, "duedate", None),
        severity=getattr(args, "severity", None),
        preliminary_testing=getattr(args, "preliminary_testing", None),
        test_coverage=getattr(args, "test_coverage", None),
        fixed_in_build=getattr(args, "fixed_in_build", None),
        test_link=getattr(args, "test_link", None),
        developer_email=getattr(args, "developer_email", None),
        qa_contact_email=getattr(args, "qa_contact_email", None),
        doc_contact_email=getattr(args, "doc_contact_email", None),
        contributors_emails=getattr(args, "contributors_email", None),
        parent_key=getattr(args, "parent", None),
        as_json=args.json,
        out=sys.stdout,
        err=sys.stderr,
    )


def _cmd_fields(client: JiraClient, _settings, args: argparse.Namespace) -> int:
    search = getattr(args, "search", None)
    search_regex = getattr(args, "search_regex", False)
    if search_regex and not (search or "").strip():
        cmd = getattr(args, "field_map_cmd_name", "fields")
        print(f"jira-cli {cmd}: --regex requires --search TEXT", file=sys.stderr)
        return 2
    return field_map_cmd.run_field_map(
        client,
        custom_only=not getattr(args, "include_builtin", False),
        as_json=getattr(args, "json", False),
        header=getattr(args, "header", False),
        id_name_only=getattr(args, "id_name_only", False),
        search=search,
        search_regex=search_regex,
        out=sys.stdout,
        err=sys.stderr,
    )


def _cmd_show(client: JiraClient, _settings, args: argparse.Namespace) -> int:
    return show_issue_cmd.run_show(
        client,
        args.issue_key,
        expand=args.expand,
        compact=args.compact,
        brief=args.brief,
        short=args.short,
        custom_id=args.custom_id,
        preliminary_testing_field_id=_settings.preliminary_testing_field_id,
        fixed_in_build_field_id=_settings.fixed_in_build_field_id,
        test_coverage_field_id=_settings.test_coverage_field_id,
        test_link_field_id=_settings.test_link_field_id,
        git_pull_request_field_id=_settings.git_pull_request_field_id,
        story_points_field_id=_settings.story_points_field_id,
        assigned_team_field_id=_settings.assigned_team_field_id,
        out=sys.stdout,
        err=sys.stderr,
    )


def _cmd_edit(client: JiraClient, settings, args: argparse.Namespace) -> int:
    key = args.issue_key
    summary = getattr(args, "summary", None)
    description = getattr(args, "description", None)
    description_ipsum = bool(getattr(args, "description_ipsum", False))
    if description_ipsum:
        if description is not None:
            print(
                "jira-cli edit: cannot use --description-ipsum together with --description.",
                file=sys.stderr,
            )
            return 2
        description = new_issue_cmd.DEFAULT_NEW_ISSUE_DESCRIPTION
    story_points = args.story_points
    sprint = args.sprint
    comment = args.comment
    comment_idx = getattr(args, "comment_idx", None)
    delete_comment_idx = getattr(args, "delete_comment_idx", None)
    transition = args.transition
    assignee_email = getattr(args, "assignee_email", None)
    assignee_clear = bool(getattr(args, "assignee_clear", False))
    reporter_email = getattr(args, "reporter_email", None)
    reporter_clear = bool(getattr(args, "reporter_clear", False))
    priority_name = getattr(args, "priority_name", None)
    issuetype_name = getattr(args, "issuetype_name", None)
    duedate = getattr(args, "duedate", None)
    clear_due = bool(getattr(args, "clear_due", False))
    severity = getattr(args, "severity", None)
    team = getattr(args, "team", None)
    preliminary_testing = getattr(args, "preliminary_testing", None)
    test_coverage = getattr(args, "test_coverage", None)
    fixed_in_build = getattr(args, "fixed_in_build", None)
    test_link = getattr(args, "test_link", None)
    git_pull_request = getattr(args, "git_pull_request", None)
    developer_email = getattr(args, "developer_email", None)
    developer_clear = bool(getattr(args, "developer_clear", False))
    qa_contact_email = getattr(args, "qa_contact_email", None)
    qa_contact_clear = bool(getattr(args, "qa_contact_clear", False))
    doc_contact_email = getattr(args, "doc_contact_email", None)
    doc_contact_clear = bool(getattr(args, "doc_contact_clear", False))
    contributors_emails = getattr(args, "contributors_email", None)
    contributors_clear = bool(getattr(args, "contributors_clear", False))
    edit_fields = getattr(args, "edit_fields", None)

    if delete_comment_idx is not None:
        if comment_idx is not None:
            print(
                "jira-cli edit: cannot use --delete-comment-idx together with --comment-idx.",
                file=sys.stderr,
            )
            return 2
        if comment is not None and str(comment).strip():
            print(
                "jira-cli edit: cannot use --delete-comment-idx together with --comment; "
                "omit --comment to delete.",
                file=sys.stderr,
            )
            return 2

    if comment_idx is not None:
        if comment is None or not str(comment).strip():
            print(
                "jira-cli edit: --comment TEXT is required when --comment-idx is set.",
                file=sys.stderr,
            )
            return 2

    use_interactive = args.interactive
    has_flags = any(
        [
            summary is not None,
            description is not None,
            description_ipsum,
            story_points is not None,
            sprint is not None,
            comment is not None,
            comment_idx is not None,
            delete_comment_idx is not None,
            transition is not None,
            assignee_clear,
            assignee_email is not None,
            reporter_clear,
            reporter_email is not None,
            priority_name is not None,
            issuetype_name is not None,
            duedate is not None,
            clear_due,
            severity is not None,
            team is not None,
            preliminary_testing is not None,
            test_coverage is not None,
            fixed_in_build is not None,
            test_link is not None,
            git_pull_request is not None,
            developer_email is not None,
            developer_clear,
            qa_contact_email is not None,
            qa_contact_clear,
            doc_contact_email is not None,
            doc_contact_clear,
            contributors_emails is not None,
            contributors_clear,
            edit_fields,
        ]
    )
    if not has_flags and not use_interactive:
        if _no_input(args) or not sys.stdin.isatty():
            print(
                "Specify at least one edit flag (see jira-cli edit --help), "
                "or use --interactive (requires a TTY).",
                file=sys.stderr,
            )
            return 2
        use_interactive = True

    if use_interactive:
        if not sys.stdin.isatty():
            print("--interactive requires a TTY.", file=sys.stderr)
            return 2
        prompted = collect_edit_actions(
            client,
            settings,
            key,
            refresh_sprint_cache=getattr(args, "refresh_sprint_cache", False),
        )
        if summary is None and "summary" in prompted:
            summary = str(prompted["summary"])
        if description is None and "description" in prompted:
            description = str(prompted["description"])
        if story_points is None and "story_points" in prompted:
            story_points = prompted["story_points"]
        if sprint is None and "sprint_id" in prompted:
            sprint = str(prompted["sprint_id"])
        if comment is None and "comment" in prompted:
            comment = str(prompted["comment"])
        if transition is None and "transition_id" in prompted:
            transition = str(prompted["transition_id"])

    if (
        not any(
            x is not None
            for x in (
                summary,
                description,
                story_points,
                sprint,
                comment,
                delete_comment_idx,
                transition,
                assignee_email,
                reporter_email,
                priority_name,
                issuetype_name,
                duedate,
                severity,
                team,
                preliminary_testing,
                test_coverage,
                fixed_in_build,
                test_link,
                git_pull_request,
                developer_email,
                qa_contact_email,
                doc_contact_email,
                contributors_emails,
            )
        )
        and not assignee_clear
        and not reporter_clear
        and not clear_due
        and not developer_clear
        and not qa_contact_clear
        and not doc_contact_clear
        and not contributors_clear
        and not edit_fields
    ):
        print("Nothing to do.", file=sys.stderr)
        return 0

    additional_fields = None
    if edit_fields:
        additional_fields, rc = edit_issue_cmd.run_edit_field_specs(
            client,
            settings,
            key.strip().upper(),
            edit_fields,
            skip_confirm=getattr(args, "yes", False),
            force_no_input=_no_input(args),
            err=sys.stderr,
        )
        if rc != 0:
            return rc

    sprint_lookup = sprint if sprint and not str(sprint).isdigit() else None
    sprint_id = int(sprint) if sprint and str(sprint).isdigit() else None

    return edit_issue_cmd.apply_edit(
        client,
        settings,
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
        refresh_sprint_cache=getattr(args, "refresh_sprint_cache", False),
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
        err=sys.stderr,
    )


def _cmd_agenda(client: JiraClient, settings, args: argparse.Namespace) -> int:
    show_sp = getattr(args, "show_story_points", False)
    sp_id = settings.story_points_field_id
    if show_sp and not sp_id:
        sp_id = edit_issue_cmd.resolve_story_points_field_id(client)
    if show_sp and not sp_id:
        print(
            "jira-cli agenda: --show-story-points requires a Story Points field "
            "(set JIRA_STORY_POINTS_FIELD_ID or ensure the site has a custom field named Story Points).",
            file=sys.stderr,
        )
        return 2
    return agenda_cmd.run_agenda(
        client,
        settings,
        sprint=getattr(args, "sprint", None),
        sprint_pattern=getattr(args, "sprint_pattern", None),
        sprint_project=getattr(args, "sprint_project", agenda_cmd.DEFAULT_SPRINT_PROJECT),
        preferred_board=getattr(args, "preferred_board", agenda_cmd.DEFAULT_PREFERRED_BOARD),
        refresh_sprint_cache=not getattr(args, "no_refresh_sprint_cache", False),
        max_results=args.max_results,
        show_story_points=show_sp,
        story_points_field_id=sp_id,
        as_json=args.json,
        out=sys.stdout,
        err=sys.stderr,
        debug=getattr(args, "debug", False),
    )


def _cmd_move(client: JiraClient, _settings, args: argparse.Namespace) -> int:
    return move_issue_cmd.run_move(
        client,
        issue_key=args.issue_key,
        project=args.project,
        issue_type=getattr(args, "issue_type", None),
        as_json=getattr(args, "json", False),
        out=sys.stdout,
        err=sys.stderr,
    )


def _cmd_transitions(client: JiraClient, _settings, args: argparse.Namespace) -> int:
    try:
        data = client.get_transitions(args.issue_key)
    except JiraApiError as e:
        print(e, file=sys.stderr)
        return 1
    for t in data.get("transitions") or []:
        print(f"{t.get('id')}\t{t.get('name')}")
    return 0


def _cmd_sprints(client: JiraClient, _settings, args: argparse.Namespace) -> int:
    from jira_cli.sprint_listing import fetch_project_sprint_rows

    rows, err_msg = fetch_project_sprint_rows(
        client,
        project=args.project,
        state=args.state,
        refresh_sprint_cache=getattr(args, "refresh_sprint_cache", False),
    )
    if err_msg:
        print(err_msg, file=sys.stderr)
        return 1
    for s in rows:
        print(f"{s.get('id')}\t{s.get('state')}\t{s.get('board_name')}\t{s.get('name')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jira-cli",
        description="Jira REST CLI: list/show issues, agenda, fields/field-map, edit, move, transitions, sprints.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    plm = sub.add_parser(
        "list-mine",
        help="Issues where you are assignee, Developer, QA Contact, Doc Contact, or Contributors (JQL currentUser)",
    )
    plm.add_argument("--max-results", type=int, default=50, help="Page size (default 50)")
    plm.add_argument("--json", action="store_true", help="Raw API JSON")
    plm.add_argument(
        "--debug",
        action="store_true",
        help="Print the JQL query on stderr before results",
    )
    plm.add_argument(
        "--all-fields",
        action="store_true",
        help="Request every issue field (*all); implies JSON output",
    )
    plm.add_argument(
        "--show-story-points",
        "-p",
        action="store_true",
        dest="show_story_points",
        help=(
            "Include story points in each row (tab column; '-' when unset). "
            "Uses JIRA_STORY_POINTS_FIELD_ID or resolves the Story Points custom field."
        ),
    )
    plm.add_argument(
        "--unfinished",
        action="store_true",
        help=(
            "Only unfinished issues; excludes Jira terminal statuses (Done/Closed/etc.) "
            "discovered from /rest/api/3/status"
        ),
    )
    plm.add_argument(
        "--jql",
        help="Extra JQL AND clause (e.g. 'status != \"Done\"')",
    )
    plm.add_argument(
        "--type",
        dest="issue_type",
        metavar="NAME",
        help='Filter by issue type display name (JQL issuetype = "NAME"; same as fields.issuetype.name)',
    )
    plm.add_argument(
        "--sprint",
        metavar="ID_OR_NAME",
        help=(
            "Agile sprint filter (JQL sprint = id). Numeric id, or name "
            "(resolved per-project with --sprint-project, else all Scrum boards)"
        ),
    )
    plm.add_argument(
        "--sprint-project",
        metavar="KEY",
        dest="sprint_project",
        help="Optional project key: faster name resolution via jira-cli sprints KEY (omit to scan all Scrum boards)",
    )
    plm.add_argument(
        "--refresh-sprint-cache",
        action="store_true",
        help="When resolving --sprint by name, refetch sprint lists from Jira",
    )
    plm.set_defaults(handler=_cmd_list_mine, issue_type=None, sprint=None, sprint_project=None)

    pl = sub.add_parser(
        "list",
        help=(
            "List issues for a user by email: same JQL OR as list-mine "
            "(assignee, Developer, QA Contact, Doc Contact, Contributors); default email from JIRA_EMAIL when omitted"
        ),
    )
    pl.add_argument(
        "email",
        nargs="?",
        default=None,
        metavar="EMAIL",
        help="Assignee email (default: JIRA_EMAIL or JIRA_USER from environment)",
    )
    pl.add_argument("--max-results", type=int, default=50, help="Page size (default 50)")
    pl.add_argument("--json", action="store_true", help="Raw API JSON")
    pl.add_argument(
        "--debug",
        action="store_true",
        help="Print the JQL query on stderr before results",
    )
    pl.add_argument(
        "--all-fields",
        action="store_true",
        help="Request every issue field (*all); implies JSON output",
    )
    pl.add_argument(
        "--show-story-points",
        "-p",
        action="store_true",
        dest="show_story_points",
        help=(
            "Include story points in each row (tab column; '-' when unset). "
            "Uses JIRA_STORY_POINTS_FIELD_ID or resolves the Story Points custom field."
        ),
    )
    pl.add_argument(
        "--unfinished",
        action="store_true",
        help=(
            "Only unfinished issues; excludes Jira terminal statuses (Done/Closed/etc.) "
            "discovered from /rest/api/3/status"
        ),
    )
    pl.add_argument(
        "--jql",
        help="Extra JQL AND clause (e.g. 'status != \"Done\"')",
    )
    pl.add_argument(
        "--type",
        dest="issue_type",
        metavar="NAME",
        help='Filter by issue type display name (JQL issuetype = "NAME"; same as fields.issuetype.name)',
    )
    pl.add_argument(
        "--sprint",
        metavar="ID_OR_NAME",
        help="Agile sprint filter (JQL sprint = id). Numeric id, or name (see list-mine --sprint)",
    )
    pl.add_argument(
        "--sprint-project",
        metavar="KEY",
        dest="sprint_project",
        help="Optional project key for faster --sprint name resolution (see list-mine --sprint-project)",
    )
    pl.add_argument(
        "--refresh-sprint-cache",
        action="store_true",
        help="When resolving --sprint by name, refetch sprint lists from Jira",
    )
    pl.set_defaults(
        handler=_cmd_list, email=None, issue_type=None, sprint=None, sprint_project=None
    )

    psearch = sub.add_parser(
        "search",
        help="Search issues by show-like fields with OR semantics, or pass direct --jql",
    )
    psearch.add_argument(
        "term",
        nargs="?",
        default=None,
        metavar="TERM",
        help="Optional text term searched across common show-like fields (OR)",
    )
    psearch.add_argument("--max-results", type=int, default=50, help="Page size (default 50)")
    psearch.add_argument("--json", action="store_true", help="Raw API JSON")
    psearch.add_argument(
        "--debug",
        action="store_true",
        help="Print the JQL query on stderr before results",
    )
    psearch.add_argument("--jql", help="Direct JQL query (mutually exclusive with TERM/filters)")
    psearch.add_argument(
        "--summary",
        dest="summary_substring",
        metavar="TEXT",
        help="Substring match on summary only (JQL: summary ~ TEXT)",
    )
    psearch.add_argument(
        "--project",
        metavar="KEYS",
        help="Project key(s), comma-separated (JQL: project = KEY or project in (...)); ANDed with other filters",
    )
    psearch.add_argument(
        "--unfinished",
        action="store_true",
        help=(
            "Only unfinished issues; excludes Jira terminal statuses (Done/Closed/etc.) "
            "discovered from /rest/api/3/status"
        ),
    )
    psearch.add_argument("--status", metavar="NAME", help="Status name")
    psearch.add_argument("--type", dest="issue_type", metavar="NAME", help="Issue type name")
    psearch.add_argument("--priority", metavar="NAME", help="Priority name")
    psearch.add_argument("--due", metavar="YYYY-MM-DD", help="Due date")
    psearch.add_argument("--severity", metavar="VALUE", help='Custom field "Severity"')
    psearch.add_argument(
        "--testing",
        metavar="VALUE",
        help='Custom field "Preliminary Testing"',
    )
    psearch.add_argument("--coverage", metavar="VALUE", help='Custom field "Test Coverage"')
    psearch.add_argument("--build", metavar="VALUE", help='Custom field "Fixed in Build"')
    psearch.add_argument("--test-link", metavar="VALUE", help='Custom field "Test Link"')
    psearch.add_argument(
        "--team",
        metavar="VALUE",
        help='Custom field "AssignedTeam" (optional JIRA_ASSIGNED_TEAM_FIELD_ID)',
    )
    psearch.add_argument("--assignee-email", metavar="EMAIL", help="Assignee user email")
    psearch.add_argument("--reporter-email", metavar="EMAIL", help="Reporter user email")
    psearch.add_argument("--qa-contact-email", metavar="EMAIL", help='User picker "QA Contact"')
    psearch.add_argument("--developer-email", metavar="EMAIL", help='User picker "Developer"')
    psearch.add_argument("--doc-contact-email", metavar="EMAIL", help='User picker "Doc Contact"')
    psearch.set_defaults(handler=_cmd_search, issue_type=None)

    pnew = sub.add_parser(
        "new",
        help="Create a new issue (POST /rest/api/3/issue)",
    )
    pnew.add_argument(
        "--project",
        required=True,
        metavar="KEY",
        help="Project key, e.g. PROJ",
    )
    pnew.add_argument(
        "--summary",
        required=True,
        metavar="TEXT",
        help="Issue summary (title)",
    )
    pnew.add_argument(
        "--type",
        dest="issue_type",
        default="Task",
        metavar="NAME",
        help="Issue type display name (default: Task; same as fields.issuetype.name)",
    )
    pnew.add_argument(
        "--description",
        metavar="TEXT",
        help=(
            "Plain-text description (stored as Atlassian Document Format; "
            "default placeholder text if omitted)"
        ),
    )
    pnew.add_argument(
        "--parent",
        metavar="KEY",
        help="Parent issue key (fields.parent; use with Sub-task / child types per project)",
    )
    pnew.add_argument("--story-points", type=float, dest="story_points", help="Story points value")
    pnew.add_argument(
        "--sprint",
        help="Sprint id (number) or sprint name (matched across Scrum boards for --project)",
    )
    pnew.add_argument(
        "--comment",
        help="Comment body (plain text); added after the issue is created",
    )
    pnew.add_argument(
        "--transition",
        metavar="NAME_OR_ID",
        help="Workflow transition name or numeric id (applied after create)",
    )
    pnew.add_argument(
        "--assignee-email",
        metavar="EMAIL",
        help="Assignee via user search (same as edit)",
    )
    pnew.add_argument(
        "--reporter-email",
        metavar="EMAIL",
        help="Reporter (requires permission on most sites)",
    )
    pnew.add_argument(
        "--priority",
        dest="priority_name",
        metavar="NAME",
        help="Priority display name (fields.priority.name)",
    )
    pnew.add_argument(
        "--issuetype",
        dest="issuetype_name",
        metavar="NAME",
        help="Issue type display name; overrides --type if set (fields.issuetype.name)",
    )
    pnew.add_argument(
        "--due",
        dest="duedate",
        metavar="YYYY-MM-DD",
        help="Due date (fields.duedate)",
    )
    pnew.add_argument(
        "--severity",
        metavar="VALUE",
        help='Custom field "Severity"',
    )
    pnew.add_argument(
        "--preliminary-testing",
        metavar="VALUE",
        help='Custom field "Preliminary Testing"',
    )
    pnew.add_argument(
        "--test-coverage",
        metavar="VALUE",
        help='Custom field "Test Coverage"',
    )
    pnew.add_argument(
        "--fixed-in-build",
        metavar="VALUE",
        help='Custom field "Fixed in Build"',
    )
    pnew.add_argument(
        "--test-link",
        metavar="VALUE",
        help='Custom field "Test Link"',
    )
    pnew.add_argument(
        "--developer-email",
        metavar="EMAIL",
        help='User-picker "Developer"',
    )
    pnew.add_argument(
        "--qa-contact-email",
        metavar="EMAIL",
        help='User-picker "QA Contact"',
    )
    pnew.add_argument(
        "--doc-contact-email",
        metavar="EMAIL",
        help='User-picker "Doc Contact"',
    )
    pnew.add_argument(
        "--contributors-email",
        dest="contributors_email",
        metavar="EMAILS",
        help='Multi-user "Contributors" (comma-separated; optional JIRA_CONTRIBUTORS_FIELD_ID)',
    )
    pnew.add_argument(
        "--refresh-sprint-cache",
        action="store_true",
        help="Skip sprint cache when resolving --sprint by name",
    )
    pnew.add_argument("--json", action="store_true", help="Print raw API response JSON")
    pnew.set_defaults(handler=_cmd_new)

    pshow = sub.add_parser("show", help="Print one issue with all fields (JSON)")
    pshow.add_argument("issue_key", help="Issue key, e.g. PROJ-123")
    pshow.add_argument(
        "--expand",
        metavar="NAMES",
        help="Extra comma-separated expand values (names is always included for field display names)",
    )
    pshow.add_argument(
        "--compact",
        action="store_true",
        help="Single-line JSON",
    )
    pshow.add_argument(
        "--brief",
        action="store_true",
        help="JSON: rename fields via names map, omit names, strip empty values (not with --short)",
    )
    pshow.add_argument(
        "-s",
        "--short",
        action="store_true",
        help="Compact lines: …; Description; …; Links; Comments (extra GET, email+date+flat text); …",
    )
    pshow.add_argument(
        "--custom-id",
        action="store_true",
        help="Keep fields.customfield_* keys instead of replacing with custom field names",
    )
    pshow.set_defaults(handler=_cmd_show, brief=False, short=False)

    def _add_field_map_cli(subparsers, name: str, help_text: str, *, id_name_only: bool) -> None:
        sp = subparsers.add_parser(name, help=help_text)
        sp.add_argument(
            "--all",
            action="store_true",
            dest="include_builtin",
            help="Include built-in fields, not only custom (default: custom only)",
        )
        sp.add_argument(
            "--json",
            action="store_true",
            help=(
                "JSON output: full FieldDetails array"
                if not id_name_only
                else "JSON array of {id, name} objects"
            ),
        )
        sp.add_argument(
            "--header",
            action="store_true",
            help="Print column header row for TSV"
            + (" (id, name, key)" if not id_name_only else " (id, name)"),
        )
        sp.add_argument(
            "-s",
            "--search",
            metavar="TEXT",
            help="Only fields whose id, name, key, or JQL clause name matches (substring, case-insensitive)",
        )
        sp.add_argument(
            "--regex",
            action="store_true",
            help="Treat --search as a case-insensitive regular expression",
        )
        sp.set_defaults(
            handler=_cmd_fields,
            search=None,
            search_regex=False,
            include_builtin=False,
            id_name_only=id_name_only,
            field_map_cmd_name=name,
        )

    _add_field_map_cli(
        sub,
        "fields",
        "Custom field id, name, and key (GET /rest/api/3/field)",
        id_name_only=False,
    )
    _add_field_map_cli(
        sub,
        "field-map",
        "Custom field id → display name only (same API as fields; two TSV columns)",
        id_name_only=True,
    )

    pe = sub.add_parser("edit", help="Update an issue")
    pe.add_argument("issue_key", help="Issue key, e.g. PROJ-123")
    pe.add_argument(
        "--field",
        action="append",
        dest="edit_fields",
        metavar="KEY=VALUE",
        help="Set field by id, name, key, or JQL clause (repeatable); shows preview and confirms",
    )
    pe.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply --field updates without confirmation (required when stdin is not a TTY)",
    )
    pe.add_argument("--summary", help="New issue summary (title)")
    pe.add_argument(
        "--description",
        metavar="TEXT",
        help='New issue description (plain text; converted to ADF). Use "" to clear',
    )
    pe.add_argument(
        "--description-ipsum",
        action="store_true",
        help=(
            "Set description to default placeholder text "
            "(same as jira-cli new without --description; mutually exclusive with --description)"
        ),
    )
    pe.add_argument("--story-points", type=float, dest="story_points", help="Story points value")
    pe.add_argument(
        "--sprint",
        help="Sprint id (number) or sprint name (matched across all boards for the issue's project)",
    )
    pe.add_argument(
        "--comment",
        help="Comment body (plain text); with --comment-idx, replaces that comment",
    )
    pe.add_argument(
        "--comment-idx",
        type=int,
        default=None,
        metavar="N",
        help="0-based index of comment to replace (requires --comment; order is oldest-first from Jira)",
    )
    pe.add_argument(
        "--delete-comment-idx",
        type=int,
        default=None,
        metavar="N",
        help="0-based index of comment to delete (mutually exclusive with --comment and --comment-idx)",
    )
    pe.add_argument(
        "--transition",
        metavar="NAME_OR_ID",
        help="Workflow transition name or numeric id",
    )
    pe.add_argument(
        "--assignee-email",
        metavar="EMAIL",
        help="Set assignee via user search (same account as show --short assignee line)",
    )
    pe.add_argument(
        "--assignee-clear",
        action="store_true",
        help="Unassign the issue (mutually exclusive with --assignee-email)",
    )
    pe.add_argument(
        "--reporter-email",
        metavar="EMAIL",
        help="Set reporter (requires permission on most sites)",
    )
    pe.add_argument(
        "--reporter-clear",
        action="store_true",
        help="Clear reporter (mutually exclusive with --reporter-email)",
    )
    pe.add_argument(
        "--priority",
        dest="priority_name",
        metavar="NAME",
        help="Priority display name (fields.priority.name)",
    )
    pe.add_argument(
        "--issuetype",
        dest="issuetype_name",
        metavar="NAME",
        help="Issue type display name (fields.issuetype.name)",
    )
    pe.add_argument(
        "--due",
        dest="duedate",
        metavar="YYYY-MM-DD",
        help="Due date (fields.duedate); mutually exclusive with --clear-due",
    )
    pe.add_argument(
        "--clear-due",
        action="store_true",
        dest="clear_due",
        help="Clear due date",
    )
    pe.add_argument(
        "--severity",
        metavar="VALUE",
        help='Custom field "Severity" (option or text per site)',
    )
    pe.add_argument(
        "--team",
        metavar="VALUE",
        help='Custom field "AssignedTeam" (optional JIRA_ASSIGNED_TEAM_FIELD_ID)',
    )
    pe.add_argument(
        "--preliminary-testing",
        metavar="VALUE",
        help='Custom field "Preliminary Testing" (optional JIRA_PRELIMINARY_TESTING_FIELD_ID)',
    )
    pe.add_argument(
        "--test-coverage",
        metavar="VALUE",
        help='Custom field "Test Coverage"',
    )
    pe.add_argument(
        "--fixed-in-build",
        metavar="VALUE",
        help='Custom field "Fixed in Build"',
    )
    pe.add_argument(
        "--test-link",
        metavar="VALUE",
        help='Custom field "Test Link"',
    )
    pe.add_argument(
        "--git-pull-request",
        metavar="URL",
        dest="git_pull_request",
        help=(
            'Custom field "Git Pull Request" (MR/PR URL; optional JIRA_GIT_PULL_REQUEST_FIELD_ID)'
        ),
    )
    pe.add_argument(
        "--developer-email",
        metavar="EMAIL",
        help='User-picker "Developer"',
    )
    pe.add_argument(
        "--developer-clear",
        action="store_true",
        help='Clear "Developer" (mutually exclusive with --developer-email)',
    )
    pe.add_argument(
        "--qa-contact-email",
        metavar="EMAIL",
        help='User-picker "QA Contact"',
    )
    pe.add_argument(
        "--qa-contact-clear",
        action="store_true",
        help='Clear "QA Contact" (mutually exclusive with --qa-contact-email)',
    )
    pe.add_argument(
        "--doc-contact-email",
        metavar="EMAIL",
        help='User-picker "Doc Contact"',
    )
    pe.add_argument(
        "--doc-contact-clear",
        action="store_true",
        help='Clear "Doc Contact" (mutually exclusive with --doc-contact-email)',
    )
    pe.add_argument(
        "--contributors-email",
        dest="contributors_email",
        metavar="EMAILS",
        help='Multi-user "Contributors" (comma-separated; optional JIRA_CONTRIBUTORS_FIELD_ID)',
    )
    pe.add_argument(
        "--contributors-clear",
        action="store_true",
        help='Clear "Contributors" (mutually exclusive with --contributors-email)',
    )
    pe.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Prompt for fields (default when no flags and stdin is a TTY)",
    )
    pe.add_argument(
        "--no-input",
        action="store_true",
        help="Never prompt; exit 2 if no edit flags (or set JIRA_CLI_NO_INPUT=1).",
    )
    pe.add_argument(
        "--refresh-sprint-cache",
        action="store_true",
        help="Skip sprint cache and refetch from Jira (use when cache is stale)",
    )
    pe.set_defaults(handler=_cmd_edit)

    pa = sub.add_parser(
        "agenda",
        help=(
            "My unfinished issues in the current sprint "
            "(default: active sprint matching *IDM-SSSD* in project IDM)"
        ),
    )
    pa.add_argument("--max-results", type=int, default=50, help="Page size (default 50)")
    pa.add_argument("--json", action="store_true", help="JSON: sprint metadata + issues")
    pa.add_argument(
        "--debug",
        action="store_true",
        help="Print the JQL query on stderr",
    )
    pa.add_argument(
        "--sprint",
        metavar="ID_OR_NAME",
        help="Sprint id or name (overrides --sprint-pattern auto-detection)",
    )
    pa.add_argument(
        "--sprint-pattern",
        metavar="GLOB",
        help=(
            "Active sprint name glob when --sprint is omitted "
            f"(default: {agenda_cmd.DEFAULT_SPRINT_PATTERN!r})"
        ),
    )
    pa.add_argument(
        "--sprint-project",
        metavar="KEY",
        default=agenda_cmd.DEFAULT_SPRINT_PROJECT,
        help=f"Project for sprint lookup (default: {agenda_cmd.DEFAULT_SPRINT_PROJECT})",
    )
    pa.add_argument(
        "--preferred-board",
        metavar="NAME",
        default=agenda_cmd.DEFAULT_PREFERRED_BOARD,
        help=(
            "When several active sprints match --sprint-pattern, prefer this board name "
            f"(default: {agenda_cmd.DEFAULT_PREFERRED_BOARD!r})"
        ),
    )
    pa.add_argument(
        "--show-story-points",
        "-p",
        action="store_true",
        dest="show_story_points",
        help="Include story points column (same as list-mine -p)",
    )
    pa.add_argument(
        "--no-refresh-sprint-cache",
        action="store_true",
        help="Use local sprint cache instead of refetching active sprints from Jira",
    )
    pa.set_defaults(
        handler=_cmd_agenda,
        sprint=None,
        sprint_pattern=None,
        refresh_sprint_cache=True,
    )

    pm = sub.add_parser(
        "move",
        help="Move an issue to another project (POST /rest/api/3/bulk/issues/move)",
    )
    pm.add_argument("issue_key", help="Issue key, e.g. PROJ-123")
    pm.add_argument(
        "--project",
        required=True,
        metavar="KEY",
        help="Target project key, e.g. NEWPROJ",
    )
    pm.add_argument(
        "--type",
        dest="issue_type",
        metavar="NAME",
        help=(
            "Target issue type display name in the new project "
            "(default: keep current issue type name)"
        ),
    )
    pm.add_argument("--json", action="store_true", help="Print move result as JSON")
    pm.set_defaults(handler=_cmd_move, issue_type=None)

    pt = sub.add_parser("transitions", help="List transitions for an issue")
    pt.add_argument("issue_key")
    pt.set_defaults(handler=_cmd_transitions)

    ps = sub.add_parser("sprints", help="List sprints for a project board")
    ps.add_argument("project", help="Project key, e.g. PROJ")
    ps.add_argument(
        "--state",
        default="future,active",
        help="Sprint states filter (default: future,active)",
    )
    ps.add_argument(
        "--refresh-sprint-cache",
        action="store_true",
        help="Skip cache and refetch sprint lists from Jira (use when cache is stale)",
    )
    ps.set_defaults(handler=_cmd_sprints)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 2

    client = JiraClient(settings)
    handler = args.handler
    return handler(client, settings, args)


if __name__ == "__main__":
    raise SystemExit(main())
