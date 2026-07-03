---
name: create-rheltest-testcase
description: >-
  Creates Test Case issues in the RHELTEST project on stage Jira
  (stage-redhat.atlassian.net) by default, or production when explicitly
  requested, with the correct field IDs and option values. Use when creating
  RHELTEST test cases, stage or prod Jira Test Case tickets, or RHELTEST issues
  of type Test Case.
---

# Create RHELTEST Test Case

## Target

| Item | Stage (default) | Production (explicit ask only) |
|------|-----------------|--------------------------------|
| Instance | `https://stage-redhat.atlassian.net` | `https://redhat.atlassian.net` |
| MCP server | `user-stage-atlassian` | `user-mcp-atlassian` / `user-jira-cli` |
| Creds file | `@POLARION_IMPORT/jira_creds.sh` | `@POLARION_IMPORT/prod_jira_creds.sh` |
| Project | `RHELTEST` | `RHELTEST` |
| Issue type | `Test Case` (id `10236` on stage; `10239` on prod) | same name |

Do **not** use production unless the user explicitly asks.

**Issue type scheme:** Before a create or bulk import on a host, verify `Test Case`
is createable for `RHELTEST` (`list_createable_issue_types` / createmeta). Prod
RHELTEST currently accepts Test Case creates (smoke-checked during CERT import);
if create fails with “Specify a valid issue type”, a Jira admin must add the type
to the project scheme.

If stage MCP calls return empty or 401, authenticate with `mcp_auth` on
`user-stage-atlassian`, or fall back to REST with a working API token against
`stage-redhat.atlassian.net`.

**Custom field ids differ stage vs prod.** Prefer `import-jira-testcase` /
`get_custom_fields` (host-specific cache) for imports. MCP `additional_fields`
ids in this skill are **stage** createmeta — resolve with createmeta or
[reference.md](reference.md) before hardcoding on prod.

## Create workflow (single issue, MCP)

1. Confirm summary (required). Ask for optional fields only if missing and useful.
2. For select fields, resolve options with `jira_get_field_options` or use [reference.md](reference.md). Prefer option **value** strings in `additional_fields`.
3. Call `jira_create_issue` on the matching MCP server:

```json
{
  "project_key": "RHELTEST",
  "issue_type": "Test Case",
  "summary": "<required title>",
  "description": "<optional markdown>",
  "assignee": "<optional email or display name>",
  "components": "<optional comma-separated names>",
  "additional_fields": "{\"labels\":[\"...\"],\"customfield_11177\":{\"value\":\"1\"},\"customfield_10606\":{\"value\":\"rhel-idm-sssd\"},\"customfield_10772\":[{\"value\":\"x86_64\"}],\"customfield_10591\":\"<external id>\",\"customfield_10933\":\"https://...\",\"customfield_10766\":\"https://...\",\"fixVersions\":[{\"name\":\"...\"}],\"parent\":{\"key\":\"RHELTEST-123\"}}"
}
```

`additional_fields` is a **JSON string**. Omit keys you are not setting.
Stage field ids above — re-resolve on prod.

4. Return the new issue key and browse URL:
   - Stage: `https://stage-redhat.atlassian.net/browse/<KEY>`
   - Prod: `https://redhat.atlassian.net/browse/<KEY>`

## Create-screen fields

### Required

| Field | ID | Notes |
|-------|-----|--------|
| Issue Type | `issuetype` | Set via `issue_type: "Test Case"` |
| Project | `project` | Set via `project_key: "RHELTEST"` |
| Summary | `summary` | Top-level `summary` |

### Optional

| Field | ID | Schema | How to set |
|-------|-----|--------|------------|
| Description | `description` | string (ADF/markdown via MCP) | Top-level `description` |
| Assignee | `assignee` | user | Top-level `assignee` |
| Components | `components` | component[] | Top-level `components` (comma-separated names) |
| Labels | `labels` | string[] | `additional_fields.labels` |
| Fix versions | `fixVersions` | version[] | `[{"name":"..."}]` or `[{"id":"..."}]` |
| Linked Issues | `issuelinks` | — | Prefer link tools after create |
| Parent | `parent` | issuelink | `{"key":"RHELTEST-…"}` |
| Architecture | `customfield_10772` | multi-select | `[{"value":"x86_64"}, …]` (stage id) |
| AssignedTeam | `customfield_10606` | select | `{"value":"rhel-idm-sssd"}` (stage id) |
| Tier | `customfield_11177` | select | `{"value":"0"}` … `"3"` (stage id) |
| ID | `customfield_10591` | text | string (external/test id) (stage id) |
| URL | `customfield_10933` | URL | string (stage id) |
| External issue URL | `customfield_10766` | URL | string (stage id) |

## Common option values

**Tier** (`customfield_11177` on stage): `0`, `1`, `2`, `3`

**Architecture** (frequent): `Unspecified`, `All`, `x86_64`, `aarch64`, `ppc64le`, `s390x`, `noarch`
Full list and **AssignedTeam** values: [reference.md](reference.md)

IdM-related teams often used: `rhel-idm`, `rhel-idm-sssd`, `rhel-idm-ipa`, `rhel-idm-ds`, `rhel-idm-cs`, `rhel-idm-ops`, `rhel-idm-pki`, `rhel-se-idm`

## Polarion → Jira import

