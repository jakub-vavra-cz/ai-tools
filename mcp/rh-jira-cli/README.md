# jira-cli

Python CLI for Jira (REST API v3 + Agile): list/search issues, show issues, and edit summary, description, story points, sprint membership, comments, and workflow transitions.

## Install

```bash
cd rh-jira-cli
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Run as `jira-cli` or `python -m jira_cli`.

## MCP server (Cursor, Claude Desktop, …)

Install the optional extra, then run the stdio server (same `JIRA_*` environment variables as the CLI):

```bash
pip install 'jira-cli[mcp]'
jira-cli-mcp
```

The server sets `JIRA_CLI_NO_INPUT=1` by default. Tools mirror the CLI: `jira_list_mine`, `jira_list_for_email`, `jira_search`, `jira_get_issue`, `jira_create_issue`, `jira_update_issue`, `jira_agenda`, `jira_backlog`, `jira_list_link_types`, `jira_create_issue_link`, `jira_create_issue_link_explicit`, `jira_delete_issue_link`, `jira_list_issue_links`, `jira_move_issue`, `jira_list_fields`, `jira_get_transitions`, `jira_list_sprints`.

For programmatic use without MCP, import `JiraService` from `jira_cli.service` (structured dict/list results, no argparse).

## Configuration (environment)

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_URL` | Yes | Base URL (no trailing slash), e.g. `https://your-site.atlassian.net` |
| `JIRA_EMAIL` | Yes | Account email (or `JIRA_USER`) |
| `JIRA_API_TOKEN` | Yes | [API token](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_SPRINT_CACHE` | Optional | `1` (default) or `0` — local sprint list cache under `$XDG_CACHE_HOME/jira-cli/sprints` or `~/.cache/jira-cli/sprints` |
| `JIRA_CLI_NO_INPUT` | Optional | Set to `1` to disable interactive prompts in CI |

## Usage

**List my issues** (assignee **or** user fields **Developer**, **QA Contact**, **Doc Contact** — same roles as `show --short`; JQL uses `currentUser()` with those field display names).

```bash
jira-cli list-mine
jira-cli list-mine --json
jira-cli list-mine --unfinished   # excludes terminal statuses (Done/Closed/Resolved/...)
jira-cli list-mine --sprint 42    # only issues in Agile sprint id 42 (see jira-cli sprints PROJ)
jira-cli list-mine --sprint "Sprint 12"   # resolve name across all Scrum boards you can see (slower)
jira-cli list-mine --sprint "Sprint 12" --sprint-project PROJ   # optional: resolve name in one project only
jira-cli list-mine --jql 'status != "Done"' --max-results 100
jira-cli list-mine --type Story   # JQL: issuetype = "Story" (issue type display name)
jira-cli list-mine --all-fields   # every field per issue; JSON output (same as --json + *all)
```

**List by email** resolves the user with `GET /rest/api/3/user/search`, then runs the **same JQL OR** as **`list-mine`**: that user as **assignee**, **Developer**, **QA Contact**, or **Doc Contact** (using the same quoted id as assignee in each clause). Omit `EMAIL` to use **`JIRA_EMAIL`** (or `JIRA_USER`).

```bash
jira-cli list                                    # same roles as list-mine for JIRA_EMAIL
jira-cli list colleague@example.com
jira-cli list colleague@example.com --unfinished --max-results 100
jira-cli list colleague@example.com --jql 'project = PROJ'
jira-cli list --sprint 42   # same `--sprint` / optional `--sprint-project` as list-mine
jira-cli list --type Bug          # optional `--type` with default JIRA_EMAIL user
```

**Search issues** using show-like fields with OR semantics, or pass direct `--jql`.
Default line output is: `KEY<TAB>SUMMARY<TAB>ISSUETYPE<TAB>STATUS`.

```bash
jira-cli search login
jira-cli search --summary "auth bug"
jira-cli search --project PROJ
jira-cli search --project PROJ1,PROJ2 --summary "fix"
jira-cli search --status "In Progress" --priority High
jira-cli search --developer-email dev@example.com --qa-contact-email qa@example.com
jira-cli search --testing "In progress" --coverage Full --build "build 42"
jira-cli search --jql 'project = PROJ AND labels = "backend"'
```

**Create an issue** (`POST /rest/api/3/issue`). Requires **`--project`** and **`--summary`**. Issue type defaults to **`Task`**; use **`--type`** or **`--issuetype`** (same as `edit`; `--issuetype` wins if both are set). Optional flags match **`edit`** except user-field clearing options (`--assignee-clear`, `--reporter-clear`, `--developer-clear`, `--qa-contact-clear`, `--doc-contact-clear`, `--contributors-clear`, `--clear-due`) and comment replace/delete (`--comment-idx`, `--delete-comment-idx`); **`--comment`** adds a first comment after create, **`--sprint`** / **`--transition`** run after the issue exists.

```bash
jira-cli new --project PROJ --summary "Fix login redirect"
jira-cli new --project PROJ --summary "Story title" --type Story
jira-cli new --project PROJ --summary "With body" --description $'Line one\n\nLine two'
jira-cli new --project PROJ --summary "Assigned" --assignee-email dev@example.com --due 2026-12-31
jira-cli new --project PROJ --summary "In sprint" --sprint "Sprint 42" --comment "Initial note"
jira-cli new --project PROJ --summary "Subtask title" --type "Sub-task" --parent PROJ-100
jira-cli new --project PROJ --summary "API response" --json
```

**Show one issue** (all fields, pretty-printed JSON):

By default, `show` rewrites `fields.customfield_*` keys to custom field display names. Use `--custom-id` to keep raw custom field ids. The response also includes **`names`** (field id → display name, including custom fields). If Jira omits `names`, the CLI fills it from `GET /rest/api/3/field`.

```bash
jira-cli show PROJ-123
jira-cli show PROJ-123 --expand schema,changelog   # names is always merged
jira-cli show PROJ-123 --custom-id                 # keep customfield_* keys
jira-cli show PROJ-123 --compact
jira-cli show PROJ-123 --brief              # JSON: fields renamed via ``names``, ``names`` omitted, empties stripped
```

**Agenda** — my unfinished sprint tickets. Resolves the **active** sprint automatically (default name pattern `*IDM-SSSD*` in project **IDM**, board **rhel-idm-sssd** when ambiguous). Same user roles as **`list-mine`**. Line output includes a **role** column (`Assignee`, `Developer`, `Contributor`, `QA Contact`, `Doc Contact`; comma-separated when you hold several). When **Git Pull Request** is set, an extra tab column with the MR/PR URL (or dev-status summary) is appended. Issues are grouped into **In Progress**, **Other open**, and **Contributor** (any ticket where you are a Contributor appears only in the last section).

```bash
jira-cli agenda
jira-cli agenda --json
jira-cli agenda --sprint 42
jira-cli agenda --sprint-pattern '*IDM-SSSD-S*' --sprint-project IDM
jira-cli agenda --no-refresh-sprint-cache
```

**Backlog** — my pre-sprint tickets for estimation and planning. Same active sprint resolution as **agenda** (that sprint is **excluded**). Issues where you are **assignee** or **reporter**, status **New**, **Refinement**, or **Backlog**, and `sprint not in (<current>)`. Line output includes **relation**, **status**, **sprint** (or `-`), optional **story points**, and **summary**. JSON includes story point totals, per-issue `sprint`, and future sprints on the same board pattern.

```bash
jira-cli backlog
jira-cli backlog --json
jira-cli backlog --no-story-points
jira-cli backlog --sprint 42
jira-cli backlog --no-future-sprints
```

**Issue links** — create, list, and delete relationships between tickets (`POST/DELETE /rest/api/3/issueLink`). Use **`link-types`** to see inward/outward labels (e.g. Blocks: inward=`is blocked by`, outward=`blocks`). With **`link SOURCE TARGET --type Blocks --as blocks`**, SOURCE shows *blocks* toward TARGET (same semantics used when creating IDM-7305 blocking IDM-6829).

```bash
jira-cli link-types
jira-cli link-types --search block --json
jira-cli link IDM-7305 IDM-6829 --type Blocks --as blocks
jira-cli link IDM-7305 IDM-6829 --type Blocks --as "is blocked by"
jira-cli link --type Blocks --inward IDM-6829 --outward IDM-7305
jira-cli links IDM-7305 --json
jira-cli unlink 2045989
```

**Move an issue** to another project (`POST /rest/api/3/bulk/issues/move`). Requires **`--project`**. Keeps the current issue type name unless you pass **`--type`**. Prints the new issue key on stdout (the key changes when the project changes).

```bash
jira-cli move PROJ-123 --project NEWPROJ
jira-cli move PROJ-123 --project NEWPROJ --type Story
jira-cli move PROJ-123 --project NEWPROJ --json
```

**Edit** (non-interactive):

```bash
jira-cli edit PROJ-123 --summary "New title"
jira-cli edit PROJ-123 --description "Steps:\n1. …"
jira-cli edit PROJ-123 --story-points 5
jira-cli edit PROJ-123 --sprint 42
jira-cli edit PROJ-123 --sprint "Sprint 12"
jira-cli edit PROJ-123 --comment "Verified on build 99"
jira-cli edit PROJ-123 --comment-idx 0 --comment "Edited: verified on build 100"
jira-cli edit PROJ-123 --delete-comment-idx 1
jira-cli edit PROJ-123 --transition "In Progress"
jira-cli edit PROJ-123 --no-input --story-points 3   # fail if you omit flags by mistake in scripts
```

Fields aligned with **`show --short`** (system fields, then custom fields resolved by display name or optional `JIRA_*_FIELD_ID`; Story Points uses the field named **Story Points** or `JIRA_STORY_POINTS_FIELD_ID`):

```bash
jira-cli edit PROJ-123 --assignee-email you@example.com
jira-cli edit PROJ-123 --assignee-clear
jira-cli edit PROJ-123 --reporter-clear
jira-cli edit PROJ-123 --developer-clear --qa-contact-clear
jira-cli edit PROJ-123 --field 'QA Contact=' --yes   # clear via --field (empty value)
jira-cli edit PROJ-123 --priority High --due 2026-04-01
jira-cli edit PROJ-123 --clear-due
jira-cli edit PROJ-123 --issuetype Story
jira-cli edit PROJ-123 --severity Major
jira-cli edit PROJ-123 --preliminary-testing "In progress" --test-coverage Full --fixed-in-build "build 42"
jira-cli edit PROJ-123 --test-link "https://example.test/case/1"
jira-cli edit PROJ-123 --developer-email dev@example.com --qa-contact-email qa@example.com --doc-contact-email doc@example.com
```

**Arbitrary fields** (`--field KEY=VALUE`, repeatable): `KEY` is matched against **id**, **key**, **name**, and **clauseNames** from `GET /rest/api/3/field` (best score; ambiguous matches are rejected). Current and new values are shown on stderr, then confirmation is required unless you pass **`--yes`** (needed for non-TTY or when `JIRA_CLI_NO_INPUT=1`).

```bash
jira-cli edit PROJ-123 --field summary="Adjusted title" --field "My Custom Field=foo"
jira-cli edit PROJ-123 --field labels=backend,api --yes
```

User-picker flags resolve **`EMAIL`** with `GET /rest/api/3/user/search` (same as list/show). Select-list custom fields are sent as `{"value": "..."}`; if Jira rejects it, use `field-map` / `fields` to confirm option text or field type.

**Edit** (interactive, default when no flags and stdin is a TTY):

```bash
jira-cli edit PROJ-123
jira-cli edit PROJ-123 -i
```

**Field id ↔ name** (for optional `JIRA_*_FIELD_ID` env vars such as preliminary testing or fixed-in-build):

```bash
jira-cli field-map               # custom fields only: TSV id → display name (two columns)
jira-cli field-map --header      # with header row
jira-cli field-map --json        # JSON array of {"id", "name"} per field
jira-cli fields                  # custom fields: TSV columns id, name, key
jira-cli fields --header         # same with header row
jira-cli fields --json           # full FieldDetails from GET /rest/api/3/field
jira-cli fields --all            # include built-in fields (status, summary, …)
jira-cli fields -s story         # substring match on id, name, key, or clauseNames
jira-cli fields -s '^customfield_10' --regex
```

`field-map` uses the same `GET /rest/api/3/field` data as `fields`; use it when you only need **custom field id → name** for optional field-id env vars or JQL.

**Helpers**:

```bash
jira-cli transitions PROJ-123
jira-cli sprints PROJ
```

## Notes

- Jira **Cloud** uses `/rest/api/3`. Issue lists use **`POST /rest/api/3/search/jql`** (enhanced JQL search); the removed **`POST /rest/api/3/search`** endpoint is not used. Older **Server** instances may need different paths (not switched in this version). Command **`list`** resolves the user with **`GET /rest/api/3/user/search`**; if several users match and none share the exact email, resolution fails (use a unique address).
- Story points on `edit` use the field named **Story Points** from `GET /rest/api/3/field` (site-specific).
- Sprint names for `edit --sprint` and the `sprints` command are resolved by scanning every Scrum board in the project (future, active, and closed sprints). Use `jira-cli sprints PROJ --state future,active,closed` to list past sprints.
- Sprint lists are cached locally (see `JIRA_SPRINT_CACHE`). `jira-cli sprints` and `edit --sprint` use the cache whenever a matching file exists; Jira is queried only on cache miss (no file yet, or disabled cache), or when you pass `--refresh-sprint-cache`. Entries are not expired by time—delete cache files or use `--refresh-sprint-cache` to update. A successful API fetch also writes merged and per-board cache files so the two commands can share data when the `--state` filter matches.
- `list-mine`, `list`, and `search` accept `--debug` to print the JQL sent to `POST /rest/api/3/search/jql` on **stderr** before the results (stdout stays clean for piping).
- `list --unfinished` and `search --unfinished` fetch statuses from Jira (`GET /rest/api/3/status`) and build `status NOT IN (...)` for terminal states. If status lookup fails, they fall back to `statusCategory != "Done"`.
- `list-mine` ORs `assignee = currentUser()` with user-picker fields **Developer**, **QA Contact**, and **Doc Contact** (aligned with `show --short`), using those display names in JQL.

## Development

`jira-cli` is co-developed with [Cursor IDE](https://cursor.com/), including iterative design, implementation, and review of CLI behavior.

LLMs used during co-development:
- OpenAI GPT-5.3 Codex (Cursor Agent mode)
