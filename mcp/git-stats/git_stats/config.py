"""Environment defaults and workspace clone discovery."""

from __future__ import annotations

import os
from pathlib import Path

from git_stats.cli_util import run_cmd

CloneInfo = tuple[str, str, Path]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value != "" else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def default_github_limit() -> int:
    return _env_int("GIT_STATS_GITHUB_LIMIT", 20)


def default_gitlab_limit() -> int:
    return _env_int("GIT_STATS_GITLAB_LIMIT", 30)


def default_gitlab_host() -> str:
    return _env("GIT_STATS_GITLAB_HOST", "gitlab.cee.redhat.com")


def default_include_drafts() -> bool:
    return _env_bool("GIT_STATS_INCLUDE_DRAFTS", False)


def default_include_all() -> bool:
    return _env_bool("GIT_STATS_INCLUDE_ALL", False)


def default_done_max_pages() -> int:
    return _env_int("GIT_STATS_DONE_MAX_PAGES", 10)


def default_categories_csv() -> str | None:
    raw = os.environ.get("GIT_STATS_CATEGORIES")
    return raw if raw else None


def git_base_path() -> str:
    return os.path.expanduser(_env("GIT_PATH", os.path.join("~", "git")))


def remote_host_for_clone(clone: Path, *, gitlab_host: str | None = None) -> str:
    gl_host = (gitlab_host or default_gitlab_host()).lower()
    for remote in ("origin", "upstream"):
        result = run_cmd(["git", "-C", str(clone), "remote", "get-url", remote])
        if not result.ok:
            continue
        url = result.stdout.strip().lower()
        if gl_host in url:
            return "gitlab"
        if "github.com" in url:
            return "github"
    return "unknown"


def iter_workspace_clones(
    *,
    dirs: list[str] | None = None,
    gitlab_host: str | None = None,
) -> list[CloneInfo]:
    base = Path(git_base_path())
    if not base.is_dir():
        return []

    allowed = set(dirs) if dirs else None
    out: list[CloneInfo] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if allowed is not None and entry.name not in allowed:
            continue
        if not (entry / ".git").exists():
            continue
        host = remote_host_for_clone(entry, gitlab_host=gitlab_host)
        if host in {"github", "gitlab"}:
            out.append((entry.name, host, entry))
    return out


def github_token() -> str | None:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    return None
