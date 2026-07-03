---
name: agenda
description: >-
  Builds a daily work agenda: last workday repo/file activity via worklog MCP
  `worklog_workspace_activity`, review-requested PR/MR queues via git-stats MCP
  `git_stats_reviews`, and unfinished Jira sprint tickets via jira-cli MCP `jira_agenda`. Use when the user asks
  for an agenda, morning standup prep, what they worked on yesterday, pending reviews,
  or current sprint tickets.
---

# Agenda

Produce a concise daily agenda in three sections. Run all data-gathering steps **in parallel** where possible, then assemble the report.

Related skills: [jira-cli-mcp](../jira-cli-mcp/SKILL.md), [review-changes](../review-changes/SKILL.md).

---

## 1. Last workday — workspace activity

Use MCP server **`user-worklog`**, tool **`worklog_workspace_activity`** (same as `worklog activity --json`). Read the tool schema before calling.

### Fetch activity

One call computes the previous Mon–Fri workday, scans the git workspace, and returns repos, files, and commits:

```json
{}
```

Defaults: workspace from `GIT_PATH` env (else `~/git`); previous workday; `max_repos` 8; `max_files_per_repo` 10; `max_commits_per_repo` 10; `@*` scratch dirs excluded.

Optional overrides:

| Parameter | Use |
|-----------|-----|
| `workspaces` | Array of roots when not using default `GIT_PATH` |
| `workday` | ISO date (`YYYY-MM-DD`) instead of auto last workday |
| `max_repos`, `max_files_per_repo`, `max_commits_per_repo` | Scan limits |
| `include_scratch_dirs` | `true` to include `@*` dirs |

Do **not** run shell `find`/`ls -ltr`/`git log` for this section — `worklog_workspace_activity` replaces them.

### Use the response

| Field | Use |
|-------|-----|
| `workday` | Report header date (Yesterday section) |
| `active_repos[]` | Repos touched that day |
| `active_repos[].name` | Repo name in report |
| `active_repos[].commits[]` | `hash`, `subject` — one-line commit notes |
| `active_repos[].files[]` | `path` — notable files (sample of `file_count`) |
| `active_repos[].file_count`, `commit_count` | Summary when lists are truncated |
| `no_activity_on_workday` | When `true`, say no repos matched |
| `recent_repos[]` | Fallback context when `no_activity_on_workday` (newest dirs per workspace) |
| `errors[]` | Non-fatal workspace issues |

If `ok: false`, report the `error` string and continue with reviews/Jira.

### Present in the report

Per active repo: name, commit subjects, and 1–2 notable file paths. When `no_activity_on_workday`, mention the newest entries from `recent_repos` instead.

---

## 2. Pull requests awaiting my review

Use MCP server **`user-git-stats`**, tool **`git_stats_reviews`** (same as `git-stats reviews --json`). Read the tool schema before calling.

### Fetch review queue

One call returns open GitHub PRs and GitLab MRs where you are a reviewer:

```json
{}
```

Defaults: both `github` and `gitlab`; `github_limit` 20; `gitlab_limit` 30; `gitlab_host` `gitlab.cee.redhat.com`; drafts excluded from GitLab `items` (listed under `drafts` instead).

Optional overrides:

| Parameter | Use |
|-----------|-----|
| `hosts` | `["github"]`, `["gitlab"]`, or both |
| `github_limit`, `gitlab_limit` | Per-host caps |
| `include_drafts` | `true` to merge GitLab drafts into `items` |
| `dirs` | Limit repo-scan fallback to named `GIT_PATH` children |
| `include_all` | `true` for closed/merged PRs/MRs |

Do **not** run `gh search prs` or `glab api` for this section — `git_stats_reviews` replaces them (with per-repo `gh`/`glab` fallbacks inside the tool).

### Use the response

| Field | Use |
|-------|-----|
| `github.review_requested.items[]` | GitHub PRs — `ref`, `title`, `url`, `updated_at` |
| `gitlab.review_requested.items[]` | GitLab MRs (non-draft) |
| `gitlab.review_requested.drafts[]` | Draft/WIP MRs — mention separately when `items` is empty |
| `github.ok`, `gitlab.ok` | Per-host success |
| `github.error`, `gitlab.error` | Per-host failure message |
| `errors[]` | Non-fatal issues (`host`, `category`, `message`) |

If top-level `ok: false`, report the `error` string and continue with Jira.

### Present in the report

Split **GitHub** and **GitLab** subsections. Per item: `[ref](url) — title`. Say "None" when a host's `items` is empty. Mention GitLab `drafts` only when there are no non-draft MRs (or when the user asked for drafts).

For a fuller queue (authored PRs with changes requested / no reviewer), use `git_stats` with all categories instead.

---

## 3. Jira — current sprint tickets

Use MCP server **`user-jira-cli`**, tool **`jira_agenda`** (same as `jira-cli agenda --json`). Read the tool schema before calling.

### Fetch agenda

One call resolves the active SSSD sprint, lists your unfinished issues, partitions them, and annotates roles:

```json
{
  "refresh_sprint_cache": true
}
```

Defaults (override only when the user asks): `sprint_pattern` `*IDM-SSSD*`, `sprint_project` `IDM`, `preferred_board` `rhel-idm-sssd`, `max_results` 50.

Optional overrides: `sprint` (id or name), `sprint_pattern`, `sprint_project`, `preferred_board`, `show_story_points`.

### Use the response

| Field | Use |
|-------|-----|
| `sprint.name`, `sprint.id`, `sprint.board_name` | Report header |
| `fallback_used` | Note when `true` (sprint filter empty; used `openSprints()` fallback) |
| `sections.in_progress` | **In Progress** tickets (already sorted by `updated` desc) |
| `sections.other_open` | Other unfinished tickets |
| `sections.contributor` | Tickets where you are **Contributor** only |
| `issues[].key`, `fields.summary`, `fields.status.name` | Ticket lines |
| `issues[].my_roles` | Role hint (Assignee, Developer, …) |
| `issues[].git_pull_request` | MR/PR link when set on the ticket |

Do **not** call `jira_list_sprints` or `jira_list_mine` for agenda ticket data — `jira_agenda` handles sprint resolution, querying, sorting, and sectioning.

### Present in the report

Link format: `https://redhat.atlassian.net/browse/<KEY>` (adjust host if `JIRA_URL` differs).

Per ticket, include summary; add status for non–In Progress items; add `my_roles` and `git_pull_request` when useful.

---

## Report template

Use this structure:

```markdown
# Agenda — <weekday>, <date>

## Yesterday (<workday>)
- **Repos:** <repo> — <one-line note: commits, file count, or mtime>
- **Notable files:** <path> (only if useful)

## Reviews waiting on me
### GitHub
- [owner/repo#N](url) — title
### GitLab
- [group/project!N](url) — title

## Sprint: <sprint name> (<sprint id>) [<board_name>]
### In Progress
- [IDM-1234](url) — summary *(Assignee)*
### Other open
- [IDM-5678](url) — summary (Review)
### Contributor
- [IDM-9999](url) — summary

---
*Generated via agenda skill.*
```

Keep each section short. If a source returned nothing, say "None" rather than omitting the section. If a tool failed (auth, network), say which source and the error in one line.

---

## Checklist

```
Agenda progress:
- [ ] worklog_workspace_activity fetched
- [ ] git_stats_reviews fetched
- [ ] jira_agenda fetched (sprint + tickets)
- [ ] Report assembled
```
