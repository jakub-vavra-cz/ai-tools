"""Print a single issue with all fields from the REST API."""

from __future__ import annotations

import json
import re
from typing import Any, TextIO

from jira_cli.api import JiraApiError, JiraClient, print_jira_api_error
from jira_cli.jql import jql_quote


def _merge_expand_with_names(expand: str | None) -> str | None:
    """Ensure `names` is in expand so the API returns id → display name for each field."""
    parts: list[str] = []
    for raw in (expand or "").split(","):
        s = raw.strip()
        if s:
            parts.append(s)
    if "names" not in parts:
        parts.insert(0, "names")
    return ",".join(parts) if parts else None


def _inject_names_from_field_list(client: JiraClient, data: dict[str, Any]) -> None:
    """Fallback if the server omits `names` (merge expand not supported)."""
    try:
        field_list = client.get_fields()
    except JiraApiError:
        return
    by_id = {str(f["id"]): f.get("name") for f in field_list if f.get("id")}
    flds = data.get("fields") or {}
    data["names"] = {fid: by_id.get(fid) or fid for fid in flds}


def _rewrite_custom_field_keys(data: dict[str, Any]) -> None:
    """
    Replace fields.customfield_* keys with display names.

    If a display name collides with an existing key, keep it unique by appending
    the original id, for example: "Story Points (customfield_10016)".
    """
    fields = data.get("fields")
    names = data.get("names")
    if not isinstance(fields, dict) or not isinstance(names, dict):
        return

    rewritten: dict[str, Any] = {}
    for key, value in fields.items():
        new_key = key
        if key.startswith("customfield_"):
            display = names.get(key)
            if isinstance(display, str) and display.strip():
                candidate = display.strip()
                if candidate in rewritten or candidate in fields:
                    candidate = f"{candidate} ({key})"
                new_key = candidate
        rewritten[new_key] = value
    data["fields"] = rewritten


def _brief_rename_fields_with_names(data: dict[str, Any]) -> None:
    """
    Rename ``fields`` keys using the issue ``names`` map (field id → display name), then drop ``names``.

    Used for ``--brief`` so output has display names only and no redundant ``names`` object.
    """
    names = data.get("names")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        data.pop("names", None)
        return
    if not isinstance(names, dict) or not names:
        data.pop("names", None)
        return

    rewritten: dict[str, Any] = {}
    for key, value in fields.items():
        new_key = key
        if key in names:
            nm = names[key]
            if isinstance(nm, str) and nm.strip():
                candidate = nm.strip()
                if candidate in rewritten or (candidate in fields and candidate != key):
                    candidate = f"{candidate} ({key})"
                new_key = candidate
        rewritten[new_key] = value
    data["fields"] = rewritten
    data.pop("names", None)


def _is_omitted_value(value: Any) -> bool:
    if value is None:
        return True
    if value == {} or value == []:
        return True
    if isinstance(value, str):
        s = value.strip()
        return s == "" or s == "{}"
    return False


def _strip_empty_json(value: Any) -> Any:
    """
    Deep copy of JSON-like data with null, ``{}``, ``[]``, ``""``, and ``"{}"`` strings removed
    at every level (keys dropped when the value becomes empty).
    """
    if _is_omitted_value(value):
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            sv = _strip_empty_json(v)
            if _is_omitted_value(sv):
                continue
            out[k] = sv
        return out
    if isinstance(value, list):
        out_list: list[Any] = []
        for item in value:
            sv = _strip_empty_json(item)
            if _is_omitted_value(sv):
                continue
            out_list.append(sv)
        return out_list
    return value


