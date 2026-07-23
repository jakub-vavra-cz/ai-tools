---
name: create-rheltest-testcase
description: >-
  Creates Test Case issues in the RHELTEST project on stage Jira
  (stage-redhat.atlassian.net) with the correct field IDs and option values.
  Use when creating RHELTEST test cases, stage Jira Test Case tickets, or
  RHELTEST issues of type Test Case.
---

# Create RHELTEST Test Case (stage Jira)

## Target

| Item | Value |
|------|--------|
| Instance | Stage — `https://stage-redhat.atlassian.net` |
| MCP server | `user-stage-atlassian` |
| Project | `RHELTEST` |
| Issue type | `Test Case` (id `10236` on stage; `10239` on prod) |

Do **not** use production (`user-jira-cli` / `user-mcp-atlassian`) unless the user explicitly asks for prod.

**Issue type scheme:** `Test Case` must be enabled for project `RHELTEST`. On
production (`redhat.atlassian.net`) the type exists instance-wide but is often
**not** on the RHELTEST scheme (create fails with “Specify a valid issue type”).
A Jira admin must add `Test Case` to the project before import/create will work.

If stage MCP calls return empty or 401, authenticate with `mcp_auth` on `user-stage-atlassian`, or fall back to REST with a working API token against `stage-redhat.atlassian.net`.

## Create workflow

1. Confirm summary (required). Ask for optional fields only if missing and useful.
2. For select fields, resolve options with `jira_get_field_options` or use [reference.md](reference.md). Prefer option **value** strings in `additional_fields`.
3. Call `jira_create_issue` on `user-stage-atlassian`:

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

4. Return the new issue key and browse URL:
   `https://stage-redhat.atlassian.net/browse/<KEY>`

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
| Architecture | `customfield_10772` | multi-select | `[{"value":"x86_64"}, …]` |
| AssignedTeam | `customfield_10606` | select | `{"value":"rhel-idm-sssd"}` |
| Tier | `customfield_11177` | select | `{"value":"0"}` … `"3"` |
| ID | `customfield_10591` | text | string (external/test id) |
| URL | `customfield_10933` | URL | string |
| External issue URL | `customfield_10766` | URL | string |

## Common option values

**Tier** (`customfield_11177`): `0`, `1`, `2`, `3`

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
| `subsystemteam` | `AssignedTeam` | `customfield_10606` |
| `testCaseID` | `ID` | `customfield_10591` |
| `automation_script` if valid http(s) URL, else `hyperlinks` testscript | `URL` | `customfield_10933` |
| Polarion browse URL (work item id) | `External issue URL` | `customfield_10766` |
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
`assignee` / `components` top-level; `AssignedTeam` → `customfield_10606`,
`ID` → `customfield_10591`, `URL` → `customfield_10933`,
`External issue URL` → `customfield_10766` in `additional_fields`).

Or import with the CLI (match by `customfield_10591`, then summary; update or
create):

```bash
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 -o /tmp/tc.properties
import-jira-testcase /tmp/tc.properties --skip-assignee
```

From Betelgeuse / IdM-CI Polarion artifact XML (`import-testcase.xml`):

```bash
beetlejuice test-case /path/to/polarion/ -o /tmp/bj-dumps
beetlejuice test-case /path/to/import-testcase.xml --import --skip-assignee -n
```

## Related issue types in RHELTEST

Also available on stage (not covered by this skill): Bug, Epic, Story, Sub-task, Task, **Test Result** (`10237`).
