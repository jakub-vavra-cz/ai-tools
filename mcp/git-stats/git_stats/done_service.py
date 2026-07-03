"""Done activity orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from git_stats import config
from git_stats.categories import normalize_hosts
from git_stats.dates import parse_activity_date
from git_stats import done_github, done_gitlab


def done_fetch(
    *,
    activity_date: date | str | None = None,
    hosts: list[str] | None = None,
    gitlab_host: str | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    try:
        resolved_hosts = normalize_hosts(hosts)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    day = parse_activity_date(activity_date)
    gl_host = config.default_gitlab_host() if gitlab_host is None else gitlab_host
    pages = config.default_done_max_pages() if max_pages is None else max_pages
    day_iso = day.isoformat()

    response: dict[str, Any] = {
        "ok": True,
        "date": day_iso,
        "git_path": config.git_base_path(),
        "errors": [],
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures: dict[str, Any] = {}
        if "github" in resolved_hosts:
            futures["github"] = pool.submit(
                done_github.fetch_github_done,
                activity_date=day_iso,
                max_pages=pages,
            )
        if "gitlab" in resolved_hosts:
            futures["gitlab"] = pool.submit(
                done_gitlab.fetch_gitlab_done,
                hostname=gl_host,
                activity_date=day_iso,
                max_pages=pages,
            )
        for name, future in futures.items():
            result = future.result()
            host: dict[str, Any] = {
                "ok": result.error is None,
                "error": result.error,
            }
            host.update(result.to_dict())
            if result.error:
                response["errors"].append({"host": name, "message": result.error})
            response[name] = host

    if response["errors"] and not any(
        (response.get(host) or {}).get("count") for host in resolved_hosts
    ):
        response["ok"] = False
        response["error"] = "; ".join(item["message"] for item in response["errors"])

    return response
