---
name: migrate-polarion-confluence
description: >-
  Migrates Polarion project documents and requirements into stage Confluence
  (IDMRHEL): dump via Polarion REST, render heading/requirement/testcase links,
  import under a legacy-documents parent page. Use when migrating Polarion docs
  or requirements to Confluence, Polarion legacy documents, CERT/RHDS/RHEL_IDM
  Confluence import, or dump-polarion-docs / import-polarion-confluence.
---

# Migrate Polarion → Confluence (stage IDMRHEL)

## When this applies

User asks to **migrate a Polarion project** (documents and/or requirements) into
**stage** Confluence space `IDMRHEL` under a “Polarion legacy documents …” parent.

Do **not** use production Confluence unless the user explicitly asks.

Related: [create-rheltest-testcase](../create-rheltest-testcase/SKILL.md) (testcase
links target stage RHELTEST summary search).

## Tools (ai-tools)

Install once:

```bash
pip install -e ~/git/ai-tools/tools
```

| Command | Role |
|---------|------|
| `dump-polarion-docs` | Polarion documents → `polarion-dump/` |
| `dump-polarion-requirements` | Requirements → `polarion-dump/requirements/` |
| `import-polarion-confluence` | Dump → Confluence pages + state file |

Library: `ai_tools.polarion_confluence.render` (heading anchors, req pages, RHELTEST links).

Details and flags: [reference.md](reference.md).

## Credentials

| Env | Purpose |
|-----|---------|
| `POLARION_TOKEN` | Polarion REST (required for dump) |
| `POLARION_URL` | Default `https://polarion.engineering.redhat.com` |
| `CONFLUENCE_URL` | Stage Confluence base (or `stage-atlassian` in `~/.cursor/mcp.json`) |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_EMAIL` | Atlassian account email |
| `CONFLUENCE_API_TOKEN` | Atlassian API token |
| `RHELTEST_JIRA_URL` | Optional; default stage Jira for testcase search links |

## Workflow checklist

```
Task Progress:
- [ ] 1. Workspace + parent page
- [ ] 2. Dump documents
- [ ] 3. Dump requirements
- [ ] 4. Import requirements then documents (or both)
- [ ] 5. Soft-dump / missing WI recovery if needed
- [ ] 6. Update parent landing page
- [ ] 7. Spot-check headings / req / RHELTEST links
```

### 1. Workspace + parent page

Create `~/git/<project>-doc-migration/` (or reuse). Working dump dir is usually
`./polarion-dump` inside that workspace.

Confirm or create the Confluence **parent** page in space `IDMRHEL` (stage). Known parents:

| Project | Parent page id | Label |
|---------|----------------|-------|
| CERT | `454623270` | RedHatCertificateSystem |
| RHDS | `454853969` | RedHatDirectoryServer |
| RHEL_IDM | `454629179` | RHEL Identity Management |

Ask the user for Polarion `--project-id`, human `--project-label`, and `--parent-id`
if not in the table.

**Before dumping:** if the project is CERT, RHDS, or RHEL_IDM, check
[Prior migrations](#prior-migrations-reuse--do-not-re-dump-blindly) and reuse the
existing workspace dump/state instead of a full re-download.

### 2. Dump documents

```bash
cd ~/git/<project>-doc-migration
export POLARION_TOKEN=…
dump-polarion-docs --project-id <ID> --out-dir polarion-dump
```

Writes `polarion-dump/documents/…`, `manifest.json`. Parts API failures become
`download_status: soft_ok` (body from `homePageContent` + WI ids from that HTML).

Resume: default `--skip-existing`. Force redo: `--no-skip-existing`.

### 3. Dump requirements

```bash
dump-polarion-requirements --project-id <ID> --out-dir polarion-dump/requirements
```

Also writes `polarion-dump/requirements-manifest.json`. Re-dump a single failed id
by removing its dir and re-running (or calling dump for that WI via the library).

### 4. Import to Confluence

Prefer **requirements first**, then documents with `--update-existing` so doc→req
links resolve:

```bash
import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import.json \
  --parent-id <PARENT> \
  --project-id <ID> \
  --project-label "<Label>" \
  --space-key IDMRHEL \
  --skip-attachments \
  --requirements --no-documents

