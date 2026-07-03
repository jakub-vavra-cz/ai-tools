---
name: migrate-polarion-confluence
description: >-
  Migrates Polarion project documents and requirements into Confluence space
  IDMRHEL (stage by default; production only when explicitly requested): dump
  via Polarion REST, render heading/requirement/testcase links, import under a
  legacy-documents parent. Use when migrating Polarion docs or requirements to
  Confluence, Polarion legacy documents, CERT/RHDS/RHEL_IDM Confluence import,
  or dump-polarion-docs / import-polarion-confluence.
---

# Migrate Polarion → Confluence (IDMRHEL)

## When this applies

User asks to **migrate a Polarion project** (documents and/or requirements) into
Confluence space `IDMRHEL` under a “Polarion legacy documents …” parent.

**Default target is stage.** Do **not** use production Confluence unless the user
explicitly asks (e.g. `redhat.atlassian.net` URL or “production”).

Related: [create-rheltest-testcase](../create-rheltest-testcase/SKILL.md) /
[git-to-jira-case](../git-to-jira-case/SKILL.md) (testcase links follow
`RHELTEST_JIRA_URL`).

## Tools (ai-tools)

Install once:

```bash
pip install -e ~/git/ai-tools/tools
```

Prefer `PYTHONPATH=~/git/ai-tools/tools` (or reinstall editable) after local
package edits so CLIs pick up the source tree, not a stale site-packages copy.

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
| `CONFLUENCE_URL` | Confluence base (`…/wiki`) |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_EMAIL` | Atlassian account email |
| `CONFLUENCE_API_TOKEN` | Atlassian API token |
| `RHELTEST_JIRA_URL` | Jira host for testcase summary links — **must match target** (stage vs prod) |

| Target | Creds / URL |
|--------|-------------|
| Stage (default) | `stage-atlassian` in `~/.cursor/mcp.json`, or stage Confluence env |
| Production (explicit ask only) | `source ~/git/@POLARION_IMPORT/prod_jira_creds.sh` then map `JIRA_EMAIL`/`JIRA_API_TOKEN` → `CONFLUENCE_*`; `CONFLUENCE_URL=https://redhat.atlassian.net/wiki`; `RHELTEST_JIRA_URL=https://redhat.atlassian.net` |

## Workflow checklist

```
Task Progress:
- [ ] 1. Workspace + parent page (+ stage vs prod state file)
- [ ] 2. Dump documents (or reuse existing dump)
- [ ] 3. Dump requirements (or reuse)
- [ ] 4. Import requirements then documents (or both)
- [ ] 5. Soft-dump / missing WI recovery if needed
- [ ] 6. Update parent landing page
- [ ] 7. Spot-check headings / req / RHELTEST links
```

### 1. Workspace + parent page

Create `~/git/<project>-doc-migration/` (or reuse). Working dump dir is usually
`./polarion-dump` inside that workspace.

**Stage parents** (per-project pages under IDMRHEL):

| Project | Parent page id | Label |
|---------|----------------|-------|
| CERT | `454623270` | RedHatCertificateSystem |
| RHDS | `454853969` | RedHatDirectoryServer |
| RHEL_IDM | `454629179` | RHEL Identity Management |

**Production parent** (shared; only when user asks for prod):

