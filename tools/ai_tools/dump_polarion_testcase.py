#!/usr/bin/env python3
"""Dump a Polarion testcase via REST API v1 for Jira RHELTEST import."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

# Standard Polarion work-item attributes (same allowlist as mcp-server-polarion).
STANDARD_WORK_ITEM_ATTRIBUTES = frozenset(
    {
        "id",
        "type",
        "title",
        "description",
        "status",
        "priority",
        "severity",
        "resolution",
        "resolvedOn",
        "created",
        "updated",
        "outlineNumber",
        "dueDate",
        "plannedStart",
        "plannedEnd",
        "initialEstimate",
        "remainingEstimate",
        "timeSpent",
        "hyperlinks",
    }
)

# Preferred order for common standard keys in the Polarion dump.
STANDARD_KEY_ORDER = (
    "id",
    "project_id",
    "title",
    "type",
    "status",
    "priority",
    "severity",
    "resolution",
    "created",
    "updated",
    "author",
    "author_email",
    "assignee",
    "assignee_email",
    "description",
    "outlineNumber",
    "dueDate",
    "plannedStart",
    "plannedEnd",
    "initialEstimate",
    "remainingEstimate",
    "timeSpent",
    "resolvedOn",
    "hyperlinks",
)

# Polarion → Jira RHELTEST Test Case (create-rheltest-testcase skill).
# Unmapped Polarion fields are folded into description as rich text.
JIRA_KEY_ORDER = (
    "summary",
    "description",
    "assignee",
    "components",
    "labels",
    "AssignedTeam",
    "Tier",
    "Architecture",
    "ID",
    "URL",
    "External issue URL",
    "status",
)

# Keys consumed by a direct Jira field mapping (not repeated as metadata rows).
JIRA_MAPPED_POLARION_KEYS = frozenset(
    {
        "title",
        "assignee",
        "assignee_email",
        "author_email",
        "casecomponent",
        "subsystemteam",
        "tags",
        "id",
        "project_id",
        "type",
        "status",
        "testCaseID",
        "automation_script",
        "upstream",
        "created",
        "updated",
    }
)

# Polarion testcase status → Jira issue status name.
# Normalized keys are lowercase with spaces/underscores stripped to alnum.
POLARION_STATUS_TO_JIRA: dict[str, str] = {
    "draft": "Draft",
    "needsupdate": "Draft",
    "proposed": "Draft",
    "inactive": "Retired",
    "approved": "Active",
}

# Keys rendered as dedicated rich-text sections in the Jira description.
# ``automation_script`` maps to Jira URL, so it is not a description section.
JIRA_DESCRIPTION_SECTION_KEYS = (
    "description",
    "setup",
    "teardown",
)

# Always omit these from the Polarion-fields table in description.
JIRA_DESCRIPTION_OMIT_KEYS = frozenset({"created", "updated"})

_EMPTY_HTML_RE = re.compile(
    r"^(?:\s|<p\s*/?>|</p>|&nbsp;|<br\s*/?>)*$",
    re.IGNORECASE,
)
_PLACEHOLDER_VALUE_RE = re.compile(r"^-+$")
# Polarion docstring blocks embedded in description, e.g.
#   :title: ...\n:setup:\n    1. Start SSSD\n:steps:\n    ...
_DOCSTRING_SECTION_RE = re.compile(
    r"(?im)(?:^|(?<=\n)|(?<=>))[ \t]*"
    r":(title|setup|steps|expectedresults|customerscenario):[ \t]*[^\n<]*"
    r"(?:\n[ \t]+[^\n]*)*",
)
_CUSTOMERSCENARIO_VALUE_RE = re.compile(
    r"(?i):customerscenario:[ \t]*([^\n<]*)",
)
_TRUTHY_RE = re.compile(r"^(?:true|yes|1)$", re.IGNORECASE)


def is_blank_rich_text(value: str) -> bool:
    if not value or not value.strip():
        return True
    return bool(_EMPTY_HTML_RE.match(value))


def is_placeholder_meta_value(key: str, value: str) -> bool:
    """True for subtype fields whose value is only ``-`` / ``--`` (etc.)."""
    if not key.lower().startswith("subtype"):
        return False
    return bool(_PLACEHOLDER_VALUE_RE.match(value.strip()))


def strip_duplicate_docstring_sections(
    description: str,
    *,
    strip_title: bool,
    strip_setup: bool,
    strip_steps: bool,
    strip_expectedresults: bool,
    strip_customerscenario: bool = False,
) -> str:
    """Remove docstring blocks already covered by Polarion/Jira mapped fields.

    Strips ``:title:`` / ``:setup:`` / ``:steps:`` / ``:expectedresults:`` /
    ``:customerscenario:`` from the description when the same content is
    already taken from Polarion fields or mapped to Jira labels.
    """
    remove: set[str] = set()
    if strip_title:
        remove.add("title")
    if strip_setup:
        remove.add("setup")
    if strip_steps:
        remove.add("steps")
    if strip_expectedresults:
        remove.add("expectedresults")
    if strip_customerscenario:
        remove.add("customerscenario")
    if not remove or not description:
        return description

    def _repl(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        return "" if name in remove else match.group(0)

    cleaned = _DOCSTRING_SECTION_RE.sub(_repl, description)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def is_truthy_flag(value: str) -> bool:
    return bool(_TRUTHY_RE.match(value.strip()))


def parse_customerscenario(pairs: dict[str, str]) -> bool | None:
    """Return True/False if customerscenario is set, else None.

    Prefers a Polarion ``customerscenario`` field; otherwise parses
    ``:customerscenario:`` from the description docstring.
    """
    for key in ("customerscenario", "customerScenario"):
        raw = pairs.get(key, "").strip()
        if raw:
            # Strip simple HTML wrappers if present.
            text = re.sub(r"<[^>]+>", "", raw).strip()
            if text:
                return is_truthy_flag(text)

    description = pairs.get("description", "")
    match = _CUSTOMERSCENARIO_VALUE_RE.search(description)
    if not match:
        return None
    text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    if not text:
        return None
    return is_truthy_flag(text.split()[0])


def merge_csv_labels(*parts: str) -> str:
    """Merge comma-separated label lists, preserving order and uniqueness."""
    seen: list[str] = []
    for part in parts:
        for label in part.split(","):
            label = label.strip()
            if label and label not in seen:
                seen.append(label)
    return ",".join(seen)


def is_upstream_yes(pairs: dict[str, str]) -> bool:
    """True when Polarion ``upstream`` is yes/true/1."""
    raw = pairs.get("upstream", "").strip()
    if not raw:
        return False
    text = re.sub(r"<[^>]+>", "", raw).strip()
    if not text:
        return False
    return is_truthy_flag(text.split()[0])


def normalize_jira_summary(title: str) -> str:
    """Collapse whitespace/newlines and truncate for the Jira summary (max 255)."""
    return re.sub(r"\s+", " ", title).strip()[:255]


def has_nonblank_teststep_field(pairs: dict[str, str], field: str) -> bool:
    suffix = f".{field}"
    for key, value in pairs.items():
        if not key.startswith("teststep.") or not key.endswith(suffix):
            continue
        # Avoid matching ``.step`` against ``.expectedResult`` etc.: require
        # exactly teststep.<index>.<field>
        parts = key.split(".", 2)
        if len(parts) != 3 or parts[2] != field:
            continue
        if not is_blank_rich_text(value):
            return True
    return False


class PolarionError(RuntimeError):
    """Polarion REST API or client error."""


def ca_bundle_from_env() -> str | None:
    return os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")


def polarion_config_from_env() -> tuple[str, str, bool]:
    """Return (base_api_url, token, verify_ssl) from environment."""
    url = os.environ.get("POLARION_URL", "").strip()
    token = os.environ.get("POLARION_TOKEN", "").strip()
    if not url:
        raise PolarionError("set POLARION_URL (e.g. https://polarion.example.com)")
    if not token:
        raise PolarionError("set POLARION_TOKEN (Polarion personal access token)")
    verify_raw = os.environ.get("POLARION_VERIFY_SSL", "true").strip().lower()
    verify_ssl = verify_raw not in ("0", "false", "no", "off")
    base = f"{url.rstrip('/')}/polarion/rest/v1"
    return base, token, verify_ssl


def _ssl_context(verify_ssl: bool, ca_bundle: str | None) -> ssl.SSLContext | bool:
    if not verify_ssl:
        return False
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def encode_path_segment(segment: str) -> str:
    return quote(segment, safe="")


def polarion_get(
    base_api_url: str,
    path: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
    verify_ssl: bool = True,
    ca_bundle: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """GET a Polarion REST v1 JSON:API resource."""
    url = f"{base_api_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(
            request,
            context=_ssl_context(verify_ssl, ca_bundle),
            timeout=timeout,
        ) as response:
            body = response.read()
    except HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if isinstance(errors, list) and errors:
                parts = [
                    str(e.get("detail") or e.get("title") or "")
                    for e in errors
                    if isinstance(e, dict)
                ]
                detail = "; ".join(p for p in parts if p)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        suffix = f": {detail}" if detail else ""
        if exc.code in (401, 403):
            raise PolarionError(
                f"Polarion auth failed ({exc.code}); check POLARION_TOKEN{suffix}",
            ) from exc
        if exc.code == 404:
            raise PolarionError(f"Polarion resource not found (404){suffix}") from exc
        raise PolarionError(f"Polarion API error {exc.code}{suffix}") from exc
    except URLError as exc:
        raise PolarionError(f"Polarion HTTP transport error: {exc.reason}") from exc

    if not body:
        return {}
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        return {"data": data}
    return data


def extract_relationship_ids(
    relationships: dict[str, Any],
    rel_name: str,
) -> list[str]:
    rel = relationships.get(rel_name, {})
    if not isinstance(rel, dict):
        return []
    data = rel.get("data")
    if isinstance(data, dict):
        rid = data.get("id")
        return [str(rid)] if rid else []
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("id"):
            ids.append(str(entry["id"]))
    return ids


def short_id(full_id: str) -> str:
    if "/" not in full_id:
        return full_id
    return full_id.rsplit("/", maxsplit=1)[-1]


def safe_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def unwrap_text_value(value: Any) -> str:
    """Flatten Polarion rich-text ``{type, value}`` objects to their text."""
    if value is None:
        return ""
    if isinstance(value, dict) and "value" in value:
        return "" if value["value"] is None else str(value["value"])
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def format_hyperlinks(value: Any) -> str:
    if not isinstance(value, list):
        return unwrap_text_value(value)
    parts: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        uri = str(entry.get("uri") or "")
        title = str(entry.get("title") or "")
        if not uri:
            continue
        if title:
            parts.append(f"{role}|{title}|{uri}")
        else:
            parts.append(f"{role}|{uri}")
    return ",".join(parts)


def escape_property_value(value: str) -> str:
    """Escape a value so each property fits on one line (Java-properties style)."""
    return (
        value.replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def unescape_property_value(value: str) -> str:
    """Inverse of :func:`escape_property_value`."""
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(value[i])
        i += 1
    return "".join(out)


def parse_key_value_text(text: str) -> dict[str, str]:
    """Parse a ``key=value`` dump (``#`` comments and blank lines ignored)."""
    pairs: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid key=value line: {raw_line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty key in line: {raw_line!r}")
        pairs[key] = unescape_property_value(value)
    return pairs


def parse_key_value_file(path: Path) -> dict[str, str]:
    return parse_key_value_text(path.read_text(encoding="utf-8"))


def parse_included_user_map(
    response: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Map user id → ``{name, email}`` from JSON:API ``included`` users."""
    user_map: dict[str, dict[str, str]] = {}
    included = response.get("included", [])
    if not isinstance(included, list):
        return user_map
    for entry in included:
        if not isinstance(entry, dict) or entry.get("type") != "users":
            continue
        user_id = short_id(safe_str(entry.get("id", "")))
        if not user_id:
            continue
        attrs = entry.get("attributes", {})
        if not isinstance(attrs, dict):
            attrs = {}
        user_map[user_id] = {
            "name": safe_str(attrs.get("name", "")),
            "email": safe_str(attrs.get("email", "")),
        }
    return user_map


def emails_for_user_ids(
    user_ids: list[str],
    user_map: dict[str, dict[str, str]],
) -> str:
    emails: list[str] = []
    for uid in user_ids:
        email = (user_map.get(uid) or {}).get("email", "").strip()
        if email and email not in emails:
            emails.append(email)
    return ",".join(emails)


def resolve_jira_assignee_email(pairs: dict[str, str]) -> str:
    """Prefer Polarion assignee email; fall back to author email."""
    assignee_email = pairs.get("assignee_email", "").strip()
    if assignee_email:
        return assignee_email.split(",")[0].strip()
    author_email = pairs.get("author_email", "").strip()
    if author_email:
        return author_email.split(",")[0].strip()
    return ""


def normalize_polarion_status(status: str) -> str:
    """Normalize Polarion status for map lookup (lowercase, alnum only)."""
    return re.sub(r"[^a-z0-9]+", "", status.strip().lower())


def map_polarion_status_to_jira(status: str) -> str | None:
    """Map Polarion testcase status to a Jira status name, or None if unknown."""
    key = normalize_polarion_status(status)
    if not key:
        return None
    return POLARION_STATUS_TO_JIRA.get(key)

def attributes_to_pairs(
    attributes: dict[str, Any],
    *,
    project_id: str,
    author: str = "",
    assignee: str = "",
    author_email: str = "",
    assignee_email: str = "",
) -> dict[str, str]:
    """Map work-item attributes (+ meta) to flat string values."""
    pairs: dict[str, str] = {
        "id": str(attributes.get("id") or ""),
        "project_id": project_id,
    }
    if author:
        pairs["author"] = author
    if author_email:
        pairs["author_email"] = author_email
    if assignee:
        pairs["assignee"] = assignee
    if assignee_email:
        pairs["assignee_email"] = assignee_email

    for key, raw in attributes.items():
        if key == "id":
            continue
        if key == "hyperlinks":
            pairs[key] = format_hyperlinks(raw)
        elif isinstance(raw, list) and key not in STANDARD_WORK_ITEM_ATTRIBUTES:
            # Enum multi-select style custom fields.
            pairs[key] = ",".join(unwrap_text_value(item) for item in raw)
        else:
            pairs[key] = unwrap_text_value(raw)
    return pairs


def teststeps_to_pairs(steps: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten teststeps into ``teststep.<index>.<key>=...`` entries."""
    pairs: dict[str, str] = {}
    for step in steps:
        attrs = step.get("attributes") if isinstance(step, dict) else None
        if not isinstance(attrs, dict):
            continue
        index = str(attrs.get("index") or short_id(str(step.get("id") or "")) or "")
        if not index:
            continue
        keys = attrs.get("keys")
        values = attrs.get("values")
        if not isinstance(keys, list) or not isinstance(values, list):
            continue
        for key, value in zip(keys, values, strict=False):
            field = str(key)
            pairs[f"teststep.{index}.{field}"] = unwrap_text_value(value)
    return pairs


def ordered_items(pairs: dict[str, str]) -> list[tuple[str, str]]:
    """Order dump keys: standard first, then other attrs, then teststeps."""
    remaining = dict(pairs)
    ordered: list[tuple[str, str]] = []
    for key in STANDARD_KEY_ORDER:
        if key in remaining:
            ordered.append((key, remaining.pop(key)))
    teststep_items = sorted(
        ((k, remaining.pop(k)) for k in list(remaining) if k.startswith("teststep.")),
        key=lambda item: item[0],
    )
    other = sorted(remaining.items(), key=lambda item: item[0])
    ordered.extend(other)
    ordered.extend(teststep_items)
    return ordered


def format_key_value(
    pairs: dict[str, str],
    *,
    key_order: tuple[str, ...] | None = None,
) -> str:
    if key_order is None:
        items = ordered_items(pairs)
    else:
        remaining = dict(pairs)
        items = []
        for key in key_order:
            if key in remaining:
                items.append((key, remaining.pop(key)))
        items.extend(sorted(remaining.items(), key=lambda item: item[0]))
    lines = [f"{key}={escape_property_value(value)}" for key, value in items]
    return "\n".join(lines) + ("\n" if lines else "")


def polarion_workitem_url(polarion_url: str, project_id: str, work_item_id: str) -> str:
    root = polarion_url.rstrip("/")
    return f"{root}/polarion/#/project/{project_id}/workitem?id={work_item_id}"


def parse_hyperlink_uris(hyperlinks: str) -> list[tuple[str, str]]:
    """Parse flattened ``role|uri`` / ``role|title|uri`` dump values."""
    result: list[tuple[str, str]] = []
    if not hyperlinks.strip():
        return result
    for part in hyperlinks.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split("|")
        if len(bits) == 2:
            result.append((bits[0], bits[1]))
        elif len(bits) >= 3:
            result.append((bits[0], bits[-1]))
    return result


def primary_script_url(hyperlinks: str) -> str:
    links = parse_hyperlink_uris(hyperlinks)
    for role, uri in links:
        if role.lower() in {"testscript", "verifies", "implements", "ref"}:
            return uri
    return links[0][1] if links else ""


def automation_script_for_url(value: str) -> str:
    """Flatten Polarion automation_script HTML/text for the Jira URL field."""
    text = value.strip()
    if not text:
        return ""
    if "<" in text:
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
    return " ".join(text.split()).strip()


def is_valid_http_url(value: str) -> bool:
    """True when *value* is an absolute http(s) URL (Jira URL custom fields)."""
    text = value.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def resolve_jira_url(pairs: dict[str, str]) -> str:
    """Prefer automation_script when it is a valid URL; else testscript hyperlink."""
    automation = automation_script_for_url(pairs.get("automation_script", ""))
    if is_valid_http_url(automation):
        return automation.strip()
    hyperlink = primary_script_url(pairs.get("hyperlinks", "")).strip()
    if is_valid_http_url(hyperlink):
        return hyperlink
    return ""


def collect_teststeps(pairs: dict[str, str]) -> list[dict[str, str]]:
    """Group ``teststep.<n>.*`` keys into ordered step dicts."""
    by_index: dict[str, dict[str, str]] = {}
    for key, value in pairs.items():
        if not key.startswith("teststep."):
            continue
        parts = key.split(".", 2)
        if len(parts) != 3:
            continue
        _, index, field = parts
        by_index.setdefault(index, {})[field] = value

    def sort_key(index: str) -> tuple[int, str]:
        return (int(index), index) if index.isdigit() else (10**9, index)

    return [
        {"index": index, **by_index[index]}
        for index in sorted(by_index, key=sort_key)
    ]


def _html_section(title: str, body: str) -> str:
    return f"<h2>{title}</h2>\n{body.strip()}\n"


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _table_cell_html(value: str, *, header: bool = False) -> str:
    tag = "th" if header else "td"
    if is_blank_rich_text(value):
        body = ""
    elif "<" in value:
        body = value.strip()
    else:
        body = _html_escape(value.strip())
    return f"<{tag}>{body}</{tag}>"


def format_teststeps_table(steps: list[dict[str, str]]) -> str:
    """Render test steps as an HTML table: Step | Action | Result."""
    rows: list[str] = [
        "<tr>"
        f"{_table_cell_html('Step', header=True)}"
        f"{_table_cell_html('Action', header=True)}"
        f"{_table_cell_html('Result', header=True)}"
        "</tr>"
    ]
    for step in steps:
        step_html = step.get("step", "")
        expected = step.get("expectedResult", "")
        other = {
            k: v
            for k, v in step.items()
            if k not in {"index", "step", "expectedResult"} and not is_blank_rich_text(v)
        }
        if (
            is_blank_rich_text(step_html)
            and is_blank_rich_text(expected)
            and not other
        ):
            continue
        action = step_html.strip() if not is_blank_rich_text(step_html) else ""
        if other:
            extras = "\n".join(
                f"<p><b>{_html_escape(key)}:</b></p>\n{value}"
                for key, value in sorted(other.items())
            )
            action = f"{action}\n{extras}".strip() if action else extras
        result = expected.strip() if not is_blank_rich_text(expected) else ""
        rows.append(
            "<tr>"
            f"{_table_cell_html(str(step.get('index', '')))}"
            f"{_table_cell_html(action)}"
            f"{_table_cell_html(result)}"
            "</tr>"
        )
    if len(rows) == 1:
        return ""
    return (
        '<table border="1" cellpadding="4" cellspacing="0">\n'
        "<tbody>\n"
        + "\n".join(rows)
        + "\n</tbody>\n</table>"
    )


def build_jira_description(pairs: dict[str, str]) -> str:
    """Rich-text description: Polarion body + unmapped fields/sections."""
    sections: list[str] = []

    has_title = not is_blank_rich_text(pairs.get("title", ""))
    has_setup = not is_blank_rich_text(pairs.get("setup", ""))
    has_step_actions = has_nonblank_teststep_field(pairs, "step")
    has_step_results = has_nonblank_teststep_field(pairs, "expectedResult")
    steps_table = format_teststeps_table(collect_teststeps(pairs))
    # True → label; False/True both drop the docstring line once handled.
    customerscenario = parse_customerscenario(pairs)

    description = pairs.get("description", "")
    if not is_blank_rich_text(description):
        description = strip_duplicate_docstring_sections(
            description.strip(),
            strip_title=has_title,
            strip_setup=has_setup,
            strip_steps=bool(steps_table) or has_step_actions,
            strip_expectedresults=bool(steps_table) or has_step_results,
            strip_customerscenario=customerscenario is True,
        )
        if not is_blank_rich_text(description):
            sections.append(description)

    if has_setup:
        sections.append(_html_section("Setup", pairs["setup"]))

    if steps_table:
        sections.append(_html_section("Test steps", steps_table))

    teardown = pairs.get("teardown", "")
    if not is_blank_rich_text(teardown):
        sections.append(_html_section("Teardown", teardown))

    skip_meta = (
        JIRA_MAPPED_POLARION_KEYS
        | set(JIRA_DESCRIPTION_SECTION_KEYS)
        | JIRA_DESCRIPTION_OMIT_KEYS
        | {k for k in pairs if k.startswith("teststep.")}
    )
    if parse_customerscenario(pairs) is True:
        skip_meta = skip_meta | {"customerscenario", "customerScenario"}
    meta_rows: list[str] = []
    for key, value in ordered_items(pairs):
        if (
            key in skip_meta
            or is_blank_rich_text(value)
            or is_placeholder_meta_value(key, value)
        ):
            continue
        meta_rows.append(
            "<tr>"
            f"<th>{_html_escape(key)}</th>"
            f"<td>{value if '<' in value else _html_escape(value)}</td>"
            "</tr>"
        )
    if meta_rows:
        table = (
            '<table border="1" cellpadding="4" cellspacing="0">\n'
            "<tbody>\n"
            + "\n".join(meta_rows)
            + "\n</tbody>\n</table>"
        )
        sections.append(_html_section("Polarion fields", table))

    return "\n".join(sections).strip()


def polarion_pairs_to_jira(
    pairs: dict[str, str],
    *,
    polarion_url: str,
) -> dict[str, str]:
    """Map Polarion dump pairs to Jira RHELTEST Test Case import fields.

    Clear mappings follow ``create-rheltest-testcase``:
    title→summary, assignee email (else author email)→assignee,
    casecomponent→components, tags→labels, subsystemteam→AssignedTeam,
    testCaseID→ID, URL from automation_script when it is a valid http(s) URL
    else hyperlinks testscript, Polarion browse link→External issue URL,
    status→Jira status (draft/needsupdate/proposed→Draft, inactive→Retired,
    approved→Active). ``:customerscenario: True`` (or a Polarion
    customerscenario field) adds a ``customerscenario`` label and is removed
    from the description. Polarion ``upstream`` is omitted from description;
    when set to yes it adds an ``upstream`` label.
    Everything else goes into ``description`` as HTML rich text (created /
    updated timestamps are omitted).
    """
    work_item_id = pairs.get("id", "").strip()
    project_id = pairs.get("project_id", "").strip()
    jira: dict[str, str] = {
        "summary": normalize_jira_summary(pairs.get("title", "")),
        "description": build_jira_description(pairs),
    }

    assignee_email = resolve_jira_assignee_email(pairs)
    if assignee_email:
        jira["assignee"] = assignee_email

    components = pairs.get("casecomponent", "").strip()
    if components:
        jira["components"] = components

    labels = pairs.get("tags", "").strip()
    if parse_customerscenario(pairs) is True:
        labels = merge_csv_labels(labels, "customerscenario")
    if is_upstream_yes(pairs):
        labels = merge_csv_labels(labels, "upstream")
    if labels:
        jira["labels"] = labels

    team = pairs.get("subsystemteam", "").strip()
    if team:
        jira["AssignedTeam"] = team

    test_case_id = pairs.get("testCaseID", "").strip()
    if test_case_id:
        jira["ID"] = test_case_id

    url = resolve_jira_url(pairs)
    if url:
        jira["URL"] = url

    if polarion_url and project_id and work_item_id:
        jira["External issue URL"] = polarion_workitem_url(
            polarion_url,
            project_id,
            work_item_id,
        )

    jira_status = map_polarion_status_to_jira(pairs.get("status", ""))
    if jira_status:
        jira["status"] = jira_status

    return {k: v for k, v in jira.items() if v}


def fetch_testcase(
    project_id: str,
    work_item_id: str,
    *,
    base_api_url: str,
    token: str,
    verify_ssl: bool = True,
    ca_bundle: str | None = None,
    include_teststeps: bool = True,
) -> dict[str, str]:
    """Fetch a work item (and optional test steps) and return key/value pairs."""
    wi_path = (
        f"/projects/{encode_path_segment(project_id)}"
        f"/workitems/{encode_path_segment(work_item_id)}"
    )
    response = polarion_get(
        base_api_url,
        wi_path,
        token=token,
        params={
            "fields[workitems]": "@all",
            "include": "author,assignee",
            "fields[users]": "name,email",
        },
        verify_ssl=verify_ssl,
        ca_bundle=ca_bundle,
    )
    data = response.get("data")
    if not isinstance(data, dict):
        raise PolarionError(
            f"unexpected response for work item '{work_item_id}' in '{project_id}'",
        )

    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    relationships = data.get("relationships")
    if not isinstance(relationships, dict):
        relationships = {}

    user_map = parse_included_user_map(response)
    author_ids = [short_id(x) for x in extract_relationship_ids(relationships, "author")]
    assignee_ids = [
        short_id(x) for x in extract_relationship_ids(relationships, "assignee")
    ]
    if "id" not in attributes or not attributes["id"]:
        attributes = {**attributes, "id": work_item_id}

    pairs = attributes_to_pairs(
        attributes,
        project_id=project_id,
        author=",".join(author_ids),
        assignee=",".join(assignee_ids),
        author_email=emails_for_user_ids(author_ids, user_map),
        assignee_email=emails_for_user_ids(assignee_ids, user_map),
    )

    if include_teststeps:
        steps_path = f"{wi_path}/teststeps"
        steps_response = polarion_get(
            base_api_url,
            steps_path,
            token=token,
            params={"fields[teststeps]": "@all"},
            verify_ssl=verify_ssl,
            ca_bundle=ca_bundle,
        )
        steps_data = steps_response.get("data")
        if isinstance(steps_data, list):
            pairs.update(teststeps_to_pairs(steps_data))

    return pairs


def dump_testcase_to_file(
    pairs: dict[str, str],
    output: Path,
    *,
    key_order: tuple[str, ...] | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    text = format_key_value(pairs, key_order=key_order)
    output.write_text(text, encoding="utf-8")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dump a Polarion testcase via REST API v1 as key=value, formatted "
            "for RHELTEST Jira Test Case import by default "
            "(see create-rheltest-testcase skill). Requires POLARION_URL and "
            "POLARION_TOKEN."
        ),
    )
    parser.add_argument(
        "-P",
        "--project",
        required=True,
        help="Polarion project ID (e.g. RHEL_IDM)",
    )
    parser.add_argument(
        "-i",
        "--id",
        dest="work_item_id",
        required=True,
        help="Work item / testcase ID (e.g. RHEL-130263)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file (default: <id>.properties in the current directory)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write key=value dump to stdout instead of a file",
    )
    parser.add_argument(
        "--format",
        choices=("jira", "polarion"),
        default="jira",
        help=(
            "Output format: jira (default, RHELTEST import fields) or "
            "polarion (raw Polarion attributes)"
        ),
    )
    parser.add_argument(
        "--allow-any-type",
        action="store_true",
        help="Do not require attributes.type to be 'testcase'",
    )
    parser.add_argument(
        "--no-teststeps",
        action="store_true",
        help="Skip fetching /teststeps",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ca_bundle = ca_bundle_from_env()

    try:
        base_api_url, token, verify_ssl = polarion_config_from_env()
        polarion_url = os.environ.get("POLARION_URL", "").strip()
        pairs = fetch_testcase(
            args.project,
            args.work_item_id,
            base_api_url=base_api_url,
            token=token,
            verify_ssl=verify_ssl,
            ca_bundle=ca_bundle,
            include_teststeps=not args.no_teststeps,
        )
    except PolarionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    item_type = pairs.get("type", "")
    if not args.allow_any_type and item_type and item_type != "testcase":
        print(
            f"error: work item type is {item_type!r}, expected 'testcase' "
            "(pass --allow-any-type to override)",
            file=sys.stderr,
        )
        return 1

    key_order: tuple[str, ...] | None = None
    if args.format == "jira":
        pairs = polarion_pairs_to_jira(pairs, polarion_url=polarion_url)
        key_order = JIRA_KEY_ORDER
        if not pairs.get("summary"):
            print("error: Polarion testcase has empty title/summary", file=sys.stderr)
            return 1

    text = format_key_value(pairs, key_order=key_order)
    if args.stdout:
        sys.stdout.write(text)
        return 0

    output = args.output or Path(f"{args.work_item_id}.properties")
    try:
        dump_testcase_to_file(pairs, output, key_order=key_order)
    except OSError as exc:
        print(f"error: cannot write {output}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
