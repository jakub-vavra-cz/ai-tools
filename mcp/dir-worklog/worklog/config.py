"""Environment defaults for worklog."""

from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def default_git_path() -> str:
    return os.environ.get("GIT_PATH", "~/git")


def default_max_repos() -> int:
    return _env_int("WORKLOG_MAX_REPOS", 8)


def default_max_files() -> int:
    return _env_int("WORKLOG_MAX_FILES", 10)


def default_max_commits() -> int:
    return _env_int("WORKLOG_MAX_COMMITS", 10)


def default_recent_repos() -> int:
    return _env_int("WORKLOG_RECENT_REPOS", 25)


def default_include_scratch() -> bool:
    return _env_bool("WORKLOG_INCLUDE_SCRATCH", False)
