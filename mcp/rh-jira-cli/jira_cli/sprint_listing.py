"""Shared sprint listing for CLI and programmatic callers."""

from __future__ import annotations

from typing import Any

from jira_cli.api import JiraApiError, JiraClient
from jira_cli import sprint_cache


def fetch_project_sprint_rows(
    client: JiraClient,
    *,
    project: str,
    state: str,
    refresh_sprint_cache: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Return sprint rows for Scrum boards in a project.

    Each row is ``{"id": int|None, "state": str, "board_name": str, "name": str}``.
    On failure returns ``([], error_message)`` (empty list and a human-readable error).
    """
    scope_key = "all"
    if not refresh_sprint_cache and sprint_cache.is_enabled():
        cached = sprint_cache.load_by_board_sprints(project, state, scope_key)
        if cached is not None:
            rows: list[dict[str, Any]] = []
            for b in cached:
                bname = b.get("name") or ""
                for s in b.get("sprints") or []:
                    rows.append(
                        {
                            "id": s.get("id"),
                            "state": s.get("state") or "",
                            "board_name": bname,
                            "name": s.get("name") or "",
                        }
                    )
            return rows, None

    try:
        boards_data = client.boards_for_project(
            project,
            board_type="scrum",
        )
    except JiraApiError as e:
        return [], str(e)

    boards = boards_data.get("values") or []
    if not boards:
        return [], f"No boards for project {project}."

    boards_payload: list[dict] = []
    rows = []
    for b in boards:
        bid = int(b["id"])
        bname = b.get("name") or ""
        sprints = client.all_sprints_for_board(bid, state=state)
        boards_payload.append({"id": bid, "name": bname, "sprints": sprints})
        for s in sprints:
            rows.append(
                {
                    "id": s.get("id"),
                    "state": s.get("state") or "",
                    "board_name": bname,
                    "name": s.get("name") or "",
                }
            )
    if sprint_cache.is_enabled():
        sprint_cache.save_by_board_sprints(project, state, scope_key, boards_payload)
    return rows, None