def _scalar_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _adf_flatten_inline(node: Any) -> str:
    """Extract text and hard breaks from an ADF subtree."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        nt = node.get("type")
        if nt == "text":
            t = node.get("text")
            return t if isinstance(t, str) else ""
        if nt == "hardBreak":
            return "\n"
        if nt in ("mention", "emoji", "date", "status"):
            return ""
        parts: list[str] = []
        for c in node.get("content") or []:
            parts.append(_adf_flatten_inline(c))
        return "".join(parts)
    if isinstance(node, list):
        return "".join(_adf_flatten_inline(x) for x in node)
    return ""


def _adf_block_to_plain_top(block: dict[str, Any]) -> str:
    """One ADF top-level block to plain text (lists / quotes recurse)."""
    t = block.get("type")
    if t in ("paragraph", "heading"):
        return _adf_flatten_inline(block)
    if t in ("bulletList", "orderedList"):
        lines: list[str] = []
        for item in block.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "listItem":
                lines.append(_adf_flatten_inline(item))
        return "\n".join(lines)
    if t == "blockquote":
        inner = block.get("content") or []
        return "\n".join(_adf_block_to_plain_top(x) for x in inner if isinstance(x, dict))
    if t in ("rule", "mediaGroup", "mediaSingle", "extension"):
        return ""
    if t in ("codeBlock", "panel", "table"):
        return _adf_flatten_inline(block)
    return _adf_flatten_inline(block)


def _adf_doc_to_plain(doc: dict[str, Any]) -> str:
    """ADF document body to plain multiline text (top-level blocks separated by blank line)."""
    blocks = doc.get("content")
    if not isinstance(blocks, list):
        return ""
    lines_out: list[str] = []
    for b in blocks:
        if isinstance(b, dict):
            lines_out.append(_adf_block_to_plain_top(b))
    return "\n\n".join(lines_out)


def _fields_description_to_plain_text(raw: Any) -> str | None:
    """
    ``fields.description`` as plain text: legacy string or REST v3 ADF
    (``type: doc``, or ``body`` with doc, or bare ``content`` list).
    """
    if raw is None or _is_omitted_value(raw):
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s if s else None
    if not isinstance(raw, dict):
        return None
    if raw.get("type") == "doc":
        text = _adf_doc_to_plain(raw)
        s = text.strip()
        return s if s else None
    body = raw.get("body")
    if isinstance(body, dict) and body.get("type") == "doc":
        text = _adf_doc_to_plain(body)
        s = text.strip()
        return s if s else None
    if isinstance(raw.get("content"), list):
        wrapped = {"type": "doc", "version": raw.get("version", 1), "content": raw["content"]}
        text = _adf_doc_to_plain(wrapped)
        s = text.strip()
        return s if s else None
    return None


def _comment_body_to_flat_plain(body: Any) -> str:
    """Comment ``body`` (ADF or string) as a single flattened line (whitespace normalized)."""
    if body is None or _is_omitted_value(body):
        return ""
    if isinstance(body, str):
        return " ".join(body.split())
    text = _fields_description_to_plain_text(body)
    if not text:
        return ""
    return " ".join(text.split())


def _brief_parent_merged(parent: dict[str, Any]) -> str | None:
    """Format ``[issue-key] summary`` from parent issue object."""
    key = parent.get("key")
    k = key.strip() if isinstance(key, str) else ""
    summary: str | None = None
    nested = parent.get("fields")
    if isinstance(nested, dict):
        sm = nested.get("summary")
        if isinstance(sm, str) and sm.strip():
            summary = sm.strip()
    if summary is None:
        sm = parent.get("summary")
        if isinstance(sm, str) and sm.strip():
            summary = sm.strip()
    if k and summary:
        return f"[{k}] {summary}"
    if k:
        return f"[{k}]"
    if summary:
        return summary
    return None


def _brief_issue_merged(issue: dict[str, Any]) -> str | None:
    """Format ``[issue-key] summary`` from issue JSON (``key`` + ``fields.summary``)."""
    raw_key = issue.get("key")
    k = raw_key.strip() if isinstance(raw_key, str) else ""
    summary: str | None = None
    fields = issue.get("fields")
    if isinstance(fields, dict):
        sm = fields.get("summary")
        if isinstance(sm, str) and sm.strip():
            summary = sm.strip()
    if k and summary:
        return f"[{k}] {summary}"
    if k:
        return f"[{k}]"
    if summary:
        return summary
    return None


def _short_parent_line(issue: dict[str, Any]) -> str | None:
    """``Parent: [key] summary`` when ``fields.parent`` is present (sub-task / child issues)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    parent = fields.get("parent")
    if not isinstance(parent, dict) or _is_omitted_value(parent):
        return None
    merged = _brief_parent_merged(parent)
    if merged is None or _is_omitted_value(merged):
        return None
    return f"Parent: {merged}"


def _short_epic_link_field_raw(fields: dict[str, Any]) -> Any:
    """Epic Link custom field value (after display-name rewrite)."""
    for exact in ("Epic Link", "Epic link"):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.replace(" ", "").casefold() == "epiclink":
            return v
    return None


def _epic_link_key_and_summary_from_raw(raw: Any) -> tuple[str | None, str | None]:
    """Issue key and optional summary from Epic Link field (string key or nested issue)."""
    if raw is None or _is_omitted_value(raw):
        return None, None
    if isinstance(raw, str):
        k = raw.strip()
        return (k if k else None, None)
    if isinstance(raw, dict):
        k_raw = raw.get("key") or raw.get("issueKey")
        k = k_raw.strip() if isinstance(k_raw, str) else None
        summary: str | None = None
        nested = raw.get("fields")
        if isinstance(nested, dict):
            sm = nested.get("summary")
            if isinstance(sm, str) and sm.strip():
                summary = sm.strip()
        if summary is None:
            sm = raw.get("summary")
            if isinstance(sm, str) and sm.strip():
                summary = sm.strip()
        return (k, summary)
    return None, None


