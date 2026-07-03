"""Print field id / key / name mapping from GET /rest/api/3/field."""

from __future__ import annotations

import json
import re
from typing import Any, Pattern, TextIO

from jira_cli.api import JiraApiError, JiraClient, print_jira_api_error


def _field_search_text(f: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in ("id", "name", "key"):
        v = f.get(k)
        if v is not None:
            parts.append(str(v))
    clauses = f.get("clauseNames")
    if isinstance(clauses, list):
        for c in clauses:
            if isinstance(c, str):
                parts.append(c)
    return "\n".join(parts)


def filter_field_definitions(
    fields: list[dict[str, Any]],
    *,
    custom_only: bool,
    search: str | None,
    search_regex: bool,
    err: TextIO,
) -> list[dict[str, Any]] | None:
    """
    Filter ``GET /rest/api/3/field`` results like ``fields`` / ``field-map``.

    Returns the filtered list, or ``None`` if the search regex is invalid (message printed to ``err``).
    """
    if custom_only:
        filtered = [f for f in fields if f.get("custom")]
    else:
        filtered = list(fields)

    needle = (search or "").strip()
    rx: Pattern[str] | None = None
    if needle:
        if search_regex:
            try:
                rx = re.compile(needle, re.IGNORECASE)
            except re.error as exc:
                print(f"Invalid regular expression: {exc}", file=err)
                return None

        def _matches(fld: dict[str, Any]) -> bool:
            text = _field_search_text(fld)
            if rx is not None:
                return rx.search(text) is not None
            return needle.casefold() in text.casefold()

        filtered = [f for f in filtered if _matches(f)]

    return filtered


def fetch_fields_filtered(
    client: JiraClient,
    *,
    custom_only: bool,
    search: str | None,
    search_regex: bool,
    err: TextIO,
) -> list[dict[str, Any]]:
    """Load fields from Jira and apply the same filters as ``fields`` / ``field-map``."""
    fields = client.get_fields()
    filtered = filter_field_definitions(
        fields,
        custom_only=custom_only,
        search=search,
        search_regex=search_regex,
        err=err,
    )
    if filtered is None:
        raise ValueError("Invalid field search regular expression.")
    return filtered


def run_field_map(
    client: JiraClient,
    *,
    custom_only: bool,
    as_json: bool,
    header: bool,
    id_name_only: bool = False,
    search: str | None,
    search_regex: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    try:
        filtered = fetch_fields_filtered(
            client,
            custom_only=custom_only,
            search=search,
            search_regex=search_regex,
            err=err,
        )
    except JiraApiError as e:
        print_jira_api_error(e, err)
        return 1
    except ValueError:
        return 2

    if as_json:
        if id_name_only:
            slim = [{"id": f.get("id"), "name": f.get("name")} for f in filtered]
            json.dump(slim, out, indent=2, ensure_ascii=False)
        else:
            json.dump(filtered, out, indent=2, ensure_ascii=False)
        out.write("\n")
        return 0

    if id_name_only:
        rows2: list[tuple[str, str]] = []
        for f in filtered:
            rows2.append((str(f.get("id") or ""), str(f.get("name") or "")))
        rows2.sort(key=lambda r: r[1].casefold())
        if header:
            print("id\tname", file=out)
        for fid, name in rows2:
            print(f"{fid}\t{name}", file=out)
        return 0

    rows: list[tuple[str, str, str]] = []
    for f in filtered:
        rows.append(
            (
                str(f.get("id") or ""),
                str(f.get("name") or ""),
                str(f.get("key") or ""),
            ),
        )
    rows.sort(key=lambda r: r[1].casefold())

    if header:
        print("id\tname\tkey", file=out)
    for fid, name, key in rows:
        print(f"{fid}\t{name}\t{key}", file=out)
    return 0
