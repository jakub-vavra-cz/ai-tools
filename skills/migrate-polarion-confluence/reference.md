# Polarion → Confluence CLI reference

## Install

```bash
pip install -e ~/git/ai-tools/tools
```

Package: `ai_tools.polarion_confluence`.

## dump-polarion-docs

```bash
dump-polarion-docs --project-id RHEL_IDM --out-dir polarion-dump
dump-polarion-docs --project-id CERT --only-space "Features Test Plans" --limit 5
dump-polarion-docs --project-id RHDS --no-skip-existing
```

| Flag | Default | Notes |
|------|---------|--------|
| `--project-id` | `CERT` | Polarion project id |
| `--out-dir` | `polarion-dump` | Creates `documents/`, `manifest.json` |
| `--base-url` | `POLARION_URL` or engineering Polarion | |
| `--skip-existing/--no-skip-existing` | skip | Skip dirs that already have `meta.json` |
| `--limit` | none | Smoke / partial dump |
| `--only-space` | none | One Polarion space id |

**Soft dump:** if `/parts` fails, still saves `homePageContent.html`, fetches WI ids
from that HTML, sets `download_status: soft_ok` and `meta.parts_error`.

Requires `POLARION_TOKEN`.

## dump-polarion-requirements

```bash
dump-polarion-requirements --project-id RHEL_IDM --out-dir polarion-dump/requirements
```

Writes per-WI dirs under `--out-dir`, `requirements/manifest.json`, and
`polarion-dump/requirements-manifest.json` (parent of `--out-dir`).

Requires `POLARION_TOKEN`.

## import-polarion-confluence

```bash
import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import.json \
  --parent-id 454629179 \
  --project-id RHEL_IDM \
  --project-label "RHEL Identity Management" \
  --space-key IDMRHEL \
  --skip-attachments \
  --update-existing
```

| Flag | Default | Notes |
|------|---------|--------|
| `--dump-dir` | `polarion-dump` | Must contain `manifest.json` and/or requirements manifest |
| `--state-file` | `polarion-dump/confluence-import.json` | Resume / skip map |
| `--parent-id` | CERT parent | Confluence page id under IDMRHEL |
| `--project-id` / `--project-label` | CERT | Title prefix + root page title |
| `--space-key` | `IDMRHEL` | |
| `--documents/--no-documents` | documents on | |
| `--requirements/--no-requirements` | requirements on | |
| `--update-existing/--no-update-existing` | off | Refresh page bodies |
| `--skip-attachments/--no-skip-attachments` | off | Prefer skip for large dumps |
| `--limit` / `--req-limit` / `--only-space` | | Partial import |

Credentials: `CONFLUENCE_URL`, `CONFLUENCE_USERNAME` (or `CONFLUENCE_EMAIL`),
`CONFLUENCE_API_TOKEN`, or `stage-atlassian` env block in `~/.cursor/mcp.json`.

## Rendering rules

| Polarion | Confluence |
|----------|------------|
| Heading work item | `<hN id="WI-id">` + anchor; cross-doc `#WI-id` / page URL |
| Requirement | Link to `{project} · Req · …` page when imported |
| Test case | Title → stage RHELTEST JQL; Polarion id → Polarion work-item URL (fallback) |
| Empty parts + `homePageContent.html` | Soft-render that HTML + soft-dump note |

## State file shape

```json
{
  "parent_id": "…",
  "space_key": "IDMRHEL",
  "project_id": "RHEL_IDM",
  "project_page": {"id": "…", "url": "…", "title": "…"},
  "requirements_hub": {"id": "…", "url": "…"},
  "spaces": {"SpaceId": {"id": "…", "url": "…"}},
  "pages": {"SpaceId/DocName": {"id": "…", "url": "…", "status": "created"}},
  "requirements": {"WI-id": {"id": "…", "url": "…", "status": "created"}}
}
```

## Known stage parents (IDMRHEL)

| Project | Parent id | URL slug |
|---------|-----------|----------|
| CERT | `454623270` | Polarion+legacy+documents+-+CERT |
| RHDS | `454853969` | Polarion+legacy+documents+RHDS |
| RHEL_IDM | `454629179` | Polarion+legacy+documents+-+RHEL+IDM |

## Existing dumps

Local Polarion dumps + Confluence import state already on disk (stage IDMRHEL).
**Reuse these** for the three projects below; do not full re-dump unless asked.

### CERT — `~/git/cert-doc-migration/polarion-dump/`

| Item | Value |
|------|--------|
| Documents | 115 (`manifest.json`, downloaded 2026-09-21) |
| Requirements | 182 |
| Soft docs | 0 |
| State | `confluence-import.json` — 115 pages, 182 reqs |
| Parent | `454623270` — [Polarion legacy documents - CERT](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454623270) |
| Root | `454525011` — [CERT (RedHatCertificateSystem)](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454525011/CERT+RedHatCertificateSystem) |
| Req hub | `454526150` — [CERT · Requirements](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454526150/CERT+Requirements) |

### RHDS — `~/git/rhds-doc-migration/polarion-dump/`

| Item | Value |
|------|--------|
| Documents | 85 |
| Requirements | 213 |
| Soft docs | 0 |
| State | `confluence-import.json` — 85 pages, 213 reqs |
| Parent | `454853969` — [Polarion legacy documents RHDS](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454853969) |
| Root | `454790925` — [RHDS (RedHatDirectoryServer)](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454790925/RHDS+RedHatDirectoryServer) |
| Req hub | `454626527` — [RHDS · Requirements](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454626527/RHDS+Requirements) |

### RHEL_IDM — `~/git/rhel-idm-doc-migration/polarion-dump/`

| Item | Value |
|------|--------|
| Documents | 123 (11 soft: parts API failed; body from `homePageContent`) |
| Requirements | 393 (includes recovered `IDM-293077`) |
| Soft docs | 11 |
| State | `confluence-import.json` — 123 pages, 393 reqs |
| Parent | `454629179` — [Polarion legacy documents - RHEL IDM](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454629179) |
| Root | `454856930` — [RHEL_IDM (RHEL Identity Management)](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454856930/RHEL_IDM+RHEL+Identity+Management) |
| Req hub | `454629187` — [RHEL_IDM · Requirements](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454629187/RHEL_IDM+Requirements) |

### What to keep when updating

- Keep `documents/`, `requirements/`, both manifests, and especially
  `confluence-import.json` (maps Polarion keys → Confluence page ids).
- Incremental dump: `dump-polarion-docs --skip-existing` / requirements dump with
  skip; then import with the same `--state-file`.
- Body/link refresh only: `import-polarion-confluence --update-existing` (no dump).
