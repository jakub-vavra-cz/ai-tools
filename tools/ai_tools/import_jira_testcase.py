#!/usr/bin/env python3
"""Import a dump-polarion-testcase (jira format) file into Jira RHELTEST."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ai_tools.dump_polarion_testcase import parse_key_value_file, is_valid_http_url

# RHELTEST Test Case fields (create-rheltest-testcase skill / stage createmeta).
FIELD_ID = "customfield_10591"
FIELD_ASSIGNED_TEAM = "customfield_10606"
FIELD_URL = "customfield_10933"
FIELD_EXTERNAL_URL = "customfield_10766"
FIELD_TIER = "customfield_11177"
FIELD_ARCHITECTURE = "customfield_10772"

DEFAULT_PROJECT = "RHELTEST"
DEFAULT_ISSUE_TYPE = "Test Case"


class JiraError(RuntimeError):
    """Jira REST client or import error."""


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    verify_ssl: bool = True
    ca_bundle: str | None = None


@dataclass
class ImportResult:
    action: str  # created | updated | dry-run-create | dry-run-update
    issue_key: str | None
    match: str  # id | summary | none
    browse_url: str | None = None
    status: str | None = None
    status_applied: bool = False
    status_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "issue_key": self.issue_key,
            "match": self.match,
            "browse_url": self.browse_url,
            "status": self.status,
            "status_applied": self.status_applied,
            "status_warning": self.status_warning,
        }


def jira_config_from_env() -> JiraConfig:
    base = os.environ.get("JIRA_URL", "").strip().rstrip("/")
    email = (
        os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_USER") or ""
    ).strip()
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not base:
        raise JiraError(
            "set JIRA_URL (e.g. https://stage-redhat.atlassian.net)",
        )
    if not email or not token:
        raise JiraError("set JIRA_EMAIL (or JIRA_USER) and JIRA_API_TOKEN")
    verify_raw = os.environ.get("JIRA_VERIFY_SSL", "true").strip().lower()
    verify_ssl = verify_raw not in ("0", "false", "no", "off")
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
        "SSL_CERT_FILE",
    )
    return JiraConfig(
        base_url=base,
        email=email,
        api_token=token,
        verify_ssl=verify_ssl,
        ca_bundle=ca_bundle or None,
    )


def _ssl_context(verify_ssl: bool, ca_bundle: str | None) -> ssl.SSLContext | bool:
    if not verify_ssl:
        return False
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def _basic_auth_header(email: str, token: str) -> str:
    raw = base64.b64encode(f"{email}:{token}".encode()).decode("ascii")
    return f"Basic {raw}"


def jira_request(
    config: JiraConfig,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 60,
) -> Any:
    url = f"{config.base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": _basic_auth_header(config.email, config.api_token),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(
            request,
            context=_ssl_context(config.verify_ssl, config.ca_bundle),
            timeout=timeout,
        ) as response:
            raw = response.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001
            detail = ""
        raise JiraError(
            f"Jira {method} {path} failed: {exc.code} {exc.reason}"
            + (f": {detail}" if detail else ""),
        ) from exc
    except URLError as exc:
        raise JiraError(f"Jira HTTP transport error: {exc.reason}") from exc


def escape_jql_string(value: str) -> str:
    """Escape a value for use inside JQL double quotes."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


_LUCENE_SPECIAL_RE = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def escape_lucene_chars(value: str) -> str:
    """Escape Lucene reserved characters inside a JQL ``~`` phrase."""
    return _LUCENE_SPECIAL_RE.sub(r"\\\1", value)


# ---------------------------------------------------------------------------
# HTML → Atlassian Document Format (minimal)
# ---------------------------------------------------------------------------


