---
name: git-to-jira-case
description: >-
  Clones a git repo branch, runs Betelgeuse to collect Python tests, converts
  them to jira-format dumps via beetlejuice, and imports Test Cases into Jira
  RHELTEST (stage by default; production only when explicitly requested). Use
  when dumping tests from git into Jira, beetlejuice dump-repo, git-to-jira,
  cert_auto dumps, or importing Betelgeuse-sourced cases to stage or prod
  Atlassian.
---

# Git branch → Betelgeuse → Jira Test Cases

Pipeline: **clone branch → `betelgeuse test-case` → jira-format `.properties` → RHELTEST**.

**Default target is stage.** Do **not** use production Jira unless the user
explicitly asks.

Code lives in **`idmci-fork-beetlejuice`** (`idmci/integration/jira/repo_dump.py`, CLI
`beetlejuice dump-repo`). Prefer that worktree for dump-repo. For
`import-jira-testcase` / ADF conversion, prefer editable **`~/git/ai-tools/tools`**
(`PYTHONPATH` or `pip install -e`) so empty-paragraph sanitizers apply.

## Prerequisites

| Need | Notes |
|------|--------|
| Worktree | `~/git/idmci-fork-beetlejuice` (dump-repo) + `~/git/ai-tools/tools` (import ADF) |
| `betelgeuse` | On `PATH` (`pip install betelgeuse`); idmci pins `betelgeuse==1.9.0` |
| `PYTHONPATH` | idmci root for `python -m idmci.integration.jira.cli`; also `ai-tools/tools` for import |
| Creds (stage) | `source ~/git/@POLARION_IMPORT/jira_creds.sh` |
| Creds (prod) | `source ~/git/@POLARION_IMPORT/prod_jira_creds.sh` (explicit ask only) |
| Network | GitLab CEE clone + Jira need unrestricted network (`all` / full perms) |

Do **not** commit `jira_creds.sh`, `prod_jira_creds.sh`, vault passwords, or `jira-*-cache*` files.

## Defaults (CERT / wildfly-cs style)

| Knob | Default |
|------|---------|
| Output dumps | `$GIT_PATH/@POLARION_IMPORT/cert_auto` |
| Clone dir | `<output>/repos/<repo-name>/` |
| Betelgeuse XML | `<output>/logs/<repo>-<branch>-import-testcase.xml` |
| Source subdir | `pytest` |
| Polarion project in XML | `CERT` |
| Jira project | `RHELTEST` |
| Team | **required** (e.g. `rhel-idm-cs`) |

Override dump root with `-o` or `IDMCI_POLARION_IMPORT_DIR` / `GIT_PATH`.

## Workflow

Copy and track:

```
Progress:
- [ ] 1. Confirm repo URL, branch, --team, output dir, stage vs prod
- [ ] 2. dump-repo (Betelgeuse + convert)
- [ ] 3. Spot-check dumps (ID, AssignedTeam, URL)
- [ ] 4. Bulk import (skip-assignee; correct creds + results JSONL)
- [ ] 5. Retry component / ADF / too-long failures
- [ ] 6. Report first-pass fail categories + final counts
```

### 1. Dump from git

```bash
export GIT_PATH="${GIT_PATH:-$HOME/git}"
export PYTHONPATH="$GIT_PATH/idmci-fork-beetlejuice${PYTHONPATH:+:$PYTHONPATH}"

python -m idmci.integration.jira.cli dump-repo \
  https://gitlab.cee.redhat.com/idm/pki-pytest-ansible \
  --branch RHCS11_0 \
  --team rhel-idm-cs
```

Useful flags: `--source` (relative test tree), `--limit N`, `--ignore-path`, `--no-auto-ignore`, `--polarion-project`, `--work-dir`, `-o`.

`dump-repo` auto-skips modules that crash Betelgeuse docstring parsing (log “ignored N unparsable module(s)”). Ignore paths must match Betelgeuse walk paths (relative to clone cwd).

### 2. Spot-check dumps

Under the output dir, each `*.properties` should have:

- `summary=`
- `ID=` (from Polarion `:id:` / testCaseID → **tmtid** → work-item id)
- `AssignedTeam=<team>`
- `URL=` GitLab/GitHub blob link (repo-relative path, not absolute FS path)

Bad absolute URLs mean Betelgeuse got an absolute source path — `repo_dump` passes source relative to the clone cwd; do not “fix” by passing absolute `--source`.

### 3. Bulk import to Jira

#### Stage (default)

```bash
set -a
source "$GIT_PATH/@POLARION_IMPORT/jira_creds.sh"
set +a
export PYTHONPATH="$GIT_PATH/ai-tools/tools:$GIT_PATH/idmci-fork-beetlejuice${PYTHONPATH:+:$PYTHONPATH}"
export IDMCI_JIRA_CUSTOM_FIELD_CACHE_DIR="$GIT_PATH/@POLARION_IMPORT/cert_auto/logs/jira-custom-field-cache"
export IDMCI_JIRA_MAX_CONCURRENT=5
```

Results JSONL: `logs/import_results.jsonl` (resume: skip stems already `"ok": true`).

#### Production (explicit ask only)

