---
name: jira-cli-mcp
description: >-
  Uses the rh-jira-cli MCP (Jira Cloud REST) via call_mcp_tool: search, fetch issues,
  list transitions, update fields, add comments, and apply workflow transitions with
  correct parameter names. Use when the user mentions Jira, IDM-, RHEL tickets,
  jira-cli, jira MCP, transitions, or wants issues updated from the agent without
  shell jira-cli.
---

# jira-cli MCP

## Server and tools

- **MCP server id (Cursor):** `user-jira-cli`
- **Tool names:** `jira_search`, `jira_get_issue`, `jira_get_transitions`, `jira_update_issue`, `jira_create_issue`, `jira_list_mine`, `jira_list_for_email`, `jira_agenda`, `jira_backlog`, `jira_move_issue`, `jira_list_fields`, `jira_list_sprints`
- Invoke with `call_mcp_tool`: `server: "user-jira-cli"`, `toolName: "jira_update_issue"`, etc.

Auth is configured in MCP (typically `JIRA_URL`, `JIRA_EMAIL` or `JIRA_USER`, `JIRA_API_TOKEN`). The MCP sets non-interactive mode.

---

## Critical: `jira_update_issue` parameters

The tool schema matches the jira-cli edit surface. **Unknown keys are ignored** (no error), so typos silently do nothing.

| Goal | Correct argument | Wrong (ignored) |
|------|-------------------|-----------------|
| Move workflow | `transition` — transition **name** (e.g. `"Review"`, `"In Progress"`) or id string (e.g. `"51"`) | `transition_id` |
| Add comment | `comment` — plain string | — |
| Issue key | `issue_key` | `issue` |

**Always use `transition`, never `transition_id`.** If the user asks to set status, call `jira_get_transitions` with `issue_key`, pick the transition `name` from the response, then `jira_update_issue` with `transition: "<name>"`.

You may set **`comment`** and **`transition`** in the same `jira_update_issue` call when both are needed.

---

## `jira_get_issue`

- Required: **`issue_key`** (e.g. `"IDM-6048"`).
- Optional: `brief: true` for a smaller payload (status, assignee, summary, comments, etc.).

---

## `jira_search`

The CLI requires a real search scope. Pass at least one of:

- **`jql`**: raw JQL (preferred for precise queries), e.g. `summary ~ "9.9" AND summary ~ "sudo" ORDER BY updated DESC`
- **`term`** plus filters such as **`project`**, **`status`**, **`unfinished_only`**, etc.

Calling with empty or unusable combinations can error with: *Provide TERM, one or more search filters, --project, --unfinished, or --jql.*

---

## `jira_get_transitions`

- Argument: **`issue_key`** only.
- Returns `transitions[]` with `id`, `name`, and target `to.name` (status). Use **`name`** for `transition` on update unless you standardize on ids.

---

## `jira_create_issue`

Uses **`transition`** (not `transition_id`) for an initial transition after create, same as update.

---

## Short workflows

**Find a ticket by text**

1. `jira_search` with `jql` matching summary/project text.
2. `jira_get_issue` with `issue_key` for details.

**Hand off for review with MR link**

1. `jira_get_transitions` → confirm `"Review"` (or local equivalent) exists.
2. `jira_update_issue` with `issue_key`, `comment: "<MR URL>"`, `transition: "Review"` (one call if supported; else comment then transition).

**Change status only**

- `jira_update_issue` with `issue_key` and `transition: "<exact transition name>"`.

If transition fails (workflow guard), try an intermediate transition from `jira_get_transitions` (e.g. **In Progress** then **Review**).

---

## Examples (argument shapes)

```json
{
  "issue_key": "IDM-6048",
  "comment": "https://example.com/mr/55",
  "transition": "Review"
}
```

```json
{
  "jql": "project = IDM AND status = New AND assignee = currentUser() ORDER BY updated DESC",
  "max_results": 20
}
```

```json
{
  "issue_key": "IDM-6048"
}
```

Third example is **`jira_get_transitions`** — same `issue_key` pattern as **`jira_get_issue`**.

---

## `jira_agenda`

My unfinished sprint tickets (same as `jira-cli agenda --json`).

- Optional: **`sprint`** — sprint id or name; default resolves active sprint via pattern.
- Optional: **`sprint_pattern`** — glob for sprint name (default `*IDM-SSSD*`).
- Optional: **`sprint_project`** — project key for sprint lookup (default `IDM`).
- Optional: **`preferred_board`** — board name hint (default `rhel-idm-sssd`).
- Optional: **`refresh_sprint_cache`**, **`max_results`**, **`show_story_points`**.

Returns `sections`, `issues` (with `my_roles`, optional `git_pull_request`), sprint metadata, and JQL.

---

## `jira_backlog`

My backlog tickets not in the active sprint (same as `jira-cli backlog --json`).

- Optional: **`sprint`**, **`sprint_pattern`**, **`sprint_project`**, **`preferred_board`** — same as `jira_agenda` (defaults: active *IDM-SSSD* sprint in project IDM).
- Optional: **`refresh_sprint_cache`**, **`max_results`** (default 100), **`show_story_points`** (default true), **`include_future_sprints`** (default true).

Returns issues assigned to or reported by the current user in New, Refinement, or Backlog status, grouped in `sections`, with per-issue `sprint`, `story_points` totals, and `future_sprints` for planning.

---

## `jira_move_issue`

Move an issue to another project (bulk move API).

- Required: **`issue_key`**, **`project`** (target project key).
- Optional: **`issue_type`** — defaults to keeping the current type name in the target project.

Returns `issue_key` (new key if changed), `source_issue_key`, `target_project`, `target_issue_type`, and task metadata.
