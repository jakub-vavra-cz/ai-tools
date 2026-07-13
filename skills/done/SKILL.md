---
name: done
description: >-
  Summarizes what was done today: local git workspace activity via worklog MCP
  `worklog_workspace_today`, GitHub/GitLab PR/MR activity via git-stats MCP
  `git_stats_done`, and Jira tickets touched today via jira-cli MCP `jira_search`.
  Use when the user asks for a done summary, end-of-day recap, what they accomplished
  today, standup wrap-up, or daily work summary.
---

# Done

Produce a concise end-of-day summary in three sections. Run all data-gathering steps **in parallel** where possible, then assemble the report.

Related skills: [agenda](../agenda/SKILL.md), [jira-cli-mcp](../jira-cli-mcp/SKILL.md).

---

## 1. Today — workspace activity

Use MCP server **`user-worklog`**, tool **`worklog_workspace_today`** (same as `worklog today --json`). Read the tool schema before calling.

### Fetch activity

One call scans the git workspace for today's repos, files, and commits:

```json
{}
```

Defaults: workspace from `GIT_PATH` env (else `~/git`); today's local calendar date; `max_repos` 8; `max_files_per_repo` 10; `max_commits_per_repo` 10; `@*` scratch dirs excluded.

Optional overrides:

| Parameter | Use |
|-----------|-----|
| `workspaces` | Array of roots when not using default `GIT_PATH` |
| `max_repos`, `max_files_per_repo`, `max_commits_per_repo` | Scan limits |
| `include_scratch_dirs` | `true` to include `@*` dirs |

Do **not** run shell `find`/`ls -ltr`/`git log` for this section — `worklog_workspace_today` replaces them.

### Use the response

| Field | Use |
|-------|-----|
| `workday` | Report date (today) |
| `active_repos[]` | Repos touched today |
| `active_repos[].name` | Repo name in report |
| `active_repos[].commits[]` | `hash`, `subject` — one-line commit notes |
| `active_repos[].files[]` | `path` — notable files (sample of `file_count`) |
| `active_repos[].file_count`, `commit_count` | Summary when lists are truncated |
| `no_activity_on_workday` | When `true`, say no repos matched |
| `recent_repos[]` | Fallback context when `no_activity_on_workday` |
| `errors[]` | Non-fatal workspace issues |

If `ok: false`, report the `error` string and continue with git-stats/Jira.

### Present in the report

Per active repo: name, commit subjects, and 1–2 notable file paths. When `no_activity_on_workday`, mention the newest entries from `recent_repos` instead.

---

## 2. GitHub / GitLab activity today

Use MCP server **`user-git-stats`**, tool **`git_stats_done`** (same as `git-stats done --json`). Read the tool schema before calling.

### Fetch remote activity

One call returns your GitHub and GitLab events for today (reviews, PR/MR updates, pushes, comments):

```json
{}
```

Defaults: both `github` and `gitlab`; today (local calendar date); `gitlab_host` `gitlab.cee.redhat.com`; `max_pages` 10 (100 events/page per host).

Optional overrides:

| Parameter | Use |
|-----------|-----|
| `activity_date` | ISO date (`YYYY-MM-DD`) instead of today |
| `hosts` | `["github"]`, `["gitlab"]`, or both |
| `gitlab_host`, `max_pages` | Host and pagination limits |

Do **not** run `gh api .../events` or `glab api .../events` for this section — `git_stats_done` replaces them.

### Use the response

| Field | Use |
|-------|-----|
| `date` | Report date |
| `github.items[]`, `gitlab.items[]` | Activity items — `action`, `ref`, `title`, `url`, `kind`, `detail` |
| `github.count`, `gitlab.count` | Item totals per host |
| `github.username`, `gitlab.username` | Resolved account (when available) |
| `github.ok`, `gitlab.ok` | Per-host success |
| `github.error`, `gitlab.error` | Per-host failure message |
| `errors[]` | Non-fatal issues (`host`, `message`) |

If top-level `ok: false`, report the `error` string and continue with Jira.

### Present in the report

Split **GitHub** and **GitLab** subsections. Group by `kind` when helpful (`review`, `pull_request`, `push`, `issue`, `comment`). Per item: `[ref](url) — action: title` (add `detail` when useful). Say "None" when a host's `items` is empty.

---

## 3. Jira — tickets touched today

Use MCP server **`user-jira-cli`**, tool **`jira_search`**. Read the tool schema before calling.

### Fetch today's Jira activity

Search for issues you touched today:

```json
{
  "jql": "assignee = currentUser() AND updated >= startOfDay() ORDER BY updated DESC",
  "max_results": 30
}
```

When the user asks about a specific project or sprint, add filters to the JQL (e.g. `AND project = IDM`).

Do **not** call `jira_agenda` for this section — that lists open sprint tickets (forward-looking), not today's activity.

### Use the response

| Field | Use |
|-------|-----|
| `issues[].key` | Ticket key |
| `issues[].fields.summary` | Ticket title |
| `issues[].fields.status.name` | Current status |
| `issues[].fields.updated` | Last update time |

If the search errors (auth, JQL), report the error in one line and finish the report from sections 1–2.

### Present in the report

Link format: `https://redhat.atlassian.net/browse/<KEY>` (adjust host if `JIRA_URL` differs).

Per ticket: `[KEY](url) — summary (status)`.

---

## Report template

Open with a one-paragraph **Summary** synthesizing the three sections (repos/commits, PR/MR activity, Jira movement). Then use this structure:

```markdown
# Done — <weekday>, <date>

## Summary
<2–4 sentences: main repos worked, key commits or reviews, Jira tickets moved>

## Workspace (<workday>)
- **<repo>:** <commit subjects or file note>
- **Notable files:** <path> (only if useful)

## GitHub
- [<ref>](url) — <action>: <title>

## GitLab
- [<ref>](url) — <action>: <title>

## Jira
- [IDM-1234](url) — summary (In Progress)

---
*Generated via done skill.*
```

Keep each section short. If a source returned nothing, say "None" rather than omitting the section. If a tool failed (auth, network), say which source and the error in one line.

When `activity_date` or a past day is requested, pass it to `git_stats_done` and use `worklog_workspace_activity` with `workday` instead of `worklog_workspace_today`.

---

## Checklist

```
Done progress:
- [ ] worklog_workspace_today fetched
- [ ] git_stats_done fetched
- [ ] jira_search fetched (today's tickets)
- [ ] Summary paragraph written
- [ ] Report assembled
```
