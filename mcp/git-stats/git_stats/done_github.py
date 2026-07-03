"""GitHub activity for git-stats done."""

from __future__ import annotations

import json
from typing import Any

from git_stats.cli_util import run_cmd, which
from git_stats.dates import event_on_date, parse_activity_date
from git_stats.done_group import group_done_items
from git_stats.models import DoneItem, DoneResult

_SKIP_EVENT_TYPES = frozenset(
    {
        "WatchEvent",
        "PublicEvent",
        "MemberEvent",
        "GollumEvent",
        "FollowEvent",
    }
)


def _resolve_username() -> str | None:
    if not which("gh"):
        return None
    result = run_cmd(["gh", "api", "user", "--jq", ".login"])
    if result.ok:
        login = result.stdout.strip()
        return login or None
    return None


def _fetch_events(login: str, *, max_pages: int) -> tuple[list[dict[str, Any]] | None, str | None]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        result = run_cmd(
            [
                "gh",
                "api",
                f"/users/{login}/events?per_page=100&page={page}",
            ]
        )
        if not result.ok:
            if rows:
                return rows, None
            return None, (result.stderr or result.stdout or "gh events failed").strip()
        try:
            batch = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None, "gh events returned non-JSON"
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
    return rows, None


def _html_pull_url(api_url: str) -> str:
    if api_url.startswith("https://api.github.com/repos/"):
        return api_url.replace("https://api.github.com/repos/", "https://github.com/").replace(
            "/pulls/", "/pull/"
        )
    return api_url


def _repo_ref(repo_name: str, number: int | None) -> str:
    if number:
        return f"{repo_name}#{number}"
    return repo_name


def _first_line(text: str | None, *, limit: int = 120) -> str:
    if not text:
        return ""
    line = text.strip().splitlines()[0]
    return line if len(line) <= limit else f"{line[: limit - 3]}..."


def _item_from_event(raw: dict[str, Any]) -> DoneItem | None:
    event_type = str(raw.get("type") or "")
    if event_type in _SKIP_EVENT_TYPES:
        return None

    repo_name = str((raw.get("repo") or {}).get("name") or "")
    created_at = str(raw.get("created_at") or "")
    payload = raw.get("payload") or {}

    if event_type == "PullRequestReviewEvent":
        review = payload.get("review") or {}
        pull = payload.get("pull_request") or {}
        number = pull.get("number")
        state = str(review.get("state") or "reviewed").replace("_", " ")
        url = str(review.get("html_url") or _html_pull_url(str(pull.get("url") or "")))
        return DoneItem(
            action=state,
            ref=_repo_ref(repo_name, int(number) if number else None),
            title=_first_line(review.get("body"))
            or f"Review on {_repo_ref(repo_name, int(number) if number else None)}",
            url=url,
            created_at=created_at,
            kind="review",
            detail=state,
        )

    if event_type == "PullRequestEvent":
        action = str(payload.get("action") or "updated")
        pull = payload.get("pull_request") or {}
        number = pull.get("number")
        merged = bool(pull.get("merged"))
        if action == "closed" and merged:
            action = "merged"
        url = _html_pull_url(str(pull.get("url") or ""))
        title = str(
            pull.get("title")
            or f"Pull request {_repo_ref(repo_name, int(number) if number else None)}"
        )
        return DoneItem(
            action=action,
            ref=_repo_ref(repo_name, int(number) if number else None),
            title=title,
            url=url,
            created_at=created_at,
            kind="pull_request",
        )

    if event_type == "PushEvent":
        ref = str(payload.get("ref") or "")
        branch = ref.split("/")[-1] if ref else ""
        commits = payload.get("commits") or []
        commit_title = ""
        if isinstance(commits, list) and commits:
            commit_title = _first_line(str((commits[-1] or {}).get("message") or ""))
        url = f"https://github.com/{repo_name}"
        detail = branch
        if commit_title:
            detail = f"{branch}: {commit_title}" if branch else commit_title
        return DoneItem(
            action="pushed",
            ref=repo_name,
            title=commit_title or f"Pushed to {branch or 'branch'}",
            url=url,
            created_at=created_at,
            kind="push",
            detail=detail or None,
        )

    if event_type == "IssuesEvent":
        action = str(payload.get("action") or "updated")
        issue = payload.get("issue") or {}
        number = issue.get("number")
        url = str(issue.get("html_url") or "")
        title = str(
            issue.get("title") or f"Issue {_repo_ref(repo_name, int(number) if number else None)}"
        )
        return DoneItem(
            action=action,
            ref=_repo_ref(repo_name, int(number) if number else None),
            title=title,
            url=url,
            created_at=created_at,
            kind="issue",
        )

    if event_type == "IssueCommentEvent":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        comment = payload.get("comment") or {}
        url = str(comment.get("html_url") or issue.get("html_url") or "")
        title = str(
            issue.get("title")
            or f"Comment on {_repo_ref(repo_name, int(number) if number else None)}"
        )
        return DoneItem(
            action="commented",
            ref=_repo_ref(repo_name, int(number) if number else None),
            title=title,
            url=url,
            created_at=created_at,
            kind="comment",
            detail=_first_line(comment.get("body")) or None,
        )

    if event_type == "CreateEvent":
        ref_type = str(payload.get("ref_type") or "")
        if ref_type not in {"branch", "tag", "repository"}:
            return None
        ref = str(payload.get("ref") or repo_name)
        return DoneItem(
            action=f"created {ref_type}",
            ref=repo_name if ref_type == "repository" else _repo_ref(repo_name, None),
            title=ref,
            url=f"https://github.com/{repo_name}",
            created_at=created_at,
            kind=ref_type,
            detail=ref,
        )

    if event_type == "ReleaseEvent":
        action = str(payload.get("action") or "published")
        release = payload.get("release") or {}
        tag = str(release.get("tag_name") or "")
        url = str(release.get("html_url") or f"https://github.com/{repo_name}/releases")
        return DoneItem(
            action=action,
            ref=repo_name,
            title=str(release.get("name") or tag or "Release"),
            url=url,
            created_at=created_at,
            kind="release",
            detail=tag or None,
        )

    return None


def fetch_github_done(
    *,
    activity_date: str | None = None,
    max_pages: int = 10,
) -> DoneResult:
    login = _resolve_username()
    if not login:
        return DoneResult(error="GitHub done query failed: gh not found or user lookup failed")

    day = parse_activity_date(activity_date)
    rows, err = _fetch_events(login, max_pages=max_pages)
    if rows is None:
        return DoneResult(error=err or "GitHub done query failed")

    items: list[DoneItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in rows:
        created_at = str(raw.get("created_at") or "")
        if not event_on_date(created_at, day):
            continue
        item = _item_from_event(raw)
        if item is None:
            continue
        key = (item.kind, item.action, item.ref, item.created_at)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    items.sort(key=lambda item: item.created_at, reverse=True)
    return DoneResult(items=group_done_items(items), username=login)