def _text_node(text: str, *, marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return node


def _paragraph(inline: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not inline:
        return {"type": "paragraph", "content": []}
    return {"type": "paragraph", "content": inline}


class _HtmlToAdf(HTMLParser):
    """Convert a subset of HTML used in Polarion dumps into ADF."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._inline: list[dict[str, Any]] = []
        self._marks: list[dict[str, Any]] = []
        self._list_stack: list[dict[str, Any]] = []
        self._li_stack: list[dict[str, Any]] = []
        self._table: dict[str, Any] | None = None
        self._row: dict[str, Any] | None = None
        self._cell: dict[str, Any] | None = None
        self._heading_level: int | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"b", "strong"}:
            self._marks.append({"type": "strong"})
        elif tag in {"i", "em"}:
            self._marks.append({"type": "em"})
        elif tag == "code":
            self._marks.append({"type": "code"})
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href:
                self._marks.append({"type": "link", "attrs": {"href": href}})
        elif tag == "br":
            self._inline.append({"type": "hardBreak"})
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_paragraph()
            self._heading_level = int(tag[1])
        elif tag == "p":
            self._flush_paragraph()
        elif tag in {"ul", "ol"}:
            self._flush_paragraph()
            node = {
                "type": "bulletList" if tag == "ul" else "orderedList",
                "content": [],
            }
            self._list_stack.append(node)
        elif tag == "li":
            self._flush_paragraph()
            item = {"type": "listItem", "content": []}
            self._li_stack.append(item)
        elif tag == "table":
            self._flush_paragraph()
            self._table = {
                "type": "table",
                "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
                "content": [],
            }
        elif tag == "tr" and self._table is not None:
            self._row = {"type": "tableRow", "content": []}
        elif tag in {"td", "th"} and self._row is not None:
            self._flush_paragraph()
            self._cell = {
                "type": "tableHeader" if tag == "th" else "tableCell",
                "attrs": {},
                "content": [],
            }

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {"b", "strong", "i", "em", "code", "a"}:
            if self._marks:
                self._marks.pop()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = self._heading_level or int(tag[1])
            content = self._inline or [_text_node("")]
            self._emit(
                {
                    "type": "heading",
                    "attrs": {"level": level},
                    "content": content,
                }
            )
            self._inline = []
            self._heading_level = None
        elif tag == "p":
            self._flush_paragraph()
        elif tag == "li":
            self._flush_paragraph_into_li()
            if self._li_stack and self._list_stack:
                item = self._li_stack.pop()
                if not item["content"]:
                    item["content"] = [_paragraph()]
                self._list_stack[-1]["content"].append(item)
        elif tag in {"ul", "ol"}:
            self._flush_paragraph()
            if self._list_stack:
                node = self._list_stack.pop()
                self._emit(node)
        elif tag in {"td", "th"}:
            self._flush_paragraph_into_cell()
            if self._cell is not None and self._row is not None:
                if not self._cell["content"]:
                    self._cell["content"] = [_paragraph()]
                self._row["content"].append(self._cell)
            self._cell = None
        elif tag == "tr":
            if self._row is not None and self._table is not None:
                self._table["content"].append(self._row)
            self._row = None
        elif tag == "table":
            if self._table is not None:
                self._emit(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        # Preserve meaningful whitespace inside cells/inline; drop pure
        # indentation between block tags.
        if not data.strip() and not self._inline:
            return
        marks = list(self._marks) if self._marks else None
        self._inline.append(_text_node(data, marks=marks))

    def _emit(self, block: dict[str, Any]) -> None:
        if self._cell is not None:
            self._cell["content"].append(block)
        elif self._li_stack:
            self._li_stack[-1]["content"].append(block)
        else:
            self.blocks.append(block)

    def _flush_paragraph(self) -> None:
        if not self._inline:
            return
        para = _paragraph(self._inline)
        self._inline = []
        self._emit(para)

    def _flush_paragraph_into_li(self) -> None:
        if self._inline:
            self._flush_paragraph()

    def _flush_paragraph_into_cell(self) -> None:
        if self._inline:
            self._flush_paragraph()

    def close(self) -> None:  # type: ignore[override]
        self._flush_paragraph()
        super().close()


def html_to_adf(html: str) -> dict[str, Any]:
    """Convert HTML (or plain text) to an ADF document."""
    text = (html or "").strip()
    if not text:
        return {"type": "doc", "version": 1, "content": []}
    if "<" not in text:
        return plain_text_to_adf(text)
    parser = _HtmlToAdf()
    parser.feed(text)
    parser.close()
    content = parser.blocks or [_paragraph([_text_node(re.sub(r"<[^>]+>", "", text))])]
    return {"type": "doc", "version": 1, "content": content}


def plain_text_to_adf(text: str) -> dict[str, Any]:
    t = text.strip()
    if not t:
        return {"type": "doc", "version": 1, "content": []}
    paragraphs = t.split("\n\n") if "\n\n" in t else [t]
    content: list[dict[str, Any]] = []
    for para in paragraphs:
        lines = para.split("\n")
        inline: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            if i:
                inline.append({"type": "hardBreak"})
            inline.append(_text_node(line))
        content.append(_paragraph(inline))
    return {"type": "doc", "version": 1, "content": content}


# ---------------------------------------------------------------------------
# Dump → Jira fields
# ---------------------------------------------------------------------------


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def build_issue_fields(
    dump: dict[str, str],
    *,
    project_key: str,
    issue_type: str | None = None,
    issue_type_id: str | None = None,
    include_project_type: bool = True,
    assignee_account_id: str | None = None,
) -> dict[str, Any]:
    """Build Jira ``fields`` payload from a jira-format dump."""
    summary = dump.get("summary", "").strip()
    if not summary:
        raise JiraError("dump is missing required summary=")

    fields: dict[str, Any] = {"summary": summary}
    if include_project_type:
        fields["project"] = {"key": project_key}
        if issue_type_id:
            fields["issuetype"] = {"id": str(issue_type_id)}
        elif issue_type:
            fields["issuetype"] = {"name": issue_type}
        else:
            raise JiraError("issue type name or id is required to create an issue")

    description = dump.get("description", "")
    if description.strip():
        fields["description"] = html_to_adf(description)

    if assignee_account_id:
        fields["assignee"] = {"accountId": assignee_account_id}

    components = dump.get("components", "").strip()
    component_names = [name for name in split_csv(components) if name != "-"]
    if component_names:
        fields["components"] = [{"name": name} for name in component_names]

    labels = dump.get("labels", "").strip()
    if labels:
        fields["labels"] = split_csv(labels)

    team = dump.get("AssignedTeam", "").strip()
    if team:
        fields[FIELD_ASSIGNED_TEAM] = {"value": team}

    work_item_id = dump.get("ID", "").strip()
    if work_item_id:
        fields[FIELD_ID] = work_item_id

    url = dump.get("URL", "").strip()
    if url and is_valid_http_url(url):
        fields[FIELD_URL] = url

    external = dump.get("External issue URL", "").strip()
    if external:
        fields[FIELD_EXTERNAL_URL] = external

    tier = dump.get("Tier", "").strip()
    if tier:
        fields[FIELD_TIER] = {"value": tier}

    arch = dump.get("Architecture", "").strip()
    if arch:
        fields[FIELD_ARCHITECTURE] = [{"value": v} for v in split_csv(arch)]

    return fields


def list_createable_issue_types(
    config: JiraConfig,
    project_key: str,
) -> list[dict[str, str]]:
    """Return ``[{id, name}, ...]`` createable issue types for a project."""
    data = jira_request(
        config,
        "GET",
        "/rest/api/3/issue/createmeta",
        params={
            "projectKeys": project_key,
            "expand": "projects.issuetypes",
        },
    )
    types: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return types
    for project in data.get("projects") or []:
        if not isinstance(project, dict):
            continue
        if str(project.get("key") or "") != project_key:
            continue
        for itype in project.get("issuetypes") or []:
            if not isinstance(itype, dict):
                continue
            tid = itype.get("id")
            name = itype.get("name")
            if tid and name:
                types.append({"id": str(tid), "name": str(name)})
    return types


def resolve_issue_type(
    config: JiraConfig,
    *,
    project_key: str,
    issue_type: str,
) -> dict[str, str]:
    """Resolve ``issue_type`` name or id to a createable ``{id, name}``.

    Raises ``JiraError`` with available types when the requested type is not
    on the project's create screen / issue type scheme.
    """
    requested = issue_type.strip()
    if not requested:
        raise JiraError("issue type must not be empty")

    available = list_createable_issue_types(config, project_key)
    if not available:
        # Fall back to project issueTypes (may include non-createable).
        project = jira_request(
            config,
            "GET",
            f"/rest/api/3/project/{quote(project_key, safe='')}",
        )
        if isinstance(project, dict):
            for itype in project.get("issueTypes") or []:
                if isinstance(itype, dict) and itype.get("id") and itype.get("name"):
                    available.append(
                        {"id": str(itype["id"]), "name": str(itype["name"])},
                    )

    by_id = {t["id"]: t for t in available}
    by_name = {t["name"].casefold(): t for t in available}

    if requested in by_id:
        return by_id[requested]
    match = by_name.get(requested.casefold())
    if match:
        return match

    names = ", ".join(sorted({t["name"] for t in available})) or "(none)"
    raise JiraError(
        f"issue type {requested!r} is not available for creating issues in "
        f"project {project_key}. Available: {names}. "
        "Ask a Jira admin to add it to the project's issue type scheme "
        "(Test Case exists on the instance but may not be enabled for RHELTEST)."
    )


def find_user_account_id(config: JiraConfig, query: str) -> str | None:
    """Resolve a user query to accountId; None if not uniquely found."""
    q = query.strip()
    if not q:
        return None
    data = jira_request(
        config,
        "GET",
        "/rest/api/3/user/search",
        params={"query": q},
    )
    if not isinstance(data, list) or not data:
        return None
    want = q.lower()
    exact = [
        u
        for u in data
        if isinstance(u, dict)
        and (
            str(u.get("emailAddress") or "").strip().lower() == want
            or str(u.get("accountId") or "").strip() == q
            or str(u.get("displayName") or "").strip().lower() == want
        )
    ]
    pick = exact[0] if exact else (data[0] if len(data) == 1 else None)
    if not isinstance(pick, dict):
        return None
    aid = pick.get("accountId")
    return str(aid) if aid else None


def search_issues(
    config: JiraConfig,
    jql: str,
    *,
    fields: list[str],
    max_results: int = 20,
) -> list[dict[str, Any]]:
    payload = {
        "jql": jql,
        "maxResults": max_results,
        "fields": fields,
    }
    # Prefer enhanced search; fall back to classic GET search.
    try:
        data = jira_request(
            config,
            "POST",
            "/rest/api/3/search/jql",
            body=payload,
        )
    except JiraError:
        data = jira_request(
            config,
            "GET",
            "/rest/api/3/search",
            params={
                "jql": jql,
                "maxResults": str(max_results),
                "fields": ",".join(fields),
            },
        )
    if not isinstance(data, dict):
        return []
    issues = data.get("issues")
    return issues if isinstance(issues, list) else []


def find_by_work_item_id(
    config: JiraConfig,
    *,
    project_key: str,
    issue_type: str,
    work_item_id: str,
) -> list[dict[str, Any]]:
    # Phrase search with Lucene escaping so pytest-style IDs
    # (``::``, ``[]``, ``()``) still match; filter exact client-side.
    phrase = escape_jql_string(escape_lucene_chars(work_item_id))
    jql = (
        f'project = "{escape_jql_string(project_key)}" '
        f'AND issuetype = "{escape_jql_string(issue_type)}" '
        f'AND cf[10591] ~ "\\"{phrase}\\""'
    )
    issues = search_issues(
        config,
        jql,
        fields=["summary", FIELD_ID, "issuetype"],
        max_results=50,
    )
    exact: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        fields = issue.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        value = fields.get(FIELD_ID)
        if value is None:
            continue
        if str(value).strip() == work_item_id:
            exact.append(issue)
    return exact


def find_by_summary(
    config: JiraConfig,
    *,
    project_key: str,
    issue_type: str,
    summary: str,
) -> list[dict[str, Any]]:
    jql = (
        f'project = "{escape_jql_string(project_key)}" '
        f'AND issuetype = "{escape_jql_string(issue_type)}" '
        f'AND summary ~ "{escape_jql_string(summary)}"'
    )
    issues = search_issues(
        config,
        jql,
        fields=["summary", FIELD_ID, "issuetype"],
        max_results=50,
    )
    exact: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        fields = issue.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        if str(fields.get("summary") or "").strip() == summary:
            exact.append(issue)
    return exact


def create_issue(config: JiraConfig, fields: dict[str, Any]) -> dict[str, Any]:
    data = jira_request(
        config,
        "POST",
        "/rest/api/3/issue",
        body={"fields": fields},
    )
    if not isinstance(data, dict) or not data.get("key"):
        raise JiraError(f"create issue returned unexpected payload: {data!r}")
    return data


def update_issue(config: JiraConfig, issue_key: str, fields: dict[str, Any]) -> None:
    jira_request(
        config,
        "PUT",
        f"/rest/api/3/issue/{quote(issue_key, safe='')}",
        body={"fields": fields},
    )


def get_issue_status(config: JiraConfig, issue_key: str) -> str:
    data = jira_request(
        config,
        "GET",
        f"/rest/api/3/issue/{quote(issue_key, safe='')}",
        params={"fields": "status"},
    )
    if not isinstance(data, dict):
        return ""
    fields = data.get("fields") or {}
    if not isinstance(fields, dict):
        return ""
    status = fields.get("status") or {}
    if isinstance(status, dict):
        return str(status.get("name") or "")
    return ""


def list_transitions(config: JiraConfig, issue_key: str) -> list[dict[str, Any]]:
    data = jira_request(
        config,
        "GET",
        f"/rest/api/3/issue/{quote(issue_key, safe='')}/transitions",
    )
    if not isinstance(data, dict):
        return []
    transitions = data.get("transitions")
    return transitions if isinstance(transitions, list) else []


def transition_issue_to_status(
    config: JiraConfig,
    issue_key: str,
    target_status: str,
) -> tuple[bool, str | None]:
    """Transition ``issue_key`` so its status name matches ``target_status``.

    Returns ``(applied, warning)``. No-op success when already in target status.
    """
    target = target_status.strip()
    if not target:
        return False, None

    current = get_issue_status(config, issue_key)
    if current.casefold() == target.casefold():
        return True, None

    transitions = list_transitions(config, issue_key)
    match: dict[str, Any] | None = None
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        to = transition.get("to") or {}
        to_name = str(to.get("name") or "") if isinstance(to, dict) else ""
        if to_name.casefold() == target.casefold():
            match = transition
            break
    if match is None:
        available = sorted(
            {
                str((t.get("to") or {}).get("name") or t.get("name") or "")
                for t in transitions
                if isinstance(t, dict)
            }
            - {""}
        )
        avail = ", ".join(available) or "(none)"
        return False, (
            f"no transition to status {target!r} for {issue_key} "
            f"(current={current!r}; available destinations: {avail})"
        )

    transition_id = str(match.get("id") or "")
    if not transition_id:
        return False, f"transition to {target!r} has empty id for {issue_key}"

    jira_request(
        config,
        "POST",
        f"/rest/api/3/issue/{quote(issue_key, safe='')}/transitions",
        body={"transition": {"id": transition_id}},
    )
    return True, None


def browse_url(config: JiraConfig, issue_key: str) -> str:
    return f"{config.base_url}/browse/{issue_key}"


def resolve_match(
    config: JiraConfig,
    dump: dict[str, str],
    *,
    project_key: str,
    issue_type: str,
) -> tuple[str | None, str]:
    """Return (issue_key_or_none, match_reason).

    Prefer ``customfield_10591`` (dump ``ID``). When ``ID`` is present, never
    fall back to summary — parametrized tests often share the same title.
    Summary matching is only used when ``ID`` is absent.
    """
    work_item_id = dump.get("ID", "").strip()
    summary = dump.get("summary", "").strip()

    if work_item_id:
        matches = find_by_work_item_id(
            config,
            project_key=project_key,
            issue_type=issue_type,
            work_item_id=work_item_id,
        )
        if len(matches) > 1:
            keys = ", ".join(str(m.get("key")) for m in matches)
            raise JiraError(
                f"multiple Test Cases with ID={work_item_id!r}: {keys}",
            )
        if len(matches) == 1:
            return str(matches[0].get("key")), "id"
        return None, "none"

    if summary:
        matches = find_by_summary(
            config,
            project_key=project_key,
            issue_type=issue_type,
            summary=summary,
        )
        if len(matches) > 1:
            keys = ", ".join(str(m.get("key")) for m in matches)
            raise JiraError(
                f"multiple Test Cases with summary={summary!r}: {keys}",
            )
        if len(matches) == 1:
            return str(matches[0].get("key")), "summary"

    return None, "none"


def import_testcase(
    dump: dict[str, str],
    *,
    config: JiraConfig,
    project_key: str = DEFAULT_PROJECT,
    issue_type: str = DEFAULT_ISSUE_TYPE,
    dry_run: bool = False,
    skip_assignee: bool = False,
    skip_components: bool = False,
) -> ImportResult:
    """Match by customfield_10591 (ID) when present; otherwise by summary.
    When ID is set and no ID match exists, create a new issue (do not fall
    back to summary — parametrized tests often share titles).
    """
    issue_key, match = resolve_match(
        config,
        dump,
        project_key=project_key,
        issue_type=issue_type,
    )

    assignee_id = None
    if not skip_assignee:
        assignee_query = dump.get("assignee", "").strip()
        if assignee_query:
            assignee_id = find_user_account_id(config, assignee_query)

    issue_type_id: str | None = None
    if issue_key is None:
        # Validate createable type early (also for dry-run).
        resolved = resolve_issue_type(
            config,
            project_key=project_key,
            issue_type=issue_type,
        )
        issue_type_id = resolved["id"]

    fields = build_issue_fields(
        dump,
        project_key=project_key,
        issue_type=issue_type,
        issue_type_id=issue_type_id,
        include_project_type=issue_key is None,
        assignee_account_id=assignee_id,
    )
    if skip_components:
        fields.pop("components", None)

    # ``status`` is applied via workflow transition, not fields update.
    target_status = dump.get("status", "").strip() or None

    def _result(
        action: str,
        key: str | None,
        *,
        status_applied: bool = False,
        status_warning: str | None = None,
    ) -> ImportResult:
        return ImportResult(
            action=action,
            issue_key=key,
            match=match,
            browse_url=browse_url(config, key) if key else None,
            status=target_status,
            status_applied=status_applied,
            status_warning=status_warning,
        )

    if issue_key:
        if dry_run:
            return _result("dry-run-update", issue_key)
        update_issue(config, issue_key, fields)
        status_applied = False
        status_warning = None
        if target_status:
            status_applied, status_warning = transition_issue_to_status(
                config,
                issue_key,
                target_status,
            )
        return _result(
            "updated",
            issue_key,
            status_applied=status_applied,
            status_warning=status_warning,
        )

    if dry_run:
        return _result("dry-run-create", None)

    created = create_issue(config, fields)
    key = str(created["key"])
    status_applied = False
    status_warning = None
    if target_status:
        status_applied, status_warning = transition_issue_to_status(
            config,
            key,
            target_status,
        )
    return _result(
        "created",
        key,
        status_applied=status_applied,
        status_warning=status_warning,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import a dump-polarion-testcase --format jira file into Jira. "
            "Matches existing Test Cases by customfield_10591 (ID) first; "
            "when ID is set, summary is never used (parametrized titles collide). "
            "Summary match only if ID is absent. Updates on match, otherwise creates. "
            "Requires JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN."
        ),
    )
    parser.add_argument(
        "dump_file",
        type=Path,
        help="Path to key=value dump (jira format)",
    )
    parser.add_argument(
        "-P",
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Jira project key (default: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--issue-type",
        default=DEFAULT_ISSUE_TYPE,
        help=f'Issue type name (default: "{DEFAULT_ISSUE_TYPE}")',
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Search and report action without creating/updating",
    )
    parser.add_argument(
        "--skip-assignee",
        action="store_true",
        help="Do not set assignee (Polarion ids often do not match Jira)",
    )
    parser.add_argument(
        "--skip-components",
        action="store_true",
        help="Do not set components (avoids errors when names are missing)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dump_file.is_file():
        print(f"error: dump file not found: {args.dump_file}", file=sys.stderr)
        return 2

    try:
        dump = parse_key_value_file(args.dump_file)
        config = jira_config_from_env()
        result = import_testcase(
            dump,
            config=config,
            project_key=args.project,
            issue_type=args.issue_type,
            dry_run=args.dry_run,
            skip_assignee=args.skip_assignee,
            skip_components=args.skip_components,
        )
    except (JiraError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        key = result.issue_key or "(new)"
        print(f"{result.action}: {key} (match={result.match})")
        if result.status:
            if result.action.startswith("dry-run"):
                print(f"status: would set {result.status}")
            elif result.status_applied:
                print(f"status: {result.status}")
            elif result.status_warning:
                print(f"status warning: {result.status_warning}", file=sys.stderr)
        if result.browse_url:
            print(result.browse_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
