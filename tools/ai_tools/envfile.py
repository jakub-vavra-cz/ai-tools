"""Load ``~/git/ai-tools.env`` and require Scope A host/username vars.

Real values live in the internal ``jvavra-test-tools`` repo. Public clones use
``ai-tools.env.example`` as a template. See the ai-tools README for how to
install the file under ``~/git/``.
"""

from __future__ import annotations

import os
from pathlib import Path

# Single allowed internal URL in this public tree (install instructions).
AI_TOOLS_ENV_RAW_URL = (
    "https://gitlab.cee.redhat.com/jvavra/jvavra-test-tools/-/raw/master/ai-tools.env"
)
DEFAULT_AI_TOOLS_ENV_PATH = Path.home() / "git" / "ai-tools.env"
_LOADED_PATH: Path | None = None


def ai_tools_env_path() -> Path:
    raw = (os.environ.get("AI_TOOLS_ENV") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_AI_TOOLS_ENV_PATH


def load_ai_tools_env(*, override: bool = False) -> Path | None:
    """Parse KEY=VALUE lines into ``os.environ``. Skip comments/blank lines.

    Does not override non-empty existing env vars unless *override* is true.
    Returns the path loaded, or None if the file is missing.
    """
    global _LOADED_PATH
    path = ai_tools_env_path()
    if not path.is_file():
        return None
    if _LOADED_PATH == path and not override:
        return path
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[7:].strip()
        if "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if not override and (os.environ.get(key) or "").strip():
            continue
        os.environ[key] = value
    _LOADED_PATH = path
    return path


def require_env(name: str) -> str:
    """Return a required env var after loading ``ai-tools.env`` if present."""
    load_ai_tools_env()
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    path = ai_tools_env_path()
    raise RuntimeError(
        f"{name} is unset. Install {path} from {AI_TOOLS_ENV_RAW_URL} "
        f"(or copy ai-tools.env.example), then re-run. "
        f"Override path with AI_TOOLS_ENV=…"
    )


def env_or_none(name: str) -> str | None:
    """Load env file; return stripped value or None."""
    load_ai_tools_env()
    value = (os.environ.get(name) or "").strip()
    return value or None
