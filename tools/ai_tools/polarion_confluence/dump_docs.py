#!/usr/bin/env python3
"""Dump Polarion project documents for Confluence re-import."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import click

DEFAULT_URL = "https://polarion.engineering.redhat.com"
PROJECT_ID = "CERT"
PAGE_SIZE = 100
FIELDS_DOC = "@basic,title,type,status,updated,created,homePageContent,moduleFolder"
FIELDS_WI = "id,title,type,status,description,outlineNumber"


@dataclass
class DocRef:
    space_id: str
    document_name: str
    title: str | None = None
    doc_type: str | None = None
    status: str | None = None
    updated: str | None = None


class PolarionClient:
    """Thin Polarion REST v1 client using POLARION_TOKEN."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self._wi_cache: dict[str, dict[str, Any]] = {}

    def _request(
        self,
        path: str,
        *,
        accept: str = "application/json",
        raw: bool = False,
    ) -> Any:
        url = f"{self.base}{path}"
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": accept,
            },
        )
        try:
            with urlopen(req, timeout=120) as resp:
                body = resp.read()
                if raw:
                    return body
                if not body:
                    return {}
                return json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Request failed for {url}: {exc}") from exc

    def list_documents(self, project_id: str) -> list[DocRef]:
        docs: list[DocRef] = []
        page = 1
        while True:
            path = (
                f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
                f"/documents?page%5Bsize%5D={PAGE_SIZE}&page%5Bnumber%5D={page}"
                f"&fields%5Bdocuments%5D={quote(FIELDS_DOC, safe=',@')}"
            )
            payload = self._request(path)
            for item in payload.get("data") or []:
                attrs = item.get("attributes") or {}
                doc_id = item.get("id") or ""
                # id is PROJECT/SPACE/NAME — name may contain '/' rarely; split once.
                parts = doc_id.split("/", 2)
                if len(parts) != 3:
                    click.echo(f"skip malformed document id: {doc_id}", err=True)
                    continue
                _, space_id, document_name = parts
                docs.append(
                    DocRef(
                        space_id=space_id,
                        document_name=document_name,
                        title=attrs.get("title"),
                        doc_type=attrs.get("type"),
                        status=attrs.get("status"),
                        updated=attrs.get("updated"),
                    )
                )
            total = (payload.get("meta") or {}).get("totalCount")
            if total is not None and len(docs) >= int(total):
                break
            if not (payload.get("links") or {}).get("next"):
                break
            page += 1
        return docs

    def get_project_name(self, project_id: str) -> str:
        path = (
            f"/polarion/rest/v1/projects/{quote(project_id, safe='')}?fields%5Bprojects%5D=@basic"
        )
        payload = self._request(path)
        attrs = (payload.get("data") or {}).get("attributes") or {}
        return attrs.get("name") or project_id

    def get_document(self, project_id: str, space_id: str, document_name: str) -> dict:
        path = (
            f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
            f"/spaces/{quote(space_id, safe='')}"
            f"/documents/{quote(document_name, safe='')}"
            f"?fields%5Bdocuments%5D={quote(FIELDS_DOC, safe=',@')}"
        )
        return self._request(path)

    def list_parts(
        self, project_id: str, space_id: str, document_name: str
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        page = 1
        while True:
            path = (
                f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
                f"/spaces/{quote(space_id, safe='')}"
                f"/documents/{quote(document_name, safe='')}"
                f"/parts?page%5Bsize%5D={PAGE_SIZE}&page%5Bnumber%5D={page}"
                f"&fields%5Bdocument_parts%5D=@all"
            )
            payload = self._request(path)
            batch = payload.get("data") or []
            parts.extend(batch)
            total = (payload.get("meta") or {}).get("totalCount")
            if total is not None and len(parts) >= int(total):
                break
            if not (payload.get("links") or {}).get("next"):
                break
            page += 1
        return parts

    def get_workitem(self, project_id: str, workitem_id: str) -> dict[str, Any]:
        cache_key = f"{project_id}/{workitem_id}"
        if cache_key in self._wi_cache:
            return self._wi_cache[cache_key]
        # REST id form is PROJECT/WORKITEM-ID for nested routes sometimes;
        # collection uses bare CERT-123 under /projects/CERT/workitems/CERT-123
        path = (
            f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
            f"/workitems/{quote(workitem_id, safe='')}"
            f"?fields%5Bworkitems%5D={quote(FIELDS_WI, safe=',')}"
        )
        payload = self._request(path)
        self._wi_cache[cache_key] = payload
        return payload

    def list_attachments(
        self, project_id: str, space_id: str, document_name: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            path = (
                f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
                f"/spaces/{quote(space_id, safe='')}"
                f"/documents/{quote(document_name, safe='')}"
                f"/attachments?page%5Bsize%5D={PAGE_SIZE}&page%5Bnumber%5D={page}"
                f"&fields%5Bdocument_attachments%5D=@all"
            )
            payload = self._request(path)
            batch = payload.get("data") or []
            items.extend(batch)
            if not (payload.get("links") or {}).get("next"):
                break
            page += 1
        return items

    def download_attachment(
        self,
        project_id: str,
        space_id: str,
        document_name: str,
        attachment_id: str,
    ) -> bytes:
        path = (
            f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
            f"/spaces/{quote(space_id, safe='')}"
            f"/documents/{quote(document_name, safe='')}"
            f"/attachments/{quote(attachment_id, safe='')}/content"
        )
        return self._request(path, accept="*/*", raw=True)


def safe_segment(name: str) -> str:
    """Filesystem-safe path segment; keep readability."""
    cleaned = name.replace("/", "_").replace("\0", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "_empty"


_WI_MACRO_RE = re.compile(
    r"module-workitem;params=id=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def extract_workitem_ids(html: str | None) -> list[str]:
    if not html:
        return []
    return _WI_MACRO_RE.findall(html)


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
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def description_value(attrs: dict[str, Any]) -> tuple[str | None, str]:
    desc = attrs.get("description")
    if isinstance(desc, dict):
        return desc.get("type"), desc.get("value") or ""
    if isinstance(desc, str):
        return "text/plain", desc
    return None, ""


def append_workitem_md(lines: list[str], wi_id: str, workitems: dict[str, dict[str, Any]]) -> None:
    wi = workitems.get(wi_id) or {}
    wi_attrs = (wi.get("data") or {}).get("attributes") or {}
    wi_title = wi_attrs.get("title") or wi_id or "work item"
    _, desc_html = description_value(wi_attrs)
    body = html_to_text(desc_html)
    lines.append(f"**{wi_title}** (`{wi_id}`)")
    lines.append("")
    if body and body != wi_title:
        lines.append(body)
        lines.append("")


def build_markdown(
    title: str,
    parts: list[dict[str, Any]],
    workitems: dict[str, dict[str, Any]],
) -> str:
    lines = [f"# {title}", ""]
    for part in parts:
        attrs = part.get("attributes") or {}
        part_type = attrs.get("type") or ""
        level = int(attrs.get("level") or 0)
        content = attrs.get("content") or ""

        if part_type == "heading":
            embedded = extract_workitem_ids(content)
            if embedded:
                for wi_id in embedded:
                    append_workitem_md(lines, wi_id, workitems)
                continue
            heading = html_to_text(content) or content.strip()
            prefix = "#" * min(level + 2, 6)
            lines.append(f"{prefix} {heading}")
            lines.append("")
            continue

        if part_type == "workitem":
            rel = ((part.get("relationships") or {}).get("workItem") or {}).get("data") or {}
            wi_full_id = rel.get("id") or ""
            # id like CERT/CERT-12056
            wi_id = wi_full_id.split("/", 1)[-1] if wi_full_id else ""
            if wi_id:
                append_workitem_md(lines, wi_id, workitems)
            continue

        # prose / other part types — expand any embedded work-item macros
        embedded = extract_workitem_ids(content)
        if embedded:
            for wi_id in embedded:
                append_workitem_md(lines, wi_id, workitems)
            continue
        prose = html_to_text(content)
        if prose:
            lines.append(prose)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def dump_one(
    client: PolarionClient,
    project_id: str,
    doc: DocRef,
    out_dir: Path,
    *,
    skip_existing: bool,
) -> dict[str, Any]:
    dest = out_dir / safe_segment(doc.space_id) / safe_segment(doc.document_name)
    marker = dest / "meta.json"
    if skip_existing and marker.exists():
        return {
            "space_id": doc.space_id,
            "document_name": doc.document_name,
            "status": "skipped",
            "path": str(dest),
        }

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "workitems").mkdir(exist_ok=True)
    (dest / "attachments").mkdir(exist_ok=True)

    raw_doc = client.get_document(project_id, doc.space_id, doc.document_name)
    attrs = (raw_doc.get("data") or {}).get("attributes") or {}
    hpc = attrs.get("homePageContent") or {}
    html_body = hpc.get("value") if isinstance(hpc, dict) else (hpc or "")

    meta = {
        "project_id": project_id,
        "space_id": doc.space_id,
        "document_name": doc.document_name,
        "title": attrs.get("title") or doc.title,
        "type": attrs.get("type") or doc.doc_type,
        "status": attrs.get("status") or doc.status,
        "created": attrs.get("created"),
        "updated": attrs.get("updated") or doc.updated,
        "moduleFolder": attrs.get("moduleFolder"),
        "polarion_id": (raw_doc.get("data") or {}).get("id"),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_url": (
            f"{client.base}/polarion/#/project/{project_id}"
            f"/wiki/{quote(doc.space_id)}/{quote(doc.document_name)}"
        ),
    }
    marker.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (dest / "homePageContent.html").write_text(html_body or "", encoding="utf-8")
    (dest / "document.json").write_text(json.dumps(raw_doc, indent=2) + "\n", encoding="utf-8")

    parts: list[dict[str, Any]] = []
    parts_error: str | None = None
    try:
        parts = client.list_parts(project_id, doc.space_id, doc.document_name)
    except Exception as exc:  # noqa: BLE001 — soft-dump from homePageContent
        parts_error = str(exc)
        click.echo(f"  parts API failed; soft dump from homePageContent: {exc}", err=True)

    if parts_error:
        meta["parts_error"] = "parts API failed or incomplete; body from homePageContent only"
        marker.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    (dest / "parts.json").write_text(
        json.dumps({"data": parts, "count": len(parts)}, indent=2) + "\n",
        encoding="utf-8",
    )

    wi_ids: set[str] = set()
    for part in parts:
        rel = ((part.get("relationships") or {}).get("workItem") or {}).get("data") or {}
        wi_full_id = rel.get("id") or ""
        if wi_full_id:
            wi_ids.add(wi_full_id.split("/", 1)[-1])
        content = (part.get("attributes") or {}).get("content") or ""
        wi_ids.update(extract_workitem_ids(content))
    # Soft dump: also pull WI ids embedded in homePageContent.
    wi_ids.update(extract_workitem_ids(html_body or ""))

    workitems: dict[str, dict[str, Any]] = {}
    for wi_id in sorted(wi_ids):
        try:
            wi_payload = client.get_workitem(project_id, wi_id)
        except RuntimeError as exc:
            wi_payload = {"error": str(exc), "id": wi_id}
        workitems[wi_id] = wi_payload
        (dest / "workitems" / f"{safe_segment(wi_id)}.json").write_text(
            json.dumps(wi_payload, indent=2) + "\n", encoding="utf-8"
        )

    md = build_markdown(meta["title"] or doc.document_name, parts, workitems)
    (dest / "content.md").write_text(md, encoding="utf-8")

    attachments = client.list_attachments(project_id, doc.space_id, doc.document_name)
    att_meta: list[dict[str, Any]] = []
    for att in attachments:
        a_attrs = att.get("attributes") or {}
        att_id = a_attrs.get("id") or (att.get("id") or "").rsplit("/", 1)[-1]
        file_name = a_attrs.get("fileName") or att_id
        entry: dict[str, Any] = {
            "id": att_id,
            "fileName": file_name,
            "length": a_attrs.get("length"),
            "title": a_attrs.get("title"),
        }
        if att_id:
            try:
                blob = client.download_attachment(
                    project_id, doc.space_id, doc.document_name, att_id
                )
                out_name = safe_segment(file_name)
                (dest / "attachments" / out_name).write_bytes(blob)
                entry["saved_as"] = out_name
                entry["bytes"] = len(blob)
            except RuntimeError as exc:
                entry["error"] = str(exc)
        att_meta.append(entry)
    (dest / "attachments.json").write_text(json.dumps(att_meta, indent=2) + "\n", encoding="utf-8")

    download_status = "soft_ok" if parts_error else "ok"
    return {
        "space_id": doc.space_id,
        "document_name": doc.document_name,
        "title": meta["title"],
        "type": meta["type"],
        "status": meta["status"],
        "parts": len(parts),
        "workitems": len(workitems),
        "attachments": len(att_meta),
        "path": str(dest),
        "download_status": download_status,
    }


@click.command()
@click.option(
    "--project-id",
    default=PROJECT_ID,
    show_default=True,
    help="Polarion project id.",
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=Path("polarion-dump"),
    show_default=True,
    help="Directory for dumped documents.",
)
@click.option(
    "--base-url",
    default=lambda: os.environ.get("POLARION_URL", DEFAULT_URL),
    show_default=DEFAULT_URL,
    help="Polarion base URL (or POLARION_URL).",
)
@click.option(
    "--skip-existing/--no-skip-existing",
    default=True,
    help="Skip documents that already have meta.json.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Optional max documents (for smoke tests).",
)
@click.option(
    "--only-space",
    default=None,
    help="Restrict dump to one space id.",
)
def main(
    project_id: str,
    out_dir: Path,
    base_url: str,
    skip_existing: bool,
    limit: int | None,
    only_space: str | None,
) -> None:
    """Dump Polarion project documents (HTML, markdown, work items, attachments)."""
    token = os.environ.get("POLARION_TOKEN")
    if not token:
        click.echo("POLARION_TOKEN is required", err=True)
        sys.exit(1)

    client = PolarionClient(base_url, token)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_root = out_dir / "documents"
    docs_root.mkdir(exist_ok=True)

    project_name = client.get_project_name(project_id)
    click.echo(f"Listing documents in {project_id} ({project_name}) …")
    docs = client.list_documents(project_id)
    if only_space:
        docs = [d for d in docs if d.space_id == only_space]
    if limit is not None:
        docs = docs[:limit]
    click.echo(f"Will dump {len(docs)} document(s) → {docs_root}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    started = time.time()
    for i, doc in enumerate(docs, start=1):
        label = f"{doc.space_id}/{doc.document_name}"
        click.echo(f"[{i}/{len(docs)}] {label}")
        try:
            results.append(
                dump_one(
                    client,
                    project_id,
                    doc,
                    docs_root,
                    skip_existing=skip_existing,
                )
            )
        except Exception as exc:  # noqa: BLE001 — keep dump going
            click.echo(f"  ERROR: {exc}", err=True)
            errors.append({"document": label, "error": str(exc)})

    manifest = {
        "project_id": project_id,
        "project_name": project_name,
        "base_url": base_url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 1),
        "document_count": len(docs),
        "ok_count": sum(1 for r in results if r.get("download_status") in {"ok", "soft_ok"}),
        "soft_ok_count": sum(1 for r in results if r.get("download_status") == "soft_ok"),
        "skipped_count": sum(1 for r in results if r.get("status") == "skipped"),
        "error_count": len(errors),
        "documents": results,
        "errors": errors,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    click.echo(
        f"Done. ok={manifest['ok_count']} soft_ok={manifest['soft_ok_count']} "
        f"skipped={manifest['skipped_count']} "
        f"errors={manifest['error_count']} → {out_dir / 'manifest.json'}"
    )
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
