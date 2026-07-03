"""Interactive prompts for `jira-cli edit`."""

from __future__ import annotations

import sys
from typing import Callable, Optional, TypeVar

from jira_cli.api import JiraApiError, JiraClient, print_jira_api_error, project_key_from_issue
from jira_cli.config import Settings


T = TypeVar("T")


def _pick_from_list(
    label: str,
    items: list[T],
    formatter: Callable[[T], str],
) -> Optional[T]:
    if not items:
        print(f"No options for {label}.", file=sys.stderr)
        return None
    print(f"\n{label}:", file=sys.stderr)
    for i, item in enumerate(items, start=1):
        print(f"  {i}) {formatter(item)}", file=sys.stderr)
    raw = input("Enter number (empty to skip): ").strip()
    if not raw:
        return None
    try:
        idx = int(raw) - 1
    except ValueError:
        print("Invalid number.", file=sys.stderr)
        return None
    if idx < 0 or idx >= len(items):
        print("Out of range.", file=sys.stderr)
        return None
    return items[idx]


def collect_edit_actions(
    client: JiraClient,
    settings: Settings,
    issue_key: str,
    *,
    refresh_sprint_cache: bool = False,
) -> dict[str, object]:
    """Prompt for summary, description, story points, sprint, comment, transition. Returns action dict."""
    actions: dict[str, object] = {}

    sm = input("New summary (empty to skip): ").strip()
    if sm:
        actions["summary"] = sm

    if input("Change description? [y/N]: ").strip().lower() in ("y", "yes"):
        print("Enter description (empty line to finish):", file=sys.stderr)
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line:
                break
            lines.append(line)
        body = "\n".join(lines).strip()
        if body:
            actions["description"] = body

    sp = input("Story points (empty to skip): ").strip()
    if sp:
        try:
            actions["story_points"] = float(sp) if "." in sp else int(sp)
        except ValueError:
            print("Invalid story points, skipping.", file=sys.stderr)

    if input("Change sprint? [y/N]: ").strip().lower() in ("y", "yes"):
        sprint_id = _interactive_pick_sprint(client, settings, issue_key)
        if sprint_id is not None:
            actions["sprint_id"] = sprint_id

    if input("Add comment? [y/N]: ").strip().lower() in ("y", "yes"):
        comment = input("Comment: ").strip()
        if comment:
            actions["comment"] = comment

    if input("Change workflow state? [y/N]: ").strip().lower() in ("y", "yes"):
        try:
            data = client.get_transitions(issue_key)
        except JiraApiError as e:
            print(f"Could not load transitions: {e}", file=sys.stderr)
        else:
            transitions = data.get("transitions") or []
            chosen = _pick_from_list(
                "Transition",
                transitions,
                lambda t: f"{t.get('name')} (id={t.get('id')})",
            )
            if chosen:
                actions["transition_id"] = str(chosen.get("id"))

    return actions


def _interactive_pick_sprint(
    client: JiraClient,
    _settings: Settings,
    issue_key: str,
    *,
    refresh_sprint_cache: bool = False,
) -> Optional[int]:
    proj = project_key_from_issue(issue_key)
    try:
        sprints = client.all_sprints_for_project(
            proj,
            refresh_cache=refresh_sprint_cache,
        )
    except JiraApiError as e:
        print_jira_api_error(e, sys.stderr, message="Could not list sprints")
        return None
    s = _pick_from_list(
        "Sprint",
        sprints,
        lambda s: f"{s.get('name')} (id={s.get('id')}, state={s.get('state')})",
    )
    if not s:
        return None
    return int(s["id"])
