#!/usr/bin/env python3
"""Import beetlejuice test-run dumps into Jira RHELTEST Test Result issues."""

from __future__ import annotations

import argparse
import json
import sys

from ai_tools.beetlejuice import (
    DEFAULT_PROJECT,
    DEFAULT_TESTRESULT_ISSUE_TYPE,
    ImportResult,
    JiraConfig,
    JiraError,
    TestResultImportResult,
    build_testresult_fields,
    find_parent_test_case,
    import_testresult,
    jira_config_from_env,
    normalize_architecture,
    parse_key_value_file,
)

DEFAULT_ISSUE_TYPE = DEFAULT_TESTRESULT_ISSUE_TYPE

__all__ = [
    "DEFAULT_ISSUE_TYPE",
    "DEFAULT_PROJECT",
    "ImportResult",
    "JiraConfig",
    "JiraError",
    "TestResultImportResult",
    "build_testresult_fields",
    "find_parent_test_case",
    "import_testresult",
    "jira_config_from_env",
    "main",
    "normalize_architecture",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import a beetlejuice test-run dump into Jira as a Test Result. "
            "Parent Test Case is resolved by TestCaseID (customfield_10591)."
        ),
    )
    parser.add_argument("dump_file", type=argparse.FileType("r", encoding="utf-8"))
    parser.add_argument("-P", "--project", default=DEFAULT_PROJECT)
    parser.add_argument("--issue-type", default=DEFAULT_ISSUE_TYPE)
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--skip-assignee", action="store_true")
    parser.add_argument("--skip-components", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dump = parse_key_value_file(args.dump_file)
        config = jira_config_from_env()
        result = import_testresult(
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
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        bits = [result.action, result.issue_key or "(new)", f"parent={result.parent_key}"]
        if result.browse_url:
            bits.append(result.browse_url)
        print(" | ".join(bits))
        if result.status_warning:
            print(f"warning: {result.status_warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
