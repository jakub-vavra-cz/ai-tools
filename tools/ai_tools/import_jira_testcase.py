#!/usr/bin/env python3
"""Import a dump-polarion-testcase (jira format) file into Jira RHELTEST."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_tools.beetlejuice import (
    DEFAULT_ISSUE_TYPE,
    DEFAULT_PROJECT,
    FIELD_ARCHITECTURE,
    FIELD_ASSIGNED_TEAM,
    FIELD_EXTERNAL_URL,
    FIELD_ID,
    FIELD_TIER,
    FIELD_URL,
    ImportResult,
    JiraConfig,
    JiraError,
    browse_url,
    build_issue_fields,
    create_issue,
    escape_jql_string,
    escape_lucene_chars,
    find_by_summary,
    find_by_work_item_id,
    find_user_account_id,
    get_issue_status,
    html_to_adf,
    import_testcase,
    jira_config_from_env,
    jira_request,
    list_createable_issue_types,
    list_transitions,
    parse_key_value_file,
    plain_text_to_adf,
    resolve_issue_type,
    resolve_match,
    search_issues,
    split_csv,
    transition_issue_to_status,
    update_issue,
)

__all__ = [
    "DEFAULT_ISSUE_TYPE",
    "DEFAULT_PROJECT",
    "FIELD_ARCHITECTURE",
    "FIELD_ASSIGNED_TEAM",
    "FIELD_EXTERNAL_URL",
    "FIELD_ID",
    "FIELD_TIER",
    "FIELD_URL",
    "ImportResult",
    "JiraConfig",
    "JiraError",
    "browse_url",
    "build_issue_fields",
    "create_issue",
    "escape_jql_string",
    "escape_lucene_chars",
    "find_by_summary",
    "find_by_work_item_id",
    "find_user_account_id",
    "get_issue_status",
    "html_to_adf",
    "import_testcase",
    "jira_config_from_env",
    "jira_request",
    "list_createable_issue_types",
    "list_transitions",
    "main",
    "plain_text_to_adf",
    "resolve_issue_type",
    "resolve_match",
    "search_issues",
    "split_csv",
    "transition_issue_to_status",
    "update_issue",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import a dump-polarion-testcase --format jira file into Jira. "
            "Matches existing Test Cases by customfield_10591 (ID) first; "
            "when ID is set, summary is never used (parametrized titles collide). "
            "Summary match only if ID is absent. Updates on match, otherwise creates. "
            "Requires JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN."
        ),
    )
    parser.add_argument(
        "dump_file",
        type=Path,
        help="Path to key=value dump (jira format)",
    )
    parser.add_argument(
        "-P",
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Jira project key (default: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--issue-type",
        default=DEFAULT_ISSUE_TYPE,
        help=f'Issue type name (default: "{DEFAULT_ISSUE_TYPE}")',
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Search and report action without creating/updating",
    )
    parser.add_argument(
        "--skip-assignee",
        action="store_true",
        help="Do not set assignee (Polarion ids often do not match Jira)",
    )
    parser.add_argument(
        "--skip-components",
        action="store_true",
        help="Do not set components (avoids errors when names are missing)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dump_file.is_file():
        print(f"error: dump file not found: {args.dump_file}", file=sys.stderr)
        return 2

    try:
        dump = parse_key_value_file(args.dump_file)
        config = jira_config_from_env()
        result = import_testcase(
            dump,
            config=config,
            project_key=args.project,
            issue_type=args.issue_type,
            dry_run=args.dry_run,
            skip_assignee=args.skip_assignee,
            skip_components=args.skip_components,
        )
    except (JiraError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        key = result.issue_key or "(new)"
        print(f"{result.action}: {key} (match={result.match})")
        if result.status:
            if result.action.startswith("dry-run"):
                print(f"status: would set {result.status}")
            elif result.status_applied:
                print(f"status: {result.status}")
            elif result.status_warning:
                print(f"status warning: {result.status_warning}", file=sys.stderr)
        if result.browse_url:
            print(result.browse_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
