"""Repository definitions loaded from repos.ini (extendable)."""

from __future__ import annotations

import os
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


@dataclass(frozen=True)
class RepoConfig:
    """One forked repo: upstream read-only remote, fork as origin clone URL."""

    upstream: str
    fork_template: str  # format with {gitlab_cee_user} and/or {github_user}
    default_branch: str
    default_loc: str
    prefix: str


_REQUIRED_KEYS = (
    "upstream",
    "fork_template",
    "default_branch",
    "default_loc",
    "prefix",
)


def default_repos_ini_path() -> Path:
    """Shipped repos.ini next to this module, unless GIT_WORKTREES_REPOS_INI is set."""
    override = os.environ.get("GIT_WORKTREES_REPOS_INI")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().with_name("repos.ini")


def load_repo_registry(path: Path | None = None) -> dict[str, RepoConfig]:
    """
    Load repository definitions from an INI file.

    Each ``[SECTION]`` name becomes the repo code (normalized to uppercase).
    """
    ini_path = path if path is not None else default_repos_ini_path()
    if not ini_path.is_file():
        raise FileNotFoundError(
            f"Repository config not found: {ini_path}. "
            "Set GIT_WORKTREES_REPOS_INI or add repos.ini beside the package."
        )

    parser = ConfigParser(interpolation=None)
    parser.read(ini_path, encoding="utf-8")

    out: dict[str, RepoConfig] = {}
    for section in parser.sections():
        key = section.strip().upper()
        if not key:
            continue
        missing = [k for k in _REQUIRED_KEYS if not parser.get(section, k, fallback="").strip()]
        if missing:
            raise ValueError(
                f"{ini_path}: section [{section}] missing or empty keys: {', '.join(missing)}"
            )
        out[key] = RepoConfig(
            upstream=parser.get(section, "upstream").strip(),
            fork_template=parser.get(section, "fork_template").strip(),
            default_branch=parser.get(section, "default_branch").strip(),
            default_loc=parser.get(section, "default_loc").strip(),
            prefix=parser.get(section, "prefix").strip(),
        )
    if not out:
        raise ValueError(f"{ini_path}: no repository sections found")
    return out


def repo_registry() -> dict[str, RepoConfig]:
    """Keys are uppercase repo codes (same as branch_w.sh $1)."""
    return load_repo_registry()


def resolve_fork_url(cfg: RepoConfig) -> str:
    gl = _env("GITLAB_CEE_USER", "jvavra")
    gh = _env("GITHUB_USER", "jakub-vavra-cz")
    return cfg.fork_template.format(gitlab_cee_user=gl, github_user=gh)


def git_base_path() -> str:
    """Parent directory for main clones and worktrees (default ~/git)."""
    return os.path.expanduser(_env("GIT_PATH", os.path.join("~", "git")))
