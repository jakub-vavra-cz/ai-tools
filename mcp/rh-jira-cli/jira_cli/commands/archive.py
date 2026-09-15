"""Archive issues (PUT /rest/api/3/issue/archive)."""

from __future__ import annotations

import json
from typing import Any, TextIO

from jira_cli.api import JiraApiError, JiraClient, print_jira_api_error


def normalize_issue_keys(issue_keys: list[str]) -> list[str]:
    """Strip, uppercase, and dedupe issue keys while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in issue_keys:
        for part in raw.split(","):
            key = part.strip().upper()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def execute_archive_issues(
    client: JiraClient,
    *,
    issue_keys: list[str],
    err: TextIO,
) -> tuple[dict[str, Any] | None, int]:
    """Archive ``issue_keys``; returns API payload on success."""
    keys = normalize_issue_keys(issue_keys)
    if not keys:
        print("jira-cli archive: provide at least one issue key.", file=err)
        return None, 2

    try:
        result = client.archive_issues(keys)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to archive issues")
        return None, 1

    archived = result.get("numberOfIssuesUpdated")
    errors = result.get("errors") or {}
    if isinstance(errors, dict) and errors:
        print("jira-cli archive: some issues were not archived:", file=err)
        print(json.dumps(errors, indent=2), file=err)

    if not isinstance(archived, int) or archived <= 0:
        print("jira-cli archive: no issues were archived.", file=err)
        return {"issue_keys": keys, **result}, 1

    return {"issue_keys": keys, **result}, 0


def run_archive(
    client: JiraClient,
    *,
    issue_keys: list[str],
    as_json: bool = False,
    out: TextIO,
    err: TextIO,
) -> int:
    payload, rc = execute_archive_issues(client, issue_keys=issue_keys, err=err)
    if payload is None:
        return rc
    if as_json:
        json.dump(payload, out, indent=2)
        out.write("\n")
    else:
        archived = payload.get("numberOfIssuesUpdated")
        if isinstance(archived, int):
            print(archived, file=out)
    return rc