def _short_epic_link_line(client: JiraClient, issue: dict[str, Any]) -> str | None:
    """``Epic: [key] summary`` from Epic Link; fetches epic issue for summary when only key is stored."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_epic_link_field_raw(fields)
    if raw is None:
        return None
    key, summary = _epic_link_key_and_summary_from_raw(raw)
    if not key:
        return None
    if summary is None:
        try:
            epic_data = client.get_issue(key, fields=["summary"])
        except JiraApiError:
            return f"Epic: [{key}]"
        flds = epic_data.get("fields") or {}
        sm = flds.get("summary")
        if isinstance(sm, str) and sm.strip():
            summary = sm.strip()
    if summary:
        return f"Epic: [{key}] {summary}"
    return f"Epic: [{key}]"


def _is_epic_issue_type(issue: dict[str, Any]) -> bool:
    """True when ``fields.issuetype.name`` is Epic (case-insensitive)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return False
    it = fields.get("issuetype")
    if not isinstance(it, dict):
        return False
    name = it.get("name")
    return isinstance(name, str) and name.strip().casefold() == "epic"


def _fetch_issues_for_epic_children(client: JiraClient, epic_key: str) -> list[dict[str, Any]]:
    """
    Issues under this epic: company-managed via ``Epic Link``, else team-managed ``parent``.
    Uses the first JQL that returns at least one issue; if both error or return empty, [].
    """
    qk = jql_quote(epic_key.strip())
    jqls = (
        f'"Epic Link" = {qk} ORDER BY key ASC',
        f"parent = {qk} ORDER BY key ASC",
    )
    for jql in jqls:
        try:
            data = client.search(jql, fields=["summary", "key", "status"], max_results=200)
        except JiraApiError:
            continue
        issues = data.get("issues") if isinstance(data, dict) else None
        if isinstance(issues, list) and issues:
            return issues
    return []


def _short_epic_children_lines(client: JiraClient, issue: dict[str, Any]) -> list[str] | None:
    """``Children:`` plus one ``[key] summary (Status)`` line per child when issuetype is Epic."""
    if not _is_epic_issue_type(issue):
        return None
    raw_key = issue.get("key")
    if not isinstance(raw_key, str) or not raw_key.strip():
        return None
    children = _fetch_issues_for_epic_children(client, raw_key.strip())
    if not children:
        return None
    body: list[str] = []
    for ch in children:
        k = ch.get("key")
        if not isinstance(k, str) or not k.strip():
            continue
        ks = k.strip()
        flds = ch.get("fields")
        sm: str | None = None
        st_name: str | None = None
        if isinstance(flds, dict):
            s = flds.get("summary")
            if isinstance(s, str) and s.strip():
                sm = s.strip()
            st = flds.get("status")
            if isinstance(st, dict):
                nm = st.get("name")
                if isinstance(nm, str) and nm.strip():
                    st_name = nm.strip()
        if sm and st_name:
            body.append(f"[{ks}] {sm} ({st_name})")
        elif sm:
            body.append(f"[{ks}] {sm}")
        elif st_name:
            body.append(f"[{ks}] ({st_name})")
        else:
            body.append(f"[{ks}]")
    if not body:
        return None
    return ["Children:"] + body


def _short_status_line(issue: dict[str, Any]) -> str | None:
    """``Status: <name>`` from ``fields.status.name``."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    status = fields.get("status")
    if not isinstance(status, dict):
        return None
    nm = status.get("name")
    if isinstance(nm, str) and nm.strip():
        return f"Status: {nm.strip()}"
    return None


def _short_priority_line(issue: dict[str, Any]) -> str | None:
    """``Priority: <name>`` from ``fields.priority.name``."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    priority = fields.get("priority")
    if not isinstance(priority, dict):
        return None
    nm = priority.get("name")
    if isinstance(nm, str) and nm.strip():
        return f"Priority: {nm.strip()}"
    return None


