#!/usr/bin/env python3
"""Import Betelgeuse / IdM-CI Polarion XML into Jira RHELTEST.

Subcommands (Betelgeuse-shaped):

* ``test-case`` — Polarion *testcase importer* XML
  (``import-testcase.xml``) → jira-format dumps and/or Jira import
* ``test-run`` — Polarion *test-run importer* XML
  (``import-testrun.xml``) → jira-format dumps and/or Jira import

Also provides Jira REST import helpers used by ``import-jira-testcase`` /
``import-jira-testresult``.

Name is a pun on Betelgeuse.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
import ssl
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

import click


# ---------------------------------------------------------------------------
# Polarion testcase dump → Jira RHELTEST fields (from dump_polarion_testcase)
# ---------------------------------------------------------------------------

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
def ca_bundle_from_env() -> str | None:
    return os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
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

# RHELTEST Test Case fields (create-rheltest-testcase skill / stage createmeta).
FIELD_ID = "customfield_10591"
FIELD_ASSIGNED_TEAM = "customfield_10606"
FIELD_URL = "customfield_10933"
FIELD_EXTERNAL_URL = "customfield_10766"
FIELD_TIER = "customfield_11177"
FIELD_ARCHITECTURE = "customfield_10772"

DEFAULT_JIRA_URL = "https://stage-redhat.atlassian.net"
DEFAULT_PROJECT = "RHELTEST"
DEFAULT_ISSUE_TYPE = "Test Case"
DEFAULT_TESTRESULT_ISSUE_TYPE = "Test Result"
DEFAULT_TEST_CASE_TYPE = "Test Case"
FIELD_COMPOSE_VERSION = "customfield_11501"
FIELD_COMPONENT_FIX_VERSION = "customfield_10742"


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


def _jira_config_from_values(
    *,
    base_url: str,
    email: str,
    token: str,
) -> JiraConfig:
    verify_raw = os.environ.get("JIRA_VERIFY_SSL", "true").strip().lower()
    verify_ssl = verify_raw not in ("0", "false", "no", "off")
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
        "SSL_CERT_FILE",
    )
    return JiraConfig(
        base_url=base_url,
        email=email,
        api_token=token,
        verify_ssl=verify_ssl,
        ca_bundle=ca_bundle or None,
    )


def jira_config_from_env() -> JiraConfig:
    """Load Jira auth from ``JIRA_URL`` / ``JIRA_EMAIL`` / ``JIRA_API_TOKEN``."""
    base = os.environ.get("JIRA_URL", "").strip().rstrip("/")
    email = (os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_USER") or "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not base:
        raise JiraError(
            "set JIRA_URL (e.g. https://stage-redhat.atlassian.net)",
        )
    if not email or not token:
        raise JiraError("set JIRA_EMAIL (or JIRA_USER) and JIRA_API_TOKEN")
    return _jira_config_from_values(base_url=base, email=email, token=token)


def jira_config_from_idmci_env() -> JiraConfig:
    """Load Jira auth for IdM-CI / beetlejuice (``IDMCI_JIRA_*``, ``JIRA_*`` fallback)."""
    base = (
        (os.environ.get("IDMCI_JIRA_URL") or os.environ.get("JIRA_URL") or DEFAULT_JIRA_URL)
        .strip()
        .rstrip("/")
    )
    email = (
        os.environ.get("IDMCI_JIRA_EMAIL")
        or os.environ.get("JIRA_EMAIL")
        or os.environ.get("JIRA_USER")
        or ""
    ).strip()
    token = (
        os.environ.get("IDMCI_JIRA_API_TOKEN") or os.environ.get("JIRA_API_TOKEN") or ""
    ).strip()
    if not email or not token:
        raise JiraError(
            "set IDMCI_JIRA_EMAIL and IDMCI_JIRA_API_TOKEN (or JIRA_EMAIL / JIRA_API_TOKEN)",
        )
    return _jira_config_from_values(base_url=base, email=email, token=token)


def _jira_ssl_context(verify_ssl: bool, ca_bundle: str | None) -> ssl.SSLContext | bool:
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
            context=_jira_ssl_context(config.verify_ssl, config.ca_bundle),
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


def is_valid_http_url(value: str) -> bool:
    """True when *value* is an absolute http(s) URL."""
    text = value.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def normalize_architecture(value: str) -> str:
    """Map Polarion arch tokens to Jira Architecture option values."""
    text = value.strip().replace(" ", "")
    if not text:
        return text
    if text == "x8664":
        return "x86_64"
    return text


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


@dataclass
class TestResultImportResult(ImportResult):
    parent_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["parent_key"] = self.parent_key
        return payload


def find_parent_test_case(
    config: JiraConfig,
    *,
    project_key: str,
    test_case_id: str,
) -> str | None:
    """Return parent Test Case issue key for ``test_case_id`` (cf 10591)."""
    matches = find_by_work_item_id(
        config,
        project_key=project_key,
        issue_type=DEFAULT_TEST_CASE_TYPE,
        work_item_id=test_case_id,
    )
    if not matches:
        return None
    key = matches[0].get("key")
    return str(key) if key else None


def build_testresult_fields(
    dump: dict[str, str],
    *,
    project_key: str,
    issue_type_id: str,
    parent_key: str,
    assignee_account_id: str | None,
) -> dict[str, Any]:
    summary = dump.get("summary", "").strip()
    if not summary:
        raise JiraError("dump is missing summary")

    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"id": issue_type_id},
        "summary": summary,
        "parent": {"key": parent_key},
    }

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

    compose = dump.get("Compose Version", "").strip()
    if compose:
        fields[FIELD_COMPOSE_VERSION] = compose

    build = dump.get("Build", "").strip()
    if build:
        fields[FIELD_COMPONENT_FIX_VERSION] = build

    arch = dump.get("Architecture", "").strip()
    if arch:
        fields[FIELD_ARCHITECTURE] = [
            {"value": normalize_architecture(part)} for part in split_csv(arch) if part.strip()
        ]

    return fields


def import_testresult(
    dump: dict[str, str],
    *,
    config: JiraConfig,
    project_key: str,
    issue_type: str = DEFAULT_TESTRESULT_ISSUE_TYPE,
    dry_run: bool = False,
    skip_assignee: bool = False,
    skip_components: bool = False,
) -> TestResultImportResult:
    """Create a Test Result under the matching Test Case parent."""
    test_case_id = dump.get("TestCaseID", "").strip()
    if not test_case_id:
        raise JiraError("dump is missing TestCaseID (parent Test Case lookup id)")

    parent_key = find_parent_test_case(
        config,
        project_key=project_key,
        test_case_id=test_case_id,
    )
    if parent_key is None:
        raise JiraError(
            f"no Test Case with ID {test_case_id!r} in project {project_key}",
        )

    assignee_id: str | None = None
    if not skip_assignee:
        assignee_query = dump.get("assignee", "").strip()
        if assignee_query:
            assignee_id = find_user_account_id(config, assignee_query)

    resolved = resolve_issue_type(
        config,
        project_key=project_key,
        issue_type=issue_type,
    )
    fields = build_testresult_fields(
        dump,
        project_key=project_key,
        issue_type_id=resolved["id"],
        parent_key=parent_key,
        assignee_account_id=assignee_id,
    )
    if skip_components:
        fields.pop("components", None)

    target_status = dump.get("status", "").strip() or None

    def _result(
        action: str,
        key: str | None,
        *,
        status_applied: bool = False,
        status_warning: str | None = None,
    ) -> TestResultImportResult:
        return TestResultImportResult(
            action=action,
            issue_key=key,
            match="parent-id",
            browse_url=browse_url(config, key) if key else None,
            status=target_status,
            status_applied=status_applied,
            status_warning=status_warning,
            parent_key=parent_key,
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


GZIP_MAGIC = b"\x1f\x8b"

_HREF_RE = re.compile(
    r'href=["\']([^"\']*import-testcase\.xml)["\']',
    re.IGNORECASE,
)
_HREF_RUN_RE = re.compile(
    r'href=["\']([^"\']*import-testrun\.xml)["\']',
    re.IGNORECASE,
)

JIRA_TESTRUN_KEY_ORDER = (
    "summary",
    "TestCaseID",
    "status",
    "description",
    "assignee",
    "components",
    "labels",
    "AssignedTeam",
    "Architecture",
    "Compose Version",
    "Build",
    "Run title",
    "Logs URL",
)


class BeetlejuiceError(RuntimeError):
    """Parse / download / import error."""


def project_key_from_env() -> str:
    """Jira project from ``IDMCI_JIRA_PROJECT``, else ``RHELTEST``."""
    return os.environ.get("IDMCI_JIRA_PROJECT", "").strip() or DEFAULT_PROJECT


@dataclass
class ParsedTestcaseXml:
    """One Polarion testcase-importer XML document."""

    path: str
    project_id: str
    lookup_method: str
    lookup_field_id: str
    dry_run: bool
    cases: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CaseResult:
    source: str
    test_case_id: str
    summary: str
    dump_path: str | None = None
    import_result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedTestrunXml:
    """One Polarion test-run importer XML document."""

    path: str
    project_id: str
    lookup_method: str
    lookup_field_id: str
    dry_run: bool
    include_skipped: bool
    testrun_id: str
    testrun_title: str
    testrun_status: str
    custom_fields: dict[str, str] = field(default_factory=dict)
    results: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TestrunResult:
    source: str
    test_case_id: str
    summary: str
    status: str
    dump_path: str | None = None
    import_result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def maybe_decompress(data: bytes) -> bytes:
    """Return *data*, gunzipping when the payload is gzip-compressed."""
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def read_xml_bytes(path: Path) -> bytes:
    return maybe_decompress(path.read_bytes())


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def download_bytes(url: str, *, timeout: float = 120) -> bytes:
    """HTTP GET returning decompressed body bytes."""
    request = Request(url, headers={"Accept": "*/*"})
    try:
        with urlopen(
            request,
            context=_ssl_context(ca_bundle_from_env()),
            timeout=timeout,
        ) as response:
            return maybe_decompress(response.read())
    except HTTPError as exc:
        raise BeetlejuiceError(
            f"download failed: {exc.code} {exc.reason} for {url}",
        ) from exc
    except URLError as exc:
        raise BeetlejuiceError(f"download failed: {exc.reason} for {url}") from exc


def map_sst_team(value: str) -> str:
    """Map Polarion ``sst_idm_*`` poolteam values to Jira AssignedTeam.

    Example: ``sst_idm_sssd`` → ``rhel-idm-sssd``. Values that already look
    like Jira teams (``rhel-idm-…``) are left unchanged.
    """
    text = value.strip()
    if not text:
        return text
    if text.startswith("rhel-"):
        return text
    if text == "sst_idm":
        return "rhel-idm"
    match = re.fullmatch(r"sst_idm_(.+)", text, flags=re.IGNORECASE)
    if match:
        return f"rhel-idm-{match.group(1).lower()}"
    return text


def _element_text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    # ``itertext`` keeps nested markup text; unescape entities.
    parts = [unescape(t) for t in elem.itertext() if t]
    return "".join(parts).strip()


def _child_markup(elem: ET.Element | None) -> str:
    """Inner XML/text of an element (for HTML-ish description/setup bodies)."""
    if elem is None:
        return ""
    # Prefer serialized children when present (keeps nested tags), else text.
    children = list(elem)
    if not children:
        return unescape((elem.text or "").strip())
    chunks: list[str] = []
    if elem.text and elem.text.strip():
        chunks.append(unescape(elem.text))
    for child in children:
        chunks.append(ET.tostring(child, encoding="unicode"))
        if child.tail and child.tail.strip():
            chunks.append(unescape(child.tail))
    return "".join(chunks).strip()


def _custom_fields(testcase: ET.Element) -> dict[str, str]:
    fields: dict[str, str] = {}
    for cf in testcase.findall("./custom-fields/custom-field"):
        field_id = (cf.get("id") or "").strip()
        if not field_id:
            continue
        content = cf.get("content")
        if content is None:
            content = _element_text(cf)
        fields[field_id] = unescape(content).strip()
    return fields


def _hyperlinks(testcase: ET.Element) -> str:
    """Flatten hyperlinks to dump format ``role|uri,...``."""
    parts: list[str] = []
    for link in testcase.findall("./hyperlinks/hyperlink"):
        role = (link.get("role-id") or "").strip()
        uri = (link.get("uri") or "").strip()
        if not uri:
            continue
        if role:
            parts.append(f"{role}|{uri}")
        else:
            parts.append(uri)
    return ",".join(parts)


def _teststeps_to_pairs(testcase: ET.Element) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for index, step in enumerate(testcase.findall("./test-steps/test-step"), start=1):
        for col in step.findall("./test-step-column"):
            col_id = (col.get("id") or "").strip()
            if not col_id:
                continue
            # Columns often store HTML with escaped tags in the attribute-less
            # text node (``&lt;p&gt;...``); ElementTree already unescapes once.
            value = _child_markup(col) or _element_text(col)
            if not value:
                continue
            pairs[f"teststep.{index}.{col_id}"] = value
    return pairs


def _linked_work_items(testcase: ET.Element) -> str:
    """Serialize linked-work-items for description metadata."""
    parts: list[str] = []
    for item in testcase.findall("./linked-work-items/linked-work-item"):
        wid = (item.get("workitem-id") or "").strip()
        if not wid:
            continue
        role = (item.get("role-id") or "").strip()
        method = (item.get("lookup-method") or "").strip()
        bits = [wid]
        if role:
            bits.append(f"role={role}")
        if method:
            bits.append(f"lookup={method}")
        parts.append("|".join(bits))
    return ",".join(parts)


def testcase_element_to_pairs(
    testcase: ET.Element,
    *,
    project_id: str,
    map_team: bool = True,
    team_override: str = "",
) -> dict[str, str]:
    """Map one ``<testcase>`` element to Polarion-style key/value pairs."""
    case_id = (testcase.get("id") or "").strip()
    status = (testcase.get("status-id") or testcase.get("status") or "").strip()
    title = _element_text(testcase.find("title")) or case_id
    description = _child_markup(testcase.find("description"))
    custom = _custom_fields(testcase)

    pairs: dict[str, str] = {
        "project_id": project_id,
        "title": title,
        "type": "testcase",
    }
    if description:
        pairs["description"] = description
    if status:
        pairs["status"] = status

    # Lookup id → testCaseID (Jira customfield_10591 / dump ``ID``).
    # Prefer an explicit custom-field; otherwise use ``@id``.
    test_case_id = custom.pop("testCaseID", "").strip() or case_id
    if test_case_id:
        pairs["testCaseID"] = test_case_id

    for key, value in custom.items():
        if not value:
            continue
        pairs[key] = value

    if team_override.strip():
        pairs["subsystemteam"] = team_override.strip()
    elif map_team and pairs.get("subsystemteam"):
        pairs["subsystemteam"] = map_sst_team(pairs["subsystemteam"])

    hyperlinks = _hyperlinks(testcase)
    if hyperlinks:
        pairs["hyperlinks"] = hyperlinks

    pairs.update(_teststeps_to_pairs(testcase))

    linked = _linked_work_items(testcase)
    if linked:
        pairs["linked-work-items"] = linked

    return pairs


def parse_testcase_xml(
    data: bytes | str,
    *,
    source: str = "",
    map_team: bool = True,
    team_override: str = "",
) -> ParsedTestcaseXml:
    """Parse Polarion testcase-importer XML into Polarion-style pair dicts."""
    if isinstance(data, bytes):
        data = maybe_decompress(data).decode("utf-8")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BeetlejuiceError(f"invalid XML in {source or '<input>'}: {exc}") from exc

    tag = root.tag.split("}", 1)[-1]
    if tag != "testcases":
        raise BeetlejuiceError(
            f"expected root <testcases>, got <{tag}> in {source or '<input>'}",
        )

    props = {
        (p.get("name") or "").strip(): (p.get("value") or "").strip()
        for p in root.findall("./properties/property")
        if (p.get("name") or "").strip()
    }
    project_id = (root.get("project-id") or props.get("polarion-project-id") or "").strip()
    lookup_method = props.get("lookup-method", "").strip() or "name"
    lookup_field_id = (
        props.get(
            "polarion-custom-lookup-method-field-id",
            "",
        ).strip()
        or "testCaseID"
    )
    dry_raw = props.get("dry-run", "false").strip().lower()
    dry_run = dry_raw in {"1", "true", "yes"}

    cases: list[dict[str, str]] = []
    for testcase in root.findall("testcase"):
        cases.append(
            testcase_element_to_pairs(
                testcase,
                project_id=project_id,
                map_team=map_team,
                team_override=team_override,
            )
        )

    return ParsedTestcaseXml(
        path=source,
        project_id=project_id,
        lookup_method=lookup_method,
        lookup_field_id=lookup_field_id,
        dry_run=dry_run,
        cases=cases,
    )


def pairs_to_jira_dump(pairs: dict[str, str]) -> dict[str, str]:
    """Convert Polarion-style pairs to jira-format dump keys."""
    return polarion_pairs_to_jira(pairs, polarion_url="")


def dump_filename_for_id(work_item_id: str) -> str:
    """Filesystem-safe name derived from testCaseID."""
    cleaned = re.sub(r"[^\w.\-]+", "_", work_item_id, flags=re.UNICODE)
    cleaned = cleaned.strip("._") or "testcase"
    return f"{cleaned[:200]}.properties"


def write_jira_dump(
    dump: dict[str, str],
    path: Path,
    *,
    key_order: tuple[str, ...] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        format_key_value(dump, key_order=key_order or JIRA_KEY_ORDER),
        encoding="utf-8",
    )


def find_local_testcase_xmls(path: Path) -> list[Path]:
    """Resolve a file or directory to one or more ``*import-testcase.xml`` paths."""
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise BeetlejuiceError(f"path not found: {path}")

    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in ("import-testcase.xml", "*import-testcase.xml"):
        for match in sorted(path.glob(pattern)):
            if match.is_file() and match not in seen:
                found.append(match)
                seen.add(match)
        for match in sorted(path.rglob(pattern)):
            if match.is_file() and match not in seen:
                found.append(match)
                seen.add(match)
    if not found:
        raise BeetlejuiceError(
            f"no *import-testcase.xml under {path}",
        )
    return found


def parse_directory_index_for_testcase_xmls(html: str, base_url: str) -> list[str]:
    """Extract ``*import-testcase.xml`` hrefs from an artifacts directory listing."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if href.startswith("?") or href.startswith("#"):
            continue
        full = urljoin(base_url if base_url.endswith("/") else base_url + "/", href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def resolve_inputs(target: str) -> list[tuple[str, bytes]]:
    """Return ``[(source_label, xml_bytes), ...]`` for a local path or URL."""
    parsed = urlparse(target)
    if parsed.scheme in {"http", "https"}:
        url = target.strip()
        if url.rstrip("/").endswith(".xml") or "import-testcase.xml" in url:
            return [(url, download_bytes(url))]
        # Treat as polarion/ directory listing.
        listing_url = url if url.endswith("/") else url + "/"
        html = download_bytes(listing_url).decode("utf-8", errors="replace")
        xml_urls = parse_directory_index_for_testcase_xmls(html, listing_url)
        if not xml_urls:
            # Fall back to the conventional filename.
            fallback = urljoin(listing_url, "import-testcase.xml")
            return [(fallback, download_bytes(fallback))]
        results: list[tuple[str, bytes]] = []
        for xml_url in xml_urls:
            results.append((xml_url, download_bytes(xml_url)))
        return results

    path = Path(target).expanduser()
    return [(str(p), read_xml_bytes(p)) for p in find_local_testcase_xmls(path)]


def apply_dump_overrides(
    dump: dict[str, str],
    *,
    tier: str = "",
    architecture: str = "",
    labels_extra: str = "",
) -> dict[str, str]:
    out = dict(dump)
    if tier.strip():
        out["Tier"] = tier.strip()
    if architecture.strip():
        out["Architecture"] = architecture.strip()
    if labels_extra.strip():
        existing = out.get("labels", "")
        merged = [part.strip() for part in f"{existing},{labels_extra}".split(",") if part.strip()]
        # Preserve order, unique.
        seen: list[str] = []
        for label in merged:
            if label not in seen:
                seen.append(label)
        out["labels"] = ",".join(seen)
    return out


def process_cases(
    documents: list[ParsedTestcaseXml],
    *,
    output_dir: Path | None,
    do_import: bool,
    jira_config: JiraConfig | None,
    project_key: str,
    issue_type: str,
    dry_run: bool,
    skip_assignee: bool,
    skip_components: bool,
    tier: str = "",
    architecture: str = "",
    labels_extra: str = "",
    limit: int | None = None,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    count = 0
    for doc in documents:
        for pairs in doc.cases:
            if limit is not None and count >= limit:
                return results
            count += 1
            test_case_id = pairs.get("testCaseID") or pairs.get("title") or f"case-{count}"
            try:
                dump = apply_dump_overrides(
                    pairs_to_jira_dump(pairs),
                    tier=tier,
                    architecture=architecture,
                    labels_extra=labels_extra,
                )
                if not dump.get("summary", "").strip():
                    raise BeetlejuiceError("mapped dump is missing summary")

                dump_path: Path | None = None
                if output_dir is not None:
                    dump_path = output_dir / dump_filename_for_id(test_case_id)
                    write_jira_dump(dump, dump_path)

                import_payload: dict[str, Any] | None = None
                if do_import:
                    if jira_config is None:
                        raise BeetlejuiceError("Jira config required for --import")
                    result: ImportResult = import_testcase(
                        dump,
                        config=jira_config,
                        project_key=project_key,
                        issue_type=issue_type,
                        dry_run=dry_run,
                        skip_assignee=skip_assignee,
                        skip_components=skip_components,
                    )
                    import_payload = result.to_dict()

                results.append(
                    CaseResult(
                        source=doc.path,
                        test_case_id=test_case_id,
                        summary=dump.get("summary", ""),
                        dump_path=str(dump_path) if dump_path else None,
                        import_result=import_payload,
                    )
                )
            except (BeetlejuiceError, JiraError, ValueError, OSError) as exc:
                results.append(
                    CaseResult(
                        source=doc.path,
                        test_case_id=test_case_id,
                        summary=pairs.get("title", ""),
                        error=str(exc),
                    )
                )
    return results


def _properties_dict(parent: ET.Element) -> dict[str, str]:
    props: dict[str, str] = {}
    for prop in parent.findall("./properties/property"):
        name = (prop.get("name") or "").strip()
        if not name:
            continue
        value = (prop.get("value") or "").strip()
        if value:
            props[name] = unescape(value)
    return props


def _testcase_properties(testcase: ET.Element) -> dict[str, str]:
    return _properties_dict(testcase)


def _junit_nodeid(testcase: ET.Element) -> str:
    classname = (testcase.get("classname") or "").strip()
    name = (testcase.get("name") or "").strip()
    if classname and name:
        return f"{classname}::{name}"
    return name or classname


def _junit_outcome(testcase: ET.Element) -> tuple[str, str]:
    """Return (Jira status name, detail text)."""
    failure = testcase.find("failure")
    if failure is not None:
        message = (failure.get("message") or "").strip()
        body = _element_text(failure)
        detail = message or body
        return "FAIL", detail
    error = testcase.find("error")
    if error is not None:
        message = (error.get("message") or "").strip()
        body = _element_text(error)
        detail = message or body
        return "FAIL", detail
    if testcase.find("skipped") is not None:
        skipped = testcase.find("skipped")
        detail = ""
        if skipped is not None:
            detail = (skipped.get("message") or _element_text(skipped)).strip()
        return "Blocked", detail
    return "PASS", ""


def _iter_junit_testcases(root: ET.Element) -> list[ET.Element]:
    tag = root.tag.split("}", 1)[-1]
    if tag == "testsuites":
        cases: list[ET.Element] = []
        for suite in root.findall("testsuite"):
            cases.extend(suite.findall("testcase"))
        return cases
    if tag == "testsuite":
        return list(root.findall("testcase"))
    return []


def _polarion_custom_fields(props: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in props.items():
        if key.startswith("polarion-custom-"):
            out[key.removeprefix("polarion-custom-")] = value
    return out


def _run_metadata_html(
    custom_fields: dict[str, str],
    *,
    testrun_title: str,
    testrun_id: str,
    testrun_status: str,
    project_id: str,
) -> str:
    rows: list[tuple[str, str]] = [
        ("Run title", testrun_title),
        ("Run id", testrun_id),
        ("Run status", testrun_status),
        ("Project", project_id),
    ]
    for key in sorted(custom_fields):
        rows.append((key, custom_fields[key]))
    parts = ["<table>", "<tr><th>Field</th><th>Value</th></tr>"]
    for label, value in rows:
        if not value:
            continue
        parts.append(f"<tr><td>{label}</td><td>{value}</td></tr>")
    parts.append("</table>")
    return "".join(parts)


def testrun_result_to_jira_dump(
    result: dict[str, str],
    *,
    run_meta: dict[str, str],
    map_team: bool = True,
    team_override: str = "",
) -> dict[str, str]:
    """Map one parsed test-run result to a Test Result dump."""
    dump: dict[str, str] = {
        "summary": result.get("summary", ""),
        "TestCaseID": result.get("test_case_id", ""),
        "status": result.get("status", ""),
    }
    description_parts: list[str] = []
    if run_meta.get("metadata_html"):
        description_parts.append(run_meta["metadata_html"])
    detail = result.get("detail", "").strip()
    if detail:
        description_parts.append(f"<p><strong>Detail</strong></p><pre>{detail}</pre>")
    if description_parts:
        dump["description"] = "\n".join(description_parts)

    component = run_meta.get("component", "").strip()
    if component:
        dump["components"] = component

    team = team_override.strip() or run_meta.get("poolteam", "").strip()
    if team:
        dump["AssignedTeam"] = map_sst_team(team) if map_team else team

    arch = run_meta.get("arch", "").strip()
    if arch:
        dump["Architecture"] = normalize_architecture(arch)

    compose = run_meta.get("composeid", "").strip()
    if compose:
        dump["Compose Version"] = compose

    build = run_meta.get("build", "").strip()
    if build:
        dump["Build"] = build

    assignee = run_meta.get("assignee", "").strip()
    if assignee:
        dump["assignee"] = assignee

    logs = run_meta.get("logs", "").strip()
    if logs:
        dump["Logs URL"] = logs

    title = run_meta.get("testrun_title", "").strip()
    if title:
        dump["Run title"] = title

    labels = run_meta.get("labels", "").strip()
    if labels:
        dump["labels"] = labels

    return dump


def parse_testrun_xml(
    data: bytes | str,
    *,
    source: str = "",
) -> ParsedTestrunXml:
    """Parse Polarion test-run importer XML (JUnit ``testsuites``)."""
    if isinstance(data, bytes):
        data = maybe_decompress(data).decode("utf-8")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BeetlejuiceError(f"invalid XML in {source or '<input>'}: {exc}") from exc

    tag = root.tag.split("}", 1)[-1]
    if tag not in {"testsuites", "testsuite"}:
        raise BeetlejuiceError(
            f"expected root <testsuites> or <testsuite>, got <{tag}> in {source or '<input>'}",
        )

    props = _properties_dict(root)
    project_id = (props.get("polarion-project-id") or "").strip()
    lookup_method = props.get("polarion-lookup-method", "").strip() or "custom"
    lookup_field_id = (
        props.get("polarion-custom-lookup-method-field-id", "").strip() or "testCaseID"
    )
    dry_raw = props.get("polarion-dry-run", "false").strip().lower()
    dry_run = dry_raw in {"1", "true", "yes"}
    include_raw = props.get("polarion-include-skipped", "true").strip().lower()
    include_skipped = include_raw not in {"0", "false", "no"}

    custom = _polarion_custom_fields(props)
    results: list[dict[str, str]] = []
    for testcase in _iter_junit_testcases(root):
        tc_props = _testcase_properties(testcase)
        test_case_id = tc_props.get("polarion-testcase-id", "").strip()
        if not test_case_id:
            test_case_id = _junit_nodeid(testcase)
        status, detail = _junit_outcome(testcase)
        if status == "Blocked" and not include_skipped:
            continue
        summary = test_case_id or _junit_nodeid(testcase) or "test-result"
        results.append(
            {
                "test_case_id": test_case_id,
                "summary": summary[:255],
                "status": status,
                "detail": detail,
                "nodeid": _junit_nodeid(testcase),
            }
        )

    return ParsedTestrunXml(
        path=source,
        project_id=project_id,
        lookup_method=lookup_method,
        lookup_field_id=lookup_field_id,
        dry_run=dry_run,
        include_skipped=include_skipped,
        testrun_id=props.get("polarion-testrun-id", "").strip(),
        testrun_title=props.get("polarion-testrun-title", "").strip(),
        testrun_status=props.get("polarion-testrun-status-id", "").strip(),
        custom_fields=custom,
        results=results,
    )


def find_local_testrun_xmls(path: Path) -> list[Path]:
    """Resolve a file or directory to one or more ``*import-testrun.xml`` paths."""
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise BeetlejuiceError(f"path not found: {path}")

    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in ("import-testrun.xml", "*import-testrun.xml"):
        for match in sorted(path.glob(pattern)):
            if match.is_file() and match not in seen:
                found.append(match)
                seen.add(match)
        for match in sorted(path.rglob(pattern)):
            if match.is_file() and match not in seen:
                found.append(match)
                seen.add(match)
    if not found:
        raise BeetlejuiceError(f"no *import-testrun.xml under {path}")
    return found


def parse_directory_index_for_testrun_xmls(html: str, base_url: str) -> list[str]:
    """Extract ``*import-testrun.xml`` hrefs from an artifacts directory listing."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _HREF_RUN_RE.finditer(html):
        href = match.group(1).strip()
        if href.startswith("?") or href.startswith("#"):
            continue
        full = urljoin(base_url if base_url.endswith("/") else base_url + "/", href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def resolve_testrun_inputs(target: str) -> list[tuple[str, bytes]]:
    """Return ``[(source_label, xml_bytes), ...]`` for a local path or URL."""
    parsed = urlparse(target)
    if parsed.scheme in {"http", "https"}:
        url = target.strip()
        if url.rstrip("/").endswith(".xml") or "import-testrun.xml" in url:
            return [(url, download_bytes(url))]
        listing_url = url if url.endswith("/") else url + "/"
        html = download_bytes(listing_url).decode("utf-8", errors="replace")
        xml_urls = parse_directory_index_for_testrun_xmls(html, listing_url)
        if not xml_urls:
            fallback = urljoin(listing_url, "import-testrun.xml")
            return [(fallback, download_bytes(fallback))]
        return [(xml_url, download_bytes(xml_url)) for xml_url in xml_urls]

    path = Path(target).expanduser()
    return [(str(p), read_xml_bytes(p)) for p in find_local_testrun_xmls(path)]


def run_meta_for_document(doc: ParsedTestrunXml) -> dict[str, str]:
    meta = dict(doc.custom_fields)
    meta["testrun_title"] = doc.testrun_title
    meta["testrun_id"] = doc.testrun_id
    meta["testrun_status"] = doc.testrun_status
    meta["metadata_html"] = _run_metadata_html(
        doc.custom_fields,
        testrun_title=doc.testrun_title,
        testrun_id=doc.testrun_id,
        testrun_status=doc.testrun_status,
        project_id=doc.project_id,
    )
    return meta


def process_testrun_results(
    documents: list[ParsedTestrunXml],
    *,
    output_dir: Path | None,
    do_import: bool,
    jira_config: JiraConfig | None,
    project_key: str,
    issue_type: str,
    dry_run: bool,
    skip_assignee: bool,
    skip_components: bool,
    map_team: bool = True,
    team_override: str = "",
    labels_extra: str = "",
    limit: int | None = None,
) -> list[TestrunResult]:
    results: list[TestrunResult] = []
    count = 0
    for doc in documents:
        run_meta = run_meta_for_document(doc)
        if labels_extra.strip():
            existing = run_meta.get("labels", "")
            merged = [
                part.strip() for part in f"{existing},{labels_extra}".split(",") if part.strip()
            ]
            seen: list[str] = []
            for label in merged:
                if label not in seen:
                    seen.append(label)
            run_meta["labels"] = ",".join(seen)

        for item in doc.results:
            if limit is not None and count >= limit:
                return results
            count += 1
            test_case_id = item.get("test_case_id") or item.get("summary") or f"result-{count}"
            try:
                dump = testrun_result_to_jira_dump(
                    item,
                    run_meta=run_meta,
                    map_team=map_team,
                    team_override=team_override,
                )
                if not dump.get("summary", "").strip():
                    raise BeetlejuiceError("mapped dump is missing summary")
                if not dump.get("TestCaseID", "").strip():
                    raise BeetlejuiceError("mapped dump is missing TestCaseID")

                dump_path: Path | None = None
                if output_dir is not None:
                    dump_path = output_dir / dump_filename_for_id(test_case_id)
                    write_jira_dump(
                        dump,
                        dump_path,
                        key_order=JIRA_TESTRUN_KEY_ORDER,
                    )

                import_payload: dict[str, Any] | None = None
                if do_import:
                    if jira_config is None:
                        raise BeetlejuiceError("Jira config required for --import")
                    imported: TestResultImportResult = import_testresult(
                        dump,
                        config=jira_config,
                        project_key=project_key,
                        issue_type=issue_type,
                        dry_run=dry_run,
                        skip_assignee=skip_assignee,
                        skip_components=skip_components,
                    )
                    import_payload = imported.to_dict()

                results.append(
                    TestrunResult(
                        source=doc.path,
                        test_case_id=test_case_id,
                        summary=dump.get("summary", ""),
                        status=dump.get("status", ""),
                        dump_path=str(dump_path) if dump_path else None,
                        import_result=import_payload,
                    )
                )
            except (BeetlejuiceError, JiraError, ValueError, OSError) as exc:
                results.append(
                    TestrunResult(
                        source=doc.path,
                        test_case_id=test_case_id,
                        summary=item.get("summary", ""),
                        status=item.get("status", ""),
                        error=str(exc),
                    )
                )
    return results


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
)
def cli() -> None:
    """Import Betelgeuse / IdM-CI Polarion XML into Jira RHELTEST.

    Subcommands mirror Betelgeuse: test-case and test-run (import-testcase.xml /
    import-testrun.xml).
    """


@cli.command("test-case")
@click.argument("target")
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Write one jira-format key=value dump per testcase into this directory",
)
@click.option(
    "--import",
    "do_import",
    is_flag=True,
    help=(
        "Create/update Jira Test Cases "
        "(requires IDMCI_JIRA_URL / IDMCI_JIRA_EMAIL / IDMCI_JIRA_API_TOKEN)"
    ),
)
@click.option(
    "-P",
    "--project",
    default=None,
    help=f"Jira project key (default: IDMCI_JIRA_PROJECT or {DEFAULT_PROJECT})",
)
@click.option(
    "--issue-type",
    default=DEFAULT_ISSUE_TYPE,
    show_default=True,
    help="Issue type name",
)
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    help="With --import, search and report without creating/updating",
)
@click.option(
    "--skip-assignee",
    is_flag=True,
    help="Do not set assignee on import",
)
@click.option(
    "--skip-components",
    is_flag=True,
    help="Do not set components on import",
)
@click.option(
    "--team",
    default="",
    help="Override subsystemteam / AssignedTeam for all cases",
)
@click.option(
    "--no-map-sst-team",
    is_flag=True,
    help="Do not map Polarion sst_idm_* values to rhel-idm-* AssignedTeam",
)
@click.option(
    "--tier",
    default="",
    help="Set Jira Tier (0–3) on all dumps/imports",
)
@click.option(
    "--architecture",
    default="",
    help="Set Jira Architecture (comma-separated) on all dumps/imports",
)
@click.option(
    "--label",
    multiple=True,
    help="Extra label to add (repeatable)",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process at most N testcases (useful for dry-runs)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print results as JSON",
)
def test_case_cmd(
    target: str,
    output: Path | None,
    do_import: bool,
    project: str,
    issue_type: str,
    dry_run: bool,
    skip_assignee: bool,
    skip_components: bool,
    team: str,
    no_map_sst_team: bool,
    tier: str,
    architecture: str,
    label: tuple[str, ...],
    limit: int | None,
    as_json: bool,
) -> None:
    """Read import-testcase.xml and dump and/or push Test Cases to Jira.

    TARGET is a local import-testcase.xml, a directory containing them, or an
    http(s) URL to the XML / polarion/ artifacts directory.
    """
    if output is None and not do_import:
        raise click.UsageError(
            "specify -o/--output and/or --import (nothing to do otherwise)",
        )

    try:
        inputs = resolve_inputs(target)
        documents = [
            parse_testcase_xml(
                data,
                source=label_src,
                map_team=not no_map_sst_team,
                team_override=team,
            )
            for label_src, data in inputs
        ]
        if not any(doc.cases for doc in documents):
            raise BeetlejuiceError("no <testcase> elements found")

        jira_config: JiraConfig | None = None
        if do_import:
            jira_config = jira_config_from_idmci_env()
        project_key = (project or "").strip() or project_key_from_env()

        results = process_cases(
            documents,
            output_dir=output,
            do_import=do_import,
            jira_config=jira_config,
            project_key=project_key,
            issue_type=issue_type,
            dry_run=dry_run,
            skip_assignee=skip_assignee,
            skip_components=skip_components,
            tier=tier,
            architecture=architecture,
            labels_extra=",".join(label),
            limit=limit,
        )
    except (BeetlejuiceError, JiraError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    errors = [r for r in results if r.error]
    if as_json:
        click.echo(
            json.dumps(
                {
                    "documents": len(documents),
                    "cases": len(results),
                    "errors": len(errors),
                    "results": [r.to_dict() for r in results],
                },
                indent=2,
            )
        )
    else:
        total_in = sum(len(d.cases) for d in documents)
        click.echo(
            f"parsed {len(documents)} XML file(s), {total_in} testcase(s); "
            f"processed {len(results)} (errors={len(errors)})"
        )
        for result in results:
            if result.error:
                click.echo(
                    f"error: {result.test_case_id}: {result.error}",
                    err=True,
                )
                continue
            bits = [result.test_case_id, result.summary]
            if result.dump_path:
                bits.append(f"dump={result.dump_path}")
            if result.import_result:
                action = result.import_result.get("action")
                key = result.import_result.get("issue_key") or "(new)"
                bits.append(f"{action}:{key}")
                browse = result.import_result.get("browse_url")
                if browse:
                    bits.append(browse)
            click.echo(" | ".join(bits))

    if errors:
        raise SystemExit(1)


@cli.command("test-run")
@click.argument("target")
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Write one jira-format key=value dump per result into this directory",
)
@click.option(
    "--import",
    "do_import",
    is_flag=True,
    help=(
        "Create Jira Test Results "
        "(requires IDMCI_JIRA_URL / IDMCI_JIRA_EMAIL / IDMCI_JIRA_API_TOKEN)"
    ),
)
@click.option(
    "-P",
    "--project",
    default=None,
    help=f"Jira project key (default: IDMCI_JIRA_PROJECT or {DEFAULT_PROJECT})",
)
@click.option(
    "--issue-type",
    default=DEFAULT_TESTRESULT_ISSUE_TYPE,
    show_default=True,
    help="Issue type name",
)
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    help="With --import, resolve parents and report without creating",
)
@click.option(
    "--skip-assignee",
    is_flag=True,
    help="Do not set assignee on import",
)
@click.option(
    "--skip-components",
    is_flag=True,
    help="Do not set components on import",
)
@click.option(
    "--team",
    default="",
    help="Override poolteam / AssignedTeam for all results",
)
@click.option(
    "--no-map-sst-team",
    is_flag=True,
    help="Do not map Polarion sst_idm_* values to rhel-idm-* AssignedTeam",
)
@click.option(
    "--label",
    multiple=True,
    help="Extra label to add (repeatable)",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process at most N results (useful for dry-runs)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print results as JSON",
)
def test_run_cmd(
    target: str,
    output: Path | None,
    do_import: bool,
    project: str,
    issue_type: str,
    dry_run: bool,
    skip_assignee: bool,
    skip_components: bool,
    team: str,
    no_map_sst_team: bool,
    label: tuple[str, ...],
    limit: int | None,
    as_json: bool,
) -> None:
    """Read import-testrun.xml and dump and/or push Test Results to Jira.

    TARGET is a local import-testrun.xml, a directory containing them, or an
    http(s) URL to the XML / polarion/ artifacts directory. Each JUnit
    ``<testcase>`` becomes one Test Result linked to the parent Test Case
    matched by ``TestCaseID`` (Polarion ``polarion-testcase-id``).
    """
    if output is None and not do_import:
        raise click.UsageError(
            "specify -o/--output and/or --import (nothing to do otherwise)",
        )

    try:
        inputs = resolve_testrun_inputs(target)
        documents = [parse_testrun_xml(data, source=label_src) for label_src, data in inputs]
        if not any(doc.results for doc in documents):
            raise BeetlejuiceError("no <testcase> elements found")

        jira_config: JiraConfig | None = None
        if do_import:
            jira_config = jira_config_from_idmci_env()
        project_key = (project or "").strip() or project_key_from_env()

        results = process_testrun_results(
            documents,
            output_dir=output,
            do_import=do_import,
            jira_config=jira_config,
            project_key=project_key,
            issue_type=issue_type,
            dry_run=dry_run,
            skip_assignee=skip_assignee,
            skip_components=skip_components,
            map_team=not no_map_sst_team,
            team_override=team,
            labels_extra=",".join(label),
            limit=limit,
        )
    except (BeetlejuiceError, JiraError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    errors = [r for r in results if r.error]
    if as_json:
        click.echo(
            json.dumps(
                {
                    "documents": len(documents),
                    "results": len(results),
                    "errors": len(errors),
                    "items": [r.to_dict() for r in results],
                },
                indent=2,
            )
        )
    else:
        total_in = sum(len(d.results) for d in documents)
        click.echo(
            f"parsed {len(documents)} XML file(s), {total_in} result(s); "
            f"processed {len(results)} (errors={len(errors)})"
        )
        for result in results:
            if result.error:
                click.echo(
                    f"error: {result.test_case_id}: {result.error}",
                    err=True,
                )
                continue
            bits = [result.status, result.test_case_id, result.summary]
            if result.dump_path:
                bits.append(f"dump={result.dump_path}")
            if result.import_result:
                action = result.import_result.get("action")
                key = result.import_result.get("issue_key") or "(new)"
                parent = result.import_result.get("parent_key")
                bits.append(f"{action}:{key}")
                if parent:
                    bits.append(f"parent={parent}")
                browse = result.import_result.get("browse_url")
                if browse:
                    bits.append(browse)
            click.echo(" | ".join(bits))

    if errors:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="beetlejuice", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
