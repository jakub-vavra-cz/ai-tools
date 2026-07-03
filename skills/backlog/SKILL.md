---
name: backlog
description: >-
  Lists Jira backlog tickets for sprint planning: issues assigned to or created by
  the current user in New, Refinement, or Backlog status that are not in the active
  sprint, via jira-cli MCP `jira_backlog`. Use when the user asks for backlog review,
  sprint planning, story point estimation, or moving tickets to future sprints.
---

# Backlog

Produce a concise backlog report for estimation and sprint planning. Fetch backlog data and (when useful) future sprints, then assemble the report.

Related skills: [agenda](../agenda/SKILL.md), [jira-cli-mcp](../jira-cli-mcp/SKILL.md).

---

## 1. Jira — backlog tickets (not in current sprint)

Use MCP server **`user-jira-cli`**, tool **`jira_backlog`** (same as `jira-cli backlog --json`). Read the tool schema before calling.

### Fetch backlog

One call resolves the active sprint to exclude, lists your backlog issues, partitions them by status, totals story points, and includes future sprints for planning:

```json
{
  "refresh_sprint_cache": true,
  "show_story_points": true
}
```

Defaults (override only when the user asks): `sprint_pattern` `*IDM-SSSD*`, `sprint_project` `IDM`, `preferred_board` `rhel-idm-sssd`, `max_results` 100, `show_story_points` true, `include_future_sprints` true.

Optional overrides:

| Parameter | Use |
|-----------|-----|
| `sprint` | Sprint id or name to exclude (instead of auto-detecting active sprint) |
| `sprint_pattern`, `sprint_project`, `preferred_board` | Active sprint resolution (same as agenda) |
| `refresh_sprint_cache` | `true` to refetch sprint data from Jira |
| `max_results` | Cap on issues returned |
| `show_story_points` | Include story point field and totals |
| `include_future_sprints` | `false` to omit future sprint list |

Do **not** call `jira_search` or `jira_agenda` for backlog ticket data — `jira_backlog` handles sprint resolution, JQL, sorting, sectioning, and story point totals.

### Use the response

| Field | Use |
|-------|-----|
| `sprint.name`, `sprint.id`, `sprint.board_name` | Current sprint being excluded |
| `sections.New`, `sections.Refinement`, `sections.Backlog` | Tickets grouped by workflow status |
| `issues[].key`, `fields.summary`, `fields.status.name` | Ticket lines |
| `issues[].my_relation` | `Assignee`, `Reporter`, or both |
| `issues[].sprint` | Sprint name(s) when set; omitted when unset |
| `issues[].fields` (story points) | Point estimate per ticket when `show_story_points` is true |
| `story_points.total`, `story_points.unset_count` | Sum of set points; count missing estimates |
| `future_sprints[]` | `id`, `name`, `board_name` — candidate sprints for planning |
| `jql` | Underlying query (for debugging) |

### Present in the report

Link format: `https://redhat.atlassian.net/browse/<KEY>` (adjust host if `JIRA_URL` differs).

Per ticket: summary, status, sprint (or “none”), story points (or “unset”), and `my_relation`. Group under **New**, **Refinement**, and **Backlog** headings.

Show a **Story points** summary line: total and how many tickets lack estimates.

List **Future sprints** (name and id) when `future_sprints` is non-empty — this supports moving tickets into upcoming sprints.

---

## 2. Planning actions (when the user asks)

Use [jira-cli-mcp](../jira-cli-mcp/SKILL.md) for follow-up work:

| Goal | Tool | Notes |
|------|------|-------|
| Set story points | `jira_update_issue` | `story_points` argument |
| Move to a sprint | `jira_update_issue` | `sprint` — id or name |
| Link tickets | `jira_create_issue_link` | `source_key`, `target_key`, `link_type`, `as_relationship` |
| Change status | `jira_update_issue` | `transition` — get names from `jira_get_transitions` |
| Inspect one ticket | `jira_get_issue` | `brief: true` for a compact view |

When the user wants to plan capacity, compare `story_points.total` against typical sprint capacity and call out tickets with unset points first.

---

## Report template

```markdown
# Backlog — <weekday>, <date>

## Excluding sprint: <sprint name> (<sprint id>) [<board_name>]
**Story points:** <total> (<unset_count> unset)

### New
- [IDM-1234](url) — summary — *IDM-SSSD Sprint 45* — *3 sp* *(Assignee)*

### Refinement
- [IDM-5678](url) — summary — *none* — *unset* *(Reporter)*

### Backlog
- [IDM-9999](url) — summary — *IDM-SSSD Sprint 46* — *5 sp* *(Assignee, Reporter)*

## Future sprints
- <sprint name> (<id>) [<board_name>]

---
*Generated via backlog skill.*
```

Keep each section short. If a status section is empty, say "None". If `future_sprints` is empty, omit that section or say "None found". If the tool failed (auth, network), report the error in one line.

---

## Checklist

```
Backlog progress:
- [ ] jira_backlog fetched (tickets + story points + future sprints)
- [ ] Report assembled with status sections and point totals
- [ ] Planning follow-ups applied if requested (estimate, sprint move)
```