def _short_duedate_line(issue: dict[str, Any]) -> str | None:
    """``Due date: <value>`` from ``fields.duedate`` (Jira date string)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = fields.get("duedate")
    if raw is None or _is_omitted_value(raw):
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        return f"Due date: {s}"
    return f"Due date: {raw}"


def _short_issuetype_line(issue: dict[str, Any]) -> str | None:
    """``Type: <name>`` from ``fields.issuetype.name``."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    issuetype = fields.get("issuetype")
    if not isinstance(issuetype, dict):
        return None
    nm = issuetype.get("name")
    if isinstance(nm, str) and nm.strip():
        return f"Type: {nm.strip()}"
    return None


def _short_sprint_line(issue: dict[str, Any]) -> str | None:
    """``Sprint: <names>`` from ``fields.Sprint`` (``name`` on each sprint object)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    sprint = fields.get("Sprint")
    if sprint is None:
        return None
    names: list[str] = []
    if isinstance(sprint, list):
        for item in sprint:
            if isinstance(item, dict):
                nm = item.get("name")
                if isinstance(nm, str) and nm.strip():
                    names.append(nm.strip())
    elif isinstance(sprint, dict):
        nm = sprint.get("name")
        if isinstance(nm, str) and nm.strip():
            names.append(nm.strip())
    if not names:
        return None
    return f"Sprint: {', '.join(names)}"


def _short_story_points_field_raw(fields: dict[str, Any], field_id: str | None) -> Any:
    """Value for the Story Points custom field (after display-name key rewrite, or by env id)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    for exact in ("Story Points",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "story points":
            return v
    return None


def _short_story_points_line(
    issue: dict[str, Any],
    *,
    story_points_field_id: str | None = None,
) -> str | None:
    """``Story points: …`` from the Story Points custom field (numeric or option payload)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_story_points_field_raw(fields, story_points_field_id)
    if raw is None:
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"Story points: {text}"


def _short_severity_field_raw(fields: dict[str, Any]) -> Any:
    """Value under ``fields`` for the custom field labeled Severity (after ``custom_id`` rewrite)."""
    if "Severity" in fields:
        return fields["Severity"]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "severity":
            return v
    return None


def _short_custom_field_display_value(value: Any) -> str | None:
    """Readable text for select / user / simple custom field payloads."""
    if value is None or _is_omitted_value(value):
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "title"):
            if key not in value:
                continue
            inner = value[key]
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
            if isinstance(inner, dict):
                n = inner.get("name") or inner.get("displayName")
                if isinstance(n, str) and n.strip():
                    return n.strip()
        href = value.get("href")
        if isinstance(href, str) and href.strip():
            return href.strip()
        return None
    if isinstance(value, list) and value:
        parts: list[str] = []
        for item in value:
            t = _short_custom_field_display_value(item)
            if t:
                parts.append(t)
        return ", ".join(parts) if parts else None
    return None


def _short_severity_line(issue: dict[str, Any]) -> str | None:
    """``Severity: …`` from the custom field whose display name is Severity."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_severity_field_raw(fields)
    if raw is None:
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"Severity: {text}"


def _short_preliminary_testing_field_raw(fields: dict[str, Any], field_id: str | None) -> Any:
    """Value for Preliminary Testing (after key rewrite, or by ``JIRA_PRELIMINARY_TESTING_FIELD_ID``)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    for exact in ("Preliminary Testing",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "preliminary testing":
            return v
    return None


def _short_testing_line(
    issue: dict[str, Any], *, preliminary_testing_field_id: str | None = None
) -> str | None:
    """``Testing: …`` from the Preliminary Testing custom field (select / text / etc.)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_preliminary_testing_field_raw(fields, preliminary_testing_field_id)
    if raw is None or _is_omitted_value(raw):
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"Testing: {text}"


def _short_fixed_in_build_field_raw(fields: dict[str, Any], field_id: str | None) -> Any:
    """Value for Fixed in Build (after key rewrite, or by ``JIRA_FIXED_IN_BUILD_FIELD_ID``)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    for exact in ("Fixed in Build",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "fixed in build":
            return v
    return None


def _short_build_line(
    issue: dict[str, Any], *, fixed_in_build_field_id: str | None = None
) -> str | None:
    """``Build: …`` from the Fixed in Build custom field (version / text / etc.)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_fixed_in_build_field_raw(fields, fixed_in_build_field_id)
    if raw is None or _is_omitted_value(raw):
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"Build: {text}"


def _short_test_coverage_field_raw(fields: dict[str, Any], field_id: str | None) -> Any:
    """Value for the custom field labeled Test Coverage (after key rewrite, or by ``JIRA_TEST_COVERAGE_FIELD_ID``)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    for exact in ("Test Coverage",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "test coverage":
            return v
    return None


def _short_coverage_line(
    issue: dict[str, Any], *, test_coverage_field_id: str | None = None
) -> str | None:
    """``Coverage: …`` from the Test Coverage custom field."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_test_coverage_field_raw(fields, test_coverage_field_id)
    if raw is None or _is_omitted_value(raw):
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"Coverage: {text}"


def _short_test_link_field_raw(fields: dict[str, Any], field_id: str | None) -> Any:
    """Value for the custom field labeled Test Link (after key rewrite, or by ``JIRA_TEST_LINK_FIELD_ID``)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    for exact in ("Test Link",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "test link":
            return v
    return None


def _short_test_link_line(
    issue: dict[str, Any], *, test_link_field_id: str | None = None
) -> str | None:
    """``Test: …`` from the Test Link custom field (URL / text)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_test_link_field_raw(fields, test_link_field_id)
    if raw is None or _is_omitted_value(raw):
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"Test: {text}"


def _short_git_pull_request_field_raw(fields: dict[str, Any], field_id: str | None) -> Any:
    """Value for Git Pull Request (after key rewrite, or by ``JIRA_GIT_PULL_REQUEST_FIELD_ID``)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    for exact in ("Git Pull Request",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "git pull request":
            return v
    return None


def _git_pull_request_from_cached_value(obj: Any) -> str | None:
    """Readable summary from dev-status ``cachedValue`` JSON (pullrequest overall count/state)."""
    if not isinstance(obj, dict):
        return None
    cached = obj.get("cachedValue")
    if not isinstance(cached, dict):
        cached = obj
    summary = cached.get("summary")
    if not isinstance(summary, dict):
        return None
    pr = summary.get("pullrequest")
    if not isinstance(pr, dict):
        return None
    overall = pr.get("overall")
    if not isinstance(overall, dict):
        return _short_custom_field_display_value(pr)
    count = overall.get("count")
    state = overall.get("state")
    open_ = overall.get("open")
    bits: list[str] = []
    if count is not None:
        bits.append(str(count))
    if isinstance(state, str) and state.strip():
        bits.append(state.strip())
    elif open_ is True:
        bits.append("OPEN")
    elif open_ is False:
        bits.append("CLOSED")
    return " ".join(bits) if bits else None


def _git_pull_request_from_dev_status_string(s: str) -> str | None:
    """Parse Jira Development / dev-status serialized field text."""
    idx = s.find("json=")
    if idx >= 0:
        rest = s[idx + 5 :].lstrip()
        if rest.startswith("{"):
            try:
                obj, _end = json.JSONDecoder().raw_decode(rest)
            except json.JSONDecodeError:
                obj = None
            if obj is not None:
                text = _git_pull_request_from_cached_value(obj)
                if text:
                    return text
    m = re.search(r"pullrequest=\{([^}]+)\}", s)
    if m:
        inner = m.group(1)
        state_m = re.search(r"state=([^,}\s]+)", inner)
        count_m = re.search(r"stateCount=(\d+)", inner)
        bits: list[str] = []
        if count_m:
            bits.append(count_m.group(1))
        if state_m:
            bits.append(state_m.group(1))
        if bits:
            return " ".join(bits)
    return None


def _short_git_pull_request_display_value(value: Any) -> str | None:
    """URL / text / dev-status summary for the Git Pull Request custom field."""
    if value is None or _is_omitted_value(value):
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.startswith("{"):
            parsed = _git_pull_request_from_dev_status_string(s)
            if parsed:
                return parsed
        return s
    if isinstance(value, dict):
        if value.get("type") == "doc":
            text = _fields_description_to_plain_text(value)
            if text and text.strip():
                return text.strip()
        for key in ("url", "href", "name", "value", "displayName"):
            if key not in value:
                continue
            inner = value[key]
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        pull_requests = value.get("pullRequests")
        if isinstance(pull_requests, list) and pull_requests:
            parts: list[str] = []
            for pr in pull_requests:
                if not isinstance(pr, dict):
                    continue
                u = pr.get("url")
                if isinstance(u, str) and u.strip():
                    parts.append(u.strip())
                    continue
                nm = pr.get("name") or pr.get("title")
                if isinstance(nm, str) and nm.strip():
                    parts.append(nm.strip())
            if parts:
                return ", ".join(parts)
        return _git_pull_request_from_cached_value(value) or _short_custom_field_display_value(
            value
        )
    if isinstance(value, list) and value:
        parts: list[str] = []
        for item in value:
            t = _short_git_pull_request_display_value(item)
            if t:
                parts.append(t)
        return ", ".join(parts) if parts else None
    return _short_custom_field_display_value(value)


def _short_git_pull_request_line(
    issue: dict[str, Any], *, git_pull_request_field_id: str | None = None
) -> str | None:
    """``PR: …`` from the Git Pull Request custom field (URL / dev-status summary)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_git_pull_request_field_raw(fields, git_pull_request_field_id)
    if raw is None or _is_omitted_value(raw):
        return None
    text = _short_git_pull_request_display_value(raw)
    if not text:
        return None
    return f"PR: {text}"


def _short_assigned_team_field_raw(
    fields: dict[str, Any],
    field_id: str | None = None,
    *,
    names: dict[str, Any] | None = None,
) -> Any:
    """Value for AssignedTeam / Assigned Team (display-name keys, ``names`` map, or field id)."""
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid in fields:
            return fields[fid]
        if not fid.startswith("customfield_") and fid.isdigit():
            alt = f"customfield_{fid}"
            if alt in fields:
                return fields[alt]
    if isinstance(names, dict):
        for fid, display in names.items():
            if not isinstance(fid, str) or not fid.startswith("customfield_"):
                continue
            if not isinstance(display, str) or not display.strip():
                continue
            base = display.strip()
            if base.replace(" ", "").casefold() != "assignedteam":
                continue
            if fid in fields:
                return fields[fid]
    for exact in ("AssignedTeam", "Assigned Team"):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.replace(" ", "").casefold() == "assignedteam":
            return v
    return None


def _short_assigned_team_line(
    issue: dict[str, Any], *, assigned_team_field_id: str | None = None
) -> str | None:
    """``AssignedTeam: …`` from the AssignedTeam custom field (``value`` / ``name`` / etc.)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    names = issue.get("names")
    name_map = names if isinstance(names, dict) else None
    raw = _short_assigned_team_field_raw(fields, assigned_team_field_id, names=name_map)
    if raw is None or _is_omitted_value(raw):
        return None
    text = _short_custom_field_display_value(raw)
    if not text:
        return None
    return f"AssignedTeam: {text}"


def _short_qa_contact_field_raw(fields: dict[str, Any]) -> Any:
    """Value for the custom field labeled QA Contact (after key rewrite)."""
    for exact in ("QA Contact",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "qa contact":
            return v
    return None


def _short_qa_contact_line(issue: dict[str, Any]) -> str | None:
    """``QA Contact: <email>`` from the QA Contact user field (``emailAddress``)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_qa_contact_field_raw(fields)
    if raw is None or _is_omitted_value(raw):
        return None
    emails: list[str] = []
    if isinstance(raw, dict):
        em = _user_field_email(raw)
        if em:
            emails.append(em)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                em = _user_field_email(item)
                if em:
                    emails.append(em)
    if not emails:
        return None
    return f"QA Contact: {', '.join(emails)}"


def _short_developer_field_raw(fields: dict[str, Any]) -> Any:
    """Value for the custom field labeled Developer (after key rewrite)."""
    for exact in ("Developer",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "developer":
            return v
    return None


def _short_developer_line(issue: dict[str, Any]) -> str | None:
    """``Developer: <email>`` from the Developer user field (``emailAddress``)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_developer_field_raw(fields)
    if raw is None or _is_omitted_value(raw):
        return None
    emails: list[str] = []
    if isinstance(raw, dict):
        em = _user_field_email(raw)
        if em:
            emails.append(em)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                em = _user_field_email(item)
                if em:
                    emails.append(em)
    if not emails:
        return None
    return f"Developer: {', '.join(emails)}"


def _short_doc_contact_field_raw(fields: dict[str, Any]) -> Any:
    """Value for the custom field labeled Doc Contact (after key rewrite)."""
    for exact in ("Doc Contact",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "doc contact":
            return v
    return None


def _short_doc_contact_line(issue: dict[str, Any]) -> str | None:
    """``Doc Contact: <email>`` from the Doc Contact user field (``emailAddress``)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_doc_contact_field_raw(fields)
    if raw is None or _is_omitted_value(raw):
        return None
    emails: list[str] = []
    if isinstance(raw, dict):
        em = _user_field_email(raw)
        if em:
            emails.append(em)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                em = _user_field_email(item)
                if em:
                    emails.append(em)
    if not emails:
        return None
    return f"Doc Contact: {', '.join(emails)}"


def _short_contributors_field_raw(fields: dict[str, Any]) -> Any:
    """Value for the custom field labeled Contributors (after key rewrite)."""
    for exact in ("Contributors",):
        if exact in fields:
            return fields[exact]
    for k, v in fields.items():
        if not isinstance(k, str):
            continue
        base = k.split("(", 1)[0].strip()
        if base.casefold() == "contributors":
            return v
    return None


def _short_contributors_line(issue: dict[str, Any]) -> str | None:
    """``Contributors: <emails>`` from the multi-user Contributors field (``emailAddress`` per user)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = _short_contributors_field_raw(fields)
    if raw is None or _is_omitted_value(raw):
        return None
    emails: list[str] = []
    if isinstance(raw, dict):
        em = _user_field_email(raw)
        if em:
            emails.append(em)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                em = _user_field_email(item)
                if em:
                    emails.append(em)
    if not emails:
        return None
    return f"Contributors: {', '.join(emails)}"


def _short_assignee_line(issue: dict[str, Any]) -> str | None:
    """``Assignee: <email>`` from ``fields.assignee.emailAddress``."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    assignee = fields.get("assignee")
    if not isinstance(assignee, dict):
        return None
    em = _user_field_email(assignee)
    if em is None:
        return None
    return f"Assignee: {em}"


def _short_reporter_line(issue: dict[str, Any]) -> str | None:
    """``Reporter: <email>`` from ``fields.reporter.emailAddress``."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    reporter = fields.get("reporter")
    if not isinstance(reporter, dict):
        return None
    em = _user_field_email(reporter)
    if em is None:
        return None
    return f"Reporter: {em}"


def _short_description_lines(issue: dict[str, Any]) -> list[str] | None:
    """``Description:`` plus plain multiline body from ``fields.description`` (ADF or string)."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    text = _fields_description_to_plain_text(fields.get("description"))
    if text is None:
        return None
    return ["Description:", *text.splitlines()]


_COMMENT_SHORT_BODY_INDENT = "   "  # same width as `` - `` so body lines up under the author


def _short_comment_lines(client: JiraClient, issue_key: str) -> list[str] | None:
    """
    ``Comments:`` then each `` - author (created)`` line, then flattened body indented under the author
    (paginated GET so all comments are included).
    """
    try:
        comments = client.list_issue_comments(issue_key.strip().upper())
    except JiraApiError:
        return None
    if not comments:
        return None
    out: list[str] = ["Comments:"]
    first_block = True
    for c in comments:
        if not isinstance(c, dict):
            continue
        author = c.get("author")
        auth_label = ""
        if isinstance(author, dict):
            em = author.get("emailAddress")
            if isinstance(em, str) and em.strip():
                auth_label = em.strip()
            if not auth_label:
                dn = author.get("displayName")
                if isinstance(dn, str) and dn.strip():
                    auth_label = dn.strip()
        if not auth_label:
            auth_label = "(unknown)"
        cr = c.get("created")
        created = cr.strip() if isinstance(cr, str) else ""
        if created:
            head = f" - {auth_label} ({created})"
        else:
            head = f" - {auth_label}"
        plain = _comment_body_to_flat_plain(c.get("body"))
        if not first_block:
            out.append("")
        first_block = False
        out.append(head)
        if plain:
            out.append(f"{_COMMENT_SHORT_BODY_INDENT}{plain}")
    return out


def _user_field_email(value: dict[str, Any]) -> str | None:
    raw = value.get("emailAddress")
    if isinstance(raw, str):
        s = raw.strip()
        return s if s else None
    return None


def _issuelink_key_summary(link: Any) -> tuple[str | None, str | None]:
    if not isinstance(link, dict):
        return None, None
    issue_obj = None
    if isinstance(link.get("inwardIssue"), dict):
        issue_obj = link.get("inwardIssue")
    elif isinstance(link.get("outwardIssue"), dict):
        issue_obj = link.get("outwardIssue")
    elif isinstance(link.get("issue"), dict):
        issue_obj = link.get("issue")
    if not isinstance(issue_obj, dict):
        issue_obj = link

    key = issue_obj.get("key")
    if not isinstance(key, str) or not key.strip():
        key = None

    summary = None
    fields = issue_obj.get("fields")
    if isinstance(fields, dict):
        sm = fields.get("summary")
        if isinstance(sm, str) and sm.strip():
            summary = sm
    else:
        sm = issue_obj.get("summary")
        if isinstance(sm, str) and sm.strip():
            summary = sm

    return key, summary


def _short_issuelinks_lines(issue: dict[str, Any]) -> list[str] | None:
    """``Links:`` plus one ``[key] summary`` line per ``fields.issuelinks`` entry."""
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    raw = fields.get("issuelinks")
    if not isinstance(raw, list) or not raw:
        return None
    body: list[str] = []
    for link in raw:
        key, summary = _issuelink_key_summary(link)
        if key is None:
            continue
        k = key.strip()
        if summary and str(summary).strip():
            body.append(f"[{k}] {str(summary).strip()}")
        else:
            body.append(f"[{k}]")
    if not body:
        return None
    return ["Links:"] + body


def run_show(
    client: JiraClient,
    issue_key: str,
    *,
    expand: str | None,
    compact: bool,
    brief: bool = False,
    short: bool = False,
    custom_id: bool,
    preliminary_testing_field_id: str | None = None,
    fixed_in_build_field_id: str | None = None,
    test_coverage_field_id: str | None = None,
    test_link_field_id: str | None = None,
    git_pull_request_field_id: str | None = None,
    story_points_field_id: str | None = None,
    assigned_team_field_id: str | None = None,
    out: TextIO,
    err: TextIO,
) -> int:
    key = issue_key.strip().upper()
    expand_merged = _merge_expand_with_names(expand)
    try:
        data = client.get_issue(key, all_fields=True, expand=expand_merged)
    except JiraApiError as e:
        print_jira_api_error(e, err)
        return 1

    if not data.get("names"):
        _inject_names_from_field_list(client, data)
    if not custom_id:
        _rewrite_custom_field_keys(data)

    if short:
        merged = _brief_issue_merged(data)
        if merged is not None:
            print(merged, file=out)
        st_line = _short_status_line(data)
        if st_line is not None:
            print(st_line, file=out)
        it_line = _short_issuetype_line(data)
        if it_line is not None:
            print(it_line, file=out)
        pr_line = _short_priority_line(data)
        if pr_line is not None:
            print(pr_line, file=out)
        sev_line = _short_severity_line(data)
        if sev_line is not None:
            print(sev_line, file=out)
        test_line = _short_testing_line(
            data, preliminary_testing_field_id=preliminary_testing_field_id
        )
        if test_line is not None:
            print(test_line, file=out)
        cov_line = _short_coverage_line(data, test_coverage_field_id=test_coverage_field_id)
        if cov_line is not None:
            print(cov_line, file=out)
        tlink_line = _short_test_link_line(data, test_link_field_id=test_link_field_id)
        if tlink_line is not None:
            print(tlink_line, file=out)
        pr_line = _short_git_pull_request_line(
            data, git_pull_request_field_id=git_pull_request_field_id
        )
        if pr_line is not None:
            print(pr_line, file=out)
        build_line = _short_build_line(data, fixed_in_build_field_id=fixed_in_build_field_id)
        if build_line is not None:
            print(build_line, file=out)
        spoints_line = _short_story_points_line(
            data,
            story_points_field_id=story_points_field_id,
        )
        if spoints_line is not None:
            print(spoints_line, file=out)
        sp_line = _short_sprint_line(data)
        if sp_line is not None:
            print(sp_line, file=out)
        due_line = _short_duedate_line(data)
        if due_line is not None:
            print(due_line, file=out)
        team_line = _short_assigned_team_line(data, assigned_team_field_id=assigned_team_field_id)
        if team_line is not None:
            print(team_line, file=out)
        qa_line = _short_qa_contact_line(data)
        if qa_line is not None:
            print(qa_line, file=out)
        dev_line = _short_developer_line(data)
        if dev_line is not None:
            print(dev_line, file=out)
        doc_line = _short_doc_contact_line(data)
        if doc_line is not None:
            print(doc_line, file=out)
        contrib_line = _short_contributors_line(data)
        if contrib_line is not None:
            print(contrib_line, file=out)
        asn_line = _short_assignee_line(data)
        if asn_line is not None:
            print(asn_line, file=out)
        rep_line = _short_reporter_line(data)
        if rep_line is not None:
            print(rep_line, file=out)
        desc_lines = _short_description_lines(data)
        if desc_lines is not None:
            for line in desc_lines:
                print(line, file=out)
        par_line = _short_parent_line(data)
        if par_line is not None:
            print(par_line, file=out)
        epic_line = _short_epic_link_line(client, data)
        if epic_line is not None:
            print(epic_line, file=out)
        child_lines = _short_epic_children_lines(client, data)
        if child_lines is not None:
            for line in child_lines:
                print(line, file=out)
        link_lines = _short_issuelinks_lines(data)
        if link_lines is not None:
            for line in link_lines:
                print(line, file=out)
        comm_lines = _short_comment_lines(client, key)
        if comm_lines is not None:
            for line in comm_lines:
                print(line, file=out)
        return 0

    if brief:
        _brief_rename_fields_with_names(data)
        stripped = _strip_empty_json(data)
        data = stripped if isinstance(stripped, dict) else {}

    if compact:
        json.dump(data, out, separators=(",", ":"), ensure_ascii=False)
    else:
        json.dump(data, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return 0
