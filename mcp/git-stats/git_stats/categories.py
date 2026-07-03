"""Category ids and human labels."""

from __future__ import annotations

ALL_CATEGORIES: tuple[str, ...] = (
    "review_requested",
    "authored_changes_requested",
    "authored_no_reviewer",
)

CATEGORY_LABELS: dict[str, str] = {
    "review_requested": "Reviews waiting on me",
    "authored_changes_requested": "My PRs — changes requested",
    "authored_no_reviewer": "My PRs — no reviewer set",
}

SUBCOMMAND_PRESETS: dict[str, list[str]] = {
    "reviews": ["review_requested"],
    "authored": ["authored_changes_requested", "authored_no_reviewer"],
    "authored/changes-requested": ["authored_changes_requested"],
    "authored/no-reviewer": ["authored_no_reviewer"],
}

VALID_HOSTS: frozenset[str] = frozenset({"github", "gitlab"})


def normalize_categories(values: list[str] | None) -> list[str]:
    if not values:
        return list(ALL_CATEGORIES)
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        key = raw.strip().lower().replace("-", "_")
        if key not in ALL_CATEGORIES:
            raise ValueError(f"invalid categories: {raw!r}")
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def normalize_hosts(values: list[str] | None) -> list[str]:
    if not values:
        return ["github", "gitlab"]
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        key = raw.strip().lower()
        if key not in VALID_HOSTS:
            raise ValueError(f"invalid hosts: {raw!r}")
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def normalize_dirs(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        key = raw.strip()
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out or None