import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import.json \
  --parent-id <PARENT> \
  --project-id <ID> \
  --project-label "<Label>" \
  --space-key IDMRHEL \
  --skip-attachments \
  --documents --no-requirements \
  --update-existing
```

One-shot (both) is fine on a first empty import; re-run docs with `--update-existing`
after late requirements.

State file keys: `project_page`, `requirements_hub`, `pages`, `requirements`, `spaces`.

### 5. Soft dumps / gaps

- Soft docs: renderer falls back to `homePageContent.html` when `parts` is empty;
  pages note the soft dump. Re-import those keys with `--update-existing` after enriching
  `workitems/` if needed.
- Missing requirement on disk: dump that WI, append to `requirements-manifest.json` /
  `requirements/manifest.json`, import `--requirements --no-documents`.
- Rebuild a corrupted requirements manifest from `requirements/*/meta.json` on disk.

### 6. Parent landing page

Update the parent (stage MCP `confluence_update_page` or UI) with links to:

- Project root (`{ID} ({Label})`)
- Requirements hub (`{ID} · Requirements`) + counts
- Soft-dump caveat if any
- Local dump path

Pattern: RHDS / RHEL_IDM parent pages under IDMRHEL.

### 7. Spot-check

- Heading WI ids → in-page `#WI-id` anchors (not TC/req links)
- Requirements → Confluence req pages under the hub
- Test cases → stage RHELTEST JQL by summary; Polarion id links to Polarion WI

## Title conventions

| Kind | Title |
|------|--------|
| Project root | `{ID} ({Label})` |
| Space folder | `{ID} · {space}` |
| Document | `{ID} · {space} · {document_name}` |
| Requirements hub | `{ID} · Requirements` |
| Requirement | `{ID} · Req · {wi_id} — {title}` |

## Prior migrations (reuse — do not re-dump blindly)

These workspaces already have **Polarion dumps + Confluence import state**. Prefer
reuse for refresh, link fixes, or incremental adds.

| Project | Workspace | Docs | Reqs | Soft docs | Parent id |
|---------|-----------|------|------|-----------|-----------|
| CERT | `~/git/cert-doc-migration` | 115 | 182 | 0 | `454623270` |
| RHDS | `~/git/rhds-doc-migration` | 85 | 213 | 0 | `454853969` |
| RHEL_IDM | `~/git/rhel-idm-doc-migration` | 123 | 393 | 11 | `454629179` |

**Per workspace reuse paths**

| Path | Use |
|------|-----|
| `polarion-dump/documents/` | Already-fetched document trees (`meta.json`, `parts.json`, `workitems/`, `homePageContent.html`) |
| `polarion-dump/requirements/` | Requirement WI dumps (`meta.json`, …) |
| `polarion-dump/manifest.json` | Document inventory |
| `polarion-dump/requirements-manifest.json` | Requirement inventory |
| `polarion-dump/confluence-import.json` | Page id map — **required** for skip/update; do not delete |

**Confluence roots (stage IDMRHEL)** — full URLs in [reference.md](reference.md):

| Project | Root page id | Requirements hub id |
|---------|--------------|---------------------|
| CERT | `454525011` | `454526150` |
| RHDS | `454790925` | `454626527` |
| RHEL_IDM | `454856930` | `454629187` |

**Reuse rules**

1. **Same project, refresh bodies/links** — keep dump; run `import-polarion-confluence … --update-existing` with the existing `--state-file`.
2. **New/changed Polarion docs only** — `dump-polarion-docs` with default `--skip-existing` (or dump a single space via `--only-space`); then import (creates missing; use `--update-existing` if titles already exist).
3. **Do not** start a second dump dir or wipe `confluence-import.json` for these three projects unless the user asks for a clean re-import.
4. RHEL_IDM soft docs already rendered from `homePageContent`; re-dump parts only if Polarion `/parts` works again.

Inventory details (dump dates, URLs): [reference.md](reference.md#existing-dumps).
