"""Move an issue to another project (POST /rest/api/3/bulk/issues/move)."""

from __future__ import annotations

import json
import time
from typing import Any, TextIO

from jira_cli.api import JiraApiError, JiraClient, print_jira_api_error, project_key_from_issue


def resolve_project_issuetype_id(
    client: JiraClient,
    project_key: str,
    issuetype_name: str,
    err: TextIO,
) -> str | None:
    """Return issue type id for ``issuetype_name`` in ``project_key`` (createmeta issuetypes)."""
    name = issuetype_name.strip()
    if not name:
        print("jira-cli move: issue type name must not be empty.", file=err)
        return None
    try:
        types = client.get_create_issue_issuetypes(project_key)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to list issue types for project")
        return None
    matches = [
        t
        for t in types
        if isinstance(t.get("name"), str) and t["name"].strip().lower() == name.lower()
    ]
    if len(matches) == 1:
        tid = matches[0].get("id")
        if isinstance(tid, str) and tid.strip():
            return tid.strip()
        print(
            f"jira-cli move: issue type {name!r} in project {project_key!r} has no id.",
            file=err,
        )
        return None
    if len(matches) > 1:
        print(
            f"jira-cli move: multiple issue types named {name!r} in project {project_key!r}.",
            file=err,
        )
        return None
    available = sorted(
        str(t.get("name") or "")
        for t in types
        if isinstance(t.get("name"), str) and str(t["name"]).strip()
    )
    print(
        f"jira-cli move: issue type {name!r} is not available in project {project_key!r}.",
        file=err,
    )
    if available:
        print(f"Available types: {', '.join(available)}", file=err)
    return None


def _wait_for_bulk_task(
    client: JiraClient,
    task_id: str,
    *,
    err: TextIO,
    timeout_s: float = 120.0,
    poll_s: float = 0.5,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            data = client.get_bulk_task(task_id)
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to get bulk move task status")
            return None
        status = str(data.get("status") or "").upper()
        if status == "COMPLETE":
            return data
        if status in ("FAILED", "CANCELLED", "CANCELED"):
            print(f"jira-cli move: bulk task {task_id} ended with status {status!r}.", file=err)
            print(json.dumps(data, indent=2), file=err)
            return None
        time.sleep(poll_s)
    print(f"jira-cli move: timed out waiting for bulk task {task_id}.", file=err)
    return None


def execute_move_issue(
    client: JiraClient,
    *,
    issue_key: str,
    project: str,
    issue_type: str | None = None,
    err: TextIO,
) -> tuple[dict[str, Any] | None, int]:
    """
    Move ``issue_key`` to ``project``.

    Returns ``({"issue_key": ..., "task": ..., "task_result": ...}, 0)`` on success.
    """
    key = issue_key.strip().upper()
    target_project = project.strip().upper()
    if not key:
        print("jira-cli move: issue key must not be empty.", file=err)
        return None, 2
    if not target_project:
        print("jira-cli move: --project must not be empty.", file=err)
        return None, 2
    try:
        project_key_from_issue(key)
    except ValueError:
        print(
            f"jira-cli move: invalid issue key {key!r} (expected format PROJ-123).",
            file=err,
        )
        return None, 2

    try:
        issue = client.get_issue(key, fields=["project", "issuetype"])
    except JiraApiError as e:
        print_jira_api_error(e, err)
        return None, 1

    issue_id = issue.get("id")
    fields = issue.get("fields") or {}
    source_project = (fields.get("project") or {}).get("key")
    current_type = (fields.get("issuetype") or {}).get("name")
    if not isinstance(source_project, str) or not source_project.strip():
        print(f"jira-cli move: could not read project for {key}.", file=err)
        return None, 1
    if not isinstance(current_type, str) or not current_type.strip():
        print(f"jira-cli move: could not read issue type for {key}.", file=err)
        return None, 1

    target_type_name = (
        issue_type.strip()
        if issue_type is not None and str(issue_type).strip()
        else current_type.strip()
    )
    if source_project.strip().upper() == target_project and (
        issue_type is None or target_type_name.lower() == current_type.strip().lower()
    ):
        print(f"jira-cli move: {key} is already in project {target_project}.", file=err)
        return {"issue_key": key, "unchanged": True}, 0

    issuetype_id = resolve_project_issuetype_id(client, target_project, target_type_name, err)
    if issuetype_id is None:
        return None, 1

    mapping_key = f"{target_project},{issuetype_id}"
    payload = {
        "sendBulkNotification": False,
        "targetToSourcesMapping": {
            mapping_key: {
                "issueIdsOrKeys": [key],
                "inferClassificationDefaults": True,
                "inferFieldDefaults": True,
                "inferStatusDefaults": True,
                "inferSubtaskTypeDefault": True,
            }
        },
    }

    try:
        submitted = client.bulk_move_issues(payload)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to submit bulk move")
        return None, 1

    task_id = submitted.get("taskId")
    if not isinstance(task_id, str) or not task_id.strip():
        print("jira-cli move: bulk move response missing taskId.", file=err)
        return None, 1

    task_result = _wait_for_bulk_task(client, task_id.strip(), err=err)
    if task_result is None:
        return None, 1

    invalid = task_result.get("invalidOrInaccessibleIssueCount")
    if isinstance(invalid, int) and invalid > 0:
        print(
            f"jira-cli move: bulk task skipped {invalid} invalid or inaccessible issue(s).",
            file=err,
        )
        print(json.dumps(task_result, indent=2), file=err)
        return None, 1

    new_key = key
    if isinstance(issue_id, str) and issue_id.strip():
        try:
            moved = client.get_issue(issue_id.strip(), fields=["key", "project"])
            maybe_key = moved.get("key")
            if isinstance(maybe_key, str) and maybe_key.strip():
                new_key = maybe_key.strip().upper()
        except JiraApiError as e:
            print_jira_api_error(
                e,
                err,
                message="Move completed but failed to fetch moved issue key",
            )
            return None, 1

    return {
        "issue_key": new_key,
        "source_issue_key": key,
        "target_project": target_project,
        "target_issue_type": target_type_name,
        "task": submitted,
        "task_result": task_result,
    }, 0


def run_move(
    client: JiraClient,
    *,
    issue_key: str,
    project: str,
    issue_type: str | None = None,
    as_json: bool = False,
    out: TextIO,
    err: TextIO,
) -> int:
    payload, rc = execute_move_issue(
        client,
        issue_key=issue_key,
        project=project,
        issue_type=issue_type,
        err=err,
    )
    if rc != 0:
        return rc
    assert payload is not None
    new_key = payload.get("issue_key")
    if payload.get("unchanged"):
        if as_json:
            json.dump(payload, out, indent=2)
            out.write("\n")
        else:
            print(new_key, file=out)
        return 0

    if as_json:
        json.dump(payload, out, indent=2)
        out.write("\n")
    else:
        print(new_key, file=out)

    old_key = payload.get("source_issue_key")
    if isinstance(old_key, str) and old_key != new_key:
        print(f"Moved {old_key} -> {new_key}", file=err)
    else:
        print(f"Moved to {new_key}", file=err)
    return 0
