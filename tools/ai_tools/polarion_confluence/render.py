#!/usr/bin/env python3
"""Render Polarion dump docs to Confluence storage + markdown.

Heading work items become section headings with stable project WI-id anchors.
Requirements link to dedicated Confluence pages when imported.
Test cases link to stage RHELTEST Jira summary search; Polarion id kept as fallback.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

_WI_MACRO_RE = re.compile(
    r"module-workitem;params=id=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_HEADING_TAG_RE = re.compile(r"<h([1-6])\b", re.IGNORECASE)
_RTE_LINK_RE = re.compile(
    r"<span\b[^>]*\bpolarion-rte-link\b[^>]*></span>",
    re.IGNORECASE,
)
_TOC_RE = re.compile(
    r"<div\b[^>]*polarion_wiki macro name=toc[^>]*>\s*</div>",
    re.IGNORECASE,
)
_SELECTION_RE = re.compile(
    r'href="([^"]*[?&]selection=([A-Za-z0-9_-]+)[^"]*)"',
    re.IGNORECASE,
)
_POLARION_WI_HREF_RE = re.compile(
    r'href="([^"]*/polarion/#/project/[^"]*workitem\?id=([A-Za-z0-9_-]+)[^"]*)"',
    re.IGNORECASE,
)


@dataclass
class WorkItem:
    id: str
    type: str | None
    title: str
    description_html: str
    outline: str | None

    @property
    def is_heading(self) -> bool:
        return (self.type or "").lower() == "heading"


@dataclass
class HeadingTarget:
    """Where a Polarion heading id should land in Confluence."""

    workitem_id: str
    title: str
    page_url: str | None  # None = same-page / unknown page yet
    space_id: str
    document_name: str


def load_workitems(doc_dir: Path) -> dict[str, WorkItem]:
    out: dict[str, WorkItem] = {}
    wi_dir = doc_dir / "workitems"
    if not wi_dir.is_dir():
        return out
    for path in wi_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        attrs = (payload.get("data") or {}).get("attributes") or {}
        wi_id = attrs.get("id") or path.stem
        desc = attrs.get("description")
        if isinstance(desc, dict):
            desc_html = desc.get("value") or ""
        elif isinstance(desc, str):
            desc_html = desc
        else:
            desc_html = ""
        out[wi_id] = WorkItem(
            id=wi_id,
            type=attrs.get("type"),
            title=attrs.get("title") or wi_id,
            description_html=desc_html,
            outline=attrs.get("outlineNumber"),
        )
    return out


def build_heading_index(
    dump_dir: Path,
    page_map: dict[str, str] | None = None,
) -> dict[str, HeadingTarget]:
    """Map heading work-item ids → Confluence page URL (from import state page_map).

    page_map keys are ``space/document_name`` → page URL.
    """
    page_map = page_map or {}
    index: dict[str, HeadingTarget] = {}
    docs_root = dump_dir / "documents"
    for meta_path in docs_root.rglob("meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        space_id = meta["space_id"]
        document_name = meta["document_name"]
        key = f"{space_id}/{document_name}"
        page_url = page_map.get(key)
        for wi in load_workitems(meta_path.parent).values():
            if not wi.is_heading:
                continue
            index[wi.id] = HeadingTarget(
                workitem_id=wi.id,
                title=wi.title,
                page_url=page_url,
                space_id=space_id,
                document_name=document_name,
            )
    return index


def heading_level(wi: WorkItem, part_content: str | None = None) -> int:
    if part_content:
        match = _HEADING_TAG_RE.search(part_content)
        if match:
            return int(match.group(1))
    if wi.outline:
        return min(wi.outline.count(".") + 1, 6)
    return 2


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</div\s*>", "\n", text)
    text = re.sub(r"(?i)</h[1-6]\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


DEFAULT_JIRA_BASE = "https://stage-redhat.atlassian.net"
DEFAULT_POLARION_URL = "https://polarion.engineering.redhat.com"
RHELTEST_PROJECT = "RHELTEST"


def jira_base_url() -> str:
    # RHELTEST Test Cases live on stage; do not inherit prod JIRA_URL.
    return (os.environ.get("RHELTEST_JIRA_URL") or DEFAULT_JIRA_BASE).rstrip("/")


def polarion_base_url() -> str:
    return (os.environ.get("POLARION_URL") or DEFAULT_POLARION_URL).rstrip("/")


def polarion_workitem_url(
    wi_id: str,
    *,
    project_id: str,
    polarion_base: str | None = None,
) -> str:
    """Polarion portal URL for a work item (fallback when RHELTEST TC missing)."""
    base = (polarion_base or polarion_base_url()).rstrip("/")
    return f"{base}/polarion/#/project/{project_id}/workitem?id={wi_id}"


def jql_escape_phrase(text: str) -> str:
    """Escape a phrase for use inside a JQL quoted Lucene phrase."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def rheltest_summary_search_url(summary: str, *, jira_base: str | None = None) -> str:
    """Jira issue navigator URL: RHELTEST Test Case whose summary matches *summary*.

    Issues may not exist yet; the query is the forward-looking link. Polarion
    ids stay in the rendered citation as the fallback identity.
    """
    base = (jira_base or jira_base_url()).rstrip("/")
    phrase = jql_escape_phrase(summary.strip() or "")
    # Phrase match on summary (exact title when the Test Case is created later).
    jql = f'project = {RHELTEST_PROJECT} AND issuetype = "Test Case" AND summary ~ "\\"{phrase}\\""'
    return f"{base}/issues/?jql={quote(jql)}"


