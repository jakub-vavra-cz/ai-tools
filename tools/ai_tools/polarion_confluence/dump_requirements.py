#!/usr/bin/env python3
"""Dump Polarion project requirements for Confluence re-import."""

from __future__ import annotations

import json
import os
import re
import sys
import time
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
FIELDS_WI = (
    "@basic,title,type,status,description,outlineNumber,severity,severity,"
    "created,updated,reqtype,subtype1,subsystemteam"
)


class PolarionClient:
    """Thin Polarion REST v1 client using POLARION_TOKEN."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        self.token = token

    def _request(
        self,
        path: str,
        *,
        accept: str = "application/json",
        raw: bool = False,
        method: str = "GET",
        data: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
        }
        if extra_headers:
            headers.update(extra_headers)
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
        req = Request(url, data=data, headers=headers, method=method)
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

    def list_requirements(self, project_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            path = (
                f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
                f"/workitems?query={quote('type:requirement')}"
                f"&page%5Bsize%5D={PAGE_SIZE}&page%5Bnumber%5D={page}"
                f"&fields%5Bworkitems%5D={quote(FIELDS_WI, safe=',@')}"
            )
            payload = self._request(path)
            batch = payload.get("data") or []
            items.extend(batch)
            total = (payload.get("meta") or {}).get("totalCount")
            if total is not None and len(items) >= int(total):
                break
            if not (payload.get("links") or {}).get("next"):
                break
            page += 1
        return items

    def get_workitem(self, project_id: str, workitem_id: str) -> dict[str, Any]:
        path = (
            f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
            f"/workitems/{quote(workitem_id, safe='')}"
            f"?fields%5Bworkitems%5D={quote(FIELDS_WI, safe=',@')}"
        )
        return self._request(path)

    def list_links(
        self, project_id: str, workitem_id: str, *, direction: str
    ) -> list[dict[str, Any]]:
        # REST relationship collection
        rel = "linkedWorkItems" if direction == "forward" else "backlinkedWorkItems"
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            path = (
                f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
                f"/workitems/{quote(workitem_id, safe='')}"
                f"/{rel}?page%5Bsize%5D={PAGE_SIZE}&page%5Bnumber%5D={page}"
                f"&fields%5B{rel}%5D=@all"
            )
            try:
                payload = self._request(path)
            except RuntimeError:
                return items
            batch = payload.get("data") or []
            items.extend(batch)
            if not (payload.get("links") or {}).get("next"):
                break
            page += 1
        return items

    def list_attachments(self, project_id: str, workitem_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            path = (
                f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
                f"/workitems/{quote(workitem_id, safe='')}"
                f"/attachments?page%5Bsize%5D={PAGE_SIZE}&page%5Bnumber%5D={page}"
                f"&fields%5Bworkitem_attachments%5D=@all"
            )
            payload = self._request(path)
            batch = payload.get("data") or []
            items.extend(batch)
            if not (payload.get("links") or {}).get("next"):
                break
            page += 1
        return items

    def download_attachment(self, project_id: str, workitem_id: str, attachment_id: str) -> bytes:
        path = (
            f"/polarion/rest/v1/projects/{quote(project_id, safe='')}"
            f"/workitems/{quote(workitem_id, safe='')}"
            f"/attachments/{quote(attachment_id, safe='')}/content"
        )
        return self._request(path, accept="*/*", raw=True)


def safe_segment(name: str) -> str:
    cleaned = name.replace("/", "_").replace("\0", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "_empty"


def description_html(attrs: dict[str, Any]) -> str:
    desc = attrs.get("description")
    if isinstance(desc, dict):
        return desc.get("value") or ""
    if isinstance(desc, str):
        return desc
    return ""


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
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


def render_requirement_md(attrs: dict[str, Any], wi_id: str) -> str:
    title = attrs.get("title") or wi_id
    lines = [
        f"# {title}",
        "",
        f"- **ID:** `{wi_id}`",
        "- **Type:** requirement",
        f"- **Status:** {attrs.get('status') or 'n/a'}",
        f"- **Severity:** {attrs.get('severity') or 'n/a'}",
        f"- **Priority:** {attrs.get('priority') or 'n/a'}",
    ]
    if attrs.get("outlineNumber"):
        lines.append(f"- **Outline:** {attrs['outlineNumber']}")
    if attrs.get("reqtype"):
        lines.append(f"- **Req type:** {attrs['reqtype']}")
    lines.append("")
    body = html_to_text(description_html(attrs))
    if body:
        lines.append("## Description")
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def dump_one(
    client: PolarionClient,
    project_id: str,
    item: dict[str, Any],
    out_dir: Path,
    *,
    skip_existing: bool,
) -> dict[str, Any]:
    attrs = item.get("attributes") or {}
    wi_id = attrs.get("id") or (item.get("id") or "").rsplit("/", 1)[-1]
    dest = out_dir / safe_segment(wi_id)
    marker = dest / "meta.json"
    if skip_existing and marker.exists():
        return {
            "id": wi_id,
            "title": attrs.get("title"),
            "status": "skipped",
            "path": str(dest),
        }

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "attachments").mkdir(exist_ok=True)

    raw = client.get_workitem(project_id, wi_id)
    raw_attrs = (raw.get("data") or {}).get("attributes") or attrs
    desc = description_html(raw_attrs)

    meta = {
        "project_id": project_id,
        "workitem_id": wi_id,
        "title": raw_attrs.get("title"),
        "type": "requirement",
        "status": raw_attrs.get("status"),
        "severity": raw_attrs.get("severity"),
        "priority": raw_attrs.get("priority"),
        "outlineNumber": raw_attrs.get("outlineNumber"),
        "reqtype": raw_attrs.get("reqtype"),
        "created": raw_attrs.get("created"),
        "updated": raw_attrs.get("updated"),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_url": (f"{client.base}/polarion/#/project/{project_id}/workitem?id={wi_id}"),
        "portal_url": ((raw.get("data") or {}).get("links") or {}).get("portal"),
    }
    marker.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (dest / "workitem.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    (dest / "description.html").write_text(desc, encoding="utf-8")
    (dest / "content.md").write_text(render_requirement_md(raw_attrs, wi_id), encoding="utf-8")

    forward = client.list_links(project_id, wi_id, direction="forward")
    back = client.list_links(project_id, wi_id, direction="back")
    (dest / "links.json").write_text(
        json.dumps({"forward": forward, "back": back}, indent=2) + "\n",
        encoding="utf-8",
    )

    attachments = client.list_attachments(project_id, wi_id)
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
                blob = client.download_attachment(project_id, wi_id, att_id)
                out_name = safe_segment(file_name)
                (dest / "attachments" / out_name).write_bytes(blob)
                entry["saved_as"] = out_name
                entry["bytes"] = len(blob)
            except RuntimeError as exc:
                entry["error"] = str(exc)
        att_meta.append(entry)
    (dest / "attachments.json").write_text(json.dumps(att_meta, indent=2) + "\n", encoding="utf-8")

    return {
        "id": wi_id,
        "title": meta["title"],
        "status": meta["status"],
        "severity": meta.get("severity"),
        "attachments": len(att_meta),
        "path": str(dest),
        "download_status": "ok",
    }


@click.command()
@click.option("--project-id", default=PROJECT_ID, show_default=True)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=Path("polarion-dump") / "requirements",
    show_default=True,
)
@click.option(
    "--base-url",
    default=lambda: os.environ.get("POLARION_URL", DEFAULT_URL),
    show_default=DEFAULT_URL,
)
@click.option("--skip-existing/--no-skip-existing", default=True)
@click.option("--limit", type=int, default=None)
def main(
    project_id: str,
    out_dir: Path,
    base_url: str,
    skip_existing: bool,
    limit: int | None,
) -> None:
    """Dump all Polarion requirements for Confluence import."""
    token = os.environ.get("POLARION_TOKEN")
    if not token:
        click.echo("POLARION_TOKEN is required", err=True)
        sys.exit(1)

    client = PolarionClient(base_url, token)
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Listing requirements in {project_id} …")
    items = client.list_requirements(project_id)
    if limit is not None:
        items = items[:limit]
    click.echo(f"Will dump {len(items)} requirement(s) → {out_dir}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    started = time.time()
    for i, item in enumerate(items, start=1):
        attrs = item.get("attributes") or {}
        wi_id = attrs.get("id") or "?"
        click.echo(f"[{i}/{len(items)}] {wi_id} {attrs.get('title') or ''}")
        try:
            results.append(
                dump_one(
                    client,
                    project_id,
                    item,
                    out_dir,
                    skip_existing=skip_existing,
                )
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  ERROR: {exc}", err=True)
            errors.append({"id": wi_id, "error": str(exc)})

    manifest = {
        "project_id": project_id,
        "kind": "requirements",
        "base_url": base_url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 1),
        "requirement_count": len(items),
        "ok_count": sum(1 for r in results if r.get("download_status") == "ok"),
        "skipped_count": sum(1 for r in results if r.get("status") == "skipped"),
        "error_count": len(errors),
        "requirements": results,
        "errors": errors,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # Also publish under polarion-dump root for importers.
    root_manifest = out_dir.parent / "requirements-manifest.json"
    root_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    click.echo(
        f"Done. ok={manifest['ok_count']} skipped={manifest['skipped_count']} "
        f"errors={manifest['error_count']} → {out_dir / 'manifest.json'}"
    )
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
