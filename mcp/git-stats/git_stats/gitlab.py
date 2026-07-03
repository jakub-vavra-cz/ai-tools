"""GitLab MR queue fetchers."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any
from urllib.parse import urlencode

from git_stats.cli_util import run_cmd, run_json_cmd, which
from git_stats.models import CategoryResult, QueueItem

_GQL_REVIEW_REQUESTED = """
query($state: MergeRequestState, $first: Int!) {
  currentUser {
    reviewRequestedMergeRequests(
      state: $state
      reviewState: UNREVIEWED
      first: $first
    ) {
      nodes {
        title
        iid
        webUrl
        updatedAt
        draft
        state
        project { fullPath }
      }
    }
  }
}
"""


def _glab_api(path: str, *, hostname: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not which("glab"):
        return None, "glab not found on PATH"
    result = run_cmd(["glab", "api", path, "--hostname", hostname])
    if not result.ok:
        return None, (result.stderr or result.stdout or "glab api failed").strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "glab api returned non-JSON"
    if isinstance(payload, list):
        return payload, None
    return None, "unexpected glab api response"


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


def _item_from_mr(raw: dict[str, Any]) -> QueueItem:
    refs = raw.get("references") or {}
    ref = str(refs.get("full") or "")
    project = raw.get("project") or {}
    path_with_namespace = ""
    if isinstance(project, dict):
        path_with_namespace = str(
            project.get("path_with_namespace") or project.get("fullPath") or ""
        )
    if not path_with_namespace:
        path_with_namespace = str(raw.get("references", {}).get("full", "")).split("!")[0]
    if not ref and path_with_namespace and raw.get("iid") is not None:
        ref = f"{path_with_namespace}!{raw['iid']}"
    state = raw.get("state")
    return QueueItem(
        ref=ref,
        title=str(raw.get("title") or ""),
        url=str(raw.get("web_url") or raw.get("webUrl") or ""),
        updated_at=str(raw.get("updated_at") or raw.get("updatedAt") or ""),
        draft=bool(raw.get("draft")),
        work_in_progress=bool(raw.get("work_in_progress")),
        project=path_with_namespace or None,
        iid=int(raw["iid"]) if raw.get("iid") is not None else None,
        state=str(state).lower() if state else None,
    )


def _sort_items(items: list[QueueItem]) -> list[QueueItem]:
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def _query(username: str, *, include_all: bool, **params: str) -> str:
    base = {
        "scope": "all",
        "state": "all" if include_all else "opened",
        "per_page": params.pop("per_page", "30"),
    }
    base.update(params)
    return f"merge_requests?{urlencode(base)}"


def _project_path_from_mr(raw: dict[str, Any]) -> str:
    project = raw.get("project") or {}
    if isinstance(project, dict):
        path = str(project.get("path_with_namespace") or project.get("fullPath") or "")
        if path:
            return path
    refs = raw.get("references") or {}
    ref = str(refs.get("full") or "")
    if "!" in ref:
        return ref.split("!", 1)[0]
    return ""


def _user_has_approved_mr(
    *,
    project_path: str,
    iid: int,
    hostname: str,
) -> bool | None:
    if not project_path or not which("glab"):
        return None
    encoded = urllib.parse.quote(project_path, safe="")
    path = f"projects/{encoded}/merge_requests/{iid}/approvals"
    result = run_cmd(["glab", "api", path, "--hostname", hostname])
    if not result.ok:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return bool(payload.get("user_has_approved"))


def _graphql_review_requested(
    *,
    hostname: str,
    limit: int,
    include_all: bool,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not which("glab"):
        return None, "glab not found on PATH"

    pool = min(limit * 3, 100)
    args = [
        "glab",
        "api",
        "graphql",
        "--hostname",
        hostname,
        "-f",
        f"query={_GQL_REVIEW_REQUESTED}",
        "-F",
        f"first={pool}",
    ]
    if not include_all:
        args.extend(["-f", "state=opened"])
    result = run_cmd(args)
    if not result.ok:
        return None, (result.stderr or result.stdout or "glab graphql failed").strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "glab graphql returned non-JSON"
    errors = payload.get("errors")
    if errors:
        message = "; ".join(str(err.get("message") or err) for err in errors)
        return None, message or "glab graphql returned errors"
    nodes = (payload.get("data") or {}).get("currentUser", {}).get(
        "reviewRequestedMergeRequests", {}
    ).get("nodes") or []
    if not isinstance(nodes, list):
        return None, "glab graphql returned unexpected reviewRequestedMergeRequests payload"
    return [node for node in nodes if isinstance(node, dict)], None


def _partition_review_items(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    include_drafts: bool,
) -> CategoryResult:
    items: list[QueueItem] = []
    drafts: list[QueueItem] = []
    for row in rows:
        item = _item_from_mr(row)
        if item.draft or item.work_in_progress:
            drafts.append(item)
            if include_drafts:
                items.append(item)
        else:
            items.append(item)
    return CategoryResult(
        items=_sort_items(items)[:limit],
        drafts=_sort_items(drafts),
    )


def fetch_review_requested(
    *,
    username: str,
    hostname: str,
    limit: int,
    include_drafts: bool,
    include_all: bool,
) -> CategoryResult:
    rows, err = _graphql_review_requested(
        hostname=hostname,
        limit=limit,
        include_all=include_all,
    )
    if rows is not None:
        return _partition_review_items(rows, limit=limit, include_drafts=include_drafts)

    pool = min(limit * 3, 100)
    path = _query(username, include_all=include_all, reviewer_username=username, per_page=str(pool))
    rows, err = _glab_api(path, hostname=hostname)
    if rows is None:
        return CategoryResult(error=err)
    pending: list[dict[str, Any]] = []
    for row in rows:
        project_path = _project_path_from_mr(row)
        iid = int(row.get("iid") or 0)
        if not iid:
            continue
        approved = _user_has_approved_mr(
            project_path=project_path,
            iid=iid,
            hostname=hostname,
        )
        if approved is True:
            continue
        pending.append(row)
    return _partition_review_items(pending, limit=limit, include_drafts=include_drafts)


def fetch_authored_changes_requested(
    *,
    username: str,
    hostname: str,
    limit: int,
    include_all: bool,
) -> CategoryResult:
    pool = min(limit * 3, 100)
    path = _query(username, include_all=include_all, author_username=username, per_page=str(pool))
    rows, err = _glab_api(path, hostname=hostname)
    if rows is None:
        return CategoryResult(error=err)
    filtered = [
        _item_from_mr(row)
        for row in rows
        if str(row.get("detailed_merge_status") or "") == "requested_changes"
    ]
    return CategoryResult(items=_sort_items(filtered)[:limit])


def fetch_authored_no_reviewer(
    *,
    username: str,
    hostname: str,
    limit: int,
    include_all: bool,
) -> CategoryResult:
    path = _query(
        username,
        include_all=include_all,
        author_username=username,
        reviewer_username="None",
        per_page=str(limit),
    )
    rows, err = _glab_api(path, hostname=hostname)
    if rows is None:
        return CategoryResult(error=err)
    items = [_item_from_mr(row) for row in rows]
    return CategoryResult(items=_sort_items(items)[:limit])


def _mr_list_scope(include_all: bool) -> list[str]:
    return ["--all"] if include_all else []


def _mr_list_items(
    list_args: list[str],
    *,
    cwd: Any,
    limit: int,
    predicate: Any,
    include_all: bool,
    hostname: str | None = None,
) -> list[QueueItem]:
    result, parsed = run_json_cmd(
        ["glab", "mr", "list", *_mr_list_scope(include_all), *list_args],
        cwd=cwd,
    )
    if not result.ok or not isinstance(parsed, list):
        return []
    items: list[QueueItem] = []
    for row in parsed:
        if not predicate(row):
            continue
        if hostname is not None:
            project_path = _project_path_from_mr(row)
            iid = int(row.get("iid") or 0)
            if iid and _user_has_approved_mr(
                project_path=project_path,
                iid=iid,
                hostname=hostname,
            ):
                continue
        items.append(_item_from_mr(row))
    return _sort_items(items)[:limit]


def repo_scan_category(
    category: str,
    *,
    clones: list[tuple[str, Any, Any]],
    limit: int,
    include_drafts: bool,
    include_all: bool,
    gitlab_host: str | None = None,
) -> CategoryResult:
    merged: dict[str, QueueItem] = {}
    merged_drafts: dict[str, QueueItem] = {}
    draft_flag = [] if include_all else ["--not-draft"]
    for _name, host, path in clones:
        if host != "gitlab":
            continue
        if category == "review_requested":
            found = _mr_list_items(
                ["--reviewer=@me", *draft_flag],
                cwd=path,
                limit=limit,
                predicate=lambda _row: True,
                include_all=include_all,
                hostname=gitlab_host,
            )
            for item in found:
                merged[item.url] = item
        elif category == "authored_changes_requested":
            found = _mr_list_items(
                ["--author=@me"],
                cwd=path,
                limit=limit,
                predicate=lambda row: (
                    str(row.get("detailed_merge_status") or "") == "requested_changes"
                ),
                include_all=include_all,
            )
            for item in found:
                merged[item.url] = item
        elif category == "authored_no_reviewer":
            found = _mr_list_items(
                ["--author=@me"],
                cwd=path,
                limit=limit,
                predicate=lambda row: not (row.get("reviewers") or []),
                include_all=include_all,
            )
            for item in found:
                merged[item.url] = item
    items = _sort_items(list(merged.values()))[:limit]
    drafts = _sort_items(list(merged_drafts.values()))
    return CategoryResult(items=items, drafts=drafts if category == "review_requested" else [])


def fetch_gitlab(
    categories: list[str],
    *,
    gitlab_limit: int,
    gitlab_host: str,
    include_drafts: bool,
    clones: list[tuple[str, Any, Any]],
    include_all: bool,
) -> dict[str, Any]:
    username, user_err = _resolve_username(gitlab_host)
    host: dict[str, Any] = {
        "ok": True,
        "source": "api",
        "username": username,
        "error": None,
    }
    if username is None:
        host["ok"] = False
        host["error"] = user_err
        used_repo_scan = False
        for category in categories:
            scanned = repo_scan_category(
                category,
                clones=clones,
                limit=gitlab_limit,
                include_drafts=include_drafts,
                include_all=include_all,
                gitlab_host=gitlab_host,
            )
            if scanned.items or scanned.drafts:
                used_repo_scan = True
                host[category] = scanned.to_dict(include_drafts=include_drafts)
            else:
                host[category] = {"count": 0, "items": []}
        if used_repo_scan:
            host["source"] = "repo-scan"
            host["ok"] = True
        return host

    fetchers = {
        "review_requested": lambda: fetch_review_requested(
            username=username,
            hostname=gitlab_host,
            limit=gitlab_limit,
            include_drafts=include_drafts,
            include_all=include_all,
        ),
        "authored_changes_requested": lambda: fetch_authored_changes_requested(
            username=username,
            hostname=gitlab_host,
            limit=gitlab_limit,
            include_all=include_all,
        ),
        "authored_no_reviewer": lambda: fetch_authored_no_reviewer(
            username=username,
            hostname=gitlab_host,
            limit=gitlab_limit,
            include_all=include_all,
        ),
    }
    errors: list[str] = []
    used_repo_scan = False
    for category in categories:
        result = fetchers[category]()
        if result.error:
            scanned = repo_scan_category(
                category,
                clones=clones,
                limit=gitlab_limit,
                include_drafts=include_drafts,
                include_all=include_all,
                gitlab_host=gitlab_host,
            )
            if scanned.items or scanned.drafts:
                used_repo_scan = True
                result = scanned
            else:
                errors.append(f"{category}: {result.error}")
                host[category] = {"count": 0, "items": []}
                continue
        host[category] = result.to_dict(include_drafts=include_drafts)
    if used_repo_scan:
        host["source"] = "repo-scan"
    if errors and not any(host.get(cat, {}).get("items") for cat in categories):
        host["ok"] = False
        host["error"] = "; ".join(errors)
    elif errors:
        host["error"] = "; ".join(errors)
    return host