def is_testcase(wi: WorkItem) -> bool:
    return (wi.type or "").lower() == "testcase"


def testcase_storage(
    wi: WorkItem,
    *,
    project_id: str,
    jira_base: str | None = None,
    polarion_base: str | None = None,
) -> str:
    """Test case → RHELTEST summary search; Polarion id links to Polarion as fallback."""
    return f"<p>{testcase_inline_html(wi, project_id=project_id, jira_base=jira_base, polarion_base=polarion_base)}</p>"


def testcase_inline_html(
    wi: WorkItem,
    *,
    project_id: str,
    jira_base: str | None = None,
    polarion_base: str | None = None,
) -> str:
    title = wi.title or wi.id
    search_url = rheltest_summary_search_url(title, jira_base=jira_base)
    polarion_url = polarion_workitem_url(wi.id, project_id=project_id, polarion_base=polarion_base)
    return (
        f'<a href="{escape_html(search_url)}"><strong>{escape_html(title)}</strong></a>'
        f' (Polarion <a href="{escape_html(polarion_url)}">'
        f"<code>{escape_html(wi.id)}</code></a>)"
    )


def testcase_markdown(
    wi: WorkItem,
    *,
    project_id: str,
    jira_base: str | None = None,
    polarion_base: str | None = None,
) -> str:
    title = wi.title or wi.id
    search_url = rheltest_summary_search_url(title, jira_base=jira_base)
    polarion_url = polarion_workitem_url(wi.id, project_id=project_id, polarion_base=polarion_base)
    return f"**[{title}]({search_url})** (Polarion [`{wi.id}`]({polarion_url}))\n"


def confluence_anchor(anchor_id: str) -> str:
    # Stable Polarion work-item id as Confluence anchor name.
    return (
        '<ac:structured-macro ac:name="anchor" ac:schema-version="1">'
        f'<ac:parameter ac:name="">{escape_html(anchor_id)}</ac:parameter>'
        "</ac:structured-macro>"
    )


def confluence_toc() -> str:
    return (
        '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
        '<ac:parameter ac:name="printable">true</ac:parameter>'
        "</ac:structured-macro>"
    )


def heading_storage(wi: WorkItem, level: int) -> str:
    """Section heading with CERT-* anchor; title only (id is the anchor, not visible)."""
    tag = f"h{min(max(level, 1), 6)}"
    title = escape_html(wi.title)
    # id= on the heading is a second, plain-HTML fallback beside the anchor macro.
    return f'{confluence_anchor(wi.id)}<{tag} id="{escape_html(wi.id)}">{title}</{tag}>'