```bash
set -a
source "$GIT_PATH/@POLARION_IMPORT/prod_jira_creds.sh"
set +a
export PYTHONPATH="$GIT_PATH/ai-tools/tools:$GIT_PATH/idmci-fork-beetlejuice${PYTHONPATH:+:$PYTHONPATH}"
export IDMCI_JIRA_CUSTOM_FIELD_CACHE_DIR="$GIT_PATH/@POLARION_IMPORT/cert_auto/logs/jira-custom-field-cache-prod"
export IDMCI_JIRA_MAX_CONCURRENT=5
```

Results JSONL: **`logs/import_prod_results.jsonl`** — never append prod rows into the stage
`import_results.jsonl` (or vice versa). Use a separate field-cache dir per host.

Before a large prod create run, smoke-check that `Test Case` is createable on
`RHELTEST` (`list_createable_issue_types` / dry-run one dump).

Import via **`import-jira-testcase`** or
`idmci.integration.jira.testcase_import.import_testcase` (resolves custom field ids
per host with 1-day cache — do not hardcode `customfield_*`). Always
**`--skip-assignee`** for bot bulk loads.

Bulk pattern: parallel workers over `*.properties` (e.g.
`@POLARION_IMPORT/cert_auto/import_all_prod.py` or the same resume JSONL loop).

Optional one-shot from XML instead of properties:

```bash
python -m idmci.integration.jira.cli test-case \
  "$GIT_PATH/@POLARION_IMPORT/cert_auto/logs/<xml>" \
  --import --team rhel-idm-cs --skip-assignee
```

Or dump+import together: `dump-repo ... --import --skip-assignee` (still prefer separate dump then bulk import for large trees).

### 4. Retry failures

Report **first-pass categories**, then retry; report **final** ok/fail.

#### Components

If create fails with `Component name '…' is not valid`, retry those IDs with
**`--skip-components`**. Seen on CERT auto dumps:

| Invalid `components=` | Notes |
|----------------------|--------|
| `<ul class="simple">\n<li/>\n</ul>` | HTML crumb from Polarion/Betelgeuse |
| `<p/>` | HTML crumb |
| `ca`, `ocsp` | Short names not on RHELTEST component list |

Other fields stay intact when skipping components.

#### ADF (“not valid Atlassian Document Format”)

Usually **empty paragraphs/lists** from Polarion HTML (empty table cells, nested
`<ol><ol>` without `<li>`, empty `<ul></ul>`, nbsp-only cells). Prefer:

1. Ensure import uses ai-tools `html_to_adf` sanitizer (`PYTHONPATH=~/git/ai-tools/tools`).
2. Fix dump markup: fill empty cells/`li` with `-`, wrap nested lists, drop empty lists/tables.
3. Re-import the fixed `.properties`.

#### Description too long (32767)

Strip non-rendering noise from HTML description, then re-import:

- Drop presentation `style` props (`line-height`, `font-size`, `color`, …)
- Replace `&nbsp;` / collapse whitespace; optionally collapse `<br/>` → space
- Remove redundant “Polarion fields” table (metadata already in custom fields)
- Last resort: truncate with a note + Polarion `External issue URL`

Back up originals (e.g. `logs/too_long_backup/`) before rewriting dumps.

### 5. Report

Summarize: dumps count, first-pass fail categories + counts, retry results, unique
ok/fail, created vs updated, log paths (`logs/import_results.jsonl` or
`import_prod_results.jsonl`, `logs/dump-repo.log`), and one sample browse URL
(`stage-redhat.atlassian.net` or `redhat.atlassian.net`).

## Field / ID notes

- Jira **ID** custom field: dump `ID=` ← `testCaseID` else `tmtid` else Polarion/work-item `id` (`polarion_pairs_to_jira`).
- Custom field **ids differ** stage vs prod — always `get_custom_fields(config)` / cache under the host-specific `IDMCI_JIRA_CUSTOM_FIELD_CACHE_DIR`.
- Duplicate Jira matches: lowest non-**Retired** key wins (`pick_canonical_issue`).
- Empty Polarion rich text `{"type":"text/html"}` is treated as blank; empty table cells need a non-empty ADF paragraph (sanitizer / `-` placeholder).

## Related skills / tools

- Manual single-issue create: [create-rheltest-testcase](../create-rheltest-testcase/SKILL.md)
- Polarion REST dumps (not git): `dump-polarion-testcase` / `@POLARION_IMPORT/cert_manual`
- Design notes: `idmci-fork-beetlejuice/idmci/integration/jira/DESIGN.md`

## Existing dump dirs (reuse)

| Dir | Kind | Notes |
|-----|------|--------|
| `@POLARION_IMPORT/cert_auto` | Automated (Betelgeuse) | Stage + prod import JSONLs under `logs/` |
| `@POLARION_IMPORT/cert_manual` | Polarion manual TCs | Same import CLI; ADF/length fixes may rewrite dumps |

## Pitfalls

- Sandbox often blocks `gitlab.cee.redhat.com` and Atlassian — request full/`all` permissions.
- Do not use production Jira unless the user explicitly asks.
- Do not mix stage/prod result JSONL or field caches.
- Do not commit caches (`jira-custom-field-cache*/`, `jira-testcase-key-cache.json`) or vault password files.
- `fetch_custom_field_map` must **not** pass `timeout=` into the patched Jira session (double-timeout TypeError).