To prepare a Polarion testcase for create, dump it with
`dump-polarion-testcase` (default `--format jira`):

```bash
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --stdout
```

### Field mapping

| Polarion | Dump key | Jira |
|----------|----------|------|
| `title` | `summary` | Summary |
| `assignee` email, else `author` email | `assignee` | Assignee |
| `casecomponent` | `components` | Components |
| `tags` | `labels` | Labels |
| `subsystemteam` | `AssignedTeam` | AssignedTeam custom field |
| `testCaseID` | `ID` | ID custom field |
| `automation_script` if valid http(s) URL, else `hyperlinks` testscript | `URL` | URL custom field |
| Polarion browse URL (work item id) | `External issue URL` | External issue URL custom field |
| `status` | `status` | Issue status via transition (see below) |

#### Status mapping

| Polarion status | Jira status |
|-----------------|-------------|
| `draft`, `needs update` / `needsupdate`, `proposed` | `Draft` |
| `inactive` | `Retired` |
| `approved` | `Active` |

Unmapped Polarion content (description body, setup, test steps, teardown,
and remaining attributes such as `caseautomation`, `caselevel`, …) is placed
in `description` as HTML rich text. `created` / `updated` are omitted.

`Tier` and `Architecture` have no reliable Polarion equivalent and are omitted
unless you set them manually when calling `jira_create_issue`.

Use the dump keys with the create workflow above (`summary` / `description` /
`assignee` / `components` top-level; map AssignedTeam / ID / URL / External issue
URL via host-resolved custom field ids in `additional_fields`).

Or import with the CLI (match by ID custom field, then summary; update or create):

```bash
# Stage
set -a; source ~/git/@POLARION_IMPORT/jira_creds.sh; set +a
export PYTHONPATH=~/git/ai-tools/tools${PYTHONPATH:+:$PYTHONPATH}
export IDMCI_JIRA_CUSTOM_FIELD_CACHE_DIR=~/git/@POLARION_IMPORT/cert_manual/logs/jira-custom-field-cache

dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 -o /tmp/tc.properties
import-jira-testcase /tmp/tc.properties --skip-assignee
```

From Betelgeuse / IdM-CI Polarion artifact XML (`import-testcase.xml`):

```bash
beetlejuice test-case /path/to/polarion/ -o /tmp/bj-dumps
beetlejuice test-case /path/to/import-testcase.xml --import --skip-assignee -n
```

Git-sourced dumps: [git-to-jira-case](../git-to-jira-case/SKILL.md).

## Production / bulk import

Only when the user asks for production. Prefer the CLI over MCP for hundreds of dumps.

```bash
set -a
source ~/git/@POLARION_IMPORT/prod_jira_creds.sh
set +a
export PYTHONPATH=~/git/ai-tools/tools${PYTHONPATH:+:$PYTHONPATH}
export IDMCI_JIRA_CUSTOM_FIELD_CACHE_DIR=~/git/@POLARION_IMPORT/<dump-dir>/logs/jira-custom-field-cache-prod
export IDMCI_JIRA_MAX_CONCURRENT=5
```

| Artifact | Stage | Production |
|----------|-------|------------|
| Creds | `jira_creds.sh` | `prod_jira_creds.sh` |
| Field cache | `logs/jira-custom-field-cache` | `logs/jira-custom-field-cache-prod` |
| Results JSONL | `logs/import_results.jsonl` | `logs/import_prod_results.jsonl` |

Never append prod rows into the stage JSONL (or vice versa). Prefer
`PYTHONPATH=~/git/ai-tools/tools` after beetlejuice edits so ADF sanitizers apply.

Bulk pattern: parallel workers over `*.properties` with resume JSONL (e.g.
`@POLARION_IMPORT/cert_manual/import_all_prod.py` / `cert_auto/import_all_prod.py`).
Always `--skip-assignee` for bot loads. Report **first-pass fail categories**, then
retry; report **final** ok/fail.

### Retry: invalid components

If create fails with `Component name '…' is not valid`, retry with
**`--skip-components`**. Known bad `components=` values from CERT dumps:

| Value | Notes |
|-------|--------|
| `<ul class="simple">\n<li/>\n</ul>` | HTML crumb |
| `<p/>` | HTML crumb |
| `ca`, `ocsp` | Short names not on RHELTEST |

Other fields stay intact when skipping components.

### Retry: ADF (“not valid Atlassian Document Format”)

Usually empty paragraphs/lists from Polarion HTML (empty table cells, nested
`<ol><ol>` without `<li>`, empty `<ul></ul>`, nbsp-only cells). Prefer:

1. Import via ai-tools `html_to_adf` sanitizer (`PYTHONPATH=~/git/ai-tools/tools`).
2. Fix dump markup (placeholder `-` in empty cells/`li`, wrap nested lists, drop empty lists).
3. Re-import the fixed `.properties`.

### Retry: description too long (32767)

Prefer fixing the dump over skipping:

1. Drop presentation `style` props; replace `&nbsp;`; optionally collapse `<br/>`.
2. Remove redundant “Polarion fields” table (metadata already in custom fields).
3. Last resort: truncate with a note + Polarion `External issue URL`.

Back up originals under `logs/too_long_backup/` before rewriting.

## Related issue types in RHELTEST

Also available on stage (not covered by this skill): Bug, Epic, Story, Sub-task, Task, **Test Result** (`10237`).