def workitem_storage(
    wi: WorkItem,
    *,
    project_id: str,
    requirement_pages: dict[str, str] | None = None,
) -> str:
    """Non-heading work item citation.

    - Requirements → dedicated Confluence page when imported.
    - Test cases → RHELTEST Jira summary search; Polarion id links to Polarion.
    """
    if is_testcase(wi):
        return testcase_storage(wi, project_id=project_id)

    wtype = escape_html(wi.type or "workitem")
    wid = escape_html(wi.id)
    title = escape_html(wi.title)
    req_url = (requirement_pages or {}).get(wi.id) if wi.type == "requirement" else None
    if req_url:
        body = (
            f'<p><a href="{escape_html(req_url)}"><code>{wid}</code></a> '
            f'({wtype}) — <strong><a href="{escape_html(req_url)}">{title}</a></strong></p>'
        )
        return body
    body = f"<p><code>{wid}</code> ({wtype}) — <strong>{title}</strong></p>"
    desc = wi.description_html.strip()
    if desc and html_to_text(desc) and html_to_text(desc) != wi.title:
        body += f"<div>{desc}</div>"
    return body


def heading_markdown(wi: WorkItem, level: int) -> str:
    hashes = "#" * min(max(level, 1), 6)
    # Markdown heading + explicit HTML anchor for local preview / md→html paths.
    return f'<a id="{wi.id}"></a>\n{hashes} {wi.title}\n<!-- polarion-heading-anchor: {wi.id} -->\n'


def workitem_markdown(
    wi: WorkItem,
    *,
    project_id: str,
    requirement_pages: dict[str, str] | None = None,
) -> str:
    if is_testcase(wi):
        return testcase_markdown(wi, project_id=project_id)
    req_url = (requirement_pages or {}).get(wi.id) if wi.type == "requirement" else None
    if req_url:
        return f"[`{wi.id}`]({req_url}) ({wi.type or 'workitem'}) — **[{wi.title}]({req_url})**\n"
    lines = [f"`{wi.id}` ({wi.type or 'workitem'}) — **{wi.title}**", ""]
    body = html_to_text(wi.description_html)
    if body and body != wi.title:
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _href_for_heading(
    wi_id: str,
    heading_index: dict[str, HeadingTarget],
    *,
    current_key: str | None,
) -> str | None:
    target = heading_index.get(wi_id)
    if not target:
        return None
    target_key = f"{target.space_id}/{target.document_name}"
    if target.page_url and current_key and target_key != current_key:
        return f"{target.page_url}#{wi_id}"
    return f"#{wi_id}"


def _href_for_requirement(
    wi_id: str,
    requirement_pages: dict[str, str] | None,
) -> str | None:
    if not requirement_pages:
        return None
    return requirement_pages.get(wi_id)


def rewrite_prose_html(
    html: str,
    *,
    workitems: dict[str, WorkItem],
    heading_index: dict[str, HeadingTarget],
    current_key: str | None,
    project_id: str,
    requirement_pages: dict[str, str] | None = None,
    requirement_titles: dict[str, str] | None = None,
) -> str:
    """Rewrite Polarion TOC / rte-links / selection links inside prose HTML."""

    def rte_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        id_match = re.search(r'data-item-id="([A-Za-z0-9_-]+)"', tag, re.I)
        if not id_match:
            return ""
        wi_id = id_match.group(1)
        wi = workitems.get(wi_id) or (
            WorkItem(wi_id, None, wi_id, "", None)
            if wi_id not in heading_index
            else WorkItem(
                wi_id,
                "heading",
                heading_index[wi_id].title,
                "",
                None,
            )
        )
        # Prefer heading index even if local workitems missed the type.
        if wi_id in heading_index or wi.is_heading:
            title = escape_html(heading_index[wi_id].title if wi_id in heading_index else wi.title)
            href = _href_for_heading(wi_id, heading_index, current_key=current_key)
            if href:
                return f'<a href="{escape_html(href)}">{title}</a>'
            return f"<strong>{title}</strong>"

        # Requirements → dedicated Confluence page.
        req_href = None
        if (wi.type or "").lower() == "requirement" or wi_id in (requirement_pages or {}):
            req_href = _href_for_requirement(wi_id, requirement_pages)
        if req_href:
            label = (requirement_titles or {}).get(wi_id) or wi.title or wi_id
            if label == wi_id:
                return f'<a href="{escape_html(req_href)}"><code>{escape_html(wi_id)}</code></a>'
            return (
                f'<a href="{escape_html(req_href)}"><code>{escape_html(wi_id)}</code> '
                f"{escape_html(label)}</a>"
            )

        # Test cases → RHELTEST summary search; Polarion id links to Polarion.
        if is_testcase(wi):
            return testcase_inline_html(wi, project_id=project_id)

        # Other work items: citation, not a section jump.
        label = escape_html(wi.title if wi.title != wi_id else wi_id)
        return f"<code>{escape_html(wi_id)}</code> ({escape_html(wi.type or 'workitem')}) {label}"

    html = _RTE_LINK_RE.sub(rte_repl, html)
    html = _TOC_RE.sub(confluence_toc(), html)

    def selection_repl(match: re.Match[str]) -> str:
        full_href, wi_id = match.group(1), match.group(2)
        if wi_id in heading_index:
            href = _href_for_heading(wi_id, heading_index, current_key=current_key)
            return f'href="{escape_html(href or full_href)}"'
        req_href = _href_for_requirement(wi_id, requirement_pages)
        if req_href:
            return f'href="{escape_html(req_href)}"'
        wi = workitems.get(wi_id)
        if wi and is_testcase(wi):
            return f'href="{escape_html(rheltest_summary_search_url(wi.title or wi.id))}"'
        return f'href="{escape_html(full_href)}"'

    html = _SELECTION_RE.sub(selection_repl, html)

    def polarion_wi_repl(match: re.Match[str]) -> str:
        full_href, wi_id = match.group(1), match.group(2)
        if wi_id in heading_index:
            href = _href_for_heading(wi_id, heading_index, current_key=current_key)
            return f'href="{escape_html(href or full_href)}"'
        req_href = _href_for_requirement(wi_id, requirement_pages)
        if req_href:
            return f'href="{escape_html(req_href)}"'
        wi = workitems.get(wi_id)
        if wi and is_testcase(wi):
            return f'href="{escape_html(rheltest_summary_search_url(wi.title or wi.id))}"'
        return match.group(0)

    return _POLARION_WI_HREF_RE.sub(polarion_wi_repl, html)


