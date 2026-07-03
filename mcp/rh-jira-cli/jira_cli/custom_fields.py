"""Helpers for Jira field metadata (GET /rest/api/3/field)."""

from __future__ import annotations

from typing import Any


def find_custom_field_id_by_exact_display_name(
    fields: list[dict[str, Any]],
    display_name: str,
) -> str | None:
    """First custom field whose trimmed ``name`` equals ``display_name`` (trimmed)."""
    want = display_name.strip()
    for f in fields:
        if not f.get("custom"):
            continue
        if (f.get("name") or "").strip() != want:
            continue
        fid = f.get("id")
        if isinstance(fid, str) and fid.strip():
            return fid.strip()
    return None
