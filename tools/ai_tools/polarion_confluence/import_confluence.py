#!/usr/bin/env python3
"""Import dumped Polarion project documents into stage Confluence."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
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

from ai_tools.polarion_confluence.render import (
    build_heading_index,
    load_requirement_titles,
    page_map_from_import_state,
    render_document,
    render_requirement_page,
    requirement_pages_from_import_state,
)

DEFAULT_DUMP = Path("polarion-dump")
DEFAULT_STATE = Path("polarion-dump") / "confluence-import.json"
SPACE_KEY = "IDMRHEL"
# Override per project (CERT / RHDS / RHEL_IDM, …).
PARENT_ID = "454623270"
PROJECT_ID = "CERT"
PROJECT_LABEL = "RedHatCertificateSystem"


@dataclass
class PageRef:
    id: str
    title: str
    url: str


def title_prefix(project_id: str) -> str:
    return project_id


def space_title(project_id: str, space_id: str) -> str:
    return f"{title_prefix(project_id)} · {space_id}"


def document_title(project_id: str, space_id: str, document_name: str) -> str:
    # Unique within IDMRHEL space
    return f"{title_prefix(project_id)} · {space_id} · {document_name}"


def requirement_title(project_id: str, wi_id: str, title: str | None) -> str:
    """Unique Confluence title for a requirement page."""
    base = f"{title_prefix(project_id)} · Req · {wi_id}"
    if not title or title == wi_id:
        return base
    # Keep under Confluence's 255-char title limit.
    suffix = f" — {title}"
    max_len = 255
    if len(base) + len(suffix) <= max_len:
        return base + suffix
    keep = max_len - len(base) - 3
    return base + " — " + title[:keep] + "…"


class ConfluenceClient:
    """Confluence Cloud REST client (basic auth email + API token)."""

    def __init__(self, base_url: str, username: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        raw = f"{username}:{token}".encode()
        self.auth = base64.b64encode(raw).decode()

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        content_type: str | None = "application/json",
        accept: str = "application/json",
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base}{path}"
        headers = {
            "Authorization": f"Basic {self.auth}",
            "Accept": accept,
        }
        if content_type and data is not None:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=180) as resp:
                body = resp.read()
                if not body:
                    return {}
                if accept.startswith("application/json"):
                    return json.loads(body.decode("utf-8"))
                return body
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Request failed {method} {url}: {exc}") from exc

    def find_page_by_title(self, space_key: str, title: str) -> PageRef | None:
        q = (
            f"/rest/api/content?spaceKey={quote(space_key)}"
            f"&title={quote(title)}&expand=version&limit=1"
        )
        payload = self._request("GET", q)
        results = payload.get("results") or []
        if not results:
            return None
        item = results[0]
        links = item.get("_links") or {}
        webui = links.get("webui") or ""
        base = links.get("base") or self.base.replace("/wiki", "")
        # base from API is usually https://host
        if webui.startswith("http"):
            url = webui
        else:
            url = f"{self.base}{webui}" if webui.startswith("/") else f"{base}{webui}"
        return PageRef(id=str(item["id"]), title=item["title"], url=url)

    def create_page(
        self,
        *,
        space_key: str,
        title: str,
        parent_id: str,
        storage_html: str,
    ) -> PageRef:
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "ancestors": [{"id": parent_id}],
            "body": {
                "storage": {
                    "value": storage_html,
                    "representation": "storage",
                }
            },
        }
        data = json.dumps(payload).encode("utf-8")
        item = self._request("POST", "/rest/api/content", data=data)
        links = item.get("_links") or {}
        webui = links.get("webui") or f"/spaces/{space_key}/pages/{item['id']}"
        url = f"{self.base}{webui}" if webui.startswith("/") else webui
        return PageRef(id=str(item["id"]), title=item["title"], url=url)

    def update_page(
        self,
        *,
        page_id: str,
        title: str,
        storage_html: str,
        version_number: int,
    ) -> PageRef:
        payload = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version_number + 1},
            "body": {
                "storage": {
                    "value": storage_html,
                    "representation": "storage",
                }
            },
        }
        data = json.dumps(payload).encode("utf-8")
        item = self._request("PUT", f"/rest/api/content/{page_id}", data=data)
        links = item.get("_links") or {}
        webui = links.get("webui") or f"/pages/{page_id}"
        url = f"{self.base}{webui}" if webui.startswith("/") else webui
        return PageRef(id=str(item["id"]), title=item["title"], url=url)

    def get_version(self, page_id: str) -> int:
        item = self._request("GET", f"/rest/api/content/{page_id}?expand=version")
        return int((item.get("version") or {}).get("number") or 1)

    def upload_attachment(self, page_id: str, path: Path) -> None:
        boundary = f"----Boundary{int(time.time() * 1000)}"
        file_name = path.name
        mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        blob = path.read_bytes()
        parts = [
            f"--{boundary}\r\n".encode(),
            (f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n').encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            blob,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)
        self._request(
            "POST",
            f"/rest/api/content/{page_id}/child/attachment",
            data=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            accept="application/json",
            extra_headers={"X-Atlassian-Token": "nocheck"},
        )


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def info_panel(lines: list[str]) -> str:
    inner = "<br/>".join(escape_html(line) for line in lines)
    return (
        '<ac:structured-macro ac:name="info" ac:schema-version="1">'
        "<ac:rich-text-body>"
        f"<p>{inner}</p>"
        "</ac:rich-text-body>"
        "</ac:structured-macro>"
    )


def ensure_page(
    client: ConfluenceClient,
    *,
    space_key: str,
    title: str,
    parent_id: str,
    storage_html: str,
    update_existing: bool,
) -> tuple[PageRef, str]:
    existing = client.find_page_by_title(space_key, title)
    if existing and not update_existing:
        return existing, "skipped"
    if existing and update_existing:
        ver = client.get_version(existing.id)
        page = client.update_page(
            page_id=existing.id,
            title=title,
            storage_html=storage_html,
            version_number=ver,
        )
        return page, "updated"
    page = client.create_page(
        space_key=space_key,
        title=title,
        parent_id=parent_id,
        storage_html=storage_html,
    )
    return page, "created"


def load_creds() -> tuple[str, str, str]:
    url = os.environ.get("CONFLUENCE_URL")
    user = os.environ.get("CONFLUENCE_USERNAME") or os.environ.get("CONFLUENCE_EMAIL")
    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if url and user and token:
        return url, user, token
    # Fall back to Cursor MCP config for stage (local migration helper)
    mcp_path = Path.home() / ".cursor" / "mcp.json"
    if mcp_path.exists():
        cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
        env = (cfg.get("mcpServers") or {}).get("stage-atlassian", {}).get("env") or {}
        url = env.get("CONFLUENCE_URL")
        user = env.get("CONFLUENCE_USERNAME")
        token = env.get("CONFLUENCE_API_TOKEN")
        if url and user and token:
            return url, user, token
    raise click.ClickException(
        "Set CONFLUENCE_URL, CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN "
        "(or configure stage-atlassian in ~/.cursor/mcp.json)."
    )


@click.command()
@click.option(
    "--dump-dir",
    type=click.Path(path_type=Path, exists=True),
    default=DEFAULT_DUMP,
    show_default=True,
)
@click.option(
    "--state-file",
    type=click.Path(path_type=Path),
    default=DEFAULT_STATE,
    show_default=True,
)
@click.option("--parent-id", default=PARENT_ID, show_default=True)
@click.option(
    "--project-id",
    default=PROJECT_ID,
    show_default=True,
    help="Polarion project id (also used as Confluence title prefix).",
)
@click.option(
    "--project-label",
    default=PROJECT_LABEL,
    show_default=True,
    help="Human-readable Polarion project name.",
)
@click.option("--space-key", default=SPACE_KEY, show_default=True)
@click.option("--limit", type=int, default=None, help="Max documents to import.")
@click.option("--req-limit", type=int, default=None, help="Max requirements to import.")
@click.option("--only-space", default=None, help="Import one Polarion space only.")
@click.option(
    "--update-existing/--no-update-existing",
    default=False,
    help="Update body when page title already exists.",
)
@click.option(
    "--skip-attachments/--no-skip-attachments",
    default=False,
)
@click.option(
    "--documents/--no-documents",
    default=True,
    help="Import Polarion documents.",
)
@click.option(
    "--requirements/--no-requirements",
    default=True,
    help="Import dumped requirements as pages.",
)
def main(
    dump_dir: Path,
    state_file: Path,
    parent_id: str,
    project_id: str,
    project_label: str,
    space_key: str,
    limit: int | None,
    req_limit: int | None,
    only_space: str | None,
    update_existing: bool,
    skip_attachments: bool,
    documents: bool,
    requirements: bool,
) -> None:
    """Create Confluence pages under Polarion legacy documents from the dump."""
    # Prefer project id from dump manifest when present.
    manifest_path = dump_dir / "manifest.json"
    req_dir = dump_dir / "requirements"
    req_manifest_path = req_dir / "manifest.json"

    dump_manifest: dict[str, Any] = {}
    doc_list: list[dict[str, Any]] = []
    if documents:
        if not manifest_path.exists():
            raise click.ClickException(f"Missing dump manifest: {manifest_path}")
        dump_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        project_id = dump_manifest.get("project_id") or project_id
        project_label = dump_manifest.get("project_name") or project_label or project_id
        doc_list = list(dump_manifest.get("documents") or [])
        if only_space:
            doc_list = [d for d in doc_list if d.get("space_id") == only_space]
        if limit is not None:
            doc_list = doc_list[:limit]

    req_list: list[dict[str, Any]] = []
    if requirements:
        if not req_manifest_path.exists():
            click.echo(
                f"No requirements dump at {req_manifest_path}; skipping requirements.",
                err=True,
            )
            requirements = False
        else:
            req_manifest = json.loads(req_manifest_path.read_text(encoding="utf-8"))
            project_id = req_manifest.get("project_id") or project_id
            req_list = list(req_manifest.get("requirements") or [])
            # Prefer entries with a path on disk
            req_list = [r for r in req_list if r.get("path") or r.get("id")]
            if req_limit is not None:
                req_list = req_list[:req_limit]

    url, user, token = load_creds()
    client = ConfluenceClient(url, user, token)

    state: dict[str, Any] = {}
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
    state.setdefault("pages", {})
    state.setdefault("spaces", {})
    state.setdefault("requirements", {})
    state["parent_id"] = parent_id
    state["space_key"] = space_key
    state["project_id"] = project_id
    state["project_label"] = project_label
    state["started_at"] = state.get("started_at") or datetime.now(timezone.utc).isoformat()

    # Project root under Polarion legacy documents parent
    project_title = f"{project_id} ({project_label})"
    project_body = (
        info_panel(
            [
                f"Imported from Polarion project {project_id} ({project_label}).",
                "Children: Polarion document spaces + Requirements.",
                f"Source: {(dump_manifest.get('base_url') or 'https://polarion.engineering.redhat.com')}/polarion/#/project/{project_id}",
            ]
        )
        + "<p>Document spaces hang under this page; requirements live under "
        f"<strong>{escape_html(project_id)} · Requirements</strong>.</p>"
    )
    click.echo(f"Ensuring project page: {project_title}")
    project_page, project_status = ensure_page(
        client,
        space_key=space_key,
        title=project_title,
        parent_id=parent_id,
        storage_html=project_body,
        update_existing=update_existing,
    )
    state["project_page"] = {
        "id": project_page.id,
        "title": project_page.title,
        "url": project_page.url,
        "status": project_status,
    }
    click.echo(f"  {project_status}: {project_page.url}")

    req_created = req_updated = req_skipped = req_errors = 0
    if requirements and req_list:
        req_space_title = f"{project_id} · Requirements"
        req_space_body = (
            info_panel(
                [
                    f"Polarion requirements from project {project_id}.",
                    "Each child page is one requirement work item.",
                ]
            )
            + "<p>Links from imported documents to requirements point here.</p>"
        )
        click.echo(f"Ensuring requirements hub: {req_space_title}")
        req_hub, req_hub_status = ensure_page(
            client,
            space_key=space_key,
            title=req_space_title,
            parent_id=project_page.id,
            storage_html=req_space_body,
            update_existing=update_existing,
        )
        state["requirements_hub"] = {
            "id": req_hub.id,
            "title": req_hub.title,
            "url": req_hub.url,
            "status": req_hub_status,
        }
        click.echo(f"  {req_hub_status}: {req_hub.url}")

        for i, req in enumerate(req_list, start=1):
            wi_id = req.get("id")
            if not wi_id:
                continue
            req_path = Path(req["path"]) if req.get("path") else req_dir / wi_id
            if not (req_path / "meta.json").exists():
                click.echo(f"  missing dump for {wi_id}, skip", err=True)
                req_errors += 1
                continue
            meta = json.loads((req_path / "meta.json").read_text(encoding="utf-8"))
            title = requirement_title(project_id, wi_id, meta.get("title") or req.get("title"))
            click.echo(f"[req {i}/{len(req_list)}] {wi_id}")

            existing = (state.get("requirements") or {}).get(wi_id)
            if (
                existing
                and existing.get("id")
                and not update_existing
                and existing.get("status") in {"created", "updated", "skipped"}
            ):
                req_skipped += 1
                click.echo(f"  skipped (state): {existing.get('url')}")
                continue

            try:
                storage_body, _md = render_requirement_page(req_path)
            except Exception as exc:  # noqa: BLE001
                req_errors += 1
                click.echo(f"  RENDER ERROR: {exc}", err=True)
                continue

            header = info_panel(
                [
                    f"Polarion requirement {wi_id}",
                    f"Status: {meta.get('status') or 'n/a'}",
                    f"Source: {meta.get('source_url') or 'n/a'}",
                ]
            )
            body = header + storage_body
            try:
                page, status = ensure_page(
                    client,
                    space_key=space_key,
                    title=title,
                    parent_id=req_hub.id,
                    storage_html=body,
                    update_existing=update_existing,
                )
            except Exception as exc:  # noqa: BLE001
                req_errors += 1
                click.echo(f"  ERROR: {exc}", err=True)
                state["requirements"][wi_id] = {
                    "title": title,
                    "status": "error",
                    "error": str(exc),
                }
                continue

            if status == "created":
                req_created += 1
            elif status == "updated":
                req_updated += 1
            else:
                req_skipped += 1

            att_paths: list[str] = []
            if not skip_attachments:
                att_dir = req_path / "attachments"
                files = (
                    sorted(p for p in att_dir.iterdir() if p.is_file()) if att_dir.is_dir() else []
                )
                for path in files:
                    try:
                        client.upload_attachment(page.id, path)
                        att_paths.append(path.name)
                    except Exception as exc:  # noqa: BLE001
                        click.echo(f"  attachment ERROR {path.name}: {exc}", err=True)

            state["requirements"][wi_id] = {
                "id": page.id,
                "title": page.title,
                "url": page.url,
                "status": status,
                "attachments": att_paths,
            }
            click.echo(f"  {status}: {page.url}")
            if i % 10 == 0:
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        state["requirements_summary"] = {
            "requirements": len(req_list),
            "created": req_created,
            "updated": req_updated,
            "skipped": req_skipped,
            "errors": req_errors,
        }
        click.echo(
            f"Requirements done. created={req_created} updated={req_updated} "
            f"skipped={req_skipped} errors={req_errors}"
        )

    # Requirement id → Confluence URL (for rewriting document links).
    requirement_pages = requirement_pages_from_import_state(state_file)
    for wi_id, info in (state.get("requirements") or {}).items():
        if info.get("url"):
            requirement_pages[wi_id] = info["url"]
    requirement_titles = load_requirement_titles(dump_dir)
    click.echo(
        f"Requirement pages available for linking: {len(requirement_pages)} "
        f"(titles: {len(requirement_titles)})"
    )

    if not documents:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        if req_errors:
            sys.exit(2)
        return

    spaces = sorted({d["space_id"] for d in doc_list})
    space_pages: dict[str, PageRef] = {}
    for space_id in spaces:
        title = space_title(project_id, space_id)
        body = (
            info_panel(
                [
                    f"Polarion space: {space_id}",
                    f"Project: {project_id}",
                ]
            )
            + f"<p>Documents imported from Polarion space <strong>{escape_html(space_id)}</strong>.</p>"
        )
        click.echo(f"Ensuring space page: {title}")
        page, status = ensure_page(
            client,
            space_key=space_key,
            title=title,
            parent_id=project_page.id,
            storage_html=body,
            update_existing=update_existing,
        )
        space_pages[space_id] = page
        state["spaces"][space_id] = {
            "id": page.id,
            "title": page.title,
            "url": page.url,
            "status": status,
        }
        click.echo(f"  {status}: {page.url}")

    # Heading work-item ids → Confluence page URLs (for cross-doc section links).
    page_map = page_map_from_import_state(state_file)
    # Seed from in-memory state too (first run / partial).
    for key, info in (state.get("pages") or {}).items():
        if info.get("url"):
            page_map[key] = info["url"]
    heading_index = build_heading_index(dump_dir, page_map)
    click.echo(f"Heading anchors indexed: {len(heading_index)}")

    created = updated = skipped = errors = 0
    for i, doc in enumerate(doc_list, start=1):
        space_id = doc["space_id"]
        document_name = doc["document_name"]
        doc_path = Path(doc["path"])
        key = f"{space_id}/{document_name}"
        title = document_title(project_id, space_id, document_name)
        click.echo(f"[{i}/{len(doc_list)}] {key}")

        existing_state = (state.get("pages") or {}).get(key)
        if (
            existing_state
            and existing_state.get("id")
            and not update_existing
            and existing_state.get("status") in {"created", "updated", "skipped"}
        ):
            # Already recorded; verify still present
            skipped += 1
            click.echo(f"  skipped (state): {existing_state.get('url')}")
            continue

        meta_path = doc_path / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

        try:
            storage_body, markdown_body = render_document(
                doc_path,
                heading_index=heading_index,
                page_map=page_map,
                requirement_pages=requirement_pages,
                requirement_titles=requirement_titles,
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            click.echo(f"  RENDER ERROR: {exc}", err=True)
            state["pages"][key] = {
                "title": title,
                "status": "error",
                "error": f"render: {exc}",
            }
            state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            continue

        # Refresh local render artifacts for review / re-import.
        (doc_path / "content.md").write_text(markdown_body, encoding="utf-8")
        (doc_path / "content.storage.html").write_text(storage_body, encoding="utf-8")

        header = info_panel(
            [
                f"Polarion: {project_id} / {space_id} / {document_name}",
                f"Type: {meta.get('type') or doc.get('type') or 'n/a'}",
                f"Status: {meta.get('status') or doc.get('status') or 'n/a'}",
                f"Updated in Polarion: {meta.get('updated') or doc.get('updated') or 'n/a'}",
                f"Source: {meta.get('source_url') or 'n/a'}",
                f"Heading anchors use Polarion heading ids ({project_id}-…). "
                f"Requirements link to {project_id} · Requirements pages; "
                "test cases link to RHELTEST Jira summary search "
                "(Polarion id kept until re-created).",
            ]
        )
        body = header + storage_body

        parent = space_pages[space_id]
        try:
            page, status = ensure_page(
                client,
                space_key=space_key,
                title=title,
                parent_id=parent.id,
                storage_html=body,
                update_existing=update_existing,
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            click.echo(f"  ERROR: {exc}", err=True)
            state["pages"][key] = {
                "title": title,
                "status": "error",
                "error": str(exc),
            }
            state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            continue

        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1
        else:
            skipped += 1

        att_paths: list[str] = []
        if not skip_attachments:
            att_dir = doc_path / "attachments"
            files = sorted(p for p in att_dir.iterdir() if p.is_file()) if att_dir.is_dir() else []
            for path in files:
                try:
                    client.upload_attachment(page.id, path)
                    att_paths.append(path.name)
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"  attachment ERROR {path.name}: {exc}", err=True)

        state["pages"][key] = {
            "id": page.id,
            "title": page.title,
            "url": page.url,
            "status": status,
            "attachments": att_paths,
            "polarion_space": space_id,
            "polarion_document": document_name,
        }
        click.echo(f"  {status}: {page.url}")
        if i % 5 == 0:
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["summary"] = {
        "documents": len(doc_list),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    click.echo(
        f"Done. docs created={created} updated={updated} skipped={skipped} "
        f"errors={errors}; reqs created={req_created} updated={req_updated} "
        f"skipped={req_skipped} errors={req_errors} → {state_file}"
    )
    if errors or req_errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
