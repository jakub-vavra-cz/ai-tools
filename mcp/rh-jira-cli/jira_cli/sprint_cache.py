"""Local file cache for Agile sprint lists (used by `sprints` and `edit --sprint`)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional


def _state_tag(state: str) -> str:
    if not state:
        return "none"
    s = re.sub(r"[^a-zA-Z0-9-]+", "_", state).strip("_")
    return s if s else "none"


def sprint_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".cache"
    d = root / "jira-cli" / "sprints"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_enabled() -> bool:
    v = os.environ.get("JIRA_SPRINT_CACHE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _path_merged(project_key: str, state: str) -> Path:
    return sprint_cache_dir() / f"merged_{project_key.upper()}_{_state_tag(state)}.json"


def _path_by_board(project_key: str, state: str, board_scope: str) -> Path:
    safe_scope = re.sub(r"[^a-zA-Z0-9-]+", "_", str(board_scope)).strip("_") or "all"
    return (
        sprint_cache_dir() / f"boards_{project_key.upper()}_{_state_tag(state)}_{safe_scope}.json"
    )


def _path_all_projects_merged(state: str) -> Path:
    """Full-site Scrum sprint list (from a prior global scan or derived from per-project caches)."""
    return sprint_cache_dir() / f"all_projects_merged_{_state_tag(state)}.json"


def _read_cache_entry(path: Path) -> Optional[dict[str, Any]]:
    """Read a cache file if present and valid JSON. No TTL: stale data is used until miss or --refresh-sprint-cache."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_merged_sprints(project_key: str, state: str) -> Optional[list[dict[str, Any]]]:
    """
    Return cached merged sprint list for all_sprints_for_project, or None on miss.

    Tries a merged entry first, then derives from a by_board cache (scope all).
    """
    if not is_enabled():
        return None

    data = _read_cache_entry(_path_merged(project_key, state))
    if data and data.get("version") == 1 and data.get("kind") == "merged":
        sprints = data.get("sprints")
        if isinstance(sprints, list):
            return sprints

    data2 = _read_cache_entry(_path_by_board(project_key, state, "all"))
    if data2 and data2.get("version") == 1 and data2.get("kind") == "by_board":
        boards = data2.get("boards")
        if not isinstance(boards, list):
            return None
        by_id: dict[int, dict[str, Any]] = {}
        for b in boards:
            for s in b.get("sprints") or []:
                if not isinstance(s, dict):
                    continue
                try:
                    sid = int(s["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if sid not in by_id:
                    by_id[sid] = s
        return list(by_id.values())

    return None


def save_merged_sprints(
    project_key: str,
    state: str,
    sprints: list[dict[str, Any]],
    boards_payload: list[dict[str, Any]] | None = None,
) -> None:
    """Persist merged list; optionally also persist by_board (same fetch)."""
    if not is_enabled():
        return
    now = time.time()
    payload: dict[str, Any] = {
        "version": 1,
        "kind": "merged",
        "fetched_at": now,
        "project_key": project_key.upper(),
        "state": state,
        "sprints": sprints,
    }
    _atomic_write_json(_path_merged(project_key, state), payload)
    if boards_payload is not None:
        save_by_board_sprints(project_key, state, "all", boards_payload, fetched_at=now)


def save_by_board_sprints(
    project_key: str,
    state: str,
    board_scope: str,
    boards: list[dict[str, Any]],
    *,
    fetched_at: float | None = None,
) -> None:
    if not is_enabled():
        return
    now = fetched_at if fetched_at is not None else time.time()
    payload: dict[str, Any] = {
        "version": 1,
        "kind": "by_board",
        "fetched_at": now,
        "project_key": project_key.upper(),
        "state": state,
        "board_scope": board_scope,
        "boards": boards,
    }
    _atomic_write_json(_path_by_board(project_key, state, board_scope), payload)


def load_all_projects_sprints_union(state: str) -> Optional[list[dict[str, Any]]]:
    """
    Sprints for cross-project name resolution: prefer ``all_projects_merged_*``, else merge
    every ``merged_{PROJ}_{state}`` cache file (deduped by sprint id).

    Returns ``None`` if caching is disabled or no usable cache files exist; may return a
    non-empty list that still does not contain a given sprint name (caller may refetch).
    """
    if not is_enabled():
        return None
    tag = _state_tag(state)
    data = _read_cache_entry(_path_all_projects_merged(state))
    if data and data.get("version") == 1 and data.get("kind") == "all_projects_merged":
        sprints = data.get("sprints")
        if isinstance(sprints, list) and sprints:
            return sprints

    root = sprint_cache_dir()
    by_id: dict[int, dict[str, Any]] = {}
    pattern = f"merged_*_{tag}.json"
    for path in sorted(root.glob(pattern)):
        data2 = _read_cache_entry(path)
        if not data2 or data2.get("version") != 1 or data2.get("kind") != "merged":
            continue
        for s in data2.get("sprints") or []:
            if not isinstance(s, dict):
                continue
            try:
                sid = int(s["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if sid not in by_id:
                by_id[sid] = s
    if not by_id:
        return None
    return list(by_id.values())


def save_all_projects_merged(
    state: str,
    sprints: list[dict[str, Any]],
    boards_payload: list[dict[str, Any]] | None = None,
) -> None:
    """Persist global Scrum sprint list after a live scan (``list`` / ``list-mine`` name resolution)."""
    if not is_enabled():
        return
    now = time.time()
    payload: dict[str, Any] = {
        "version": 1,
        "kind": "all_projects_merged",
        "fetched_at": now,
        "state": state,
        "sprints": sprints,
    }
    if boards_payload is not None:
        payload["boards"] = boards_payload
    _atomic_write_json(_path_all_projects_merged(state), payload)


def load_by_board_sprints(
    project_key: str,
    state: str,
    board_scope: str,
) -> Optional[list[dict[str, Any]]]:
    """Return cached boards payload (list of {id, name, sprints}) or None on miss."""
    if not is_enabled():
        return None
    data = _read_cache_entry(_path_by_board(project_key, state, board_scope))
    if data and data.get("version") == 1 and data.get("kind") == "by_board":
        boards = data.get("boards")
        if isinstance(boards, list):
            return boards
    return None