| Item | Value |
|------|--------|
| Parent id | `490275433` |
| URL | [Polarion legacy documents](https://redhat.atlassian.net/wiki/spaces/IDMRHEL/pages/490275433) |

Ask the user for Polarion `--project-id`, human `--project-label`, and `--parent-id`
if not in the tables.

**State files — never mix stage and prod**

| Target | `--state-file` |
|--------|----------------|
| Stage | `polarion-dump/confluence-import.json` |
| Production | `polarion-dump/confluence-import-prod.json` |

Do **not** overwrite or reuse the stage state file for a prod import (page ids and
URL hosts differ). Warn if `CONFLUENCE_URL` host and state `parent_id` disagree.

**Before dumping:** if the project is CERT, RHDS, or RHEL_IDM, check
[Prior migrations](#prior-migrations-reuse--do-not-re-dump-blindly) and reuse the
existing workspace dump instead of a full re-download. Prod imports of these
three are usually **import-only** with a new prod state file.

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
links resolve.

**Stage example**

```bash
import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import.json \
  --parent-id <STAGE_PARENT> \
  --project-id <ID> \
  --project-label "<Label>" \
  --space-key IDMRHEL \
  --skip-attachments \
  --requirements --no-documents

import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import.json \
  --parent-id <STAGE_PARENT> \
  --project-id <ID> \
  --project-label "<Label>" \
  --space-key IDMRHEL \
  --skip-attachments \
  --documents --no-requirements \
  --update-existing
```

**Production example** (explicit user ask; reuse dump; separate state file)

```bash
set -a
source ~/git/@POLARION_IMPORT/prod_jira_creds.sh
set +a
export CONFLUENCE_URL="https://redhat.atlassian.net/wiki"
export CONFLUENCE_USERNAME="${JIRA_EMAIL}"
export CONFLUENCE_API_TOKEN="${JIRA_API_TOKEN}"
export RHELTEST_JIRA_URL="${JIRA_URL}"

import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import-prod.json \
  --parent-id 490275433 \
  --project-id <ID> \
  --project-label "<Label>" \
  --space-key IDMRHEL \
  --skip-attachments \
  --requirements --no-documents
# then documents --no-requirements --update-existing (same state file / parent)
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

Update the parent (Confluence MCP `confluence_update_page` or UI) with links to:

- Project root (`{ID} ({Label})`)
- Requirements hub (`{ID} · Requirements`) + counts
- Document count / space summary
- Soft-dump caveat if any
- Local dump path + which state file (`confluence-import.json` vs `…-prod.json`)

On the **shared prod parent** (`490275433`), keep sections for each imported project
(CERT, RHDS, RHEL_IDM, …) rather than replacing the whole page with one project.

### 7. Spot-check

- Heading WI ids → in-page anchors / Confluence `anchor` macros (`#WI-id`)
- Requirements → Confluence req pages under the hub
- Test cases → RHELTEST `/browse/<key>` when `--rheltest-map` provides Polarion id → issue key; else summary JQL; Polarion id always → Polarion WI

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

| Project | Workspace | Docs | Reqs | Soft docs | Stage parent | Prod parent |
|---------|-----------|------|------|-----------|--------------|-------------|
| CERT | `~/git/cert-doc-migration` | 115 | 182 | 0 | `454623270` | `490275433` |
| RHDS | `~/git/rhds-doc-migration` | 85 | 213 | 0 | `454853969` | `490275433` |
| RHEL_IDM | `~/git/rhel-idm-doc-migration` | 123 | 393 | 11 | `454629179` | `490275433` |

**Per workspace reuse paths**

| Path | Use |
|------|-----|
| `polarion-dump/documents/` | Already-fetched document trees |
| `polarion-dump/requirements/` | Requirement WI dumps |
| `polarion-dump/manifest.json` | Document inventory |
| `polarion-dump/requirements-manifest.json` | Requirement inventory |
| `polarion-dump/confluence-import.json` | **Stage** page id map — do not delete |
| `polarion-dump/confluence-import-prod.json` | **Prod** page id map — do not delete; do not mix with stage |

**Confluence roots** — full URLs in [reference.md](reference.md):

| Project | Stage root / hub | Prod root / hub |
|---------|------------------|-----------------|
| CERT | `454525011` / `454526150` | `490275446` / `490505096` |
| RHDS | `454790925` / `454626527` | `490509415` / `490377029` |
| RHEL_IDM | `454856930` / `454629187` | `490448995` / `490449012` |

**Reuse rules**

1. **Same project, refresh bodies/links** — keep dump; run `import-polarion-confluence … --update-existing` with the matching stage or prod `--state-file`.
2. **New/changed Polarion docs only** — `dump-polarion-docs` with default `--skip-existing` (or `--only-space`); then import.
3. **Do not** wipe `confluence-import.json` or `confluence-import-prod.json` unless the user asks for a clean re-import of that target.
4. RHEL_IDM soft docs already rendered from `homePageContent`; re-dump parts only if Polarion `/parts` works again.
5. **Prod of CERT/RHDS/RHEL_IDM** — reuse dump; import under `490275433` with `confluence-import-prod.json`.
6. **TC title → Jira browse** — after RHELTEST import, re-run documents with
   `--rheltest-map …/import_prod_results.jsonl` (Polarion id links stay Polarion).

Inventory + CLI: [reference.md](reference.md#existing-dumps).

**Ops playbook** (prod parents, dump dirs, JSONLs, incremental doc/req refresh):
[`@POLARION_IMPORT/polarion-legacy-migration-notes.md`](../../../@POLARION_IMPORT/polarion-legacy-migration-notes.md).
