"""Filesystem and git scanning."""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__"}


def _is_log_file(path: Path) -> bool:
    return path.suffix.lower() == ".log"


def _should_skip_file(path: Path) -> bool:
    if _is_log_file(path):
        return True
    name = path.name
    if name == "pytest-run.rc":
        return True
    return fnmatch.fnmatch(name, "*junit.xml")


@dataclass
class RepoEntry:
    workspace_root: Path
    path: Path
    dir_mtime: datetime

    @property
    def name(self) -> str:
        return self.path.name


def list_top_level_dirs(workspace: Path, *, include_scratch_dirs: bool) -> list[Path]:
    dirs: list[Path] = []
    try:
        entries = list(workspace.iterdir())
    except OSError:
        return dirs
    for entry in entries:
        if not entry.is_dir():
            continue
        if not include_scratch_dirs and entry.name.startswith("@"):
            continue
        dirs.append(entry)
    return dirs


def dir_mtime(path: Path, tzinfo) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=tzinfo)


def mtime_in_window(mtime: datetime, since: datetime, until: datetime) -> bool:
    return since <= mtime < until


def discover_active_repos(
    workspace: Path,
    *,
    workspace_root: Path,
    since: datetime,
    until: datetime,
    include_scratch_dirs: bool,
) -> list[RepoEntry]:
    active: list[RepoEntry] = []
    for entry in list_top_level_dirs(workspace, include_scratch_dirs=include_scratch_dirs):
        mtime = dir_mtime(entry, since.tzinfo)
        if mtime_in_window(mtime, since, until):
            active.append(RepoEntry(workspace_root=workspace_root, path=entry, dir_mtime=mtime))
    return active


def list_recent_repos(
    workspace: Path,
    *,
    workspace_root: Path,
    since: datetime,
    limit: int,
    include_scratch_dirs: bool,
) -> list[dict]:
    dirs = list_top_level_dirs(workspace, include_scratch_dirs=include_scratch_dirs)
    dirs.sort(key=lambda p: p.stat().st_mtime)
    recent = dirs[-limit:] if limit else []
    return [
        {
            "workspace_root": str(workspace_root),
            "name": entry.name,
            "path": str(entry),
            "dir_mtime": _format_dt(dir_mtime(entry, since.tzinfo)),
        }
        for entry in recent
    ]


def scan_files(
    repo: Path,
    *,
    since: datetime,
    until: datetime,
    max_files: int,
) -> tuple[list[dict], int]:
    matches: list[tuple[float, Path]] = []
    tzinfo = since.tzinfo

    for dirpath, dirnames, filenames in _walk(repo):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for name in filenames:
            path = dirpath / name
            if _should_skip_file(path):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            mtime = datetime.fromtimestamp(st.st_mtime, tz=tzinfo)
            if mtime_in_window(mtime, since, until):
                matches.append((st.st_mtime, path))

    if is_git_repo(repo):
        matches = _drop_gitignored(repo, matches)

    matches.sort(key=lambda item: item[0], reverse=True)
    total = len(matches)
    head = matches[:max_files]
    files = [
        {
            "path": str(path.relative_to(repo)),
            "mtime": _format_dt(datetime.fromtimestamp(ts, tz=tzinfo)),
        }
        for ts, path in head
    ]
    return files, total


def _drop_gitignored(repo: Path, matches: list[tuple[float, Path]]) -> list[tuple[float, Path]]:
    if not matches:
        return matches
    rel_paths = [path.relative_to(repo).as_posix() for _, path in matches]
    ignored = _git_ignored_relative_paths(repo, rel_paths)
    if not ignored:
        return matches
    return [(ts, path) for ts, path in matches if path.relative_to(repo).as_posix() not in ignored]


def _git_ignored_relative_paths(repo: Path, rel_paths: list[str]) -> set[str]:
    payload = ("\0".join(rel_paths) + "\0").encode()
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-z", "--stdin"],
            input=payload,
            capture_output=True,
            check=False,
        )
    except OSError:
        return set()
    if not proc.stdout:
        return set()
    return {part for part in proc.stdout.decode().split("\0") if part}


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        parts = Path(dirpath).parts
        if any(part in _SKIP_DIR_NAMES for part in parts):
            dirnames.clear()
            continue
        yield Path(dirpath), dirnames, filenames


def is_git_repo(repo: Path) -> bool:
    return (repo / ".git").exists()


def scan_commits(
    repo: Path,
    *,
    since: datetime,
    until: datetime,
    max_commits: int,
) -> tuple[list[dict], int]:
    if max_commits <= 0 or not is_git_repo(repo):
        return [], 0

    author = _git_config_email(repo) or "@"
    since_s = since.isoformat()
    until_s = until.isoformat()
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        f"--since={since_s}",
        f"--until={until_s}",
        f"--author={author}",
        "--format=%h%x09%s%x09%ae",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return [], 0
    if proc.returncode != 0:
        return [], 0

    commits: list[dict] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        commits.append(
            {
                "hash": parts[0],
                "subject": parts[1],
                "author_email": parts[2],
            }
        )

    total = len(commits)
    return commits[:max_commits], total


def _git_config_email(repo: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "config", "user.email"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _format_dt(dt: datetime) -> str:
    return dt.isoformat()
