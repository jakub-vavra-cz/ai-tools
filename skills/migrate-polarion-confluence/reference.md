# Polarion → Confluence CLI reference

## Install

```bash
pip install -e ~/git/ai-tools/tools
```

Package: `ai_tools.polarion_confluence`. After edits, keep using that editable install
or `PYTHONPATH=~/git/ai-tools/tools` so CLIs do not pick up a stale site-packages copy.

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
| `--state-file` | `polarion-dump/confluence-import.json` | Resume / skip map — use `…-prod.json` on production |
| `--parent-id` | CERT parent | Confluence page id under IDMRHEL |
| `--project-id` / `--project-label` | CERT | Title prefix + root page title |
| `--space-key` | `IDMRHEL` | |
| `--documents/--no-documents` | documents on | |
| `--requirements/--no-requirements` | requirements on | |
| `--update-existing/--no-update-existing` | off | Refresh page bodies |
| `--skip-attachments/--no-skip-attachments` | off | Prefer skip for large dumps |
| `--rheltest-map` | none | Repeatable path to import JSONL/JSON: Polarion id → Jira key. Title links become `/browse/<key>`; Polarion id links stay Polarion |
| `--limit` / `--req-limit` / `--only-space` | | Partial import |

Credentials: `CONFLUENCE_URL`, `CONFLUENCE_USERNAME` (or `CONFLUENCE_EMAIL`),
`CONFLUENCE_API_TOKEN`. Stage fallback: `stage-atlassian` in `~/.cursor/mcp.json`.
Production: map from `@POLARION_IMPORT/prod_jira_creds.sh` and set
`CONFLUENCE_URL=https://redhat.atlassian.net/wiki`. Set `RHELTEST_JIRA_URL` to the
same Atlassian host so rendered testcase links match the target.

## Rendering rules

| Polarion | Confluence |
|----------|------------|
| Heading work item | `<hN id="WI-id">` + anchor; cross-doc `#WI-id` / page URL |
| Requirement | Link to `{project} · Req · …` page when imported |
| Test case | Title → RHELTEST `/browse/<key>` if `--rheltest-map` has the id, else summary JQL; Polarion id → Polarion WI (never rewritten to Jira) |
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

Keep **separate** state files per target host:

| Target | Typical `--state-file` |
|--------|------------------------|
| Stage | `polarion-dump/confluence-import.json` |
| Production | `polarion-dump/confluence-import-prod.json` |

## Known parents (IDMRHEL)

### Stage

| Project | Parent id | URL slug |
|---------|-----------|----------|
| CERT | `454623270` | Polarion+legacy+documents+-+CERT |
| RHDS | `454853969` | Polarion+legacy+documents+RHDS |
| RHEL_IDM | `454629179` | Polarion+legacy+documents+-+RHEL+IDM |

### Production (explicit ask only)

| Item | Value |
|------|--------|
| Shared parent | `490275433` — [Polarion legacy documents](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490275433) |

CERT, RHDS, and RHEL_IDM all import as children of that shared parent.

## Existing dumps

Local Polarion dumps + Confluence import state already on disk.
**Reuse these** for the three projects below; do not full re-dump unless asked.

### CERT — `~/git/cert-doc-migration/polarion-dump/`

| Item | Value |
|------|--------|
| Documents | 115 (`manifest.json`, downloaded 2026-09-21) |
| Requirements | 182 |
| Soft docs | 0 |
| Stage state | `confluence-import.json` — 115 pages, 182 reqs |
| Stage parent | `454623270` — [Polarion legacy documents - CERT](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454623270) |
| Stage root | `454525011` — [CERT (RedHatCertificateSystem)](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454525011/CERT+RedHatCertificateSystem) |
| Stage req hub | `454526150` — [CERT · Requirements](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454526150/CERT+Requirements) |
| Prod state | `confluence-import-prod.json` — 115 pages, 182 reqs |
| Prod parent | `490275433` |
| Prod root | `490275446` — [CERT (RedHatCertificateSystem)](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490275446/CERT+RedHatCertificateSystem) |
| Prod req hub | `490505096` — [CERT · Requirements](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490505096/CERT+Requirements) |

### RHDS — `~/git/rhds-doc-migration/polarion-dump/`

| Item | Value |
|------|--------|
| Documents | 85 |
| Requirements | 213 |
| Soft docs | 0 |
| Stage state | `confluence-import.json` — 85 pages, 213 reqs |
| Stage parent | `454853969` — [Polarion legacy documents RHDS](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454853969) |
| Stage root | `454790925` — [RHDS (RedHatDirectoryServer)](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454790925/RHDS+RedHatDirectoryServer) |
| Stage req hub | `454626527` — [RHDS · Requirements](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454626527/RHDS+Requirements) |
| Prod state | `confluence-import-prod.json` — 85 pages, 213 reqs |
| Prod parent | `490275433` |
| Prod root | `490509415` — [RHDS (RedHatDirectoryServer)](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490509415/RHDS+RedHatDirectoryServer) |
| Prod req hub | `490377029` — [RHDS · Requirements](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490377029/RHDS+Requirements) |

### RHEL_IDM — `~/git/rhel-idm-doc-migration/polarion-dump/`

| Item | Value |
|------|--------|
| Documents | 123 (11 soft: parts API failed; body from `homePageContent`) |
| Requirements | 393 (includes recovered `IDM-293077`) |
| Soft docs | 11 |
| Stage state | `confluence-import.json` — 123 pages, 393 reqs |
| Stage parent | `454629179` — [Polarion legacy documents - RHEL IDM](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454629179) |
| Stage root | `454856930` — [RHEL_IDM (RHEL Identity Management)](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454856930/RHEL_IDM+RHEL+Identity+Management) |
| Stage req hub | `454629187` — [RHEL_IDM · Requirements](https://stage-redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/454629187/RHEL_IDM+Requirements) |
| Prod state | `confluence-import-prod.json` — 123 pages, 393 reqs |
| Prod parent | `490275433` |
| Prod root | `490448995` — [RHEL_IDM (RHEL Identity Management)](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490448995/RHEL_IDM+RHEL+Identity+Management) |
| Prod req hub | `490449012` — [RHEL_IDM · Requirements](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490449012/RHEL_IDM+Requirements) |

### What to keep when updating

- Keep `documents/`, `requirements/`, both manifests, and especially the state file
  for the target you are updating (`confluence-import.json` and/or
  `confluence-import-prod.json`).
- Incremental dump: `dump-polarion-docs --skip-existing` / requirements dump with
  skip; then import with the same `--state-file`.
- Body/link refresh only: `import-polarion-confluence --update-existing` (no dump).
- Prod-only refresh: reuse dump + `--state-file …/confluence-import-prod.json` +
  `--parent-id 490275433`.
- Remap TC title links after Jira import: `--rheltest-map` pointing at
  `@POLARION_IMPORT/<…>/logs/import_prod_results.jsonl`.

## Ops notes (prod migration playbook)

Full paths, TC dump dirs, import JSONLs, and copy-paste refresh commands:

[`@POLARION_IMPORT/polarion-legacy-migration-notes.md`](../../../@POLARION_IMPORT/polarion-legacy-migration-notes.md)

| TC dump dir | Maps for `--rheltest-map` |
|-------------|---------------------------|
| `cert_manual` + `cert_auto` | both `logs/import_prod_results.jsonl` |
| `rhds_manual` | `logs/import_prod_results.jsonl` |
| `rhel_idm_manual` | `logs/import_prod_results.jsonl` |
