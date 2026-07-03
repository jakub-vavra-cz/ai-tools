"""GitLab activity for git-stats done."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from git_stats.cli_util import run_cmd, which
from git_stats.dates import event_on_date, parse_activity_date
from git_stats.models import DoneItem, DoneResult


def _resolve_username(hostname: str) -> tuple[str | None, str | None]:
    if not which("glab"):
        return None, "glab not found on PATH"
    result = run_cmd(["glab", "api", "user", "--hostname", hostname])
    if not result.ok:
        return None, (result.stderr or result.stdout or "glab user lookup failed").strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "glab user lookup returned non-JSON"
    username = payload.get("username")
    return (str(username) if username else None), None


def _fetch_events(
    username: str,
    *,
    hostname: str,
    max_pages: int,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        result = run_cmd(
            [
                "glab",
                "api",
                f"users/{username}/events?per_page=100&page={page}",
                "--hostname",
                hostname,
            ]
        )
        if not result.ok:
            if rows:
                return rows, None
            return None, (result.stderr or result.stdout or "glab events failed").strip()
        try:
            batch = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None, "glab events returned non-JSON"
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
    return rows, None


def _project_path(project_id: int, *, hostname: str, cache: dict[int, str]) -> str:
    if project_id in cache:
        return cache[project_id]
    encoded = urllib.parse.quote(str(project_id), safe="")
    result = run_cmd(["glab", "api", f"projects/{encoded}", "--hostname", hostname])
    if not result.ok:
        cache[project_id] = ""
        return ""
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        cache[project_id] = ""
        return ""
    path = str(payload.get("path_with_namespace") or "")
    cache[project_id] = path
    return path


def _web_base(hostname: str) -> str:
    return f"https://{hostname}"


def _mr_ref(project_path: str, iid: int | None) -> str:
    if project_path and iid:
        return f"{project_path}!{iid}"
    if project_path:
        return project_path
    return f"!{iid}" if iid else ""


def _item_from_event(
    raw: dict[str, Any],
    *,
    hostname: str,
    project_cache: dict[int, str],
) -> DoneItem | None:
    action = str(raw.get("action_name") or "updated")
    created_at = str(raw.get("created_at") or "")
    target_type = str(raw.get("target_type") or "")
    target_title = str(raw.get("target_title") or "")
    project_id = int(raw.get("project_id") or 0)
    target_iid = raw.get("target_iid")
    iid = int(target_iid) if target_iid is not None else None

    project_path = (
        _project_path(project_id, hostname=hostname, cache=project_cache) if project_id else ""
    )
    base = _web_base(hostname)

    if target_type == "MergeRequest" and iid:
        path = project_path or target_title
        url = f"{base}/{path}/-/merge_requests/{iid}" if path else base
        return DoneItem(
            action=action,
            ref=_mr_ref(project_path, iid),
            title=target_title or _mr_ref(project_path, iid),
            url=url,
            created_at=created_at,
            kind="merge_request",
        )

    if target_type in {"Note", "DiffNote"}:
        note = raw.get("note") or {}
        noteable_type = str(note.get("noteable_type") or "")
        noteable_iid = note.get("noteable_iid")
        mr_iid = int(noteable_iid) if noteable_iid is not None else iid
        if noteable_type == "MergeRequest" and mr_iid:
            path = project_path or target_title
            url = f"{base}/{path}/-/merge_requests/{mr_iid}#note_{note.get('id')}"
            return DoneItem(
                action=action,
                ref=_mr_ref(project_path, mr_iid),
                title=target_title or _mr_ref(project_path, mr_iid),
                url=url,
                created_at=created_at,
                kind="comment",
                detail=_first_line(note.get("body")) or None,
            )

    if target_type == "Project" or action == "pushed to" or action == "pushed new":
        push = raw.get("push_data") or {}
        ref = str(push.get("ref") or "")
        commit_title = str(push.get("commit_title") or "")
        path = project_path or target_title
        url = f"{base}/{path}" if path else base
        detail = ref
        if commit_title:
            detail = f"{ref}: {commit_title}" if ref else commit_title
        return DoneItem(
            action=action,
            ref=path or target_title,
            title=commit_title or target_title or f"Pushed to {ref or 'branch'}",
            url=url,
            created_at=created_at,
            kind="push",
            detail=detail or None,
        )

    if target_type == "Issue" and iid:
        path = project_path or target_title
        url = f"{base}/{path}/-/issues/{iid}" if path else base
        return DoneItem(
            action=action,
            ref=f"{project_path}#{iid}" if project_path else f"#{iid}",
            title=target_title,
            url=url,
            created_at=created_at,
            kind="issue",
        )

    if target_title:
        path = project_path or target_title
        url = f"{base}/{path}" if path else base
        return DoneItem(
            action=action,
            ref=path or target_title,
            title=target_title,
            url=url,
            created_at=created_at,
            kind=target_type.lower() or "event",
        )

    return None


def _first_line(text: str | None, *, limit: int = 120) -> str:
    if not text:
        return ""
    line = text.strip().splitlines()[0]
    return line if len(line) <= limit else f"{line[: limit - 3]}..."


def fetch_gitlab_done(
    *,
    hostname: str,
    activity_date: str | None = None,
    max_pages: int = 10,
) -> DoneResult:
    username, user_err = _resolve_username(hostname)
    if username is None:
        return DoneResult(error=user_err or "GitLab done query failed: could not resolve user")

    day = parse_activity_date(activity_date)
    rows, err = _fetch_events(username, hostname=hostname, max_pages=max_pages)
    if rows is None:
        return DoneResult(error=err or "GitLab done query failed")

    project_cache: dict[int, str] = {}
    items: list[DoneItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in rows:
        created_at = str(raw.get("created_at") or "")
        if not event_on_date(created_at, day):
            continue
        item = _item_from_event(raw, hostname=hostname, project_cache=project_cache)
        if item is None:
            continue
        key = (item.kind, item.action, item.ref, item.created_at)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    items.sort(key=lambda item: item.created_at, reverse=True)
    return DoneResult(items=items, username=username)