def extract_workitem_ids(html: str | None) -> list[str]:
    if not html:
        return []
    return _WI_MACRO_RE.findall(html)


def render_document(
    doc_dir: Path,
    *,
    heading_index: dict[str, HeadingTarget] | None = None,
    page_map: dict[str, str] | None = None,
    requirement_pages: dict[str, str] | None = None,
    requirement_titles: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return (storage_html, markdown) for one dumped document directory."""
    meta = json.loads((doc_dir / "meta.json").read_text(encoding="utf-8"))
    space_id = meta["space_id"]
    document_name = meta["document_name"]
    project_id = meta.get("project_id") or ""
    current_key = f"{space_id}/{document_name}"
    workitems = load_workitems(doc_dir)
    parts_path = doc_dir / "parts.json"
    parts_payload = (
        json.loads(parts_path.read_text(encoding="utf-8")) if parts_path.exists() else {}
    )
    parts = parts_payload.get("data") or []
    req_pages = requirement_pages or {}
    req_titles = requirement_titles or {}

    # Enrich local workitems with requirement type/title from the requirements dump.
    for wi_id in list(workitems):
        if wi_id not in req_pages and wi_id not in req_titles:
            continue
        wi = workitems[wi_id]
        title = req_titles.get(wi_id) or wi.title
        workitems[wi_id] = WorkItem(
            wi.id,
            "requirement",
            title,
            wi.description_html,
            wi.outline,
        )

    local_headings = {
        wi_id: HeadingTarget(
            workitem_id=wi_id,
            title=wi.title,
            page_url=(page_map or {}).get(current_key),
            space_id=space_id,
            document_name=document_name,
        )
        for wi_id, wi in workitems.items()
        if wi.is_heading
    }
    h_index = dict(heading_index or {})
    h_index.update(local_headings)

    storage_parts: list[str] = []
    md_parts: list[str] = []
    doc_title = meta.get("title") or document_name
    # Avoid duplicating the Polarion document-title heading in markdown.
    wrote_md_title = False

    # Soft dump fallback: parts API failed — render homePageContent.html instead.
    if not parts:
        hpc_path = doc_dir / "homePageContent.html"
        hpc = hpc_path.read_text(encoding="utf-8") if hpc_path.exists() else ""
        if hpc.strip():
            note = (
                "<p><em>Polarion parts API unavailable for this document; "
                "body rendered from homePageContent (may lack expanded work-item "
                "titles).</em></p>"
            )
            rewritten = rewrite_prose_html(
                hpc,
                workitems=workitems,
                heading_index=h_index,
                current_key=current_key,
                project_id=project_id,
                requirement_pages=req_pages,
                requirement_titles=req_titles,
            )
            storage_parts.append(note + rewritten)
            md_parts.append(f"# {doc_title}")
            md_parts.append("")
            md_parts.append("_Soft dump: rendered from homePageContent (parts API failed)._")
            md_parts.append("")
            text = html_to_text(rewritten)
            if text:
                md_parts.append(text)
                md_parts.append("")
            return "\n".join(storage_parts), "\n".join(md_parts).rstrip() + "\n"

    for part in parts:
        attrs = part.get("attributes") or {}
        part_type = (attrs.get("type") or "").lower()
        content = attrs.get("content") or ""

        if part_type == "toc" or (part_type == "normal" and "macro name=toc" in content):
            storage_parts.append(confluence_toc())
            md_parts.append("<!-- toc -->\n")
            continue

        if part_type == "heading":
            rel = ((part.get("relationships") or {}).get("workItem") or {}).get("data") or {}
            wi_full = rel.get("id") or ""
            wi_id = wi_full.split("/", 1)[-1] if wi_full else ""
            if not wi_id:
                ids = extract_workitem_ids(content)
                wi_id = ids[0] if ids else ""
            wi = workitems.get(wi_id)
            if wi is None and wi_id:
                # Heading part without dumped WI payload — still anchor by id.
                title_guess = html_to_text(content) or wi_id
                wi = WorkItem(wi_id, "heading", title_guess, "", None)
            if wi and wi.is_heading:
                level = heading_level(wi, content)
                storage_parts.append(heading_storage(wi, level))
                if not wrote_md_title and level == 1:
                    wrote_md_title = True
                md_parts.append(heading_markdown(wi, level))
            elif wi:
                # Mis-typed: part says heading but WI is not — treat as WI citation.
                storage_parts.append(
                    workitem_storage(wi, project_id=project_id, requirement_pages=req_pages)
                )
                md_parts.append(
                    workitem_markdown(wi, project_id=project_id, requirement_pages=req_pages)
                )
            continue

        if part_type == "workitem":
            rel = ((part.get("relationships") or {}).get("workItem") or {}).get("data") or {}
            wi_full = rel.get("id") or ""
            wi_id = wi_full.split("/", 1)[-1] if wi_full else ""
            if not wi_id:
                ids = extract_workitem_ids(content)
                wi_id = ids[0] if ids else ""
            wi = workitems.get(wi_id)
            if wi is None and wi_id:
                # Prefer requirement typing when we have a dedicated page.
                wtype = "requirement" if wi_id in req_pages else None
                wi = WorkItem(wi_id, wtype, wi_id, "", None)
            elif wi and wi_id in req_pages and (wi.type or "").lower() != "requirement":
                # Some dumps may miss type; treat known requirement ids as requirements.
                wi = WorkItem(wi.id, "requirement", wi.title, wi.description_html, wi.outline)
            if wi and wi.is_heading:
                # Some docs embed headings as workitem parts.
                level = heading_level(wi, content)
                storage_parts.append(heading_storage(wi, level))
                if not wrote_md_title and level == 1:
                    wrote_md_title = True
                md_parts.append(heading_markdown(wi, level))
            elif wi:
                if not wrote_md_title:
                    md_parts.append(f"# {doc_title}")
                    md_parts.append("")
                    wrote_md_title = True
                storage_parts.append(
                    workitem_storage(wi, project_id=project_id, requirement_pages=req_pages)
                )
                md_parts.append(
                    workitem_markdown(wi, project_id=project_id, requirement_pages=req_pages)
                )
            continue

        # Prose / other
        if not content.strip():
            continue
        if not wrote_md_title:
            md_parts.append(f"# {doc_title}")
            md_parts.append("")
            wrote_md_title = True
        embedded = extract_workitem_ids(content)
        if embedded and re.fullmatch(r"\s*(?:<div[^>]*>\s*)+(?:</div>\s*)+", content, re.I):
            # Part is only work-item macros.
            for wi_id in embedded:
                wi = workitems.get(wi_id)
                if wi is None and wi_id in req_pages:
                    wi = WorkItem(wi_id, "requirement", wi_id, "", None)
                if wi and wi.is_heading:
                    level = heading_level(wi, content)
                    storage_parts.append(heading_storage(wi, level))
                    md_parts.append(heading_markdown(wi, level))
                elif wi:
                    if wi_id in req_pages and (wi.type or "").lower() != "requirement":
                        wi = WorkItem(
                            wi.id,
                            "requirement",
                            wi.title,
                            wi.description_html,
                            wi.outline,
                        )
                    storage_parts.append(
                        workitem_storage(wi, project_id=project_id, requirement_pages=req_pages)
                    )
                    md_parts.append(
                        workitem_markdown(wi, project_id=project_id, requirement_pages=req_pages)
                    )
            continue

        rewritten = rewrite_prose_html(
            content,
            workitems=workitems,
            heading_index=h_index,
            current_key=current_key,
            project_id=project_id,
            requirement_pages=req_pages,
            requirement_titles=req_titles,
        )
        # Drop empty polarion template shells.
        if html_to_text(rewritten) or "ac:structured-macro" in rewritten:
            storage_parts.append(rewritten)
            text = html_to_text(rewritten)
            if text:
                md_parts.append(text)
                md_parts.append("")

    if not wrote_md_title:
        md_parts.insert(0, "")
        md_parts.insert(0, f"# {doc_title}")

    storage = "\n".join(storage_parts)
    markdown = "\n".join(md_parts).rstrip() + "\n"
    return storage, markdown


def page_map_from_import_state(state_path: Path) -> dict[str, str]:
    if not state_path.exists():
        return {}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for key, info in (state.get("pages") or {}).items():
        url = info.get("url")
        if url:
            out[key] = url
    return out


def requirement_pages_from_import_state(state_path: Path) -> dict[str, str]:
    """Map requirement work-item id → Confluence page URL."""
    if not state_path.exists():
        return {}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for wi_id, info in (state.get("requirements") or {}).items():
        url = info.get("url")
        if url:
            out[wi_id] = url
    return out


def load_requirement_titles(dump_dir: Path) -> dict[str, str]:
    """Map requirement id → title from the requirements dump."""
    out: dict[str, str] = {}
    req_root = dump_dir / "requirements"
    if not req_root.is_dir():
        return out
    for meta_path in req_root.glob("*/meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        wi_id = meta.get("workitem_id") or meta_path.parent.name
        title = meta.get("title")
        if wi_id and title:
            out[wi_id] = title
    return out


def render_requirement_page(req_dir: Path) -> tuple[str, str]:
    """Return (storage_html, markdown) for a dumped requirement directory."""
    meta = json.loads((req_dir / "meta.json").read_text(encoding="utf-8"))
    wi_id = meta["workitem_id"]
    title = meta.get("title") or wi_id
    desc_path = req_dir / "description.html"
    desc = desc_path.read_text(encoding="utf-8") if desc_path.exists() else ""
    md_path = req_dir / "content.md"
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else f"# {title}\n"

    rows = [
        ("ID", f"<code>{escape_html(wi_id)}</code>"),
        ("Type", "requirement"),
        ("Status", escape_html(str(meta.get("status") or "n/a"))),
        ("Severity", escape_html(str(meta.get("severity") or "n/a"))),
        ("Priority", escape_html(str(meta.get("priority") or "n/a"))),
    ]
    if meta.get("outlineNumber"):
        rows.append(("Outline", escape_html(str(meta["outlineNumber"]))))
    if meta.get("reqtype"):
        rows.append(("Req type", escape_html(str(meta["reqtype"]))))
    if meta.get("source_url"):
        src = escape_html(meta["source_url"])
        rows.append(("Polarion", f'<a href="{src}">{src}</a>'))

    table = (
        "<table><tbody>"
        + "".join(f"<tr><th>{escape_html(k)}</th><td>{v}</td></tr>" for k, v in rows)
        + "</tbody></table>"
    )
    storage = (
        f"{confluence_anchor(wi_id)}"
        f'<h1 id="{escape_html(wi_id)}">{escape_html(title)}</h1>\n'
        f"{table}\n"
        f"<h2>Description</h2>\n"
        f"{desc or '<p><em>No description.</em></p>'}"
    )
    return storage, md
