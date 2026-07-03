"""GitHub PR queue fetchers."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from git_stats import config
from git_stats.cli_util import run_cmd, run_json_cmd, which
from git_stats.models import CategoryResult, QueueItem

_SEARCH_JSON = "number,title,url,updatedAt,isDraft,repository,state"

_GQL_SEARCH_PRS = """
query($q: String!, $n: Int!) {
  search(query: $q, type: ISSUE, first: $n) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        updatedAt
        isDraft
        state
        repository { nameWithOwner }
        reviewRequests(first: 1) { totalCount }
      }
    }
  }
}
"""


def _repo_name(raw: dict[str, Any]) -> str:
    repo = raw.get("repository") or {}
    if isinstance(repo, dict):
        name = str(repo.get("nameWithOwner") or repo.get("name") or "")
        if name:
            return name
    repo_url = str(raw.get("repository_url") or "")
    if repo_url:
        parts = repo_url.rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
    for key in ("html_url", "url"):
        url = str(raw.get(key) or "")
        marker = "github.com/"
        if marker in url:
            path = url.split(marker, 1)[1]
            owner_repo = "/".join(path.split("/")[:2])
            if owner_repo and "/" in owner_repo:
                return owner_repo
    return ""


def _item_state(raw: dict[str, Any], *, rest: bool = False) -> str | None:
    if rest:
        if raw.get("pull_request", {}).get("merged_at"):
            return "merged"
        if raw.get("state"):
            return str(raw["state"]).lower()
        return None
    state = raw.get("state")
    return str(state).lower() if state else None


def _item_from_search(raw: dict[str, Any], *, rest: bool = False) -> QueueItem:
    repo = _repo_name(raw)
    number = int(raw.get("number") or 0)
    ref = f"{repo}#{number}" if repo else f"#{number}"
    return QueueItem(
        ref=ref,
        title=str(raw.get("title") or ""),
        url=str(raw.get("url") or raw.get("html_url") or ""),
        updated_at=str(raw.get("updatedAt") or raw.get("updated_at") or ""),
        draft=bool(raw.get("isDraft")),
        repository=repo or None,
        number=number or None,
        state=_item_state(raw, rest=rest),
    )


def _sort_items(items: list[QueueItem]) -> list[QueueItem]:
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def _merge_items(items: list[QueueItem]) -> list[QueueItem]:
    merged: dict[str, QueueItem] = {}
    for item in items:
        merged[item.url] = item
    return _sort_items(list(merged.values()))


def _has_pending_review_requests(raw: dict[str, Any]) -> bool:
    requests = raw.get("reviewRequests")
    if isinstance(requests, dict):
        return int(requests.get("totalCount") or 0) > 0
    if isinstance(requests, list):
        return len(requests) > 0
    return False


def _rows_to_items(rows: list[dict[str, Any]], *, rest: bool = False) -> list[QueueItem]:
    return [_item_from_search(row, rest=rest) for row in rows]


def _open_qualifier(include_all: bool) -> str:
    return "" if include_all else "is:open "


def _gh_search_one(
    *,
    search_args: list[str],
    api_query: str,
    rest_query: str,
    limit: int,
    state: str,
    json_fields: str = _SEARCH_JSON,
) -> tuple[list[dict[str, Any]] | None, str, str | None]:
    if not which("gh"):
        rows = _rest_search(rest_query, limit=limit)
        if rows is not None:
            return rows, "api", None
        return None, "gh", "gh not found on PATH"

    args = ["gh", "search", "prs", f"--state={state}", f"--limit={limit}", *search_args]
    result, parsed = run_json_cmd(args, json_fields=json_fields)
    if result.ok and isinstance(parsed, list):
        return parsed, "gh", None

    stderr = (result.stderr or result.stdout or "gh search failed").strip()
    api = run_cmd(
        [
            "gh",
            "api",
            "search/issues",
            "-f",
            f"q={api_query}",
            "-f",
            f"per_page={limit}",
            "-f",
            "sort=updated",
            "-f",
            "order=desc",
        ]
    )
    if api.ok:
        payload = json.loads(api.stdout)
        items = payload.get("items") or []
        if isinstance(items, list):
            return items, "gh", None

    rows = _rest_search(rest_query, limit=limit)
    if rows is not None:
        return rows, "api", None
    return None, "gh", stderr


def _gh_search(
    *,
    search_args: list[str],
    api_query: str,
    rest_query: str,
    limit: int,
    include_all: bool,
    json_fields: str = _SEARCH_JSON,
) -> tuple[list[dict[str, Any]] | None, str, str | None]:
    if not include_all:
        return _gh_search_one(
            search_args=search_args,
            api_query=api_query,
            rest_query=rest_query,
            limit=limit,
            state="open",
            json_fields=json_fields,
        )

    rows_open, source, err_open = _gh_search_one(
        search_args=search_args,
        api_query=api_query.replace("is:open ", "", 1) if "is:open " in api_query else api_query,
        rest_query=rest_query.replace("is:open ", "", 1)
        if "is:open " in rest_query
        else rest_query,
        limit=limit,
        state="open",
        json_fields=json_fields,
    )
    closed_query = api_query.replace("is:open ", "is:closed ", 1)
    closed_rest = rest_query.replace("is:open ", "is:closed ", 1)
    rows_closed, source_closed, err_closed = _gh_search_one(
        search_args=search_args,
        api_query=closed_query,
        rest_query=closed_rest,
        limit=limit,
        state="closed",
        json_fields=json_fields,
    )
    if rows_open is None and rows_closed is None:
        return None, "gh", err_open or err_closed
    combined = (rows_open or []) + (rows_closed or [])
    return combined, source or source_closed or "gh", None


def _rest_search(query: str, *, limit: int) -> list[dict[str, Any]] | None:
    token = config.github_token()
    if not token:
        return None
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": str(limit),
        }
    )
    url = f"https://api.github.com/search/issues?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except OSError:
        return None
    items = payload.get("items")
    return items if isinstance(items, list) else None


def _resolve_username() -> str | None:
    if not which("gh"):
        return None
    result = run_cmd(["gh", "api", "user", "--jq", ".login"])
    if result.ok:
        login = result.stdout.strip()
        return login or None
    return None


def _graphql_search_pull_requests(
    *,
    search_query: str,
    limit: int,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not which("gh"):
        return None, "gh not found on PATH"
    result = run_cmd(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={_GQL_SEARCH_PRS}",
            "-f",
            f"q={search_query}",
            "-F",
            f"n={limit}",
        ]
    )
    if not result.ok:
        return None, (result.stderr or result.stdout or "gh graphql failed").strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "gh graphql returned invalid JSON"
    errors = payload.get("errors")
    if errors:
        message = "; ".join(str(err.get("message") or err) for err in errors)
        return None, message or "gh graphql returned errors"
    nodes = (payload.get("data") or {}).get("search", {}).get("nodes") or []
    if not isinstance(nodes, list):
        return None, "gh graphql returned unexpected search payload"
    return [node for node in nodes if isinstance(node, dict)], None


def fetch_review_requested(*, limit: int, include_all: bool) -> CategoryResult:
    open_q = _open_qualifier(include_all)
    rows, source, err = _gh_search(
        search_args=["--review-requested=@me"],
        api_query=f"is:pr {open_q}review-requested:@me".strip(),
        rest_query=f"is:pr {open_q}review-requested:@me".strip(),
        limit=limit,
        include_all=include_all,
    )
    if rows is None:
        return CategoryResult(error=err or "GitHub review_requested query failed")
    items = _rows_to_items(rows, rest=(source == "api"))
    return CategoryResult(items=_merge_items(items)[:limit])


def fetch_authored_changes_requested(*, limit: int, include_all: bool) -> CategoryResult:
    open_q = _open_qualifier(include_all)
    rows, source, err = _gh_search(
        search_args=["--author=@me", "--review=changes_requested"],
        api_query=f"is:pr {open_q}author:@me review:changes_requested".strip(),
        rest_query=f"is:pr {open_q}author:@me review:changes_requested".strip(),
        limit=limit,
        include_all=include_all,
    )
    if rows is None:
        return CategoryResult(error=err or "GitHub authored_changes_requested query failed")
    items = _rows_to_items(rows, rest=(source == "api"))
    return CategoryResult(items=_merge_items(items)[:limit])


def fetch_authored_no_reviewer(*, limit: int, include_all: bool) -> CategoryResult:
    login = _resolve_username()
    if not login:
        return CategoryResult(
            error="GitHub authored_no_reviewer query failed: could not resolve @me"
        )

    pool = min(limit * 3, 100)
    open_q = _open_qualifier(include_all)
    rows, err = _graphql_search_pull_requests(
        search_query=f"is:pr {open_q}author:{login}".strip(),
        limit=pool,
    )
    if rows is None:
        return CategoryResult(error=err or "GitHub authored_no_reviewer query failed")
    filtered = [_item_from_search(raw) for raw in rows if not _has_pending_review_requests(raw)]
    return CategoryResult(items=_merge_items(filtered)[:limit])


def _pr_list_state(include_all: bool) -> list[str]:
    return ["--state", "all"] if include_all else ["--state", "open"]


def _pr_list_items(
    clone_args: list[str],
    *,
    cwd: Any,
    limit: int,
    predicate: Any,
    include_all: bool,
) -> list[QueueItem]:
    result, parsed = run_json_cmd(
        ["gh", "pr", "list", *_pr_list_state(include_all), *clone_args],
        cwd=cwd,
    )
    if not result.ok or not isinstance(parsed, list):
        return []
    items = [_item_from_search(row) for row in parsed if predicate(row)]
    return _sort_items(items)[:limit]


def repo_scan_category(
    category: str,
    *,
    clones: list[tuple[str, Any, Any]],
    limit: int,
    include_all: bool,
) -> list[QueueItem]:
    merged: dict[str, QueueItem] = {}
    for _name, host, path in clones:
        if host != "github":
            continue
        if category == "review_requested":
            found = _pr_list_items(
                ["--review-requested", "@me"],
                cwd=path,
                limit=limit,
                predicate=lambda _row: True,
                include_all=include_all,
            )
        elif category == "authored_changes_requested":
            found = _pr_list_items(
                ["--author", "@me"],
                cwd=path,
                limit=limit,
                predicate=lambda row: (
                    str(row.get("reviewDecision") or "").upper() == "CHANGES_REQUESTED"
                ),
                include_all=include_all,
            )
        elif category == "authored_no_reviewer":
            found = _pr_list_items(
                ["--author", "@me"],
                cwd=path,
                limit=limit,
                predicate=lambda row: not _has_pending_review_requests(row),
                include_all=include_all,
            )
        else:
            found = []
        for item in found:
            merged[item.url] = item
    return _sort_items(list(merged.values()))[:limit]


def fetch_github(
    categories: list[str],
    *,
    github_limit: int,
    clones: list[tuple[str, Any, Any]],
    include_all: bool,
) -> dict[str, Any]:
    fetchers = {
        "review_requested": lambda: fetch_review_requested(
            limit=github_limit, include_all=include_all
        ),
        "authored_changes_requested": lambda: fetch_authored_changes_requested(
            limit=github_limit, include_all=include_all
        ),
        "authored_no_reviewer": lambda: fetch_authored_no_reviewer(
            limit=github_limit, include_all=include_all
        ),
    }
    host: dict[str, Any] = {
        "ok": True,
        "source": "gh",
        "username": _resolve_username(),
        "error": None,
    }
    errors: list[str] = []
    used_repo_scan = False
    for category in categories:
        result = fetchers[category]()
        if result.error:
            scanned = repo_scan_category(
                category,
                clones=clones,
                limit=github_limit,
                include_all=include_all,
            )
            if scanned:
                used_repo_scan = True
                result = CategoryResult(items=scanned)
            else:
                errors.append(f"{category}: {result.error}")
                host[category] = {"count": 0, "items": []}
                continue
        host[category] = result.to_dict()
    if used_repo_scan:
        host["source"] = "repo-scan"
    if errors:
        host["error"] = "; ".join(errors)
        if not any(host.get(cat, {}).get("count") for cat in categories):
            host["ok"] = False
    return host
