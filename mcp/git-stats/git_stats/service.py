"""queue_fetch orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from git_stats import config
from git_stats.categories import normalize_categories, normalize_dirs, normalize_hosts
from git_stats import github, gitlab


def queue_fetch(
    *,
    categories: list[str] | None = None,
    hosts: list[str] | None = None,
    github_limit: int | None = None,
    gitlab_limit: int | None = None,
    include_drafts: bool | None = None,
    gitlab_host: str | None = None,
    dirs: list[str] | None = None,
    include_all: bool = False,
) -> dict[str, Any]:
    try:
        resolved_categories = normalize_categories(categories)
        resolved_hosts = normalize_hosts(hosts)
        dir_filter = normalize_dirs(dirs)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    gh_limit = config.default_github_limit() if github_limit is None else github_limit
    gl_limit = config.default_gitlab_limit() if gitlab_limit is None else gitlab_limit
    drafts = config.default_include_drafts() if include_drafts is None else include_drafts
    gl_host = config.default_gitlab_host() if gitlab_host is None else gitlab_host

    clones = config.iter_workspace_clones(dirs=dir_filter, gitlab_host=gl_host)

    response: dict[str, Any] = {
        "ok": True,
        "git_path": config.git_base_path(),
        "categories": resolved_categories,
        "include_all": include_all,
        "errors": [],
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures: dict[str, Any] = {}
        if "github" in resolved_hosts:
            futures["github"] = pool.submit(
                github.fetch_github,
                resolved_categories,
                github_limit=gh_limit,
                clones=clones,
                include_all=include_all,
            )
        if "gitlab" in resolved_hosts:
            futures["gitlab"] = pool.submit(
                gitlab.fetch_gitlab,
                resolved_categories,
                gitlab_limit=gl_limit,
                gitlab_host=gl_host,
                include_drafts=drafts,
                clones=clones,
                include_all=include_all,
            )
        for name, future in futures.items():
            response[name] = future.result()

    return response


def review_queue(**kwargs: Any) -> dict[str, Any]:
    categories = kwargs.pop("categories", None)
    if categories is None:
        categories = ["review_requested"]
    return queue_fetch(categories=categories, **kwargs)
