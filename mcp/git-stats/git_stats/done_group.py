"""Group done activity items by pull request / merge request."""

from __future__ import annotations

from git_stats.models import DoneItem

_PR_MR_KINDS = frozenset({"pull_request", "review", "merge_request", "comment"})
_KIND_PRIORITY = {"pull_request": 0, "merge_request": 0, "review": 1, "comment": 2}


def _is_pr_mr_item(item: DoneItem) -> bool:
    if item.kind not in _PR_MR_KINDS:
        return False
    if "!" in item.ref:
        return True
    return "#" in item.ref


def _unique_actions(items: list[DoneItem]) -> list[str]:
    seen: set[str] = set()
    actions: list[str] = []
    for item in sorted(items, key=lambda row: row.created_at):
        if item.action in seen:
            continue
        seen.add(item.action)
        actions.append(item.action)
    return actions


def _pick_title(items: list[DoneItem]) -> str:
    for kind in ("pull_request", "merge_request"):
        for item in items:
            if item.kind != kind:
                continue
            title = item.title.strip()
            if title and not title.startswith("Review on "):
                return title
    for item in items:
        title = item.title.strip()
        if title and not title.startswith("Review on "):
            return title
    return items[0].title


def _pick_url(items: list[DoneItem]) -> str:
    for kind in ("pull_request", "merge_request"):
        for item in items:
            if item.kind == kind:
                return item.url
    for item in items:
        if "#pullrequestreview-" not in item.url and "#note_" not in item.url:
            return item.url
    return items[0].url


def _pick_kind(items: list[DoneItem]) -> str:
    return min(items, key=lambda item: (_KIND_PRIORITY.get(item.kind, 99), item.created_at)).kind


def _merge_group(ref: str, items: list[DoneItem]) -> DoneItem:
    ordered = sorted(items, key=lambda row: row.created_at, reverse=True)
    actions = _unique_actions(items)
    details = [item.detail for item in ordered if item.detail]
    return DoneItem(
        action=", ".join(actions),
        ref=ref,
        title=_pick_title(items),
        url=_pick_url(items),
        created_at=ordered[0].created_at,
        kind=_pick_kind(items),
        detail="; ".join(dict.fromkeys(details)) if details else None,
        events=ordered,
    )


def group_done_items(items: list[DoneItem]) -> list[DoneItem]:
    """Merge multiple events on the same PR/MR into one item."""
    grouped: dict[str, list[DoneItem]] = {}
    standalone: list[DoneItem] = []
    group_order: list[str] = []

    for item in items:
        if not _is_pr_mr_item(item):
            standalone.append(item)
            continue
        if item.ref not in grouped:
            grouped[item.ref] = []
            group_order.append(item.ref)
        grouped[item.ref].append(item)

    merged = [_merge_group(ref, grouped[ref]) for ref in group_order]
    result = merged + standalone
    result.sort(key=lambda row: row.created_at, reverse=True)
    return result
